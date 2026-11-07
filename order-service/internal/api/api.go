// Package api implements HTTP handlers for order-service.
package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"nexus/order-service/internal/store"
)

const (
	headerUserID      = "X-User-Id"
	headerDepartments = "X-User-Departments"
)

var (
	orderIDRegex   = regexp.MustCompile(`^DH\d+$`)
	productIDRegex = regexp.MustCompile(`^P\d+$`)
)

type Store interface {
	Ping(ctx context.Context) error
	OrderByID(ctx context.Context, id string) (*store.Order, error)
	ProductByID(ctx context.Context, id string) (*store.Product, error)
	SearchProducts(ctx context.Context, query string, limit int) ([]store.ProductSummary, error)
	ProductStock(ctx context.Context, id string) (*store.ProductStock, error)
}

type Handler struct {
	store Store
}

func New(s Store) *Handler {
	return &Handler{store: s}
}

func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.health)
	mux.HandleFunc("GET /api/orders/{order_id}", h.getOrder)
	mux.HandleFunc("GET /api/products/{product_id}/stock", h.getProductStock)
	mux.HandleFunc("GET /api/products/{product_id}", h.getProduct)
	mux.HandleFunc("GET /api/products", h.searchProducts)
	return mux
}

func (h *Handler) health(w http.ResponseWriter, r *http.Request) {
	if err := h.store.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "degraded", "db": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) checkAuth(w http.ResponseWriter, r *http.Request) bool {
	userID := strings.TrimSpace(r.Header.Get(headerUserID))
	if userID == "" {
		writeError(w, http.StatusUnauthorized, "unauthorized: missing user id")
		return false
	}
	deptsRaw := r.Header.Get(headerDepartments)
	allowed := false
	for _, dept := range strings.Split(deptsRaw, ",") {
		dept = strings.TrimSpace(dept)
		if dept == "cskh" || dept == "executive" {
			allowed = true
			break
		}
	}
	if !allowed {
		writeError(w, http.StatusForbidden, "forbidden: insufficient department permissions")
		return false
	}
	return true
}

func (h *Handler) getOrder(w http.ResponseWriter, r *http.Request) {
	if !h.checkAuth(w, r) {
		return
	}
	orderID := r.PathValue("order_id")
	if !orderIDRegex.MatchString(orderID) {
		writeError(w, http.StatusBadRequest, "invalid order id format")
		return
	}

	order, err := h.store.OrderByID(r.Context(), orderID)
	if err != nil {
		if err == store.ErrNotFound {
			writeError(w, http.StatusNotFound, fmt.Sprintf("order %s does not exist", orderID))
			return
		}
		writeError(w, http.StatusInternalServerError, "database error")
		return
	}
	writeJSON(w, http.StatusOK, order)
}

func (h *Handler) getProduct(w http.ResponseWriter, r *http.Request) {
	if !h.checkAuth(w, r) {
		return
	}
	productID := r.PathValue("product_id")
	if !productIDRegex.MatchString(productID) {
		writeError(w, http.StatusBadRequest, "invalid product id format")
		return
	}

	product, err := h.store.ProductByID(r.Context(), productID)
	if err != nil {
		if err == store.ErrNotFound {
			writeError(w, http.StatusNotFound, fmt.Sprintf("product %s does not exist", productID))
			return
		}
		writeError(w, http.StatusInternalServerError, "database error")
		return
	}
	writeJSON(w, http.StatusOK, product)
}

func (h *Handler) searchProducts(w http.ResponseWriter, r *http.Request) {
	if !h.checkAuth(w, r) {
		return
	}
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if len(q) < 2 {
		writeError(w, http.StatusBadRequest, "query 'q' must be at least 2 characters")
		return
	}

	limit := 5
	if limitParam := r.URL.Query().Get("limit"); limitParam != "" {
		if parsed, err := strconv.Atoi(limitParam); err == nil && parsed > 0 {
			limit = parsed
		}
	}

	items, err := h.store.SearchProducts(r.Context(), q, limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

func (h *Handler) getProductStock(w http.ResponseWriter, r *http.Request) {
	if !h.checkAuth(w, r) {
		return
	}
	productID := r.PathValue("product_id")
	if !productIDRegex.MatchString(productID) {
		writeError(w, http.StatusBadRequest, "invalid product id format")
		return
	}

	stock, err := h.store.ProductStock(r.Context(), productID)
	if err != nil {
		if err == store.ErrNotFound {
			writeError(w, http.StatusNotFound, fmt.Sprintf("product %s does not exist", productID))
			return
		}
		writeError(w, http.StatusInternalServerError, "database error")
		return
	}
	writeJSON(w, http.StatusOK, stock)
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
