package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"testing"

	"nexus/order-service/internal/store"
)

type memStore struct {
	mu        sync.Mutex
	orders    map[string]*store.Order
	products  map[string]*store.Product
	inventory map[string]map[string]int // product_id -> store_name -> qty
}

func newMemStore() *memStore {
	m := &memStore{
		orders:    make(map[string]*store.Order),
		products:  make(map[string]*store.Product),
		inventory: make(map[string]map[string]int),
	}

	// Preload test data matching seed
	p1 := &store.Product{ProductID: "P001", Name: "iPhone 16 128GB", Price: 22990000, WarrantyMonths: 12, StockTotal: 14}
	p2 := &store.Product{ProductID: "P002", Name: "Samsung Galaxy S25 256GB", Price: 18490000, WarrantyMonths: 12, StockTotal: 6}
	p3 := &store.Product{ProductID: "P003", Name: "Xiaomi 15 256GB", Price: 14990000, WarrantyMonths: 18, StockTotal: 0}
	m.products["P001"] = p1
	m.products["P002"] = p2
	m.products["P003"] = p3

	m.inventory["P001"] = map[string]int{"CN Quận 1": 8, "CN Thủ Đức": 6}
	m.inventory["P002"] = map[string]int{"CN Quận 1": 4, "CN Thủ Đức": 2}
	m.inventory["P003"] = map[string]int{"CN Quận 1": 0, "CN Thủ Đức": 0}

	delDate1 := "2026-10-17"
	m.orders["DH1001"] = &store.Order{
		OrderID:       "DH1001",
		CustomerName:  "Nguyễn Văn An",
		ProductID:     "P001",
		ProductName:   "iPhone 16 128GB",
		Quantity:      1,
		UnitPrice:     22990000,
		Discount:      1000000,
		PaidAmount:    21990000,
		PaymentMethod: "chuyển khoản",
		OrderDate:     "2026-10-15",
		DeliveredDate: &delDate1,
		Status:        "delivered",
		Store:         "CN Quận 1",
	}

	instMonths2 := 6
	m.orders["DH1002"] = &store.Order{
		OrderID:           "DH1002",
		CustomerName:      "Trần Thị Bình",
		ProductID:         "P002",
		ProductName:       "Samsung Galaxy S25 256GB",
		Quantity:          1,
		UnitPrice:         18490000,
		Discount:          0,
		PaidAmount:        0,
		PaymentMethod:     "trả góp qua thẻ tín dụng",
		InstallmentMonths: &instMonths2,
		OrderDate:         "2026-10-19",
		DeliveredDate:     nil,
		Status:            "shipping",
		Store:             "CN Thủ Đức",
	}

	return m
}

func (m *memStore) Ping(ctx context.Context) error { return nil }

func (m *memStore) OrderByID(ctx context.Context, id string) (*store.Order, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	o, ok := m.orders[id]
	if !ok {
		return nil, store.ErrNotFound
	}
	return o, nil
}

func (m *memStore) ProductByID(ctx context.Context, id string) (*store.Product, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.products[id]
	if !ok {
		return nil, store.ErrNotFound
	}
	return p, nil
}

func (m *memStore) SearchProducts(ctx context.Context, query string, limit int) ([]store.ProductSummary, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	unaccentedQuery := store.Unaccent(query)
	words := strings.Fields(unaccentedQuery)
	if len(words) == 0 {
		return []store.ProductSummary{}, nil
	}

	var items []store.ProductSummary
	for _, p := range m.products {
		unaccentedName := store.Unaccent(p.Name)
		matchesAll := true
		for _, w := range words {
			if !strings.Contains(unaccentedName, w) {
				matchesAll = false
				break
			}
		}
		if matchesAll {
			items = append(items, store.ProductSummary{
				ProductID: p.ProductID,
				Name:      p.Name,
				Price:     p.Price,
			})
		}
	}

	sort.Slice(items, func(i, j int) bool {
		nameI := store.Unaccent(items[i].Name)
		nameJ := store.Unaccent(items[j].Name)
		prefixI := strings.HasPrefix(nameI, unaccentedQuery)
		prefixJ := strings.HasPrefix(nameJ, unaccentedQuery)
		if prefixI != prefixJ {
			return prefixI
		}
		return items[i].Name < items[j].Name
	})

	if len(items) > limit {
		items = items[:limit]
	}
	return items, nil
}

func (m *memStore) ProductStock(ctx context.Context, id string) (*store.ProductStock, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.products[id]; !ok {
		return nil, store.ErrNotFound
	}
	inv := m.inventory[id]
	byStore := make(map[string]int)
	total := 0
	for s, qty := range inv {
		byStore[s] = qty
		total += qty
	}
	return &store.ProductStock{
		ProductID:  id,
		StockTotal: total,
		ByStore:    byStore,
	}, nil
}

func testRequest(h http.Handler, method, path string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, nil)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestHealth(t *testing.T) {
	h := New(newMemStore()).Routes()
	rec := testRequest(h, http.MethodGet, "/healthz", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var res map[string]string
	_ = json.Unmarshal(rec.Body.Bytes(), &res)
	if res["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", res)
	}
}

