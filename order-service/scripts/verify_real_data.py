"""Comprehensive verification script for real imported data through Gateway.
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECRET = "super-secret-jwt-key-with-at-least-32-characters-length"
ISSUER = "nexus"
GATEWAY_URL = "http://localhost:8080"

def make_token(sub="tester", depts=["cskh", "executive"]):
    h = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({
        "sub": sub,
        "departments": depts,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }).encode()).rstrip(b"=").decode()
    sig = hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{h}.{p}.{sig_b64}"

def test_endpoints():
    token = make_token()
    headers = {"Authorization": f"Bearer {token}"}

    client = httpx.Client(base_url=GATEWAY_URL, headers=headers, timeout=10.0)

    print("==================================================")
    print("1. TEST REAL ORDERS LOOKUP")
    print("==================================================")
    sample_orders = ["DH251101000001", "DH251101000002", "DH251101000003", "DH251101000010"]
    for oid in sample_orders:
        res = client.get(f"/api/orders/{oid}")
        assert res.status_code == 200, f"Expected 200 for {oid}, got {res.status_code}: {res.text}"
        data = res.json()
        print(f"[{oid}] Status: {data.get('status')} | Customer: {data.get('customer_name')} | Product: {data.get('product_name')} | Paid: {data.get('paid_amount', 0):,}đ | Store: {data.get('store')}")

    print("\n==================================================")
    print("2. TEST REAL PRODUCTS LOOKUP")
    print("==================================================")
    sample_products = ["P1001", "P1010", "P1050", "P1098"]
    for pid in sample_products:
        res = client.get(f"/api/products/{pid}")
        assert res.status_code == 200, f"Expected 200 for {pid}, got {res.status_code}: {res.text}"
        data = res.json()
        print(f"[{pid}] {data.get('name')} | Price: {data.get('price', 0):,}đ | Warranty: {data.get('warranty_months')}m | Stock: {data.get('stock_total')}")

    print("\n==================================================")
    print("3. TEST PRODUCT SEARCH (ACCENT-INSENSITIVE)")
    print("==================================================")
    queries = ["iphone 16", "tai nghe", "samsung", "op lung"]
    for q in queries:
        res = client.get(f"/api/products", params={"q": q})
        assert res.status_code == 200, f"Expected 200 for search '{q}', got {res.status_code}: {res.text}"
        items = res.json().get("items", [])
        print(f"Query '{q}': found {len(items)} items")
        for item in items[:3]:
            print(f"   -> [{item.get('product_id')}] {item.get('name')} ({item.get('price', 0):,}đ)")

    print("\n==================================================")
    print("4. TEST STOCK LOOKUP (DYNAMIC WAREHOUSE + STORES)")
    print("==================================================")
    for pid in ["P1001", "P1010"]:
        res = client.get(f"/api/products/{pid}/stock")
        assert res.status_code == 200, f"Expected 200 for stock {pid}, got {res.status_code}: {res.text}"
        data = res.json()
        print(f"Product {pid}: stock_total={data.get('stock_total')} across {len(data.get('by_store', {}))} stores")
        stores_with_stock = {k: v for k, v in data.get('by_store', {}).items() if v > 0}
        print(f"   Stores with stock: {stores_with_stock}")

    print("\n==================================================")
    print("5. TEST ZERO-TRUST RBAC & ERROR HANDLING")
    print("==================================================")
    # 5a. Missing token -> 401
    no_auth_res = httpx.get(f"{GATEWAY_URL}/api/orders/DH251101000001")
    assert no_auth_res.status_code == 401, f"Expected 401, got {no_auth_res.status_code}"
    print("[PASS] Missing token -> 401 Unauthorized")

    # 5b. Forbidden department (hr only) -> 403
    hr_token = make_token(depts=["hr"])
    hr_res = httpx.get(f"{GATEWAY_URL}/api/orders/DH251101000001", headers={"Authorization": f"Bearer {hr_token}"})
    assert hr_res.status_code == 403, f"Expected 403, got {hr_res.status_code}"
    print("[PASS] Department 'hr' (not cskh/executive) -> 403 Forbidden")

    # 5c. Invalid regex -> 400
    bad_req = client.get("/api/orders/INVALID_ORDER")
    assert bad_req.status_code == 400, f"Expected 400, got {bad_req.status_code}"
    print("[PASS] Invalid order pattern 'INVALID_ORDER' -> 400 Bad Request")

    # 5d. Not found -> 404
    nf_req = client.get("/api/orders/DH999999999999")
    assert nf_req.status_code == 404, f"Expected 404, got {nf_req.status_code}"
    print("[PASS] Non-existent order DH999999999999 -> 404 Not Found")

    print("\n==================================================")
    print("ALL REAL DATA INTEGRATION TESTS PASSED 100%!")
    print("==================================================")

if __name__ == "__main__":
    test_endpoints()
