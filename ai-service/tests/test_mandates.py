import pytest

from app import mandates
from app.mandates import COMMON_OUTPUT, CONTRACT_OUTPUT, EFFORTS, MODEL_TIERS, MandateError

GOOD = """---
name: demo
description: Dùng khi test.
tools: [a, b]
model_tier: standard
effort: medium
---
# Vai trò
<role>demo</role>
<output_schema>
{"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
</output_schema>
"""


@pytest.fixture
def mandate_dir(tmp_path, monkeypatch):
    (tmp_path / "_base.md").write_text("# Base\n<system_context>chung</system_context>\n", encoding="utf-8")
    monkeypatch.setattr(mandates, "DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("name", mandates.names())
def test_every_shipped_mandate_loads(name):
    m = mandates.load(name)
    assert m.name == name and m.description and isinstance(m.tools, tuple)
    assert m.system_prompt.startswith("# System context")  # _base.md comes first
    assert "<role>" in m.system_prompt and "<output_schema>" in m.system_prompt
    assert m.output_schema["required"][:len(COMMON_OUTPUT)] == list(COMMON_OUTPUT)
    assert m.model_tier in MODEL_TIERS and m.effort in EFFORTS


def test_planning_agents_get_the_strong_tier_and_lookup_the_cheap_one():
    assert (mandates.load("coordinator").model_tier, mandates.load("coordinator").effort) == ("strong", "high")
    assert (mandates.load("factory").model_tier, mandates.load("factory").effort) == ("strong", "high")
    assert (mandates.load("knowledge").model_tier, mandates.load("knowledge").effort) == ("cheap", "low")


def test_shipped_mandates():
    assert mandates.names() == [
        "compactor", "coordinator", "customer_service", "executive",
        "factory", "it_support", "knowledge", "orders",
    ]


@pytest.mark.parametrize("name, is_worker, is_department", [
    ("customer_service", True, True), ("orders", True, True),
    ("executive", True, True), ("it_support", True, True),
    ("knowledge", True, False),
    ("coordinator", False, False), ("factory", False, False), ("compactor", False, False),
])
def test_partials_match_agent_kind(name, is_worker, is_department):
    m = mandates.load(name)
    assert ("<result_contract>" in m.system_prompt) is is_worker
    assert (set(CONTRACT_OUTPUT) <= set(m.output_schema["required"])) is is_worker
    assert ("<consult_policy>" in m.system_prompt) is is_department
    if is_department:
        assert m.system_prompt.index("<result_contract>") < m.system_prompt.index("<department_scope>")
        # _base.md mentions "<role>" in prose, so match the real opening tag on its own line
        assert m.system_prompt.index("<department_scope>") < m.system_prompt.index("\n<role>\n")


def test_load_merges_common_fields_and_handles_crlf(mandate_dir):
    (mandate_dir / "demo.md").write_text(GOOD.replace("\n", "\r\n"), encoding="utf-8")
    m = mandates.load("demo")
    assert m.tools == ("a", "b")
    assert m.system_prompt.startswith("# Base")
    assert m.output_schema["required"] == ["summary", "open_questions", "x"]
    assert set(m.output_schema["properties"]) == {"summary", "open_questions", "x"}


def test_contract_tells_the_model_to_cite_tools_by_name():
    prompt = mandates.load("customer_service").system_prompt
    assert "tool's NAME" in prompt and "lookup_order#2" in prompt


def test_contract_include_adds_status_and_claims(mandate_dir):
    (mandate_dir / "_contract.md").write_text("<result_contract>c</result_contract>\n", encoding="utf-8")
    (mandate_dir / "demo.md").write_text(GOOD.replace("tools: [a, b]", "tools: [a]\nincludes: [_contract]"), encoding="utf-8")
    m = mandates.load("demo")
    assert m.output_schema["required"] == ["summary", "open_questions", "status", "claims", "x"]
    assert m.output_schema["properties"]["claims"] is CONTRACT_OUTPUT["claims"]


def test_includes_are_composed_between_base_and_body(mandate_dir):
    (mandate_dir / "_part.md").write_text("<part>p</part>\n", encoding="utf-8")
    (mandate_dir / "demo.md").write_text(GOOD.replace("tools: [a, b]", "tools: []\nincludes: [_part]"), encoding="utf-8")
    m = mandates.load("demo")
    assert m.tools == ()
    assert m.system_prompt.index("chung") < m.system_prompt.index("<part>") < m.system_prompt.index("<role>")


@pytest.mark.parametrize("broken, msg", [
    (GOOD.replace("name: demo", "name: other"), "!= file name"),
    (GOOD.replace("tools: [a, b]\n", ""), "missing 'tools'"),
    (GOOD.replace("model_tier: standard\n", ""), "missing 'model_tier'"),
    (GOOD.replace("effort: medium\n", ""), "missing 'effort'"),
    (GOOD.replace("model_tier: standard", "model_tier: claude-opus-5-5"), "model_tier must be one of"),
    (GOOD.replace("effort: medium", "effort: xhigh"), "effort must be one of"),
    (GOOD.replace("tools: [a, b]", "tools: a"), r"must be a \[list\]"),
    (GOOD.replace('"type": "object", ', ""), "object schema"),
    (GOOD.replace('{"type": "object"', '{"type": "object",'), "not valid JSON"),
    (GOOD.replace('"x": {', '"summary": {'), "redefines common"),
    (GOOD.replace('"x": {', '"claims": {'), "redefines common"),
    (GOOD + "<output_schema>{}</output_schema>", "exactly one"),
    (GOOD.replace("tools: [a, b]", "tools: [a]\nincludes: [_missing]"), "unknown include"),
    (GOOD.replace("tools: [a, b]", "tools: [a]\nincludes: [_base]"), "includes must be"),
    (GOOD.replace("tools: [a, b]", "tools: [a]\nincludes: [demo]"), "includes must be"),
    (GOOD.replace("tools: [a, b]", "tools: [a]\ndepartments: cskh"), "departments must be"),
])
def test_load_rejects_broken_mandate(mandate_dir, broken, msg):
    (mandate_dir / "demo.md").write_text(broken, encoding="utf-8")
    with pytest.raises(MandateError, match=msg):
        mandates.load("demo")


def test_departments_decide_who_may_use_an_agent():
    """D-02/D-03: three departments; orders sits with customer care."""
    shipped = {name: mandates.load(name).departments for name in mandates.names()}
    assert shipped == {
        "customer_service": ("cskh", "executive"),
        "orders": ("cskh", "executive"), "executive": ("executive",),
        "it_support": ("*",), "knowledge": ("*",),
        "coordinator": (), "factory": (), "compactor": (),
    }
    executive, it_support = mandates.load("executive"), mandates.load("it_support")
    assert executive.usable_by(("executive",)) and not executive.usable_by(("cskh",))
    assert executive.usable_by(("cskh", "executive")) and not executive.usable_by(())
    assert it_support.usable_by(("it",)) and it_support.usable_by(())


def test_unknown_and_base_are_not_loadable():
    for name in ("nope", "_base"):
        with pytest.raises(MandateError):
            mandates.load(name)
