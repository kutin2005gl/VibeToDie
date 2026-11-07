"""What every dialect client emits, and the protocol the agent loop depends on."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.core.llm.messages import AssistantMessage, Message, ToolCall

FinishReason = Literal["stop", "tool_calls", "length", "other"]


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class ContentDelta:
    text: str


@dataclass(frozen=True)
class Completion:
    """Always the last event of a stream."""

    message: AssistantMessage
    finish_reason: FinishReason
    # Tool calls cut off by the output token limit. They are kept for the trace but never appear
    # in `message.tool_calls`, so the agent loop cannot execute them.
    truncated_tool_calls: tuple[ToolCall, ...]
    usage: Usage
    attempts: int
    duration_ms: int

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


StreamEvent = ReasoningDelta | ContentDelta | Completion


class ModelClient(Protocol):
    """One model behind one dialect. The loop uses only this, so tests can script the model."""

    def stream(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Delta events, then exactly one `Completion`. Raises `LLMError` on failure."""
        ...
