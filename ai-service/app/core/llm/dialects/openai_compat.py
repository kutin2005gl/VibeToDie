"""OpenAI-compatible Chat Completions dialect (ported from ref/core/llm/client.py).

Covers DeepSeek, Qwen, Mistral, Groq, OpenRouter, Gemini's OpenAI endpoint and self-hosted
vLLM/Ollama: anything that speaks `POST /chat/completions` with streaming tool calls.
"""

import asyncio
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import openai

from app.core.llm.config import ModelConfig
from app.core.llm.dialects.openai_common import classify, make_client
from app.core.llm.errors import LLMRefusedError, LLMStreamInterrupted
from app.core.llm.messages import AssistantMessage, Message, ToolCall, ToolResultMessage
from app.core.llm.retry import stream_with_retries
from app.core.llm.types import (
    Completion,
    ContentDelta,
    FinishReason,
    ReasoningDelta,
    StreamEvent,
    Usage,
)


class OpenAICompatClient:
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
        config = self._config
        params: dict[str, Any] = {
            "model": config.model,
            "messages": to_wire(messages, send_reasoning=config.capabilities.send_reasoning_back),
            "max_tokens": config.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = list(tools)
            if not config.capabilities.parallel_tool_calls:
                params["parallel_tool_calls"] = False
        if config.effort and config.capabilities.reasoning_effort:
            params["reasoning_effort"] = config.effort
        started = time.monotonic()

        async def attempt(number: int) -> AsyncIterator[StreamEvent]:
            state = Accumulator()
            chunks = await self._client.chat.completions.create(**params)
            try:
                async for chunk in chunks:
                    for event in state.feed(chunk):
                        yield event
            finally:
                await chunks.close()
            if state.finish_reason is None:
                raise LLMStreamInterrupted("stream ended without a finish_reason")
            duration_ms = round((time.monotonic() - started) * 1000)
            yield state.completion(config.max_output_tokens, number, duration_ms)

        async for event in stream_with_retries(
            attempt,
            sdk_errors=(openai.APIError,),
            classify=classify,
            config=config,
            sleep=self._sleep,
            rand=self._rand,
        ):
            yield event


def to_wire(messages: Sequence[Message], *, send_reasoning: bool) -> list[dict[str, Any]]:
    """Neutral messages → Chat Completions messages."""
    wire: list[dict[str, Any]] = []
    for message in messages:
        match message:
            case AssistantMessage():
                item: dict[str, Any] = {"role": "assistant", "content": message.content}
                if send_reasoning and message.reasoning:
                    item["reasoning_content"] = message.reasoning
                if message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                        for call in message.tool_calls
                    ]
            case ToolResultMessage():
                item = {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            case _:
                item = {"role": message.role, "content": message.content}
        wire.append(item)
    return wire


def _reasoning_text(delta: Any) -> str:
    """Providers have used both `reasoning_content` and `reasoning` for the thinking text."""
    for name in ("reasoning_content", "reasoning"):
        value = getattr(delta, name, None)
        if isinstance(value, str) and value:
            return value
    return ""


@dataclass
class _PartialCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=lambda: [])


@dataclass
class Accumulator:
    """Assembles one streamed response and turns chunks into delta events."""

    content: list[str] = field(default_factory=lambda: [])
    reasoning: list[str] = field(default_factory=lambda: [])
    calls: dict[int, _PartialCall] = field(default_factory=lambda: {})
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)

    def feed(self, chunk: Any) -> list[StreamEvent]:
        if chunk.usage:
            self.usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
        events: list[StreamEvent] = []
        for choice in chunk.choices:
            delta = choice.delta
            if reasoning := _reasoning_text(delta):
                self.reasoning.append(reasoning)
                events.append(ReasoningDelta(reasoning))
            if delta.content:
                self.content.append(delta.content)
                events.append(ContentDelta(delta.content))
            # Fragments of one call share an index: id and name come first, arguments in pieces
            for fragment in delta.tool_calls or []:
                call = self.calls.setdefault(fragment.index, _PartialCall())
                if fragment.id:
                    call.id = fragment.id
                if fragment.function and fragment.function.name:
                    call.name = fragment.function.name
                if fragment.function and fragment.function.arguments:
                    call.arguments.append(fragment.function.arguments)
            if choice.finish_reason:
                self.finish_reason = choice.finish_reason
        return events

    def completion(self, max_tokens: int, attempts: int, duration_ms: int) -> Completion:
        raw = self.finish_reason or ""
        if raw == "content_filter":
            raise LLMRefusedError("the provider's content filter stopped the response")
        finish: FinishReason = raw if raw in ("stop", "tool_calls", "length") else "other"  # type: ignore[assignment]
        # Some servers (vLLM) report "tool_calls" even when the output hit max_tokens, so a
        # response that used the whole budget is treated as truncated whatever the server says
        if self.usage.completion_tokens >= max_tokens:
            finish = "length"
        calls = tuple(
            ToolCall(id=call.id, name=call.name, arguments="".join(call.arguments))
            for _, call in sorted(self.calls.items())
        )
        truncated = finish == "length"
        message = AssistantMessage(
            content="".join(self.content),
            reasoning="".join(self.reasoning),
            tool_calls=() if truncated else calls,
        )
        return Completion(
            message=message,
            finish_reason=finish,
            truncated_tool_calls=calls if truncated else (),
            usage=self.usage,
            attempts=attempts,
            duration_ms=duration_ms,
        )
