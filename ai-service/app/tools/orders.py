"""HTTP-based business tools calling order-service.

All tool outputs are flat JSON (`{key: value}`) to satisfy the verifier claim citation contract.
Identity headers (X-User-Id, X-User-Departments) are forwarded from RequestContext.
"""

import json
import os
from typing import Annotated, Any

import httpx
from pydantic import Field

from app.core.context import RequestContext
from app.core.tools import BaseTool, PermissionDenied, ToolArgs, ToolDescription, ToolError

DEFAULT_TIMEOUT = 5.0


def _get_client(base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=DEFAULT_TIMEOUT, transport=transport)


def _handle_error_response(response: httpx.Response, entity_name: str) -> None:
    if response.status_code == 404:
        err_msg = ""
        try:
            err_msg = response.json().get("error", "")
        except Exception:
            pass
        raise ToolError(err_msg or f"{entity_name} does not exist", "Check the id with the staff member.")
    if response.status_code == 403:
        raise PermissionDenied("you may not read order data")
    if response.status_code == 400:
        err_msg = ""
        try:
            err_msg = response.json().get("error", "")
        except Exception:
            pass
        raise ToolError(err_msg or "invalid format", "Check the format of your query or id.")
    if response.status_code >= 500:
        raise ToolError("order-service unavailable", "Try once more; if it fails again, say the data is unavailable.")


class _HttpBaseTool[ArgsT: ToolArgs](BaseTool[ArgsT]):
    def __init__(
        self,
        ctx: RequestContext,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._ctx = ctx
        self._base_url = base_url or os.getenv("ORDERS_SERVICE_URL", "http://order-service:8080")
        self._transport = transport
        super().__init__()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._ctx.user_id:
            headers["X-User-Id"] = self._ctx.user_id
        if self._ctx.departments:
            headers["X-User-Departments"] = ",".join(self._ctx.departments)
        return headers


class OrderArgs(ToolArgs):
    order_id: Annotated[str, Field(pattern=r"^DH\d+$", description="Order id, for example DH1001.")]


class LookupOrderHttp(_HttpBaseTool[OrderArgs]):
    name = "lookup_order"
    description = ToolDescription(
        summary="Look up one order by its order id.",
        when_to_use="When you need facts about a specific order: product, amount paid, purchase date, delivery date, status.",
        when_not_to_use="For general policies (use search_sop) or product information not tied to an order (use lookup_product).",
        returns="Flat JSON of the order; each key (for example paid_amount, delivered_date) can be a claim's ref.path.",
        cost="One lookup.",
        examples=('lookup_order(order_id="DH1001")',),
    )
    args_model = OrderArgs

    async def execute(self, args: OrderArgs) -> str:
        async with _get_client(self._base_url, self._transport) as client:
            try:
                resp = await client.get(f"/api/orders/{args.order_id}", headers=self._headers())
            except (httpx.TimeoutException, httpx.RequestError):
                raise ToolError(
                    "order-service unavailable",
                    "Try once more; if it fails again, say the data is unavailable.",
                )

        if resp.is_error:
            _handle_error_response(resp, f"order {args.order_id}")
        return resp.text


class ProductArgs(ToolArgs):
    product_id: Annotated[str, Field(pattern=r"^P\d+$", description="Product id, for example P001.")]


class LookupProductHttp(_HttpBaseTool[ProductArgs]):
    name = "lookup_product"
    description = ToolDescription(
        summary="Look up one product by its product id.",
        when_to_use="When you need a product's list price, warranty months or stock.",
        when_not_to_use="When you need data about a specific order (use lookup_order).",
        returns="Flat JSON of the product; each key can be a claim's ref.path.",
        cost="One lookup.",
        examples=('lookup_product(product_id="P001")',),
    )
    args_model = ProductArgs

    async def execute(self, args: ProductArgs) -> str:
        async with _get_client(self._base_url, self._transport) as client:
            try:
                resp = await client.get(f"/api/products/{args.product_id}", headers=self._headers())
            except (httpx.TimeoutException, httpx.RequestError):
                raise ToolError(
                    "order-service unavailable",
                    "Try once more; if it fails again, say the data is unavailable.",
                )

        if resp.is_error:
            _handle_error_response(resp, f"product {args.product_id}")
        return resp.text


class SearchProductArgs(ToolArgs):
    query: Annotated[
        str,
        Field(
            min_length=2,
            description="Product name or keyword to search for, for example 'Samsung Galaxy S25' or 'iPhone 16'.",
        ),
    ]


class SearchProductsHttp(_HttpBaseTool[SearchProductArgs]):
    name = "search_products"
    description = ToolDescription(
        summary="Search for products by name or keywords to find their product id.",
        when_to_use="When you know a product's name but not its product id (P001, P002, etc.).",
        when_not_to_use="When you already have the product id (use lookup_product or lookup_stock directly).",
        returns="Flat JSON mapping product_id to product_name, for example {'P002': 'Samsung Galaxy S25 256GB'}.",
        cost="One search; returns at most 5 matches.",
        examples=('search_products(query="Samsung Galaxy S25")', 'search_products(query="iPhone 16")'),
    )
    args_model = SearchProductArgs

    async def execute(self, args: SearchProductArgs) -> str:
        async with _get_client(self._base_url, self._transport) as client:
            try:
                resp = await client.get(
                    "/api/products",
                    params={"q": args.query, "limit": 5},
                    headers=self._headers(),
                )
            except (httpx.TimeoutException, httpx.RequestError):
                raise ToolError(
                    "order-service unavailable",
                    "Try once more; if it fails again, say the data is unavailable.",
                )

        if resp.is_error:
            _handle_error_response(resp, "products")

        data = resp.json()
        items = data.get("items", [])
        flat = {item["product_id"]: item["name"] for item in items[:5]}
        return json.dumps(flat, ensure_ascii=False)


class StockArgs(ToolArgs):
    product_id: Annotated[str, Field(pattern=r"^P\d+$", description="Product id, for example P001.")]


class LookupStockHttp(_HttpBaseTool[StockArgs]):
    name = "lookup_stock"
    description = ToolDescription(
        summary="Look up product stock total and breakdown by store branch.",
        when_to_use="When you need to check available inventory at specific store branches or total stock.",
        when_not_to_use="For pricing or warranty information (use lookup_product).",
        returns="Flat JSON of stock figures, with stock_total and store branches as keys (e.g. {'stock_total': 14, 'CN Quận 1': 8}).",
        cost="One lookup.",
        examples=('lookup_stock(product_id="P001")',),
    )
    args_model = StockArgs

    async def execute(self, args: StockArgs) -> str:
        async with _get_client(self._base_url, self._transport) as client:
            try:
                resp = await client.get(f"/api/products/{args.product_id}/stock", headers=self._headers())
            except (httpx.TimeoutException, httpx.RequestError):
                raise ToolError(
                    "order-service unavailable",
                    "Try once more; if it fails again, say the data is unavailable.",
                )

        if resp.is_error:
            _handle_error_response(resp, f"product {args.product_id}")

        data = resp.json()
        flat: dict[str, Any] = {"stock_total": data.get("stock_total", 0)}
        for store_name, qty in data.get("by_store", {}).items():
            flat[store_name] = qty
        return json.dumps(flat, ensure_ascii=False)


HTTP_TOOLS: dict[str, type[_HttpBaseTool[Any]]] = {
    "lookup_order": LookupOrderHttp,
    "lookup_product": LookupProductHttp,
    "search_products": SearchProductsHttp,
    "lookup_stock": LookupStockHttp,
}
