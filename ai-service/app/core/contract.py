"""Check a worker agent's result against the trace of what its tools returned.

A claim of kind `fact` points at a value with `ref = {call_id, path}`; the code compares the claimed
value with the traced one, so a parent agent can trust a result without loading the child's trace.
A `conclusion` has no ref and must list the claims it is derived from.

`call_id` names a tool call by its tool name: `lookup_order` for the first call, `lookup_order#2`
for the second. Other sources (`input`, `step:<id>`, a runtime-provided id) are registered on the trace.
A high-risk call queued for approval has no result yet, so a claim on it is checked against the
arguments staff will approve (`send_email` → `to`, `subject`, ...).
"""

import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.agent.loop import FINAL_ANSWER, QUEUED
from app.core.llm.messages import AssistantMessage, Message, ToolResultMessage, UserMessage

_FAILED = object()
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}\b)")
_FEEDBACK_LIMIT = 200
_KEYS_SHOWN = 20


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    claim: str | None = None

    def __str__(self) -> str:
        return f"claim '{self.claim}': {self.detail}" if self.claim else self.detail


class _Unresolved(Exception):
    pass


class Trace:
    """What each source returned, keyed by the `call_id` a claim cites."""

    def __init__(self) -> None:
        self._sources: dict[str, Any] = {}

    @classmethod
    def from_messages(cls, messages: list[Message]) -> "Trace":
        labels: dict[str, str] = {}
        arguments: dict[str, str] = {}
        seen: Counter[str] = Counter()
        for message in messages:
            if isinstance(message, AssistantMessage):
                for call in message.tool_calls:
                    if call.name == FINAL_ANSWER:
                        continue
                    seen[call.name] += 1
                    labels[call.id] = call.name if seen[call.name] == 1 else f"{call.name}#{seen[call.name]}"
                    arguments[call.id] = call.arguments
        trace = cls()
        for message in messages:
            if isinstance(message, ToolResultMessage) and message.tool_call_id in labels:
                if message.is_error:
                    data = _FAILED
                elif message.content == QUEUED:
                    data = _parse(arguments[message.tool_call_id])
                else:
                    data = _parse(message.content)
                trace._sources[labels[message.tool_call_id]] = data
        return trace

    def add(self, call_id: str, data: Any) -> None:
        self._sources[call_id] = data

    def resolve(self, call_id: str, path: str) -> Any:
        if call_id not in self._sources:
            raise _Unresolved(f"there is no source '{call_id}' (known: {', '.join(self._sources) or 'none'})")
        data = self._sources[call_id]
        if data is _FAILED:
            raise _Unresolved(f"'{call_id}' returned an error, so it cannot back a fact")
        if not isinstance(data, dict):
            raise _Unresolved(f"'{call_id}' has no key '{path}': it returned plain text, not keys")
        if path not in data:
            keys = list(data)
            shown = ", ".join(keys[:_KEYS_SHOWN]) + (", ..." if len(keys) > _KEYS_SHOWN else "")
            raise _Unresolved(f"'{call_id}' has no key '{path}' (its keys: {shown or 'none'})")
        value = data[path]
        # A document chunk is {title, text}; its claimed value is a quote from the text
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            return value["text"]
        return value


def check(result: dict[str, Any], trace: Trace, deliverables: list[dict[str, str]] | None = None,
          given: str = "") -> list[Violation]:
    """Violations of the result contract; an empty list means the result can be trusted.

    `given` is the text the agent was handed (its task): numbers in it, such as an order id or
    today's date, were not invented by the agent.
    """
    found: list[Violation] = []
    known = _digits(given)
    claims: dict[str, dict[str, Any]] = {}
    for claim in result.get("claims") or []:
        if claim["key"] in claims:
            found.append(Violation("duplicate_key", "key is used by more than one claim", claim["key"]))
        else:
            claims[claim["key"]] = claim
    for claim in claims.values():
        if claim.get("value") is None:
            continue
        if claim["kind"] == "fact":
            found += _check_fact(claim, claims, trace)
        else:
            found += _check_conclusion(claim, claims, known)
    found += _check_cycles(claims)
    found += _check_findings(result.get("findings") or [], claims, known)
    found += _check_deliverables(result, claims, deliverables or [])
    if result.get("status") in ("partial", "blocked", "escalate") and not result.get("open_questions"):
        found.append(Violation("missing_open_questions", f"status '{result['status']}' needs open_questions saying what is missing"))
    return found


def report(violations: list[Violation]) -> str:
    """One line per violation, for the model to fix."""
    return "\n".join(f"- {violation}" for violation in violations)


def verifier(
    sources: dict[str, Any] | None = None, deliverables: list[dict[str, str]] | None = None
) -> Callable[[dict[str, Any], Sequence[Message]], str | None]:
    """The `verify` hook of `AgentLoop`: `sources` are extra citable sources such as `input`."""

    def verify(result: dict[str, Any], history: Sequence[Message]) -> str | None:
        trace = Trace.from_messages(list(history))
        for call_id, data in (sources or {}).items():
            trace.add(call_id, data)
        given = "\n".join(m.content for m in history if isinstance(m, UserMessage))
        violations = check(result, trace, deliverables, given)
        return report(violations) if violations else None

    return verify


