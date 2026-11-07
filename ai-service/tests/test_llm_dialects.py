"""Dialects: wire conversion, response mapping, error classes, and one end-to-end stream each
through the real SDK over a mock HTTP transport (no network, no API spend)."""

import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from app.core.llm import (
    AssistantMessage,
    Completion,
    ContentDelta,
    LLMAuthError,
    LLMRefusedError,
    LLMRequestError,
    ModelConfig,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.core.llm.dialects import anthropic_messages, openai_common, openai_compat, openai_responses

TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Tra cứu đơn.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    },
}
CALL = ToolCall(id="call_1", name="lookup_order", arguments='{"order_id": "DH1"}')
HISTORY = [
    SystemMessage(content="Bạn là agent."),
    UserMessage(content="Tra đơn DH1"),
    AssistantMessage(content="Để tôi tra.", tool_calls=(CALL,)),
    ToolResultMessage(tool_call_id="call_1", content="not found", is_error=True),
    UserMessage(content="Nhắc: gọi final_answer."),
]


def config(dialect: str, **overrides) -> ModelConfig:
    values = {"id": "m", "dialect": dialect, "model": "model-x", "api_key_ref": "env:TEST_KEY"}
    return ModelConfig(**{**values, **overrides})


def sse(events: list[tuple[str | None, dict | str]]) -> bytes:
    lines = []
    for name, data in events:
        if name:
            lines.append(f"event: {name}")
        lines.append(f"data: {data if isinstance(data, str) else json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def mock_http(responses: list[httpx2.Response], seen: list[httpx2.Request]) -> httpx2.AsyncClient:
    queue = iter(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return next(queue)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def stream_ok(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


async def no_sleep(_: float) -> None:
    return None


def collect(client, messages=HISTORY, tools=(TOOL,)):
    async def run():
        return [event async for event in client.stream(messages, list(tools))]

    return asyncio.run(run())


# --- Anthropic ---------------------------------------------------------------------------


def test_anthropic_wire_merges_tool_results_and_notices_into_one_user_turn():
    system, wire = anthropic_messages.to_wire(HISTORY)
    assert system == "Bạn là agent."
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert wire[1]["content"][1] == {
        "type": "tool_use", "id": "call_1", "name": "lookup_order", "input": {"order_id": "DH1"},
    }
    results, notice = wire[2]["content"]
    assert results == {"type": "tool_result", "tool_use_id": "call_1", "content": "not found", "is_error": True}
    assert notice == {"type": "text", "text": "Nhắc: gọi final_answer."}


def test_anthropic_replays_raw_content_with_thinking_signature():
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "tool_use", "id": "t", "name": "x", "input": {}}]
    message = AssistantMessage(tool_calls=(ToolCall(id="t", name="x", arguments="{}"),), provider_state={"anthropic": raw})
    _, wire = anthropic_messages.to_wire([UserMessage(content="q"), message])
    assert wire[1]["content"] is raw


def message_dict(content, stop_reason="tool_use", **extra):
    return {
        "content": content, "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}, **extra,
    }


def test_anthropic_completion_maps_tool_use_reasoning_and_usage():
    blocks = [
        {"type": "thinking", "thinking": "nghĩ", "signature": "sig"},
        {"type": "text", "text": "Để tôi tra."},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_order", "input": {"order_id": "DH1"}},
    ]
    result = anthropic_messages.completion_from(message_dict(blocks), 1, 0)
    assert result.finish_reason == "tool_calls"
    assert result.message.reasoning == "nghĩ" and result.message.content == "Để tôi tra."
    assert json.loads(result.message.tool_calls[0].arguments) == {"order_id": "DH1"}
    assert result.message.provider_state == {"anthropic": blocks}
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (100, 5)


def test_anthropic_truncated_turn_runs_nothing_and_is_not_replayed_raw():
    blocks = [{"type": "tool_use", "id": "toolu_1", "name": "lookup_order", "input": {"order_id": "D"}}]
    result = anthropic_messages.completion_from(message_dict(blocks, "max_tokens"), 1, 0)
    assert result.truncated and result.message.tool_calls == ()
    assert result.truncated_tool_calls[0].name == "lookup_order"
    assert result.message.provider_state == {}


def test_anthropic_refusal_raises():
    data = message_dict([], "refusal", stop_details={"type": "refusal", "category": "cyber"})
    with pytest.raises(LLMRefusedError, match="cyber"):
        anthropic_messages.completion_from(data, 1, 0)


def anthropic_status_error(cls, status: int):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com"))
    return cls("boom", response=response, body=None)


def test_anthropic_error_classes():
    classify = anthropic_messages.classify
    assert isinstance(classify(anthropic_status_error(anthropic.AuthenticationError, 401)), LLMAuthError)
    assert isinstance(classify(anthropic_status_error(anthropic.PermissionDeniedError, 403)), LLMAuthError)
    assert classify(anthropic_status_error(anthropic.RateLimitError, 429)) is None
    assert classify(anthropic_status_error(anthropic.APIStatusError, 529)) is None
    assert isinstance(classify(anthropic_status_error(anthropic.BadRequestError, 400)), LLMRequestError)


ANTHROPIC_SSE = sse([
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "content": [], "model": "claude-opus-5-5",
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Để tôi tra."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
        "type": "tool_use", "id": "toolu_1", "name": "lookup_order", "input": {}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
        "type": "input_json_delta", "partial_json": "{\"order_id\": \"DH1\"}"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                       "usage": {"output_tokens": 20}}),
    ("message_stop", {"type": "message_stop"}),
])


