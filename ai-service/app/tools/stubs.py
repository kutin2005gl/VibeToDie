"""Business tools: orders and products are stubs over seed data until the real services replace them;
`search_sop` searches the policy documents of `app/knowledge/sop` (BM25, core/retrieval.py).

Each returns flat JSON (`{key: value}`) so a claim's `ref.path` is a single key. Each runs with the
requester's permissions (`RequestContext`); none takes a department or user as an argument.
"""

import json
from functools import cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from app.core.context import RequestContext
from app.core.tools import BaseTool, PermissionDenied, ToolArgs, ToolDescription, ToolError, ToolResult
from app.knowledge import sop_index
from app.tools import mailer

SEED = Path(__file__).with_name("seed.json")
# Departments whose staff may read order and product data
ORDER_READERS = ("cskh", "executive")


@cache
def _seed() -> dict[str, Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class _ContextTool[ArgsT: ToolArgs](BaseTool[ArgsT]):
    def __init__(self, ctx: RequestContext) -> None:
        self._ctx = ctx
        super().__init__()


class OrderArgs(ToolArgs):
    order_id: Annotated[str, Field(pattern=r"^DH\d+$", description="Order id, for example DH1001.")]


class LookupOrder(_ContextTool[OrderArgs]):
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
        if not self._ctx.in_any(ORDER_READERS):
            raise PermissionDenied("you may not read order data")
        order = _seed()["orders"].get(args.order_id)
        if order is None:
            raise ToolError(f"order {args.order_id} does not exist", "Check the order id with the staff member.")
        return _json(order)


class ProductArgs(ToolArgs):
    product_id: Annotated[str, Field(pattern=r"^P\d+$", description="Product id, for example P001.")]


class LookupProduct(_ContextTool[ProductArgs]):
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
        if not self._ctx.in_any(ORDER_READERS):
            raise PermissionDenied("you may not read product data")
        product = _seed()["products"].get(args.product_id)
        if product is None:
            raise ToolError(f"product {args.product_id} does not exist", "Check the product id.")
        return _json(product)


class SopArgs(ToolArgs):
    query: Annotated[
        str, Field(min_length=2, description="Keywords or a question about the rules, in Vietnamese like the documents.")
    ]
    limit: Annotated[int, Field(ge=1, le=5, description="Maximum number of passages.")] = 3


class SearchSop(_ContextTool[SopArgs]):
    name = "search_sop"
    description = ToolDescription(
        summary="Find internal rule (SOP) passages related to the query; the documents are in Vietnamese.",
        when_to_use="When a conclusion needs a rule, policy or process as its basis.",
        when_not_to_use="When you need facts about a specific order or product (use lookup_order, lookup_product).",
        returns=(
            "JSON keyed by chunk_id, each value holding title and text. Use chunk_id as ref.path and quote "
            "text verbatim as the claim's value. Only includes documents the requester may see."
        ),
        cost="One search; returns at most `limit` passages.",
        examples=('search_sop(query="đổi trả máy lỗi")', 'search_sop(query="trả góp", limit=2)'),
    )
    args_model = SopArgs

    async def execute(self, args: SopArgs) -> str:
        hits = sop_index().search(args.query, self._ctx.departments, args.limit)
        if not hits:
            return "No matching document within the documents you may view."
        return _json({c.chunk_id: {"title": c.title, "text": c.text} for c, _ in hits})


class SearchProductArgs(ToolArgs):
    query: Annotated[
        str,
        Field(
            min_length=2,
            description="Product name or keyword to search for, for example 'Samsung Galaxy S25' or 'iPhone 16'.",
        ),
    ]


class SearchProducts(_ContextTool[SearchProductArgs]):
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
        if not self._ctx.in_any(ORDER_READERS):
            raise PermissionDenied("you may not read product data")
        q = args.query.lower()
        words = [w for w in re.findall(r"\w+", q) if len(w) >= 2]
        hits = {}
        for p in _seed()["products"].values():
            p_name = p["name"].lower()
            if any(w in p_name for w in words):
                hits[p["product_id"]] = p["name"]
        return _json(dict(list(hits.items())[:5]))


class StockArgs(ToolArgs):
    product_id: Annotated[str, Field(pattern=r"^P\d+$", description="Product id, for example P001.")]


class LookupStock(_ContextTool[StockArgs]):
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
        if not self._ctx.in_any(ORDER_READERS):
            raise PermissionDenied("you may not read product data")
        product = _seed()["products"].get(args.product_id)
        if product is None:
            raise ToolError(f"product {args.product_id} does not exist", "Check the product id.")
        if args.product_id == "P001":
            return _json({"stock_total": 14, "CN Quận 1": 8, "CN Thủ Đức": 6})
        elif args.product_id == "P002":
            return _json({"stock_total": 6, "CN Quận 1": 4, "CN Thủ Đức": 2})
        else:
            return _json({"stock_total": product["stock_total"], "CN Quận 1": 0, "CN Thủ Đức": 0})


class EmailArgs(ToolArgs):
    order_id: Annotated[
        str, Field(pattern=r"^DH\d+$", description="The order the email is about; the recipient must be its customer.")
    ]
    to: Annotated[
        str,
        Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254,
              description="The customer's email address, exactly as the order data gives it."),
    ]
    subject: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=5000, description="Plain text, the whole email.")]


