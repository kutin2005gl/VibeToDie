"""ReAct agent loop: model response → tool calls → tool results, until a terminal state.

Ported from ref/core/agent/loop.py and adapted to this system:
- with an output schema (every mandate has one), a run ends only through `final_answer`, whose
  arguments must match that schema; a plain-text answer gets one reminder, then the run fails
- an optional `verify` hook can reject a schema-valid `final_answer` with feedback for the model
- high-risk tools never run here: the call is queued for staff approval (PLAN-lite §7)

Book ch01 §1.1.5: every tool call in a turn is handled, and every exit is explicit, so a caller
never mistakes "produced an answer" for "completed the task".
"""

import asyncio
import hashlib
import json
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from jsonschema import Draft202012Validator

from app.core.llm import (
    Completion,
    LLMError,
    LLMStreamInterrupted,
    Message,
    ModelClient,
    StreamEvent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from app.core.tools import Tool, ToolResult, format_error

RunStatus = Literal["done", "stopped_at_limit", "failed", "cancelled"]

# Reserved tool through which a run with an output schema ends
FINAL_ANSWER = "final_answer"


@dataclass(frozen=True)
class AgentLimits:
    # Placeholders until real runs are measured: one step of a business task is short, and the
    # whole project has a 20 USD API budget
    max_steps: int = 10
    # Times the same call may return the same result before the run is judged stuck
    max_repeated_calls: int = 3
    # Failures in a row before the run fails, counted separately for truncated model output and
    # for each tool name (final_answer included); a success of the same kind resets its count
    max_consecutive_failures: int = 3
    # Wall clock for the whole run; every model and tool call is bounded by it
    max_duration_s: float = 180.0
    # Prompt + completion tokens summed over every model call of the run
    max_run_tokens: int = 150_000
    # Times one model call is made again after its stream broke midway (a provider cut it off)
    max_stream_restarts: int = 1


@dataclass(frozen=True)
class StepStarted:
    step: int
    max_steps: int


@dataclass(frozen=True)
class ToolCallStarted:
    step: int
    call: ToolCall


@dataclass(frozen=True)
class ToolCallFinished:
    step: int
    call_id: str
    result: ToolResult


@dataclass(frozen=True)
class RunFinished:
    """Always the last event of a run."""

    status: RunStatus
    # Human-readable detail for every status except `done`
    reason: str
    # Messages the run appended to the history it was given: the trace that claims point into
    messages: tuple[Message, ...]
    steps: int
    # Summed over every model call that completed
    usage: Usage
    # The validated `final_answer` arguments; None unless status is `done` with an output schema
    final: dict[str, Any] | None
    # High-risk calls the model made; none of them ran, they wait for staff approval
    pending_actions: tuple[ToolCall, ...]


AgentEvent = StepStarted | StreamEvent | ToolCallStarted | ToolCallFinished | RunFinished


class AgentLoop:
    def __init__(
        self,
        llm: ModelClient,
        tools: Sequence[Tool],
        output_schema: dict[str, Any] | None = None,
        limits: AgentLimits | None = None,
        verify: Callable[[dict[str, Any], Sequence[Message]], str | None] | None = None,
    ) -> None:
        names = [tool.name for tool in tools]
        if FINAL_ANSWER in names:
            raise ValueError(f"tool name {FINAL_ANSWER!r} is reserved")
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate tool names: {sorted(names)}")
        self._llm = llm
        self._tools = {tool.name: tool for tool in tools}
        self._specs = [tool.spec for tool in tools]
        self._final: Draft202012Validator | None = None
        if output_schema is not None:
            Draft202012Validator.check_schema(output_schema)
            self._final = Draft202012Validator(output_schema)
            self._specs.append(_final_spec(output_schema))
        self._limits = limits or AgentLimits()
        # Given the schema-valid arguments and the history so far, returns problems to send back
        # to the model, or None to accept. A rejection counts as a failed `final_answer` call.
        self._verify = verify

    async def run(
        self, messages: Sequence[Message], cancel: asyncio.Event | None = None
    ) -> AsyncIterator[AgentEvent]:
        """Run from `messages` and stream events; the last event is always `RunFinished`.

        Setting `cancel` ends the run as `cancelled` at the next safe point: after a model
        response or a tool result. Nothing in flight is interrupted.
        """
        cancel = cancel or asyncio.Event()
        history: list[Message] = list(messages)
        start = len(history)
        max_steps = self._limits.max_steps
        max_repeated = self._limits.max_repeated_calls
        # Repeats are judged on (tool, arguments, result): looking up an order again after it
        # changed returns new data and is progress, not a loop
        fingerprints: Counter[str] = Counter()
        max_failures = self._limits.max_consecutive_failures
        consecutive_truncations = 0
        # Per tool name, so a failing lookup is not reset by a successful search in between
        tool_failures: Counter[str] = Counter()
        final_reminders = 0
        pending: list[ToolCall] = []
        # One absolute deadline: the safe points check it, and every model and tool call is
        # bounded by it, so a single long call cannot run past the limit
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._limits.max_duration_s
        time_limit = f"reached the time limit ({self._limits.max_duration_s:g} s)"
        max_run_tokens = self._limits.max_run_tokens
        usage = Usage()

        def finish(
            status: RunStatus, reason: str, steps: int, final: dict[str, Any] | None = None
        ) -> RunFinished:
            return RunFinished(
                status, reason, tuple(history[start:]), steps, usage, final, tuple(pending)
            )

        for step in range(1, max_steps + 1):
            # Safe point after the last tool result of a turn (or before the first step)
            if cancel.is_set():
                yield finish("cancelled", _CANCELLED_REASON, step - 1)
                return
            if loop.time() >= deadline:
                yield finish("stopped_at_limit", time_limit, step - 1)
                return
            # Checked before each model call, the only thing that spends tokens. A call's usage
            # is known only when it completes, so the last call can overshoot the limit
            if usage.prompt_tokens + usage.completion_tokens >= max_run_tokens:
                reason = f"reached the token limit ({max_run_tokens})"
                yield finish("stopped_at_limit", reason, step - 1)
                return
            yield StepStarted(step, max_steps)

            for restart in range(self._limits.max_stream_restarts + 1):
                completion: Completion | None = None
                stream = self._llm.stream(history, self._specs or None)
                try:
                    while True:
                        # The deadline bounds each read, never a `yield`: if it spanned a yield it
                        # could fire in the caller's code instead of here
                        event = await _before_deadline(deadline, anext(stream, None))
                        if event is None:
                            break
                        yield event
                        if isinstance(event, Completion):
                            completion = event
                except LLMStreamInterrupted as exc:
                    # The client cannot retry once output reached us. Nothing ran yet (tools run only
                    # on a whole completion), so the same history can be sent again
                    if restart < self._limits.max_stream_restarts:
                        continue
                    yield finish("failed", f"model call failed: {exc}", step)
                    return
                except LLMError as exc:
                    # The client already retried what could be retried
                    yield finish("failed", f"model call failed: {exc}", step)
                    return
                except _OutOfTime:
                    yield finish("stopped_at_limit", time_limit, step)
                    return
                break
            if completion is None:
                yield finish("failed", "model stream ended without a completion", step)
                return

            usage = Usage(
                usage.prompt_tokens + completion.usage.prompt_tokens,
                usage.completion_tokens + completion.usage.completion_tokens,
            )
            history.append(completion.message)
            # Safe point after a model response: its calls never run, but are still paired
            if cancel.is_set():
                for call in completion.message.tool_calls:
                    history.append(
                        ToolResultMessage(tool_call_id=call.id, content=_CANCELLED, is_error=True)
                    )
                yield finish("cancelled", _CANCELLED_REASON, step)
                return
            if completion.truncated:
                # Degrade and continue (ch05 §5.1.5): the cut-off calls never run, and the model
                # is told why so it can split the work into smaller calls
                consecutive_truncations += 1
                if consecutive_truncations >= max_failures:
                    reason = f"model output was cut off at max_tokens {max_failures} times in a row"
                    yield finish("failed", reason, step)
                    return
                history.append(UserMessage(content=_truncation_notice(completion)))
                continue
            consecutive_truncations = 0
            if completion.finish_reason == "other":
                yield finish("failed", "model stopped for an unexpected reason", step)
                return
            if not completion.message.tool_calls:
                if self._final is None:
                    yield finish("done", "", step)
                    return
                # A worker answering in plain text has not fulfilled its contract
                final_reminders += 1
                if final_reminders > _MAX_FINAL_REMINDERS:
                    yield finish("failed", f"model ended without calling {FINAL_ANSWER}", step)
                    return
                history.append(UserMessage(content=_FINAL_REMINDER))
                continue

            # Every call gets a result before the next model request, in the order the model
            # made them, so the trajectory stays valid for every provider
            repeated: list[ToolCall] = []
            failing: list[str] = []
            out_of_time = False
            cancelled = False
            final: dict[str, Any] | None = None
            for call in completion.message.tool_calls:
                if final is not None:
                    history.append(ToolResultMessage(tool_call_id=call.id, content=_AFTER_FINAL))
                    continue
                if out_of_time or loop.time() >= deadline:
                    # Never started, but still paired so the history stays valid
                    out_of_time = True
                    history.append(
                        ToolResultMessage(tool_call_id=call.id, content=_NOT_RUN, is_error=True)
                    )
                    continue
                # Safe point after the previous tool result
                if cancelled or cancel.is_set():
                    cancelled = True
                    history.append(
                        ToolResultMessage(tool_call_id=call.id, content=_CANCELLED, is_error=True)
                    )
                    continue
                yield ToolCallStarted(step, call)

                if call.name == FINAL_ANSWER and self._final is not None:
                    final, result = self._check_final(call, history)
                elif (tool := self._tools.get(call.name)) is not None and tool.high_risk:
                    # Checked before queueing, so staff never approve a call that cannot run
                    invalid = tool.validate(call.arguments)
                    if invalid is None:
                        pending.append(call)
                    result = invalid or ToolResult(QUEUED)
                else:
                    try:
                        result = await _before_deadline(deadline, self._execute(call))
                    except _OutOfTime:
                        out_of_time = True
                        result = ToolResult(_INTERRUPTED, is_error=True)
                        history.append(
                            ToolResultMessage(
                                tool_call_id=call.id, content=result.content, is_error=True
                            )
                        )
                        yield ToolCallFinished(step, call.id, result)
                        continue
                    # Fingerprint the tool's own result, before any note is added to it
                    fingerprint = _fingerprint(call, result)
                    fingerprints[fingerprint] += 1
                    count = fingerprints[fingerprint]
                    if count >= max_repeated:
                        repeated.append(call)
                    elif count > 1:
                        # A repeat below the limit may be legitimate, so the model is told, not
                        # stopped, and gets a chance to change course
                        result = replace(
                            result, content=f"{result.content}\n\n{_repeat_note(max_repeated)}"
                        )

                if result.is_error:
                    tool_failures[call.name] += 1
                    if tool_failures[call.name] >= max_failures:
                        failing.append(call.name)
                else:
                    tool_failures[call.name] = 0
                history.append(
                    ToolResultMessage(
                        tool_call_id=call.id, content=result.content, is_error=result.is_error
                    )
                )
                yield ToolCallFinished(step, call.id, result)

            # Checked after the turn, so the run still ends on paired results. Cancellation first:
            # once it is set, the calls after it are skipped before the clock is looked at
            if cancelled:
                yield finish("cancelled", _CANCELLED_REASON, step)
                return
            if out_of_time:
                yield finish("stopped_at_limit", time_limit, step)
                return
            if final is not None:
                yield finish("done", "", step, final)
                return
            if repeated:
                reason = (
                    f"tool '{repeated[0].name}' returned the same result for the same arguments "
                    f"{max_repeated} times"
                )
                yield finish("failed", reason, step)
                return
            if failing:
                yield finish(
                    "failed", f"tool '{failing[0]}' failed {max_failures} times in a row", step
                )
                return

        yield finish("stopped_at_limit", f"reached the step limit ({max_steps})", max_steps)

    def _check_final(
        self, call: ToolCall, history: Sequence[Message]
    ) -> tuple[dict[str, Any] | None, ToolResult]:
        """Validate `final_answer` against the output schema and `verify`; a mismatch is an observation."""
        assert self._final is not None
        try:
            args = json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            content = format_error(
                "invalid_arguments",
                f"arguments are not valid JSON: {exc}",
                f"Call {FINAL_ANSWER} again with one JSON object matching its schema.",
            )
            return None, ToolResult(content, is_error=True)
        errors = sorted(self._final.iter_errors(args), key=lambda e: list(map(str, e.path)))
        if errors:
            problems = "\n".join(
                f"{'.'.join(map(str, error.path)) or 'arguments'}: {error.message}"
                for error in errors[:_MAX_SCHEMA_ERRORS]
            )
            content = format_error(
                "invalid_arguments",
                problems,
                f"Fix these fields to match the output schema and call {FINAL_ANSWER} again.",
            )
            return None, ToolResult(content, is_error=True)
        if self._verify is not None and (problems := self._verify(args, history)):
            content = format_error(
                "invalid_arguments",
                problems,
                f"Fix these and call {FINAL_ANSWER} again; cite only what the tools returned.",
            )
            return None, ToolResult(content, is_error=True)
        return args, ToolResult("Accepted.")

    async def _execute(self, call: ToolCall) -> ToolResult:
        """Run one call; every failure becomes an observation, never a crashed run (ch05 §5.1.5)."""
        tool = self._tools.get(call.name)
        if tool is None:
            available = ", ".join(sorted([*self._tools, *([FINAL_ANSWER] if self._final else [])]))
            content = format_error(
                "unknown_tool",
                f"there is no tool named '{call.name}'.",
                f"Call one of the available tools: {available or 'none'}.",
            )
            return ToolResult(content, is_error=True)
        try:
            return await tool.run(call.arguments)
        except Exception as exc:
            # Expected failures come back as `ToolError` observations; this is a bug in the tool
            content = format_error(
                "internal_error",
                f"tool '{call.name}' failed: {type(exc).__name__}: {exc}",
                "This is not caused by your arguments. Try a different approach.",
            )
            return ToolResult(content, is_error=True)


def _final_spec(output_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": FINAL_ANSWER,
            "description": (
                "End this task and return the structured result. Call it exactly once, after "
                "the work is done; the arguments must match the schema."
            ),
            "parameters": output_schema,
        },
    }


