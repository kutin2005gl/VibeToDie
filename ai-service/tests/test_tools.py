import asyncio

import pytest
from pydantic import ValidationError

from app.core.tools import BaseTool, ToolArgs, ToolDescription, truncate_head_tail

DESC = ToolDescription(
    summary="Tra cứu đơn.",
    when_to_use="Khi cần dữ liệu đơn.",
    when_not_to_use="Khi hỏi chính sách.",
    returns="JSON của đơn.",
    cost="Một truy vấn.",
    examples=('lookup_order(order_id="DH1")',),
)


class Args(ToolArgs):
    order_id: str
    limit: int = 10


class Lookup(BaseTool[Args]):
    name = "lookup_order"
    description = DESC
    args_model = Args

    async def execute(self, args: Args) -> str:
        return args.order_id


def test_description_requires_every_section():
    with pytest.raises(ValidationError):
        ToolDescription(summary="s", when_to_use="u", when_not_to_use="", returns="r", cost="c",
                        examples=("e",))
    with pytest.raises(ValidationError):
        ToolDescription(summary="s", when_to_use="u", when_not_to_use="n", returns="r", cost="c",
                        examples=())


def test_spec_is_built_once_without_titles():
    tool = Lookup()
    spec = tool.spec
    assert spec is tool.spec
    params = spec["function"]["parameters"]
    assert "title" not in params and "title" not in params["properties"]["order_id"]
    assert "When not to use:\nKhi hỏi chính sách." in spec["function"]["description"]
    assert tool.high_risk is False


def test_run_validates_strictly():
    tool = Lookup()
    assert asyncio.run(tool.run('{"order_id": "DH1"}')).content == "DH1"
    for bad in ('{"order_id": "DH1", "x": 1}', '{"order_id": 1}', '{"order_id": "DH1", "limit": "5"}', "{"):
        result = asyncio.run(tool.run(bad))
        assert result.is_error and result.content.startswith("Error (invalid_arguments)")


def test_truncation_keeps_head_and_tail_and_says_what_was_cut():
    text = "".join(f"line {i}\n" for i in range(1, 501))
    out = truncate_head_tail(text, how_to_read_rest="Call again with offset.")
    assert out.startswith("line 1\n") and out.endswith("line 500\n")
    assert "lines 51–450 of 500 omitted" in out and "Call again with offset." in out
    assert truncate_head_tail("short", how_to_read_rest="x") == "short"
    with pytest.raises(ValueError):
        truncate_head_tail(text, how_to_read_rest=" ")
