"""gRPC transport for the order tools: same tools as `orders.py` (arguments, descriptions, flat JSON),
only `execute` differs. Used when ORDERS_GRPC_ADDR and INTERNAL_TOKEN are set."""

import asyncio
import json
import os
from typing import Any

import grpc

from app.core.tools import PermissionDenied, ToolError
from app.pb.orders.v1 import orders_pb2 as pb
from app.pb.orders.v1 import orders_pb2_grpc as pb_grpc
from app.tools.orders import (
    LookupOrderHttp,
    LookupProductHttp,
    LookupStockHttp,
    OrderArgs,
    ProductArgs,
    SearchProductArgs,
    SearchProductsHttp,
    StockArgs,
)

DEADLINE_SECONDS = 3.0
_UNAVAILABLE = ("order-service unavailable", "Try once more; if it fails again, say the data is unavailable.")

# grpc.aio channels belong to the loop that made them, so the cache is keyed by loop as well.
_channels: dict[tuple[str, int], grpc.aio.Channel] = {}


def _stub(addr: str) -> pb_grpc.OrdersServiceStub:
    key = (addr, id(asyncio.get_running_loop()))
    if key not in _channels:
        _channels[key] = grpc.aio.insecure_channel(addr)
    return pb_grpc.OrdersServiceStub(_channels[key])


def grpc_enabled() -> str | None:
    """The gRPC address when both it and the internal token are configured, else None."""
    addr = os.getenv("ORDERS_GRPC_ADDR")
    return addr if addr and os.getenv("INTERNAL_TOKEN") else None


def _metadata(ctx: Any) -> tuple[tuple[str, str], ...]:
    meta = [("x-internal-token", os.getenv("INTERNAL_TOKEN", ""))]
    if ctx.user_id:
        meta.append(("x-user-id", ctx.user_id))
    if ctx.departments:
        meta.append(("x-user-departments", ",".join(ctx.departments)))
    return tuple(meta)


def _raise_for(err: grpc.aio.AioRpcError, entity: str) -> None:
    code = err.code()
    detail = err.details() or ""
    if code is grpc.StatusCode.NOT_FOUND:
        raise ToolError(detail or f"{entity} does not exist", "Check the id with the staff member.")
    if code is grpc.StatusCode.INVALID_ARGUMENT:
        raise ToolError(detail or "invalid format", "Check the format of your query or id.")
    if code in (grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.UNAUTHENTICATED):
        raise PermissionDenied("you may not read order data")
    raise ToolError(*_UNAVAILABLE)


class _GrpcCall:
    # `base_url` of the HTTP tools holds the gRPC address (host:port) here.
    _base_url: str
    _ctx: Any

    async def _call(self, method: str, request: Any, entity: str) -> Any:
        try:
            return await getattr(_stub(self._base_url), method)(request, metadata=_metadata(self._ctx), timeout=DEADLINE_SECONDS)
        except grpc.aio.AioRpcError as err:
            _raise_for(err, entity)


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


class LookupOrderGrpc(_GrpcCall, LookupOrderHttp):
    async def execute(self, args: OrderArgs) -> str:
        o = await self._call("GetOrder", pb.GetOrderRequest(order_id=args.order_id), f"order {args.order_id}")
        flat: dict[str, Any] = {
            "order_id": o.order_id,
            "customer_name": o.customer_name,
            "customer_email": o.customer_email if o.HasField("customer_email") else None,
            "product_id": o.product_id,
            "product_name": o.product_name,
            "quantity": o.quantity,
            "unit_price": o.unit_price,
            "discount": o.discount,
            "paid_amount": o.paid_amount,
            "payment_method": o.payment_method,
        }
        if o.HasField("installment_months"):
            flat["installment_months"] = o.installment_months
        flat["order_date"] = o.order_date
        flat["delivered_date"] = o.delivered_date if o.HasField("delivered_date") else None
        flat["status"] = o.status
        flat["store"] = o.store
        return _dump(flat)


class LookupProductGrpc(_GrpcCall, LookupProductHttp):
    async def execute(self, args: ProductArgs) -> str:
        p = await self._call("GetProduct", pb.GetProductRequest(product_id=args.product_id), f"product {args.product_id}")
        return _dump({
            "product_id": p.product_id,
            "name": p.name,
            "price": p.price,
            "warranty_months": p.warranty_months,
            "stock_total": p.stock_total,
        })


class SearchProductsGrpc(_GrpcCall, SearchProductsHttp):
    async def execute(self, args: SearchProductArgs) -> str:
        r = await self._call("SearchProducts", pb.SearchProductsRequest(query=args.query, limit=5), "products")
        return _dump({item.product_id: item.name for item in list(r.items)[:5]})


class LookupStockGrpc(_GrpcCall, LookupStockHttp):
    async def execute(self, args: StockArgs) -> str:
        s = await self._call("GetStock", pb.GetStockRequest(product_id=args.product_id), f"product {args.product_id}")
        flat: dict[str, Any] = {"stock_total": s.stock_total}
        flat.update(dict(s.by_store))
        return _dump(flat)


GRPC_TOOLS: dict[str, type[Any]] = {
    "lookup_order": LookupOrderGrpc,
    "lookup_product": LookupProductGrpc,
    "search_products": SearchProductsGrpc,
    "lookup_stock": LookupStockGrpc,
}