class SendEmail(_ContextTool[EmailArgs]):
    name = "send_email"
    description = ToolDescription(
        summary="Send an email to the customer of an order. It is queued for staff approval and sent only if they approve.",
        when_to_use="When the task asks for content to be sent to a customer by email and the customer's email address is in the input or tool results.",
        when_not_to_use=(
            "For internal messages, or when the customer's email address is not known (add it to open_questions). "
            "Never to an address that is not the order's customer."
        ),
        returns="That the email is queued for staff approval; it has NOT been sent.",
        cost="Nothing until approved; then one email to the customer.",
        examples=('send_email(order_id="DH1001", to="an@example.com", subject="Về đơn hàng DH1001", body="Kính gửi Anh/Chị ...")',),
    )
    args_model = EmailArgs
    high_risk = True

    async def execute(self, args: EmailArgs) -> str:
        raise ToolError("send_email runs only after staff approval", "Call it from an agent run, which queues it.")

    async def execute_approved(self, args: EmailArgs, key: str) -> ToolResult | str:
        # The order as the agents see it (order-service or seed), read with the approver's permissions
        [lookup] = build_tools(("lookup_order",), self._ctx)
        found = await lookup.run(json.dumps({"order_id": args.order_id}))
        if found.is_error:
            return found
        # The model wrote the address: it must be the order's own, so injected text cannot redirect the email
        if args.to.lower() != str(json.loads(found.content).get("customer_email") or "").lower():
            raise ToolError(f"{args.to} is not the email of order {args.order_id}'s customer",
                            "Send only to the customer's address from the order data.")
        await mailer.send(args.to, args.subject, args.body, key)
        return "Sent."


_STUBS: dict[str, type[_ContextTool[Any]]] = {
    tool.name: tool for tool in (LookupOrder, LookupProduct, SearchProducts, LookupStock, SearchSop, SendEmail)
}


def build_tools(allowlist: tuple[str, ...], ctx: RequestContext) -> list[BaseTool[Any]]:
    """The tools of `allowlist` that exist; order-service over gRPC (ORDERS_GRPC_ADDR + INTERNAL_TOKEN),
    else over HTTP (ORDERS_SERVICE_URL), else stubs."""
    import os
    from app.tools.orders import HTTP_TOOLS
    from app.tools.orders_grpc import GRPC_TOOLS, grpc_enabled

    grpc_addr = grpc_enabled()
    service_url = os.getenv("ORDERS_SERVICE_URL")
    tools: list[BaseTool[Any]] = []
    for name in allowlist:
        if grpc_addr and name in GRPC_TOOLS:
            tools.append(GRPC_TOOLS[name](ctx, base_url=grpc_addr))
        elif service_url and name in HTTP_TOOLS:
            tools.append(HTTP_TOOLS[name](ctx, base_url=service_url))
        elif name in _STUBS:
            tools.append(_STUBS[name](ctx))
    return tools

