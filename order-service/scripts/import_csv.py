"""Build an idempotent SQL import of the real CSV data (data/*.csv) for order-service.

Usage (from the repo root, stack running):
    python order-service/scripts/import_csv.py            # writes data/import.sql
    docker compose cp data/import.sql db:/tmp/import.sql
    docker compose exec -T db psql -U nexus -d nexus -v ON_ERROR_STOP=1 -f /tmp/import.sql

Mapping decisions (v1 keeps one line per order in `orders`; see plan-order-service.md):
- Ids get prefixes the API accepts and that never collide with the seed (P001-P011, DH1001-DH1013):
  product N -> P{1000+N}; order_code (DH...) is used as is.
- Every order line is kept in `order_items`; `orders` carries the first line as its product line,
  while discount and paid_amount are the order totals.
- unit_price = list price of that line, discount = discount_vnd, paid_amount = total_vnd,
  so for single-line orders unit_price * quantity - discount = paid_amount, as in the seed.
- No per-store stock in the source: products.stock_qty goes to the store "Kho tổng".
- Online orders (website/app) go to the stores "Online (website)" / "Online (app)".
- The source has no delivered date and no installment term: both stay NULL.
- The customer's name and email are copied; phone and address stay out of order-service. The email
  keeps its local part but its domain becomes example.com: send_email really sends, and the source
  addresses may be real people's inboxes.
Everything is inserted with ON CONFLICT DO NOTHING inside one transaction, so a rerun is safe
and existing rows (including the seed) are never changed, except that an imported order gets its
customer_email filled in.
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "import.sql"

STATUS = {
    "hoan_thanh": "delivered",
    "da_huy": "cancelled",
    "hoan_tra": "returned",
    "cho_xac_nhan": "pending",
    "dang_giao": "shipping",
}
PAYMENT = {
    "chuyen_khoan": "chuyển khoản",
    "cod": "thanh toán khi nhận hàng (COD)",
    "momo": "ví MoMo",
    "the_tin_dung": "thẻ tín dụng",
    "tra_gop": "trả góp",
    "vnpay": "VNPay",
    "zalopay": "ví ZaloPay",
}
BRANCH = {"Q1": "Quận 1", "Q3": "Quận 3"}
ONLINE = {"website": "Online (website)", "app": "Online (app)"}
WAREHOUSE = ("STORE_WAREHOUSE", "Kho tổng")

# Same table as order-service/internal/store/unaccent.go, so the stored column matches the query.
_GROUPS = {
    "a": "àáảãạăằắẳẵặâầấẩẫậ", "e": "èéẻẽẹêềếểễệ", "i": "ìíỉĩị",
    "o": "òóỏõọôồốổỗộơờớởỡợ", "u": "ùúủũụưừứửữự", "y": "ỳýỷỹỵ", "d": "đ",
}
_MAP = {ch: base for base, chars in _GROUPS.items() for ch in chars}


def unaccent(s: str) -> str:
    return "".join(_MAP.get(ch, ch) for ch in s.lower())


def q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def rows(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_email(email: str) -> str | None:
    """`email` with the domain example.com, which never delivers; None when there is none."""
    local = email.strip().split("@")[0]
    return f"{local}@example.com" if local else None


def product_id(n: str) -> str:
    return f"P{1000 + int(n)}"


def product_name(p: dict) -> str:
    model, brand = p["model"].strip(), p["brand"].strip()
    if brand != "Apple" and brand.lower() not in model.lower():
        model = f"{brand} {model}"
    gb = int(p["storage_gb"])
    return f"{model} {gb // 1024}TB" if gb >= 1024 and gb % 1024 == 0 else f"{model} {gb}GB"


def store_name(o: dict) -> str:
    if o["channel"] in ONLINE:
        return ONLINE[o["channel"]]
    branch = o["store_branch"].strip()
    if not branch:
        raise ValueError(f"order {o['order_code']}: store channel without branch")
    return "CN " + BRANCH.get(branch, branch)


def store_id(name: str) -> str:
    return "STORE_" + "".join(c if c.isalnum() else "_" for c in unaccent(name).upper()).strip("_")


def values(tuples: list[tuple], chunk: int = 1000):
    for i in range(0, len(tuples), chunk):
        yield ",\n".join("(" + ", ".join(q(v) for v in t) + ")" for t in tuples[i : i + chunk])


def main() -> None:
    customers = {c["customer_id"]: (c["full_name"].strip(), safe_email(c["email"])) for c in rows("customers.csv")}
    products = rows("products.csv")
    orders = rows("orders.csv")
    items = rows("order_items.csv")

    lines: dict[str, list[dict]] = {}
    for it in items:
        lines.setdefault(it["order_id"], []).append(it)
    for v in lines.values():
        v.sort(key=lambda it: int(it["order_item_id"]))

    errors: list[str] = []
    prod_rows, inv_rows, order_rows, item_rows, stores = [], [], [], [], {WAREHOUSE[1]: WAREHOUSE[0]}
    known_pids = set()
    for p in products:
        pid = product_id(p["product_id"])
        known_pids.add(pid)
        name = product_name(p)
        prod_rows.append((pid, name, int(p["price_vnd"]), int(p["warranty_months"]), unaccent(name)))
        inv_rows.append((pid, WAREHOUSE[0], int(p["stock_qty"])))

    for o in orders:
        code = o["order_code"].strip()
        its = lines.get(o["order_id"])
        if not its:
            errors.append(f"{code}: no order lines"); continue
        if o["status"] not in STATUS:
            errors.append(f"{code}: unknown status {o['status']!r}"); continue
        if o["payment_method"] not in PAYMENT:
            errors.append(f"{code}: unknown payment {o['payment_method']!r}"); continue
        if o["customer_id"] not in customers:
            errors.append(f"{code}: unknown customer {o['customer_id']}"); continue
        sname = store_name(o)
        stores.setdefault(sname, store_id(sname))
        first = its[0]
        order_rows.append((
            code, *customers[o["customer_id"]], product_id(first["product_id"]), int(first["quantity"]),
            int(first["unit_list_price_vnd"]), int(o["discount_vnd"]), int(o["total_vnd"]),
            PAYMENT[o["payment_method"]], None, o["order_date"][:10], None, STATUS[o["status"]], sname,
        ))
        for n, it in enumerate(its, 1):
            pid = product_id(it["product_id"])
            if pid not in known_pids:
                errors.append(f"{code}: unknown product {it['product_id']}")
            item_rows.append((code, n, pid, it["color"].strip(), int(it["quantity"]),
                              int(it["unit_list_price_vnd"]), int(it["unit_price_vnd"]), int(it["line_total_vnd"])))

    if errors:
        print(f"{len(errors)} problems, nothing written:", *errors[:20], sep="\n  ")
        sys.exit(1)

    out = ["-- Generated by order-service/scripts/import_csv.py. Do not edit by hand.",
           "\\set ON_ERROR_STOP on", "BEGIN;", """