def test_anthropic_end_to_end_stream_with_retry_and_request_shape(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    seen: list[httpx2.Request] = []
    overloaded = httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    http = mock_http([overloaded, stream_ok(ANTHROPIC_SSE)], seen)
    client = anthropic_messages.AnthropicClient(
        config("anthropic", effort="low", fallbacks="default"), http_client=http, sleep=no_sleep
    )
    events = collect(client)

    assert isinstance(events[0], ContentDelta) and events[0].text == "Để tôi tra."
    final = events[-1]
    assert isinstance(final, Completion) and final.attempts == 2
    assert final.message.tool_calls[0].id == "toolu_1"
    assert json.loads(final.message.tool_calls[0].arguments) == {"order_id": "DH1"}
    body = json.loads(seen[-1].content)
    assert body["system"] == "Bạn là agent." and body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default" and body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["input_schema"] == TOOL["function"]["parameters"]
    assert anthropic_messages.FALLBACK_BETA in seen[-1].headers["anthropic-beta"]
    # The configured key is the one sent (anthropic 2.x sends it in the authorization header)
    assert "sk-secret" in seen[-1].headers["authorization"]


# --- OpenAI Responses ----------------------------------------------------------------------


def test_responses_wire_items():
    instructions, wire = openai_responses.to_wire(HISTORY)
    assert instructions == "Bạn là agent."
    assert wire == [
        {"role": "user", "content": "Tra đơn DH1"},
        {"role": "assistant", "content": "Để tôi tra."},
        {"type": "function_call", "call_id": "call_1", "name": "lookup_order", "arguments": '{"order_id": "DH1"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "not found"},
        {"role": "user", "content": "Nhắc: gọi final_answer."},
    ]


RESPONSE_OUTPUT = [
    {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "nghĩ"}], "encrypted_content": "enc"},
    {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "lookup_order",
     "arguments": "{\"order_id\":\"DH1\"}", "status": "completed"},
]


def test_responses_completion_keeps_encrypted_reasoning_for_replay():
    data = {"status": "completed", "output": RESPONSE_OUTPUT, "usage": {"input_tokens": 5, "output_tokens": 7}}
    result = openai_responses.completion_from(data, 1, 0)
    assert result.finish_reason == "tool_calls" and result.message.reasoning == "nghĩ"
    assert result.message.provider_state == {"openai_responses": RESPONSE_OUTPUT}
    _, wire = openai_responses.to_wire([UserMessage(content="q"), result.message])
    assert wire[1:] == RESPONSE_OUTPUT


def test_responses_incomplete_and_refusal():
    cut = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": RESPONSE_OUTPUT}
    result = openai_responses.completion_from(cut, 1, 0)
    assert result.truncated and result.message.tool_calls == () and result.message.provider_state == {}
    refusal = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}
    with pytest.raises(LLMRefusedError):
        openai_responses.completion_from(refusal, 1, 0)
    with pytest.raises(LLMRequestError, match="quota"):
        openai_responses.completion_from({"status": "failed", "error": {"message": "quota"}}, 1, 0)


