"""Offline model client that replays scripted completions (tests and UI work, never FR-23 evidence)."""

import json
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any

from app.core.llm.errors import LLMRequestError
from app.core.llm.messages import AssistantMessage, Message, ToolCall
from app.core.llm.types import Completion, FinishReason, StreamEvent, Usage


class ScriptedClient:
    """Returns the scripted completions in order and records what the model was shown."""

    def __init__(self, completions: Iterable[Completion]) -> None:
        self._completions = iter(completions)
        self.seen: list[tuple[tuple[Message, ...], tuple[dict[str, Any], ...]]] = []

    async def stream(
        self, messages: Sequence[Message], tools: Sequence[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.seen.append((tuple(messages), tuple(tools or ())))
        completion = next(self._completions, None)
        if completion is None:
            raise LLMRequestError("scripted client ran out of completions")
        yield completion


def schema_answer_client(output_schema: dict[str, Any]) -> ScriptedClient:
    """A client whose only reply is a `final_answer` that satisfies `output_schema`.

    Lets the offline `fake` provider run any mandate end to end without an API key.
    """
    return ScriptedClient([completion(call("fake-final", "final_answer", example_for(output_schema)))])


def example_for(schema: dict[str, Any]) -> Any:
    """The smallest value matching `schema`, for the JSON Schema subset mandates use."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        if "null" in kind:
            return None
        kind = kind[0]
    if kind == "object":
        properties = schema.get("properties", {})
        return {name: example_for(properties.get(name, {})) for name in schema.get("required", [])}
    if kind == "array":
        return []
    if kind == "string":
        return "[FAKE]"
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    return None


def call(id: str, name: str, arguments: Any = None) -> ToolCall:
    """A tool call; `arguments` is JSON-encoded unless it is already a string."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    return ToolCall(id=id, name=name, arguments=raw)


def completion(
    *calls: ToolCall,
    content: str = "",
    finish_reason: FinishReason | None = None,
    usage: Usage | None = None,
) -> Completion:
    """A model response; with `finish_reason="length"` its calls are truncated, as a dialect does."""
    finish = finish_reason or ("tool_calls" if calls else "stop")
    truncated = finish == "length"
    return Completion(
        message=AssistantMessage(content=content, tool_calls=() if truncated else calls),
        finish_reason=finish,
        truncated_tool_calls=calls if truncated else (),
        usage=usage or Usage(),
        attempts=1,
        duration_ms=0,
    )
