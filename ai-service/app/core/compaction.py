"""Room context: what earlier turns of a room did, kept within a fixed token budget.

Each turn leaves a digest built by code from its checked result (observation compaction: no tool
trace, plan, rejections or draft bodies; selective: the request and summary clipped, the verified
facts as `key: value`). Agents of a later turn read the digests of the last `KEEP_RECENT_TURNS`
turns verbatim (sliding window); when the room grows past `ROOM_CONTEXT_TOKENS`, older turns are
folded into one rolling summary by a model whose kept facts code checks against the digests, and
the summary is saved as a checkpoint so each turn folds only what newly left the window. If folding
fails or does not shrink the room, the oldest digests are dropped instead (truncation), so a turn
never fails because of its context.

A digest's facts are citable in a later turn as source `room:t<turn>`, the way `step:<id>` is.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

from app.core.llm.messages import Message

ROOM_CONTEXT_TOKENS = 2000
KEEP_RECENT_TURNS = 3
MAX_TURNS = 20
REQUEST_CHARS = 400
SUMMARY_CHARS = 600
FACT_CHARS = 200
# No tokenizer here: Vietnamese text costs more tokens per character than English, so count high
CHARS_PER_TOKEN = 3
ROOM = "room_context"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _facts(result: dict[str, Any]) -> dict[str, Any]:
    """Verified `fact` claims of a result as `key: value`; a Coordinator result's come from its accepted steps."""
    claims = list(result.get("claims") or [])
    for record in [*(result.get("steps") or []),
                   *(s for replan in result.get("replans") or [] for s in replan.get("steps") or [])]:
        if record.get("status") == "accepted" and record.get("result"):
            claims += record["result"].get("claims") or []
    facts: dict[str, Any] = {}
    for claim in claims:
        # A fact quoted from the request repeats `request`; a long quote (a policy passage) is looked up again
        if claim.get("kind") != "fact" or (claim.get("ref") or {}).get("call_id") == "input":
            continue
        if isinstance(claim["value"], str) and len(claim["value"]) > FACT_CHARS:
            continue
        facts.setdefault(claim["key"], claim["value"])
    return facts


def digest(turn: int, request: str, agent: str, outcome: str, result: dict[str, Any] | None = None,
           text: str = "") -> dict[str, Any]:
    """What a later turn keeps of turn `turn`; `text` is the answer when `result` has none (a failure)."""
    result = result or {}
    answer = next((result[k] for k in ("final_response", "answer", "summary", "clarify_question")
                   if isinstance(result.get(k), str) and result[k].strip()), text)
    return {"turn": turn, "request": _cut(request, REQUEST_CHARS), "agent": agent, "outcome": outcome,
            "summary": _cut(answer, SUMMARY_CHARS), "facts": _facts(result),
            "open_questions": list(result.get("open_questions") or [])}


def estimate_tokens(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False)) // CHARS_PER_TOKEN + 1


def _recent(context: dict[str, Any], turns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turns the rolling summary does not cover yet."""
    return [t for t in turns if t["turn"] > context.get("through_turn", 0)]


def room_view(context: dict[str, Any], turns: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The room as agents read it: the rolling summary (if any), then the digests it does not cover."""
    view: dict[str, Any] = {}
    if context.get("through_turn"):
        view["earlier"] = {k: context[k] for k in ("through_turn", "summary", "facts", "open_questions")}
    view["turns"] = _recent(context, turns)
    return view


def to_fold(context: dict[str, Any], turns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turns to fold into the rolling summary: those past the window, once the room is over budget."""
    if estimate_tokens(room_view(context, turns)) <= ROOM_CONTEXT_TOKENS:
        return []
    return _recent(context, turns)[:-KEEP_RECENT_TURNS]


def folded(context: dict[str, Any], fold: Sequence[dict[str, Any]], final: dict[str, Any]) -> dict[str, Any]:
    """The checkpoint after the compactor's `final` folded `fold` into `context`.

    A key a later turn repeated with the same value is kept once, at its earliest turn: the room stays small
    and `room:t<turn>` still resolves it.
    """
    facts, seen = [], set()
    for fact in sorted(final["facts"], key=lambda f: f["turn"]):
        pair = (fact["key"], json.dumps(fact["value"]))
        if pair not in seen:
            seen.add(pair)
            facts.append(fact)
    return {"through_turn": fold[-1]["turn"], "summary": final["summary"], "facts": facts,
            "open_questions": final["open_questions"]}


def fit(view: dict[str, Any]) -> dict[str, Any]:
    """Truncation fallback: drop the oldest digests (the newest always stays) until `view` is in budget."""
    view = {**view, "turns": list(view["turns"])}
    while len(view["turns"]) > 1 and estimate_tokens(view) > ROOM_CONTEXT_TOKENS:
        view["turns"].pop(0)
    return view


def sources(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The facts of `view` as citable sources, one per turn: `room:t<turn>` → `{key: value}`."""
    out: dict[str, dict[str, Any]] = {}
    for fact in (view.get("earlier") or {}).get("facts") or []:
        out.setdefault(f"room:t{fact['turn']}", {})[fact["key"]] = fact["value"]
    for turn in view["turns"]:
        out.setdefault(f"room:t{turn['turn']}", {}).update(turn["facts"])
    return out


def block(view: dict[str, Any]) -> str:
    """`view` as a data block: staff wrote its requests, so it cannot close its own tag."""
    body = json.dumps(view, ensure_ascii=False).replace(f"</{ROOM}>", f"&lt;/{ROOM}&gt;")
    return f"<{ROOM}>\n{body}\n</{ROOM}>"


def fold_input(context: dict[str, Any], fold: Sequence[dict[str, Any]]) -> str:
    """The compactor's user message: the summary so far and the turns to fold into it."""
    earlier = room_view(context, []).get("earlier", {"summary": "", "facts": [], "open_questions": []})
    return (
        "<task>\nFold <turns> into <summary_so_far> and return the new room summary.\n</task>\n"
        f"{block({'summary_so_far': earlier, 'turns': list(fold)})}"
    )


def facts_verifier(context: dict[str, Any], fold: Sequence[dict[str, Any]]
                   ) -> Callable[[dict[str, Any], Sequence[Message]], str | None]:
    """The compactor's `verify` hook: every kept fact is copied exactly from the summary so far or a folded turn."""
    known = {(f["turn"], f["key"]): f["value"] for f in context.get("facts") or []}
    for turn in fold:
        known.update({(turn["turn"], k): v for k, v in turn["facts"].items()})

    def verify(result: dict[str, Any], history: Sequence[Message]) -> str | None:
        problems = []
        for fact in result.get("facts") or []:
            where = (fact.get("turn"), fact.get("key"))
            if where not in known:
                problems.append(f"- turn {where[0]} has no fact '{where[1]}'; keep only facts given in the input")
            elif known[where] != fact.get("value"):
                problems.append(f"- fact '{where[1]}' of turn {where[0]} is {known[where]!r}; copy it exactly")
        return "\n".join(problems) or None

    return verify
