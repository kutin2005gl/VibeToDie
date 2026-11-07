"""Parity check comparing stub seed data against order-service for DH1001-DH1003 and P001-P003.

Must match 100% key-for-key to prevent regression on e2e evals.
Run with:
    python -m evals.e2e.parity [--url http://localhost:8080]
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
import httpx

SEED_PATH = Path(__file__).resolve().parent.parent.parent / "app" / "tools" / "seed.json"


def _generate_dev_token(secret: str, issuer: str = "nexus") -> str:
    h = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({
        "sub": "parity-checker",
        "departments": ["cskh", "executive"],
        "iss": issuer,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }).encode()).rstrip(b"=").decode()
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{h}.{p}.{sig_b64}"


async def check_parity(base_url: str, token: str | None = None) -> bool:
    seed_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seed_orders = seed_data.get("orders", {})
    seed_products = seed_data.get("products", {})

    headers = {
        "X-User-Id": "parity-checker",
        "X-User-Departments": "cskh,executive",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        secret = os.getenv("JWT_SECRET", "super-secret-jwt-key-with-at-least-32-characters-length")
        issuer = os.getenv("JWT_ISSUER", "nexus")
        headers["Authorization"] = f"Bearer {_generate_dev_token(secret, issuer)}"

    all_matched = True

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # Check health
        try:
            health_resp = await client.get("/healthz")
            print(f"Healthcheck {base_url}/healthz: {health_resp.status_code}")
        except Exception as e:
            print(f"ERROR: Cannot connect to order-service at {base_url}: {e}")
            return False

        # 1. Check Orders
        for order_id, expected in seed_orders.items():
            resp = await client.get(f"/api/orders/{order_id}", headers=headers)
            if resp.status_code != 200:
                print(f"FAIL [Order {order_id}]: status {resp.status_code}, expected 200")
                all_matched = False
                continue

            actual = resp.json()
            mismatches = []
            for key, exp_val in expected.items():
                act_val = actual.get(key)
                if act_val != exp_val:
                    mismatches.append(f"  key '{key}': expected {exp_val!r}, got {act_val!r}")

            for key in actual:
                if key not in expected:
                    mismatches.append(f"  unexpected key '{key}' in service output")

            if mismatches:
                print(f"FAIL [Order {order_id}] key mismatches:")
                for m in mismatches:
                    print(m)
                all_matched = False
            else:
                print(f"PASS [Order {order_id}] 100% key-for-key match")

        # 2. Check Products
        for prod_id, expected in seed_products.items():
            resp = await client.get(f"/api/products/{prod_id}", headers=headers)
            if resp.status_code != 200:
                print(f"FAIL [Product {prod_id}]: status {resp.status_code}, expected 200")
                all_matched = False
                continue

            actual = resp.json()
            mismatches = []
            for key, exp_val in expected.items():
                act_val = actual.get(key)
                if act_val != exp_val:
                    mismatches.append(f"  key '{key}': expected {exp_val!r}, got {act_val!r}")

            for key in actual:
                if key not in expected:
                    mismatches.append(f"  unexpected key '{key}' in service output")

            if mismatches:
                print(f"FAIL [Product {prod_id}] key mismatches:")
                for m in mismatches:
                    print(m)
                all_matched = False
            else:
                print(f"PASS [Product {prod_id}] 100% key-for-key match")

        # 3. Check Stock Invariant
        for prod_id, expected in seed_products.items():
            resp = await client.get(f"/api/products/{prod_id}/stock", headers=headers)
            if resp.status_code != 200:
                print(f"FAIL [Stock {prod_id}]: status {resp.status_code}")
                all_matched = False
                continue
            stock = resp.json()
            expected_total = expected["stock_total"]
            if stock.get("stock_total") != expected_total:
                print(f"FAIL [Stock {prod_id}]: total {stock.get('stock_total')}, expected {expected_total}")
                all_matched = False
            else:
                by_store = stock.get("by_store", {})
                sum_store = sum(by_store.values())
                if sum_store != expected_total:
                    print(f"FAIL [Stock {prod_id}]: by_store sum {sum_store} != stock_total {expected_total}")
                    all_matched = False
                else:
                    print(f"PASS [Stock {prod_id}] total {expected_total} matches sum of stores {by_store}")

    return all_matched


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check data parity between seed and order-service")
    parser.add_argument(
        "--url",
        default=os.getenv("ORDERS_SERVICE_URL", "http://localhost:8080"),
        help="Base URL of order-service or gateway",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional JWT Bearer token if connecting through gateway",
    )
    args = parser.parse_args()

    success = asyncio.run(check_parity(args.url, token=args.token))
    if not success:
        print("\nPARITY CHECK FAILED!")
        sys.exit(1)
    print("\nPARITY CHECK 100% PASSED!")


if __name__ == "__main__":
    main()
