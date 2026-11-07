"""Factory: designs an agent a request needs when no agent the requester may use can do the work.

The design is model output, so code compiles it into a mandate the same way a mandate file is read
(`mandates.parse`), with its text kept as prompt (never frontmatter or markup) and its tools limited
to the ones the requester may use already. The requester approves it before it ever runs; approved,
it is theirs only, and checked again against their tools each time it is loaded (PLAN-lite §Skill).
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app import mandates
from app.core import router
from app.core.agent import RunFinished
from app.core.context import RequestContext
from app.core.coordinator import Verify
from app.core.llm import Message, SystemMessage, UserMessage
from app.store.sessions import SessionStore
from app.tools import build_tools

log = logging.getLogger(__name__)

FACTORY = "factory"
NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
DESIGN_FIELDS = {"name", "description", "tools", "role", "procedure", "business_rules", "output_schema"}
# Choices Jev is offered beside the agents: an agent named like one would be mistaken for it
RESERVED = {router.POLICY, router.MULTI, router.NO_AGENT}
# How much a model may write into an agent's prompt
MAX_TEXT = 2000
MAX_LINES = 12
MAX_TOOLS = 8
MAX_SCHEMA_CHARS = 8000

RunAgent = Callable[[mandates.Mandate, list[Message], Verify], Awaitable[RunFinished]]


@dataclass(frozen=True)
class OwnAgents:
    """The requester's own agents for one run: the approved ones, and every name a new one may not take."""

    agents: list[mandates.Mandate] = field(default_factory=list)
    taken: set[str] = field(default_factory=set)


def allowed_tools(ctx: RequestContext) -> set[str]:
    """The tools the requester may give a new agent: those of the worker agents they may use already."""
    workers = (m for m in map(mandates.load, mandates.names()) if "claims" in m.output_schema["properties"])
    return {tool for m in workers if m.usable_by(ctx.departments) for tool in m.tools}


def compile(design: Any, taken: set[str], allowed: set[str]) -> mandates.Mandate:
    """The mandate of a Factory design; MandateError says what is wrong with it, for the model to fix."""
    if not isinstance(design, dict) or set(design) != DESIGN_FIELDS:
        raise mandates.MandateError(f"agent needs exactly the fields {', '.join(sorted(DESIGN_FIELDS))}")
    name = design["name"]
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise mandates.MandateError("agent name must be snake_case, 3-40 characters")
    if name in taken or name in RESERVED or name in mandates.names():
        raise mandates.MandateError(f"agent name {name!r} is already taken; choose another")
    description = design["description"]
    if not _text(description) or not description.startswith("Use when ") or "Not for " not in description:
        raise mandates.MandateError("description must be one text in the form 'Use when … Not for …'")
    if not _text(design["role"]):
        raise mandates.MandateError(f"role must be a non-empty text of at most {MAX_TEXT} characters")
    for key in ("procedure", "business_rules"):
        lines = design[key]
        if not isinstance(lines, list) or len(lines) > MAX_LINES or not all(_text(line) for line in lines):
            raise mandates.MandateError(f"{key} must be a list of at most {MAX_LINES} non-empty texts")
    if not design["procedure"] or "final_answer" not in design["procedure"][-1]:
        raise mandates.MandateError("the last procedure step must call final_answer")
    tools = design["tools"]
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools) or len(set(tools)) != len(tools) \
            or len(tools) > MAX_TOOLS:
        raise mandates.MandateError(f"tools must be a list of at most {MAX_TOOLS} distinct tool names")
    if set(tools) - allowed:
        raise mandates.MandateError(f"tools not in <allowed_tools>: {', '.join(sorted(set(tools) - allowed))}")
    schema = json.dumps(design["output_schema"], ensure_ascii=False)
    if len(schema) > MAX_SCHEMA_CHARS or "$ref" in schema:
        raise mandates.MandateError(f"output_schema must be at most {MAX_SCHEMA_CHARS} characters, without $ref")
    try:
        Draft202012Validator.check_schema(design["output_schema"])
    except SchemaError as e:
        raise mandates.MandateError(f"output_schema is not a valid JSON schema: {e.message}") from e

    # Model text becomes prompt only: one line in the frontmatter, no tag of its own in the body
    # (JSON may spell `<` as <, so the schema cannot close its block either)
    schema = schema.replace("<", "\\u003c")
    steps = "\n".join(f"{n}. {_prompt(step)}" for n, step in enumerate(design["procedure"], 1))
    rules = "\n".join(f"- {_prompt(rule)}" for rule in design["business_rules"])
    text = (f"---\nname: {name}\ndescription: {' '.join(description.split())}\ntools: [{', '.join(tools)}]\n"
            f"includes: [_contract, _department]\ndepartments: [{mandates.ANY_DEPARTMENT}]\n"
            f"model_tier: standard\neffort: medium\n---\n"
            f"<role>\n{_prompt(design['role'])}\n</role>\n\n<procedure>\n{steps}\n</procedure>\n\n"
            f"<business_rules>\n{rules}\n</business_rules>\n\n"
            f"<output_schema>\n{schema}\n</output_schema>\n")
    return mandates.parse(name, text)