CREATE TABLE IF NOT EXISTS order_items (
    order_id        TEXT   NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    line_no         INT    NOT NULL,
    product_id      TEXT   NOT NULL REFERENCES products (id),
    color           TEXT   NOT NULL DEFAULT '',
    quantity        INT    NOT NULL,
    unit_list_price BIGINT NOT NULL,
    unit_price      BIGINT NOT NULL,
    line_total      BIGINT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);""",
           "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_email TEXT;",
           "CREATE TEMP TABLE stg_orders (id TEXT, customer_name TEXT, customer_email TEXT, product_id TEXT, quantity INT, unit_price BIGINT,"
           " discount BIGINT, paid_amount BIGINT, payment_method TEXT, installment_months INT, order_date DATE,"
           " delivered_date DATE, status TEXT, store_name TEXT) ON COMMIT DROP;"]
    out.append("INSERT INTO stores (id, name) VALUES\n" + ",\n".join(f"({q(i)}, {q(n)})" for n, i in stores.items())
               + "\nON CONFLICT DO NOTHING;")
    for chunk in values(prod_rows):
        out.append("INSERT INTO products (id, name, price, warranty_months, name_unaccent) VALUES\n" + chunk + "\nON CONFLICT DO NOTHING;")
    for chunk in values(inv_rows):
        out.append("INSERT INTO inventory (product_id, store_id, qty) VALUES\n" + chunk + "\nON CONFLICT DO NOTHING;")
    for chunk in values(order_rows):
        out.append("INSERT INTO stg_orders VALUES\n" + chunk + ";")
    # Store ids are looked up by name, so branches the seed already has (CN Quận 1, ...) reuse their id.
    out.append("""INSERT INTO orders (id, customer_name, customer_email, product_id, quantity, unit_price, discount, paid_amount,
    payment_method, installment_months, order_date, delivered_date, status, store_id)
SELECT o.id, o.customer_name, o.customer_email, o.product_id, o.quantity, o.unit_price, o.discount, o.paid_amount,
    o.payment_method, o.installment_months, o.order_date, o.delivered_date, o.status, s.id
FROM stg_orders o JOIN stores s ON s.name = o.store_name
ON CONFLICT (id) DO UPDATE SET customer_email = EXCLUDED.customer_email;""")
    out.append("DO $$ BEGIN IF (SELECT count(*) FROM stg_orders o LEFT JOIN stores s ON s.name = o.store_name"
               " WHERE s.id IS NULL) > 0 THEN RAISE EXCEPTION 'orders with an unknown store'; END IF; END $$;")
    for chunk in values(item_rows):
        out.append("INSERT INTO order_items (order_id, line_no, product_id, color, quantity, unit_list_price, unit_price, line_total) VALUES\n"
                   + chunk + "\nON CONFLICT DO NOTHING;")
    out.append("COMMIT;")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(stores)} stores, {len(prod_rows)} products, {len(order_rows)} orders, {len(item_rows)} order lines")


if __name__ == "__main__":
    main()

