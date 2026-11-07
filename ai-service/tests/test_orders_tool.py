import asyncio
import json
import pytest
import httpx

from app.core.context import RequestContext
from app.core.contract import Trace, check
from app.core.llm.messages import AssistantMessage, ToolCall, ToolResultMessage
from app.core.tools import PermissionDenied, ToolError
from app.tools.orders import (
    LookupOrderHttp,
    LookupProductHttp,
    SearchProductsHttp,
    LookupStockHttp,
    OrderArgs,
    ProductArgs,
    SearchProductArgs,
    StockArgs,
    HTTP_TOOLS,
)
from app.tools import build_tools

CSKH = RequestContext("u1", ("cskh",))
EXEC = RequestContext("u2", ("executive",))
IT = RequestContext("u3", ("it",))


def run(tool, **args):
    return asyncio.run(tool.run(json.dumps(args)))


def test_headers_and_successful_lookup_order():
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_headers
        captured_headers = dict(request.headers)
        assert request.url.path == "/api/orders/DH1001"
        return httpx.Response(
            200,
            json={
                "order_id": "DH1001",
                "customer_name": "Nguyễn Văn An",
                "product_id": "P001",
                "product_name": "iPhone 16 128GB",
                "quantity": 1,
                "unit_price": 22990000,
                "discount": 1000000,
                "paid_amount": 21990000,
                "payment_method": "chuyển khoản",
                "order_date": "2026-10-15",
                "delivered_date": "2026-10-17",
                "status": "delivered",
                "store": "CN Quận 1",
            },
        )

    transport = httpx.MockTransport(handler)
    tool = LookupOrderHttp(CSKH, base_url="http://mock-service", transport=transport)
    result = run(tool, order_id="DH1001")

    assert not result.is_error
    data = json.loads(result.content)
    assert data["order_id"] == "DH1001"
    assert data["paid_amount"] == 21990000
    assert captured_headers.get("x-user-id") == "u1"
    assert captured_headers.get("x-user-departments") == "cskh"


def test_error_mappings():
    # 404 -> ToolError
    t404 = httpx.MockTransport(lambda req: httpx.Response(404, json={"error": "order DH9999 does not exist"}))
    tool404 = LookupOrderHttp(CSKH, base_url="http://mock", transport=t404)
    res404 = run(tool404, order_id="DH9999")
    assert res404.is_error and "order DH9999 does not exist" in res404.content

    # 403 -> PermissionDenied
    t403 = httpx.MockTransport(lambda req: httpx.Response(403, json={"error": "forbidden"}))
    tool403 = LookupOrderHttp(IT, base_url="http://mock", transport=t403)
    res403 = run(tool403, order_id="DH1001")
    assert res403.is_error and "permission_denied" in res403.content

    # 400 -> ToolError
    t400 = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "invalid format"}))
    tool400 = SearchProductsHttp(CSKH, base_url="http://mock", transport=t400)
    res400 = run(tool400, query="ab")
    assert res400.is_error and "invalid format" in res400.content

    # 500 -> ToolError unavailable
    t500 = httpx.MockTransport(lambda req: httpx.Response(500, text="Internal error"))
    tool500 = LookupProductHttp(CSKH, base_url="http://mock", transport=t500)
    res500 = run(tool500, product_id="P001")
    assert res500.is_error and "order-service unavailable" in res500.content


def test_search_products_flattens_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/products"
        assert request.url.params["q"] == "Samsung Galaxy S25"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"product_id": "P002", "name": "Samsung Galaxy S25 256GB", "price": 18490000},
                    {"product_id": "P005", "name": "Samsung Galaxy S25 Ultra 512GB", "price": 29990000},
                ]
            },
        )

    tool = SearchProductsHttp(CSKH, base_url="http://mock", transport=httpx.MockTransport(handler))
    res = run(tool, query="Samsung Galaxy S25")
    assert not res.is_error
    flat = json.loads(res.content)
    # Output must be flat mapping product_id -> name
    assert flat == {
        "P002": "Samsung Galaxy S25 256GB",
        "P005": "Samsung Galaxy S25 Ultra 512GB",
    }


def test_lookup_stock_flattens_response_and_verifies():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/products/P001/stock"
        return httpx.Response(
            200,
            json={
                "product_id": "P001",
                "stock_total": 14,
                "by_store": {
                    "CN Quận 1": 8,
                    "CN Thủ Đức": 6,
                },
            },
        )

    tool = LookupStockHttp(CSKH, base_url="http://mock", transport=httpx.MockTransport(handler))
    res = run(tool, product_id="P001")
    assert not res.is_error
    flat = json.loads(res.content)
    assert flat == {
        "stock_total": 14,
        "CN Quận 1": 8,
        "CN Thủ Đức": 6,
    }

    # Verify claim citation works against flat JSON output
    trace = Trace.from_messages([
        AssistantMessage(tool_calls=(ToolCall(id="call_1", name="lookup_stock", arguments="{}"),)),
        ToolResultMessage(tool_call_id="call_1", content=res.content, is_error=False),
    ])
    result_data = {
        "status": "done",
        "claims": [
            {
                "key": "total",
                "kind": "fact",
                "value": 14,
                "ref": {"call_id": "lookup_stock", "path": "stock_total"},
                "derived_from": [],
                "reasoning": None,
            },
            {
                "key": "q1_stock",
                "kind": "fact",
                "value": 8,
                "ref": {"call_id": "lookup_stock", "path": "CN Quận 1"},
                "derived_from": [],
                "reasoning": None,
            },
        ],
        "open_questions": [],
    }
    violations = check(result_data, trace)
    assert len(violations) == 0


def test_build_tools_selection(monkeypatch):
    # Without ORDERS_SERVICE_URL -> stubs used
    monkeypatch.delenv("ORDERS_SERVICE_URL", raising=False)
    stubs = build_tools(("lookup_order", "search_products", "lookup_stock"), CSKH)
    assert len(stubs) == 3
    for t in stubs:
        assert not isinstance(t, (LookupOrderHttp, SearchProductsHttp, LookupStockHttp))

    # With ORDERS_SERVICE_URL -> HTTP tools used
    monkeypatch.setenv("ORDERS_SERVICE_URL", "http://order-service:8080")
    http_tools = build_tools(("lookup_order", "search_products", "lookup_stock"), CSKH)
    assert len(http_tools) == 3
    for t in http_tools:
        assert isinstance(t, (LookupOrderHttp, SearchProductsHttp, LookupStockHttp))