def _check_fact(claim: dict[str, Any], claims: dict[str, dict[str, Any]], trace: Trace) -> list[Violation]:
    key, ref = claim["key"], claim.get("ref")
    if not ref:
        return [Violation("missing_ref", "a fact needs ref = {call_id, path}", key)]
    try:
        actual = trace.resolve(ref["call_id"], ref["path"])
    except _Unresolved as exc:
        return [Violation("bad_ref", str(exc), key)]
    if not _matches(claim["value"], actual):
        shown = str(actual)[:_FEEDBACK_LIMIT]
        return [Violation("value_mismatch", f"value {claim['value']!r} is not what '{ref['path']}' holds in '{ref['call_id']}': {shown}", key)]
    return []


def _check_conclusion(claim: dict[str, Any], claims: dict[str, dict[str, Any]], known: set[str]) -> list[Violation]:
    key, found = claim["key"], []
    if claim.get("ref"):
        found.append(Violation("conclusion_has_ref", "a conclusion has no ref; list its basis in derived_from", key))
    basis = claim.get("derived_from") or []
    unknown = [name for name in basis if name not in claims or name == key]
    if not basis:
        found.append(Violation("missing_basis", "a conclusion needs derived_from", key))
    if unknown:
        found.append(Violation("bad_basis", f"derived_from names claims that do not exist: {', '.join(unknown)}", key))
    reasoning = claim.get("reasoning") or ""
    if not reasoning.strip():
        found.append(Violation("missing_reasoning", "a conclusion needs reasoning", key))
    allowed = _digits(claim["value"]) | known | {run for name in basis if name in claims for run in _digits(claims[name].get("value"))}
    invented = sorted(_digits(reasoning) - allowed)
    if invented:
        found.append(Violation("invented_number", f"reasoning uses numbers that are in no basis claim nor the task: {', '.join(invented)}", key))
    return found


def _check_findings(findings: list[dict[str, Any]], claims: dict[str, dict[str, Any]], known: set[str]) -> list[Violation]:
    """A finding is prose, so code can only hold it to the claims: the ones it cites must exist, and
    each of its numbers must come from a claim of the result or the task. A product name ("iPhone 16")
    or a branch ("Quận 1") carries digits that a finding may name without citing that claim."""
    found = []
    covered = known | {run for claim in claims.values() for run in _digits(claim.get("value"))}
    for finding in findings:
        text, cited = finding["text"], finding["claims"]
        label = f"finding \"{text[:60]}\": "
        unknown = [key for key in cited if key not in claims]
        if unknown:
            found.append(Violation("bad_finding_basis", f"{label}cites claims that do not exist: {', '.join(unknown)}"))
            continue
        invented = sorted(_digits(text) - covered)
        if invented:
            found.append(Violation("invented_number", f"{label}uses numbers that are in no claim nor the task: {', '.join(invented)}"))
    return found


def _check_cycles(claims: dict[str, dict[str, Any]]) -> list[Violation]:
    found, done = [], set()

    def visit(key: str, path: tuple[str, ...]) -> None:
        if key in done or key not in claims:
            return
        if key in path:
            found.append(Violation("cyclic_basis", f"derived_from loops back: {' -> '.join((*path, key))}", key))
            return
        for name in claims[key].get("derived_from") or []:
            visit(name, (*path, key))
        done.add(key)

    for key in claims:
        visit(key, ())
    return found


def _check_deliverables(result: dict[str, Any], claims: dict[str, dict[str, Any]], deliverables: list[dict[str, str]]) -> list[Violation]:
    found = []
    for want in deliverables:
        claim = claims.get(want["key"])
        if claim is None:
            found.append(Violation("missing_deliverable", "deliverable has no claim", want["key"]))
        elif claim["kind"] != want["kind"]:
            found.append(Violation("wrong_kind", f"deliverable must be a {want['kind']}", want["key"]))
        elif claim.get("value") is None and result.get("status") == "done":
            found.append(Violation("status_mismatch", "status is 'done' but this deliverable is null", want["key"]))
    return found


def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except ValueError:
        return content


def _matches(claimed: Any, actual: Any) -> bool:
    if isinstance(claimed, str) and isinstance(actual, str):
        # A quote only has to appear in the text, ignoring line breaks and spacing
        return bool(claimed.strip()) and " ".join(claimed.split()) in " ".join(actual.split())
    if isinstance(claimed, bool) != isinstance(actual, bool):
        return False
    return claimed == actual


def _digits(value: Any) -> set[str]:
    return set(re.findall(r"\d+", _THOUSANDS.sub("", str(value if value is not None else ""))))
