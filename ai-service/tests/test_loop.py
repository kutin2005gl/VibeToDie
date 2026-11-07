import asyncio
from typing import Annotated, Any

import pytest
from pydantic import Field

from app.core.agent import AgentLimits, AgentLoop, RunFinished, ToolCallFinished
from app.core.llm import LLMRequestError, ToolResultMessage, Usage, UserMessage
from app.core.llm.fake import ScriptedClient, call, completion
from app.core.tools import BaseTool, ToolArgs, ToolDescription, ToolError

SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}
GOOD = {"summary": "xong"}
DESC = ToolDescription(
    summary="s", when_to_use="u", when_not_to_use="n", returns="r", cost="c", examples=("e()",)
)


class OrderArgs(ToolArgs):
    order_id: Annotated[str, Field(min_length=1)]


class LookupOrder(BaseTool[OrderArgs]):
    name = "lookup_order"
    description = DESC
    args_model = OrderArgs

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def execute(self, args: OrderArgs) -> str:
        self.calls.append(args.order_id)
        if args.order_id.startswith("missing"):
            raise ToolError(f"order {args.order_id} not found", "Check the order id.")
        return f'{{"order_id": "{args.order_id}", "paid": 12990000}}'


class Buggy(LookupOrder):
    name = "buggy"

    async def execute(self, args: OrderArgs) -> str:
        raise RuntimeError("boom")


class Slow(LookupOrder):
    name = "slow"

    async def execute(self, args: OrderArgs) -> str:
        await asyncio.sleep(5)
        return "late"


class SendMessage(LookupOrder):
    name = "send_message"
    high_risk = True

    async def execute(self, args: OrderArgs) -> str:
        raise AssertionError("a high-risk tool must never run inside the loop")


def run(loop: AgentLoop, cancel: asyncio.Event | None = None) -> list[Any]:
    async def collect() -> list[Any]:
        return [event async for event in loop.run([UserMessage(content="việc")], cancel)]

    return asyncio.run(collect())


def finished(events: list[Any]) -> RunFinished:
    assert isinstance(events[-1], RunFinished)
    return events[-1]


def tool_results(result: RunFinished) -> list[ToolResultMessage]:
    return [m for m in result.messages if isinstance(m, ToolResultMessage)]


def test_tool_then_final_answer_is_done_with_validated_result():
    tool = LookupOrder()
    client = ScriptedClient([
        completion(call("1", "lookup_order", {"order_id": "DH1"}), usage=Usage(10, 5)),
        completion(call("2", "final_answer", GOOD), usage=Usage(20, 5)),
    ])
    result = finished(run(AgentLoop(client, [tool], SCHEMA)))
    assert (result.status, result.final, result.steps) == ("done", GOOD, 2)
    assert result.usage == Usage(30, 10)
    assert tool.calls == ["DH1"]
    assert "12990000" in tool_results(result)[0].content
    # final_answer is offered to the model with the caller's schema
    specs = client.seen[0][1]
    assert specs[-1]["function"]["name"] == "final_answer"
    assert specs[-1]["function"]["parameters"] is SCHEMA


def test_final_answer_not_matching_schema_is_an_observation_then_fixed():
    client = ScriptedClient([
        completion(call("1", "final_answer", {"summary": 3})),
        completion(call("2", "final_answer", GOOD)),
    ])
    result = finished(run(AgentLoop(client, [], SCHEMA)))
    assert result.status == "done" and result.final == GOOD
    first = tool_results(result)[0].content
    assert first.startswith("Error (invalid_arguments)") and "summary" in first


def test_final_answer_invalid_three_times_fails():
    client = ScriptedClient([completion(call(str(i), "final_answer", "{bad")) for i in range(3)])
    result = finished(run(AgentLoop(client, [], SCHEMA)))
    assert result.status == "failed" and "final_answer" in result.reason


def test_plain_text_gets_one_reminder_then_fails():
    client = ScriptedClient([completion(content="đây là kết quả"), completion(content="vẫn text")])
    result = finished(run(AgentLoop(client, [], SCHEMA)))
    assert result.status == "failed" and "without calling final_answer" in result.reason
    reminder = client.seen[1][0][-1]
    assert isinstance(reminder, UserMessage) and "final_answer" in reminder.content