async def own_agents(store: SessionStore, ctx: RequestContext) -> OwnAgents:
    """The requester's approved agents, each checked again against the tools they may use now: one
    asking for a tool they lost (another department, say) is left out rather than granted it."""
    allowed = allowed_tools(ctx)
    agents = []
    for row in await store.agents_of(ctx.user_id):
        try:
            agents.append(compile(row["design"], set(), allowed))
        except mandates.MandateError as e:
            log.warning("agent %s of %s left out: %s", row["name"], ctx.user_id, e)
    return OwnAgents(agents, await store.agent_names(ctx.user_id))


async def draft(text: str, clarifications: Sequence[dict[str, str]], agent_request: dict[str, Any],
                catalog: Sequence[mandates.Mandate], unavailable: Sequence[mandates.Mandate],
                ctx: RequestContext, own: OwnAgents, run_agent: RunAgent) -> RunFinished:
    """Run Factory for `agent_request`; a `create` it ends on has passed `compile`."""
    mandate = mandates.load(FACTORY)
    allowed = allowed_tools(ctx)
    usable = {m.name for m in catalog}
    wanted = {"create": "agent", "use_existing": "existing_agent", "reject": None}

    def verify(answer: dict[str, Any], history: Sequence[Message]) -> str | None:
        decision = answer["decision"]
        for key in ("agent", "existing_agent"):
            if (answer[key] is not None) != (key == wanted[decision]):
                return f"- decision '{decision}' needs {wanted[decision] or 'neither agent nor existing_agent'}; " \
                       f"set the other fields to null"
        if decision == "create":
            try:
                compile(answer["agent"], own.taken, allowed)
            except mandates.MandateError as e:
                return f"- {e}"
        if decision == "use_existing" and answer["existing_agent"] not in usable:
            return "- existing_agent must be the name of an agent in <agent_catalog>"
        return None

    described = lambda agents: [{"name": m.name, "description": m.description} for m in agents]
    tools = [{"name": t.name, "description": t.description.render()} for t in build_tools(tuple(sorted(allowed)), ctx)]
    blocks = [
        "<task>Design the agent; do not do the work.</task>",
        _block("agent_request", agent_request),
        _untrusted(text, "untrusted_input"),
        *([_untrusted(json.dumps(list(clarifications), ensure_ascii=False), "clarifications")] if clarifications else []),
        _block("agent_catalog", described(catalog)),
        _block("unavailable_agents", described(unavailable)),
        _block("allowed_tools", tools),
    ]
    messages: list[Message] = [SystemMessage(content=mandate.system_prompt), UserMessage(content="\n".join(blocks))]
    return await run_agent(mandate, messages, verify)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT


def _prompt(text: str) -> str:
    """Model-written text inside the new agent's prompt: it cannot open or close a tag."""
    return text.replace("<", "&lt;")


def _block(tag: str, value: Any) -> str:
    return f"<{tag}>\n{json.dumps(value, ensure_ascii=False)}\n</{tag}>"


def _untrusted(text: str, tag: str) -> str:
    """Staff-written text as data: it cannot close its own tag."""
    return f"<{tag}>\n{text.replace(f'</{tag}>', f'&lt;/{tag}&gt;')}\n</{tag}>"
