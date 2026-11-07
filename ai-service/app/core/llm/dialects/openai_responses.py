"""OpenAI Responses API dialect (GPT, o-series).

Runs stateless (`store=False`): the history is replayed every request. Per the OpenAI docs, every
item of a response's `output` goes back untouched, including encrypted reasoning items, so the
model keeps its reasoning across tool calls.
"""

import asyncio
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import openai

from app.core.llm.config import ModelConfig
from app.core.llm.dialects.openai_common import classify, make_client
from app.core.llm.errors import LLMRefusedError, LLMRequestError, LLMStreamInterrupted
from app.core.llm.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.core.llm.retry import stream_with_retries
from app.core.llm.types import (
    Completion,
    ContentDelta,
    FinishReason,
    ReasoningDelta,
    StreamEvent,
    Usage,
)

STATE_KEY = "openai_responses"
_TERMINAL = ("response.completed", "response.incomplete", "response.failed")


class OpenAIResponsesClient:
    def __init__(
        self,
        config: ModelConfig,
        *,
        http_client: Any = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._rand = rand
        self._client = make_client(config, http_client)

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        params = self._params(messages, tools)
        started = time.monotonic()

        async def attempt(number: int) -> AsyncIterator[StreamEvent]:
            final: dict[str, Any] | None = None
            stream = await self._client.responses.create(**params, stream=True)
            async with stream:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        yield ContentDelta(event.delta)
                    elif event.type == "response.reasoning_summary_text.delta":
                        yield ReasoningDelta(event.delta)
                    elif event.type in _TERMINAL:
                        final = event.response.to_dict(mode="json")
                    elif event.type == "error":
                        raise LLMRequestError(f"openai stream error: {getattr(event, 'message', '')}")
            if final is None:
                raise LLMStreamInterrupted("stream ended without a terminal response event")
            duration_ms = round((time.monotonic() - started) * 1000)
            yield completion_from(final, number, duration_ms)

        async for event in stream_with_retries(
            attempt,
            sdk_errors=(openai.APIError,),
            classify=classify,
            config=self._config,
            sleep=self._sleep,
            rand=self._rand,
        ):
            yield event

    def _params(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]] | None
    ) -> dict[str, Any]:
        config = self._config
        instructions, wire = to_wire(messages)
        params: dict[str, Any] = {
            "model": config.model,
            "input": wire,
            "max_output_tokens": config.max_output_tokens,
            "store": False,
        }
        if instructions:
            params["instructions"] = instructions
        if tools:
            params["tools"] = [tool_spec(spec) for spec in tools]
            if not config.capabilities.parallel_tool_calls:
                params["parallel_tool_calls"] = False
        if config.effort and config.capabilities.reasoning_effort:
            params["reasoning"] = {"effort": config.effort}
        return params


def tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Neutral tool spec → Responses function tool.

    `strict` is off: strict mode requires every property to be required, which optional
    arguments and mandate output schemas do not follow. Arguments are validated by the loop.
    """
    function = spec["function"]
    return {
        "type": "function",
        "name": function["name"],
        "description": function["description"],
        "parameters": function["parameters"],
        "strict": False,
    }


def to_wire(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Neutral messages → (instructions, Responses input items)."""
    instructions: list[str] = []
    wire: list[dict[str, Any]] = []
    for message in messages:
        match message:
            case SystemMessage() if not wire:
                instructions.append(message.content)
            case SystemMessage():
                wire.append({"role": "system", "content": message.content})
            case UserMessage():
                wire.append({"role": "user", "content": message.content})
            case AssistantMessage():
                raw = message.provider_state.get(STATE_KEY)
                if raw is not None:
                    wire.extend(raw)
                    continue
                if message.content:
                    wire.append({"role": "assistant", "content": message.content})
                wire.extend(
                    {
                        "type": "function_call",
                        "call_id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in message.tool_calls
                )
            case ToolResultMessage():
                wire.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
    return "\n\n".join(instructions), wire


def completion_from(data: dict[str, Any], attempts: int, duration_ms: int) -> Completion:
    """A Responses `Response` (as a JSON dict) → a neutral `Completion`."""
    status = data.get("status")
    if status == "failed":
        error = data.get("error") or {}
        raise LLMRequestError(f"openai response failed: {error.get('message', 'unknown error')}")
    reason = (data.get("incomplete_details") or {}).get("reason")
    if status == "incomplete" and reason == "content_filter":
        raise LLMRefusedError("openai content filter stopped the response")

    output: list[dict[str, Any]] = data.get("output") or []
    text: list[str] = []
    reasoning: list[str] = []
    calls: list[ToolCall] = []
    for item in output:
        match item.get("type"):
            case "message":
                for part in item.get("content") or []:
                    if part.get("type") == "refusal":
                        raise LLMRefusedError(f"openai refused the request: {part.get('refusal')}")
                    if part.get("type") == "output_text":
                        text.append(part.get("text", ""))
            case "reasoning":
                reasoning.extend(s.get("text", "") for s in item.get("summary") or [])
            case "function_call":
                calls.append(
                    ToolCall(id=item["call_id"], name=item["name"], arguments=item.get("arguments") or "{}")
                )

    finish: FinishReason
    if status == "completed":
        finish = "tool_calls" if calls else "stop"
    elif status == "incomplete" and reason == "max_output_tokens":
        finish = "length"
    else:
        finish = "other"
    truncated = finish == "length"
    message = AssistantMessage(
        content="".join(text),
        reasoning="".join(reasoning),
        tool_calls=() if truncated else tuple(calls),
        # A cut-off turn is not replayed raw: its partial function calls would need outputs
        provider_state={} if truncated else {STATE_KEY: output},
    )
    usage = data.get("usage") or {}
    return Completion(
        message=message,
        finish_reason=finish,
        truncated_tool_calls=tuple(calls) if truncated else (),
        usage=Usage(usage.get("input_tokens") or 0, usage.get("output_tokens") or 0),
        attempts=attempts,
        duration_ms=duration_ms,
    )