def test_plain_text_is_done_without_output_schema():
    client = ScriptedClient([completion(content="trả lời")])
    result = finished(run(AgentLoop(client, [])))
    assert (result.status, result.final) == ("done", None)


def test_calls_after_final_answer_in_the_same_turn_are_paired_but_not_run():
    tool = LookupOrder()
    client = ScriptedClient([
        completion(call("1", "final_answer", GOOD), call("2", "lookup_order", {"order_id": "X"})),
    ])
    result = finished(run(AgentLoop(client, [tool], SCHEMA)))
    assert result.status == "done" and tool.calls == []
    assert [m.tool_call_id for m in tool_results(result)] == ["1", "2"]
    assert tool_results(result)[1].content.startswith("Not run")


def test_high_risk_tool_is_queued_not_run():
    send = SendMessage()
    queued = call("1", "send_message", {"order_id": "DH1"})
    client = ScriptedClient([completion(queued), completion(call("2", "final_answer", GOOD))])
    result = finished(run(AgentLoop(client, [send], SCHEMA)))
    assert result.status == "done" and result.pending_actions == (queued,)
    assert "NOT executed" in tool_results(result)[0].content


def test_high_risk_call_breaking_the_schema_is_an_observation_not_queued():
    bad = call("1", "send_message", {"order_id": ""})
    client = ScriptedClient([completion(bad), completion(call("2", "final_answer", GOOD))])
    result = finished(run(AgentLoop(client, [SendMessage()], SCHEMA)))
    assert result.status == "done" and result.pending_actions == ()
    assert tool_results(result)[0].content.startswith("Error (invalid_arguments)")


def test_tool_failures_are_observations_with_hints():
    client = ScriptedClient([
        completion(
            call("1", "nope"),
            call("2", "lookup_order", {"order_id": "DH1", "extra": 1}),
            call("3", "lookup_order", {"order_id": "missing"}),
            call("4", "buggy", {"order_id": "DH1"}),
        ),
        completion(call("5", "final_answer", GOOD)),
    ])
    result = finished(run(AgentLoop(client, [LookupOrder(), Buggy()], SCHEMA)))
    assert result.status == "done"
    unknown, invalid, tool_error, internal = (m.content for m in tool_results(result)[:4])
    assert unknown.startswith("Error (unknown_tool)") and "final_answer, lookup_order" in unknown
    assert invalid.startswith("Error (invalid_arguments)") and "extra" in invalid
    assert tool_error.startswith("Error (tool_error)") and "Hint: Check the order id." in tool_error
    assert internal.startswith("Error (internal_error)") and "RuntimeError" in internal


def test_same_tool_failing_in_a_row_fails_the_run():
    # Different arguments each time, so this is not caught as a repeat first
    client = ScriptedClient(
        [completion(call(str(i), "lookup_order", {"order_id": f"missing{i}"})) for i in range(3)]
    )
    result = finished(run(AgentLoop(client, [LookupOrder()], SCHEMA)))
    assert result.status == "failed" and "'lookup_order' failed 3 times" in result.reason


def test_repeated_identical_call_is_noted_then_fails():
    client = ScriptedClient(
        [completion(call(str(i), "lookup_order", {"order_id": "DH1"})) for i in range(3)]
    )
    result = finished(run(AgentLoop(client, [LookupOrder()], SCHEMA)))
    assert result.status == "failed" and "same result" in result.reason
    assert "Note: this exact call" in tool_results(result)[1].content


def test_truncated_calls_never_run_and_repeated_truncation_fails():
    tool = LookupOrder()
    cut = completion(call("1", "lookup_order", {"order_id": "DH1"}), finish_reason="length")
    client = ScriptedClient([cut, cut, cut])
    result = finished(run(AgentLoop(client, [tool], SCHEMA)))
    assert result.status == "failed" and "cut off" in result.reason
    assert tool.calls == []
    notice = client.seen[1][0][-1]
    assert isinstance(notice, UserMessage) and "'lookup_order'" in notice.content


def test_token_limit_is_checked_before_the_next_model_call():
    client = ScriptedClient([
        completion(call("1", "lookup_order", {"order_id": "DH1"}), usage=Usage(90, 20)),
    ])
    limits = AgentLimits(max_run_tokens=100)
    result = finished(run(AgentLoop(client, [LookupOrder()], SCHEMA, limits)))
    assert (result.status, result.steps) == ("stopped_at_limit", 1)
    assert len(client.seen) == 1