def _fingerprint(call: ToolCall, result: ToolResult) -> str:
    """Digest of a call and its result; arguments are compared as JSON, not as formatted text."""
    try:
        arguments = json.dumps(json.loads(call.arguments), sort_keys=True)
    except json.JSONDecodeError:
        arguments = call.arguments
    payload = json.dumps([call.name, arguments, result.content, result.is_error])
    return hashlib.sha256(payload.encode()).hexdigest()


class _OutOfTime(Exception):
    """The run's own deadline passed; any other TimeoutError is not ours and propagates."""


async def _before_deadline[T](deadline: float, awaitable: Awaitable[T]) -> T:
    """Await `awaitable`, cancelling it at `deadline` (event-loop time)."""
    timeout = asyncio.timeout_at(deadline)
    try:
        async with timeout:
            return await awaitable
    except TimeoutError:
        if timeout.expired():
            raise _OutOfTime from None
        raise


_MAX_FINAL_REMINDERS = 1
_MAX_SCHEMA_ERRORS = 10
_INTERRUPTED = "Error: the run reached its time limit while this tool was running."
_NOT_RUN = "Error: not run; the run reached its time limit before this call started."
_CANCELLED = "Error: not run; the run was cancelled before this call started."
_CANCELLED_REASON = "cancelled by request"
_AFTER_FINAL = f"Not run: {FINAL_ANSWER} was accepted earlier in this turn and ended the task."
# The result of a queued high-risk call; `contract.Trace` checks claims on it against the arguments
QUEUED = (
    "Queued for staff approval; NOT executed yet. Do not report this action as done. "
    "Continue with the rest of the task."
)
_FINAL_REMINDER = (
    f"You answered in plain text, but this task must end with a call to {FINAL_ANSWER} "
    "whose arguments match its schema. Call it now."
)


def _truncation_notice(completion: Completion) -> str:
    notice = "Your previous response hit the output token limit and was cut off."
    if completion.truncated_tool_calls:
        names = ", ".join(f"'{call.name}'" for call in completion.truncated_tool_calls)
        notice += f" These tool calls were incomplete and were not run: {names}."
    return (
        f"{notice} Keep each response shorter: split large content into several smaller tool calls."
    )


def _repeat_note(max_repeated: int) -> str:
    return (
        "Note: this exact call already returned this exact result earlier in the run. "
        "If you are stuck, try a different approach; the run stops once the same call "
        f"returns the same result {max_repeated} times."
    )
