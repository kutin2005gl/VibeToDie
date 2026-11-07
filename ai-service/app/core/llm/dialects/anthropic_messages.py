"""Anthropic Messages API dialect (Claude).

Rules from the Claude API docs:
- the assistant turn goes back as the full `response.content`, so thinking blocks keep their
  signature and fallback blocks are echoed; the history is append-only, because editing an
  earlier turn invalidates thinking blocks
- all tool results of a turn go back in one user message
- check `max_tokens` and `refusal` before running any tool call of the turn
"""

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import anthropic

from app.core.llm.config import ModelConfig, resolve_api_key
from app.core.llm.errors import LLMAuthError, LLMError, LLMRefusedError, LLMRequestError
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

STATE_KEY = "anthropic"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_FINISH: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
}


class AnthropicClient:
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
        # The SDK's own retries are off: attempts are counted in `stream_with_retries`
        self._client = anthropic.AsyncAnthropic(
            api_key=resolve_api_key(config.api_key_ref),
            base_url=config.base_url,
            max_retries=0,
            timeout=anthropic.Timeout(config.read_timeout, connect=config.connect_timeout),
            http_client=http_client,
        )

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        params = self._params(messages, tools)
        started = time.monotonic()

        async def attempt(number: int) -> AsyncIterator[StreamEvent]:
            async with self._client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type == "text_delta":
                        yield ContentDelta(event.delta.text)
                    elif event.delta.type == "thinking_delta" and event.delta.thinking:
                        yield ReasoningDelta(event.delta.thinking)
                message = await stream.get_final_message()
            duration_ms = round((time.monotonic() - started) * 1000)
            yield completion_from(message.to_dict(mode="json"), number, duration_ms)

        async for event in stream_with_retries(
            attempt,
            sdk_errors=(anthropic.APIError,),
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
        system, wire = to_wire(messages)
        params: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_output_tokens,
            "messages": wire,
            # Caches the longest stable prefix: system prompt and tool list never change in a run
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [tool_spec(spec) for spec in tools]
            if not config.capabilities.parallel_tool_calls:
                params["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        if config.effort and config.capabilities.reasoning_effort:
            params["output_config"] = {"effort": config.effort}
        if config.fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = config.fallbacks
        return params


def tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Neutral (OpenAI function) tool spec → Anthropic tool definition."""
    function = spec["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


def to_wire(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Neutral messages → (system prompt, Anthropic messages)."""
    system: list[str] = []
    wire: list[dict[str, Any]] = []
    for message in messages:
        match message:
            case SystemMessage() if not wire:
                system.append(message.content)
            case SystemMessage():
                # Mid-conversation operator instruction, on the models that support it
                wire.append({"role": "system", "content": message.content})
            case AssistantMessage():
                wire.append({"role": "assistant", "content": _assistant_content(message)})
            case ToolResultMessage():
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
                if message.is_error:
                    block["is_error"] = True
                _user_blocks(wire).append(block)
            case UserMessage():
                # A notice after tool results joins their user message instead of splitting it
                _user_blocks(wire).append({"type": "text", "text": message.content})
    return "\n\n".join(system), wire


def _assistant_content(message: AssistantMessage) -> list[dict[str, Any]]:
    # Same model, same run: replay exactly what the API returned (thinking signatures included)
    raw = message.provider_state.get(STATE_KEY)
    if raw is not None:
        return raw
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    for call in message.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": json.loads(call.arguments)}
        )
    return blocks


def _user_blocks(wire: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if wire and wire[-1]["role"] == "user":
        return wire[-1]["content"]
    message: dict[str, Any] = {"role": "user", "content": []}
    wire.append(message)
    return message["content"]


def completion_from(data: dict[str, Any], attempts: int, duration_ms: int) -> Completion:
    """An Anthropic message (as a JSON dict) → a neutral `Completion`."""
    stop_reason = data.get("stop_reason")
    if stop_reason == "refusal":
        category = (data.get("stop_details") or {}).get("category")
        raise LLMRefusedError(f"anthropic refused the request (category={category})")
    blocks: list[dict[str, Any]] = data.get("content") or []
    calls = tuple(
        ToolCall(id=b["id"], name=b["name"], arguments=json.dumps(b.get("input") or {}, ensure_ascii=False))
        for b in blocks
        if b.get("type") == "tool_use"
    )
    finish = _FINISH.get(stop_reason or "", "other")
    truncated = finish == "length"
    message = AssistantMessage(
        content="".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
        reasoning="".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking"),
        tool_calls=() if truncated else calls,
        # A cut-off turn is not replayed raw: its partial tool_use blocks would need results
        # for calls that never ran. Dropping them only drops that turn's own reasoning
        provider_state={} if truncated else {STATE_KEY: blocks},
    )
    usage = data.get("usage") or {}
    prompt = sum(
        usage.get(key) or 0
        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    return Completion(
        message=message,
        finish_reason=finish,
        truncated_tool_calls=calls if truncated else (),
        usage=Usage(prompt, usage.get("output_tokens") or 0),
        attempts=attempts,
        duration_ms=duration_ms,
    )


def classify(exc: Exception) -> LLMError | None:
    """Fatal error for `exc`, or None when a retry may help (429, 5xx incl. 529, network)."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return LLMAuthError(f"anthropic {exc.status_code}: {exc.message}", exc.status_code)
    if isinstance(exc, anthropic.APIConnectionError):
        return None
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 429 or exc.status_code >= 500:
            return None
        return LLMRequestError(f"anthropic {exc.status_code}: {exc.message}", exc.status_code)
    return LLMRequestError(f"anthropic error: {exc}")