def test_step_limit():
    client = ScriptedClient(
        [completion(call(str(i), "lookup_order", {"order_id": f"DH{i}"})) for i in range(2)]
    )
    result = finished(run(AgentLoop(client, [LookupOrder()], SCHEMA, AgentLimits(max_steps=2))))
    assert result.status == "stopped_at_limit" and "step limit" in result.reason


def test_deadline_interrupts_a_slow_tool_and_keeps_history_paired():
    client = ScriptedClient([
        completion(call("1", "slow", {"order_id": "DH1"}), call("2", "lookup_order", {"order_id": "X"})),
    ])
    limits = AgentLimits(max_duration_s=0.2)
    events = run(AgentLoop(client, [Slow(), LookupOrder()], SCHEMA, limits))
    result = finished(events)
    assert result.status == "stopped_at_limit"
    assert [m.tool_call_id for m in tool_results(result)] == ["1", "2"]
    assert any(isinstance(e, ToolCallFinished) and e.result.is_error for e in events)


def test_cancel_before_start():
    cancel = asyncio.Event()
    cancel.set()
    result = finished(run(AgentLoop(ScriptedClient([]), [], SCHEMA), cancel))
    assert (result.status, result.steps) == ("cancelled", 0)


def test_model_error_fails_the_run():
    result = finished(run(AgentLoop(ScriptedClient([]), [], SCHEMA)))
    assert result.status == "failed" and "model call failed" in result.reason


def test_reserved_and_duplicate_tool_names_are_rejected():
    class Clash(LookupOrder):
        name = "final_answer"

    with pytest.raises(ValueError, match="reserved"):
        AgentLoop(ScriptedClient([]), [Clash()], SCHEMA)
    with pytest.raises(ValueError, match="duplicate"):
        AgentLoop(ScriptedClient([]), [LookupOrder(), LookupOrder()], SCHEMA)


def test_invalid_output_schema_is_rejected_at_construction():
    from jsonschema.exceptions import SchemaError

    with pytest.raises(SchemaError):
        AgentLoop(ScriptedClient([]), [], {"type": "nope"})


def test_scripted_client_out_of_completions_raises_llm_error():
    async def drain() -> None:
        async for _ in ScriptedClient([]).stream([]):
            pass

    with pytest.raises(LLMRequestError):
        asyncio.run(drain())


class CutOff(ScriptedClient):
    """The provider sends some output then drops the stream, `cuts` times, before answering whole."""

    def __init__(self, completions, cuts: int) -> None:
        super().__init__(completions)
        self.cuts = cuts

    async def stream(self, messages, tools=None):
        from app.core.llm import LLMStreamInterrupted
        from app.core.llm.types import ContentDelta
        if self.cuts:
            self.cuts -= 1
            self.seen.append((tuple(messages), tuple(tools or ())))
            yield ContentDelta("half an ans")
            raise LLMStreamInterrupted("stream ended without a finish_reason")
        async for event in super().stream(messages, tools):
            yield event


def test_a_stream_cut_off_midway_is_made_again_with_the_same_history():
    """Room #190: DeepSeek dropped a worker's stream and the whole step failed."""
    client = CutOff([completion(call("1", "final_answer", GOOD))], cuts=1)
    result = finished(run(AgentLoop(client, [], SCHEMA)))
    assert (result.status, result.final, result.steps) == ("done", GOOD, 1)
    assert client.seen[0][0] == client.seen[1][0]  # nothing from the broken attempt reached the history


def test_a_stream_cut_off_again_fails_the_run():
    client = CutOff([completion(call("1", "final_answer", GOOD))], cuts=2)
    result = finished(run(AgentLoop(client, [], SCHEMA)))
    assert result.status == "failed" and "stream ended without a finish_reason" in result.reason
    assert len(client.seen) == 2
    # Turned off, the first cut fails the run
    once = CutOff([completion(call("1", "final_answer", GOOD))], cuts=1)
    assert finished(run(AgentLoop(once, [], SCHEMA, AgentLimits(max_stream_restarts=0)))).status == "failed"
