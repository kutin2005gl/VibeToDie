"""Provider-neutral message model for trajectories (ported from ref/core).

Wire formats are produced from these types by each dialect; nothing here depends on a provider.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ToolCall(_Frozen):
    id: str
    name: str
    # Raw JSON exactly as the model produced it; schema validation belongs to the tool layer
    arguments: str


class SystemMessage(_Frozen):
    role: Literal["system"] = "system"
    content: str


class UserMessage(_Frozen):
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(_Frozen):
    role: Literal["assistant"] = "assistant"
    content: str = ""
    # Readable reasoning, for traces and for dialects that send it back as plain text
    reasoning: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    # Opaque data a dialect must send back verbatim on the next request (e.g. Claude thinking
    # blocks with their signature). It is only valid for the model config that produced it,
    # which is why a run is pinned to one model config.
    provider_state: dict[str, Any] = Field(default_factory=dict)


class ToolResultMessage(_Frozen):
    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str
    # Dialects that support it (Anthropic) flag the result as an error to the model
    is_error: bool = False


Message = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolResultMessage,
    Field(discriminator="role"),
]