func TestAuthAndRBAC(t *testing.T) {
	h := New(newMemStore()).Routes()

	// 1. Missing X-User-Id -> 401
	rec := testRequest(h, http.MethodGet, "/api/orders/DH1001", nil)
	if rec.Code != http.StatusUnauthorized {
		t.Errorf("expected 401, got %d", rec.Code)
	}

	// 2. Department 'it' (not cskh or executive) -> 403
	rec = testRequest(h, http.MethodGet, "/api/orders/DH1001", map[string]string{
		"X-User-Id":          "user-1",
		"X-User-Departments": "it",
	})
	if rec.Code != http.StatusForbidden {
		t.Errorf("expected 403, got %d", rec.Code)
	}

	// 3. Department 'cskh' -> 200
	rec = testRequest(h, http.MethodGet, "/api/orders/DH1001", map[string]string{
		"X-User-Id":          "user-1",
		"X-User-Departments": "cskh",
	})
	if rec.Code != http.StatusOK {
		t.Errorf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	// 4. Department 'executive' -> 200
	rec = testRequest(h, http.MethodGet, "/api/orders/DH1001", map[string]string{
		"X-User-Id":          "user-2",
		"X-User-Departments": "marketing,executive",
	})
	if rec.Code != http.StatusOK {
		t.Errorf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestOrdersEndpoint(t *testing.T) {
	h := New(newMemStore()).Routes()
	authHeaders := map[string]string{"X-User-Id": "u1", "X-User-Departments": "cskh"}

	// Invalid format -> 400
	rec := testRequest(h, http.MethodGet, "/api/orders/1001", authHeaders)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400 for bad id, got %d", rec.Code)
	}

	// Not found -> 404
	rec = testRequest(h, http.MethodGet, "/api/orders/DH9999", authHeaders)
	if rec.Code != http.StatusNotFound {
		t.Errorf("expected 404 for unknown order, got %d", rec.Code)
	}

	// Found DH1001 -> 200
	rec = testRequest(h, http.MethodGet, "/api/orders/DH1001", authHeaders)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var o store.Order
	if err := json.Unmarshal(rec.Body.Bytes(), &o); err != nil {
		t.Fatal(err)
	}
	if o.OrderID != "DH1001" || o.PaidAmount != 21990000 || o.Store != "CN Quận 1" {
		t.Errorf("unexpected order data: %+v", o)
	}
}

func TestProductsEndpoint(t *testing.T) {
	h := New(newMemStore()).Routes()
	authHeaders := map[string]string{"X-User-Id": "u1", "X-User-Departments": "cskh"}

	// Invalid format -> 400
	rec := testRequest(h, http.MethodGet, "/api/products/Pabc", authHeaders)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rec.Code)
	}

	// Not found -> 404
	rec = testRequest(h, http.MethodGet, "/api/products/P999", authHeaders)
	if rec.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rec.Code)
	}

	// Found P001 -> 200
	rec = testRequest(h, http.MethodGet, "/api/products/P001", authHeaders)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var p store.Product
	if err := json.Unmarshal(rec.Body.Bytes(), &p); err != nil {
		t.Fatal(err)
	}
	if p.ProductID != "P001" || p.StockTotal != 14 {
		t.Errorf("unexpected product data: %+v", p)
	}
}

func TestSearchProducts(t *testing.T) {
	h := New(newMemStore()).Routes()
	authHeaders := map[string]string{"X-User-Id": "u1", "X-User-Departments": "cskh"}

	// Query too short (< 2 chars) -> 400
	rec := testRequest(h, http.MethodGet, "/api/products?q=s", authHeaders)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400 for short query, got %d", rec.Code)
	}

	// "samsung s25" -> finds P002
	rec = testRequest(h, http.MethodGet, "/api/products?q=samsung%20s25", authHeaders)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var res map[string][]store.ProductSummary
	_ = json.Unmarshal(rec.Body.Bytes(), &res)
	if len(res["items"]) != 1 || res["items"][0].ProductID != "P002" {
		t.Errorf("expected P002 for 'samsung s25', got: %v", res["items"])
	}

	// "Samsung Galaxy S25" -> also finds P002
	rec = testRequest(h, http.MethodGet, "/api/products?q=Samsung%20Galaxy%20S25", authHeaders)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var res2 map[string][]store.ProductSummary
	_ = json.Unmarshal(rec.Body.Bytes(), &res2)
	if len(res2["items"]) != 1 || res2["items"][0].ProductID != "P002" {
		t.Errorf("expected P002 for 'Samsung Galaxy S25', got: %v", res2["items"])
	}
}

func TestStockEndpoint(t *testing.T) {
	h := New(newMemStore()).Routes()
	authHeaders := map[string]string{"X-User-Id": "u1", "X-User-Departments": "cskh"}

	// Not found -> 404
	rec := testRequest(h, http.MethodGet, "/api/products/P999/stock", authHeaders)
	if rec.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rec.Code)
	}

	// Found P001 -> 200
	rec = testRequest(h, http.MethodGet, "/api/products/P001/stock", authHeaders)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var s store.ProductStock
	if err := json.Unmarshal(rec.Body.Bytes(), &s); err != nil {
		t.Fatal(err)
	}
	if s.ProductID != "P001" || s.StockTotal != 14 {
		t.Errorf("unexpected stock data: %+v", s)
	}

	// Invariant: sum of by_store equals stock_total
	sum := 0
	for _, qty := range s.ByStore {
		sum += qty
	}
	if sum != s.StockTotal {
		t.Errorf("by_store sum %d != stock_total %d", sum, s.StockTotal)
	}
}
