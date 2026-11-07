import asyncio
import json

import grpc
import pytest

from app.core.context import RequestContext
from app.pb.orders.v1 import orders_pb2 as pb
from app.pb.orders.v1 import orders_pb2_grpc as pb_grpc
from app.tools import build_tools
from app.tools.orders_grpc import (
    LookupOrderGrpc,
    LookupProductGrpc,
    LookupStockGrpc,
    SearchProductsGrpc,
)

CSKH = RequestContext("u1", ("cskh",))


class FakeOrders(pb_grpc.OrdersServiceServicer):
    def __init__(self) -> None:
        self.metadata: dict[str, str] = {}

    async def _guard(self, context: grpc.aio.ServicerContext) -> None:
        self.metadata = dict(context.invocation_metadata())
        if self.metadata.get("x-internal-token") != "secret":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bad token")
        if "cskh" not in self.metadata.get("x-user-departments", ""):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "forbidden")

    async def GetOrder(self, request, context):
        await self._guard(context)
        if request.order_id == "DH9999":
            await context.abort(grpc.StatusCode.NOT_FOUND, "order DH9999 does not exist")
        if request.order_id == "DH0":
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid order id format")
        if request.order_id == "DH5":
            await context.abort(grpc.StatusCode.UNAVAILABLE, "down")
        order = pb.Order(
            order_id=request.order_id, customer_name="An", product_id="P001", product_name="iPhone",
            quantity=1, unit_price=22990000, discount=0, paid_amount=2**40, payment_method="cash",
            order_date="2026-10-15", status="processing", store="CN Quận 1",
        )
        if request.order_id == "DH1001":
            order.delivered_date = "2026-10-17"
            order.installment_months = 6
        return order

    async def GetProduct(self, request, context):
        await self._guard(context)
        return pb.Product(product_id=request.product_id, name="iPhone", price=1, warranty_months=12, stock_total=14)

    async def SearchProducts(self, request, context):
        await self._guard(context)
        return pb.SearchProductsResponse(items=[pb.ProductSummary(product_id="P002", name="Galaxy S25")])

    async def GetStock(self, request, context):
        await self._guard(context)
        return pb.Stock(product_id=request.product_id, stock_total=14, by_store={"CN Quận 1": 8})


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "secret")
    fake = FakeOrders()
    state: dict = {}

    async def start() -> None:
        state["server"] = grpc.aio.server()
        pb_grpc.add_OrdersServiceServicer_to_server(fake, state["server"])
        state["port"] = state["server"].add_insecure_port("127.0.0.1:0")
        await state["server"].start()

    def run(coro_fn):
        async def main():
            await start()
            try:
                return await coro_fn(f"127.0.0.1:{state['port']}", fake)
            finally:
                await state["server"].stop(None)

        return asyncio.run(main())

    return run


async def call(tool_cls, ctx, addr, **args):
    """The tool's JSON output; a tool error returns the error text prefixed so tests can match it."""
    result = await tool_cls(ctx, base_url=addr).run(json.dumps(args))
    return ("ERROR:" + result.content) if result.is_error else result.content


def test_lookup_order_flat_json_with_raw_numbers_and_metadata(server):
    async def body(addr, fake):
        out = json.loads(await call(LookupOrderGrpc, CSKH, addr, order_id="DH1001"))
        assert out["paid_amount"] == 2**40 and isinstance(out["paid_amount"], int)
        assert out["delivered_date"] == "2026-10-17" and out["installment_months"] == 6
        assert fake.metadata["x-user-id"] == "u1"
        assert fake.metadata["x-user-departments"] == "cskh"
        assert fake.metadata["x-internal-token"] == "secret"
        undelivered = json.loads(await call(LookupOrderGrpc, CSKH, addr, order_id="DH1002"))
        assert undelivered["delivered_date"] is None and "installment_months" not in undelivered

    server(body)


def test_other_tools(server):
    async def body(addr, fake):
        assert json.loads(await call(LookupProductGrpc, CSKH, addr, product_id="P001"))["warranty_months"] == 12
        assert json.loads(await call(SearchProductsGrpc, CSKH, addr, query="galaxy")) == {"P002": "Galaxy S25"}
        assert json.loads(await call(LookupStockGrpc, CSKH, addr, product_id="P001")) == {"stock_total": 14, "CN Quận 1": 8}

    server(body)


def test_error_mapping(server):
    async def body(addr, fake):
        assert "does not exist" in await call(LookupOrderGrpc, CSKH, addr, order_id="DH9999")
        assert "invalid" in await call(LookupOrderGrpc, CSKH, addr, order_id="DH0")
        assert "unavailable" in await call(LookupOrderGrpc, CSKH, addr, order_id="DH5")
        assert "permission_denied" in await call(LookupOrderGrpc, RequestContext("u9", ("it",)), addr, order_id="DH1001")

    server(body)


def test_wrong_token_is_permission_denied(server, monkeypatch):
    async def body(addr, fake):
        monkeypatch.setenv("INTERNAL_TOKEN", "nope")
        assert "permission_denied" in await call(LookupOrderGrpc, CSKH, addr, order_id="DH1001")

    server(body)


def test_unreachable_server_is_tool_error(monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "secret")
    assert "unavailable" in asyncio.run(call(LookupOrderGrpc, CSKH, "127.0.0.1:1", order_id="DH1001"))


def test_build_tools_picks_transport(monkeypatch):
    monkeypatch.delenv("ORDERS_GRPC_ADDR", raising=False)
    monkeypatch.delenv("INTERNAL_TOKEN", raising=False)
    monkeypatch.setenv("ORDERS_SERVICE_URL", "http://x")
    assert type(build_tools(("lookup_order",), CSKH)[0]).__name__ == "LookupOrderHttp"
    monkeypatch.setenv("ORDERS_GRPC_ADDR", "x:9090")
    assert type(build_tools(("lookup_order",), CSKH)[0]).__name__ == "LookupOrderHttp"  # no token: fall back
    monkeypatch.setenv("INTERNAL_TOKEN", "secret")
    assert type(build_tools(("lookup_order",), CSKH)[0]).__name__ == "LookupOrderGrpc"
