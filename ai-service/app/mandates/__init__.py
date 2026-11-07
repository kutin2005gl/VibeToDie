"""Mandates: one Markdown+XML file per agent = system prompt, tool allowlist and output schema.

File layout (same frontmatter shape as SKILL.md, PLAN-lite §7):
    ---
    name: <file stem>
    description: <when Core should route a step here>
    tools: [tool_a, tool_b]          # may be []
    includes: [_contract, _department]  # optional shared partials, composed after _base
    departments: [cskh, executive]   # optional: who may have requests routed here; [*] = everyone
    model_tier: standard             # strong | standard | cheap
    effort: medium                   # low | medium | high
    ---
    <prompt body; must contain exactly one <output_schema>{json}</output_schema>>

The final system prompt is `_base.md` + each include + the agent body. All are static so the prefix stays
cacheable; per-session data (agent catalog, allowed tools) goes in the input, never here.
Including `_contract` makes the agent a worker: its output also carries `status` + `claims`, which code
checks against the tool trace before Coordinator (or the user) sees the result.

`departments` is checked in code after routing, so a request steered towards an agent its requester
may not use is refused, never run. Agents still have no permissions of their own: their tools run with
the requester's.

A mandate never names a model: the business plugs in its own models, so `model_tier` is mapped to a
model config at deployment time. `effort` is limited to the levels every dialect accepts (Claude and
OpenAI both take low/medium/high) and overrides the model config's default for this agent.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.core import frontmatter

DIR = Path(__file__).parent
BASE = "_base"
CONTRACT = "_contract"
ANY_DEPARTMENT = "*"
MODEL_TIERS = ("strong", "standard", "cheap")
EFFORTS = ("low", "medium", "high")

_OUTPUT_SCHEMA = re.compile(r"<output_schema>\s*(.*?)\s*</output_schema>", re.S)

# Every agent result carries these.
COMMON_OUTPUT = {
    "summary": {"type": "string"},
    "open_questions": {"type": "array", "items": {"type": "string"}},
}

# Result contract for workers (see _contract.md): claims point into the trace so code can verify them.
CONTRACT_OUTPUT = {
    "status": {"type": "string", "enum": ["done", "partial", "blocked", "escalate"]},
    "claims": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "kind": {"type": "string", "enum": ["fact", "conclusion"]},
                "value": {"type": ["string", "number", "integer", "boolean", "null"]},
                "ref": {
                    "type": ["object", "null"],
                    "properties": {"call_id": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["call_id", "path"],
                },
                "derived_from": {"type": "array", "items": {"type": "string"}},
                "reasoning": {"type": ["string", "null"]},
            },
            "required": ["key", "kind", "value", "ref", "derived_from", "reasoning"],
        },
    },
}


class MandateError(ValueError):
    pass


@dataclass(frozen=True)
class Mandate:
    name: str
    description: str
    tools: tuple[str, ...]
    includes: tuple[str, ...]
    departments: tuple[str, ...]
    model_tier: str
    effort: str
    system_prompt: str
    output_schema: dict

    def usable_by(self, departments: tuple[str, ...]) -> bool:
        """Whether a requester in `departments` may have requests handled by this agent."""
        return ANY_DEPARTMENT in self.departments or any(d in self.departments for d in departments)


def names() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.md") if not p.stem.startswith("_"))


def load(name: str) -> Mandate:
    path = DIR / f"{name}.md"
    if name.startswith("_") or not path.is_file():
        raise MandateError(f"unknown mandate {name!r}")
    return parse(name, _read(path))


def parse(name: str, text: str) -> Mandate:
    """A mandate from the text of its file: `load` reads one here, Factory's agents come from the database."""
    meta, body = _split(text)

    for key in ("name", "description", "tools", "model_tier", "effort"):
        if key not in meta:
            raise MandateError(f"{name}: frontmatter missing {key!r}")
    if meta["model_tier"] not in MODEL_TIERS:
        raise MandateError(f"{name}: model_tier must be one of {', '.join(MODEL_TIERS)}")
    if meta["effort"] not in EFFORTS:
        raise MandateError(f"{name}: effort must be one of {', '.join(EFFORTS)}")
    if meta["name"] != name:
        raise MandateError(f"{name}: frontmatter name {meta['name']!r} != file name")
    if not isinstance(meta["tools"], list):
        raise MandateError(f"{name}: tools must be a [list]")
    includes = meta.get("includes", [])
    if not isinstance(includes, list) or any(not i.startswith("_") or i == BASE for i in includes):
        raise MandateError(f"{name}: includes must be a [list] of _partials other than {BASE}")
    departments = meta.get("departments", [])
    if not isinstance(departments, list):
        raise MandateError(f"{name}: departments must be a [list]")

    parts = [BASE, *includes]
    for part in parts:
        if not (DIR / f"{part}.md").is_file():
            raise MandateError(f"{name}: unknown include {part!r}")
    prompt = [_split(_read(DIR / f"{part}.md"))[1] for part in parts] + [body]

    return Mandate(
        name=name,
        description=meta["description"],
        tools=tuple(meta["tools"]),
        includes=tuple(includes),
        departments=tuple(departments),
        model_tier=meta["model_tier"],
        effort=meta["effort"],
        system_prompt="\n\n".join(p.strip() for p in prompt) + "\n",
        output_schema=_output_schema(name, body, {**COMMON_OUTPUT, **(CONTRACT_OUTPUT if CONTRACT in includes else {})}),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _split(text: str) -> tuple[dict, str]:
    try:
        return frontmatter.split(text)
    except frontmatter.FrontmatterError as e:
        raise MandateError(str(e)) from e


def _output_schema(name: str, body: str, common: dict) -> dict:
    blocks = _OUTPUT_SCHEMA.findall(body)
    if len(blocks) != 1:
        raise MandateError(f"{name}: need exactly one <output_schema> block, found {len(blocks)}")
    try:
        schema = json.loads(blocks[0])
    except json.JSONDecodeError as e:
        raise MandateError(f"{name}: <output_schema> is not valid JSON: {e}") from e
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise MandateError(f"{name}: <output_schema> must be an object schema with properties")
    clash = (COMMON_OUTPUT.keys() | CONTRACT_OUTPUT.keys()) & schema["properties"].keys()
    if clash:
        raise MandateError(f"{name}: <output_schema> redefines common fields {sorted(clash)}")
    return {
        **schema,
        "properties": {**common, **schema["properties"]},
        "required": [*common, *schema.get("required", [])],
    }
