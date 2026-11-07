"""Tool framework (ported from ref/core): what a tool is, and how its failures reach the model.

Book ch05 §5.1.5: a tool failure is an observation the model can act on, never a crashed run, so
every error says what went wrong and what to do next.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode
from pydantic_core import CoreSchema

_Text = Annotated[str, Field(min_length=1)]


class ToolDescription(BaseModel):
    """The description template every tool fills in (book ch04 §4.2.2).

    Every section is required, so a one-line description fails when the tool is defined, not when
    the model later guesses wrong. `render` is deterministic, so the tool list sent each step is
    byte-identical and stays in the KV cache.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: _Text
    when_to_use: _Text
    when_not_to_use: _Text
    returns: _Text
    cost: _Text
    # Example calls, e.g. `lookup_order(order_id="DH123")`
    examples: Annotated[tuple[_Text, ...], Field(min_length=1, max_length=5)]

    def render(self) -> str:
        examples = "\n".join(f"- {example}" for example in self.examples)
        return (
            f"{self.summary}\n\n"
            f"When to use:\n{self.when_to_use}\n\n"
            f"When not to use:\n{self.when_not_to_use}\n\n"
            f"Returns:\n{self.returns}\n\n"
            f"Cost:\n{self.cost}\n\n"
            f"Examples:\n{examples}"
        )


@dataclass(frozen=True)
class ToolResult:
    # What the model reads as the observation of its call
    content: str
    is_error: bool = False


class Tool(Protocol):
    """What the agent loop needs from a tool."""

    @property
    def name(self) -> str: ...

    @property
    def spec(self) -> dict[str, Any]:
        """The function definition sent to the model (OpenAI function shape; dialects convert it)."""
        ...

    @property
    def high_risk(self) -> bool:
        """True for actions with external side effects: the loop queues them for approval."""
        ...

    def validate(self, arguments: str) -> ToolResult | None:
        """The invalid_arguments observation when `arguments` break the schema, else None."""
        ...

    async def run(self, arguments: str, key: str | None = None) -> ToolResult:
        """Run with the raw JSON arguments the model produced; `key` is set only for a high-risk
        call staff approved, the same on every attempt at that one action."""
        ...


ErrorKind = Literal[
    "invalid_arguments", "tool_error", "permission_denied", "unknown_tool", "internal_error"
]


class ToolError(Exception):
    """An expected failure a tool reports, such as an order that does not exist."""

    kind: ErrorKind = "tool_error"

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class PermissionDenied(ToolError):
    """The requesting user may not see this data. The model must not look for another way in."""

    kind: ErrorKind = "permission_denied"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            "Do not try another tool, query or agent for the same data. Record the missing "
            "permission in open_questions and set status to blocked.",
        )


def format_error(kind: ErrorKind, message: str, hint: str) -> str:
    """The one shape every tool error takes in the model's context."""
    return f"Error ({kind}): {message}\nHint: {hint}"


class ToolArgs(BaseModel):
    """Base for a tool's arguments: a misspelt or invented argument is an error, not ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _NoTitles(GenerateJsonSchema):
    """Leaves out the titles pydantic derives from names ("Path" for `path`): tokens, no meaning."""

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False

    def generate(self, schema: CoreSchema, mode: JsonSchemaMode = "validation") -> dict[str, Any]:
        json_schema = super().generate(schema, mode)
        json_schema.pop("title", None)
        return json_schema


class BaseTool[ArgsT: ToolArgs](ABC):
    """A tool whose arguments are a pydantic model; subclasses fill in the class attributes.

    The spec is built once, so it is byte-identical on every step.
    """

    name: ClassVar[str]
    description: ClassVar[ToolDescription]
    args_model: type[ArgsT]
    # Side effects outside the system (send a message, change an order): never run by the loop,
    # queued for staff approval instead (PLAN-lite §7)
    high_risk: ClassVar[bool] = False

    def __init__(self) -> None:
        self._spec: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description.render(),
                "parameters": self.args_model.model_json_schema(schema_generator=_NoTitles),
            },
        }

    @property
    def spec(self) -> dict[str, Any]:
        return self._spec

    @abstractmethod
    async def execute(self, args: ArgsT) -> ToolResult | str:
        """The tool's work, run with arguments that are already validated."""

    async def execute_approved(self, args: ArgsT, key: str) -> ToolResult | str:
        """A high-risk call staff approved. A tool that can pass `key` on (a message id, an
        idempotency header) overrides this, so the same action never happens twice."""
        return await self.execute(args)

    def _parse(self, arguments: str) -> ArgsT | ToolResult:
        try:
            return self.args_model.model_validate_json(arguments, strict=True)
        except ValidationError as exc:
            problems = "\n".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}"
                for error in exc.errors()
            )
            content = format_error(
                "invalid_arguments",
                problems,
                "Fix these arguments to match the tool's schema and call it again.",
            )
            return ToolResult(content=content, is_error=True)

    def validate(self, arguments: str) -> ToolResult | None:
        parsed = self._parse(arguments)
        return parsed if isinstance(parsed, ToolResult) else None

    async def run(self, arguments: str, key: str | None = None) -> ToolResult:
        args = self._parse(arguments)
        if isinstance(args, ToolResult):
            return args

        try:
            result = await (self.execute(args) if key is None else self.execute_approved(args, key))
        except ToolError as exc:
            content = format_error(exc.kind, exc.message, exc.hint)
            return ToolResult(content=content, is_error=True)

        if isinstance(result, str):
            return ToolResult(result)
        return result