def test_responses_end_to_end_stream(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    seen: list[httpx2.Request] = []
    response = {
        "id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": "gpt-x",
        "output": RESPONSE_OUTPUT, "usage": {"input_tokens": 5, "output_tokens": 7, "total_tokens": 12},
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
    }
    body = sse([
        ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "m", "output_index": 0,
                                        "content_index": 0, "delta": "Hi", "sequence_number": 1, "logprobs": []}),
        ("response.completed", {"type": "response.completed", "sequence_number": 2, "response": response}),
    ])
    http = mock_http([stream_ok(body)], seen)
    client = openai_responses.OpenAIResponsesClient(config("openai_responses", effort="low"), http_client=http)
    events = collect(client)

    assert events[0].text == "Hi"
    assert events[-1].message.tool_calls[0].id == "call_1"
    sent = json.loads(seen[0].content)
    assert sent["store"] is False and sent["instructions"] == "Bạn là agent."
    assert sent["reasoning"] == {"effort": "low"}
    assert sent["tools"][0] == {**{k: TOOL["function"][k] for k in ("name", "description", "parameters")},
                                "type": "function", "strict": False}


def openai_status_error(cls, status: int):
    response = httpx2.Response(status, request=httpx2.Request("POST", "https://api.openai.com"))
    return cls("boom", response=response, body=None)


def test_openai_error_classes():
    classify = openai_common.classify
    assert isinstance(classify(openai_status_error(openai.AuthenticationError, 401)), LLMAuthError)
    assert classify(openai_status_error(openai.RateLimitError, 429)) is None
    assert classify(openai_status_error(openai.InternalServerError, 500)) is None
    assert isinstance(classify(openai_status_error(openai.BadRequestError, 400)), LLMRequestError)


# --- OpenAI-compatible Chat Completions ----------------------------------------------------


def test_compat_wire_sends_reasoning_only_when_enabled():
    message = AssistantMessage(content="x", reasoning="nghĩ", tool_calls=(CALL,))
    plain = openai_compat.to_wire([message], send_reasoning=False)[0]
    assert "reasoning_content" not in plain and plain["tool_calls"][0]["function"]["name"] == "lookup_order"
    assert openai_compat.to_wire([message], send_reasoning=True)[0]["reasoning_content"] == "nghĩ"
    assert openai_compat.to_wire(HISTORY, send_reasoning=False)[3] == {
        "role": "tool", "tool_call_id": "call_1", "content": "not found",
    }


def chunk(delta=None, finish=None, usage=None):
    choices = [] if delta is None and finish is None else [
        SimpleNamespace(delta=SimpleNamespace(**{"content": None, "tool_calls": None, **(delta or {})}),
                        finish_reason=finish)
    ]
    return SimpleNamespace(choices=choices, usage=usage)


def test_compat_accumulator_treats_a_full_budget_as_truncated_and_filters_as_refusal():
    state = openai_compat.Accumulator()
    state.feed(chunk({"content": "x"}, "tool_calls"))
    state.feed(chunk(usage=SimpleNamespace(prompt_tokens=3, completion_tokens=100)))
    assert state.completion(max_tokens=100, attempts=1, duration_ms=0).truncated
    filtered = openai_compat.Accumulator()
    filtered.feed(chunk({}, "content_filter"))
    with pytest.raises(LLMRefusedError):
        filtered.completion(max_tokens=100, attempts=1, duration_ms=0)


def test_compat_end_to_end_stream(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    seen: list[httpx2.Request] = []

    def data(choices, usage=None):
        return {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m", "choices": choices,
                **({"usage": usage} if usage else {})}

    body = sse([
        (None, data([{"index": 0, "delta": {"role": "assistant", "content": "Hi", "reasoning_content": "r"}, "finish_reason": None}])),
        (None, data([{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                            "function": {"name": "lookup_order", "arguments": "{\"order_id\":"}}]},
                      "finish_reason": None}])),
        (None, data([{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"DH1\"}"}}]},
                      "finish_reason": None}])),
        (None, data([{"index": 0, "delta": {}, "finish_reason": "tool_calls"}])),
        (None, data([], {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})),
        (None, "[DONE]"),
    ])
    http = mock_http([stream_ok(body)], seen)
    client = openai_compat.OpenAICompatClient(
        config("openai_compat", base_url="https://llm.example/v1", capabilities={"parallel_tool_calls": False}),
        http_client=http,
    )
    events = collect(client)

    final = events[-1]
    assert final.finish_reason == "tool_calls" and final.message.reasoning == "r"
    assert json.loads(final.message.tool_calls[0].arguments) == {"order_id": "DH1"}
    assert (final.usage.prompt_tokens, final.usage.completion_tokens) == (5, 7)
    assert str(seen[0].url) == "https://llm.example/v1/chat/completions"
    sent = json.loads(seen[0].content)
    assert sent["parallel_tool_calls"] is False and sent["stream_options"] == {"include_usage": True}
