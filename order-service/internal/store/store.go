// Package store persists stores, products, inventory and orders in PostgreSQL.
package store

import (
	"context"
	_ "embed"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed schema.sql
var schemaSQL string

//go:embed seed.sql
var seedSQL string

var ErrNotFound = errors.New("not found")

type Order struct {
	OrderID           string  `json:"order_id"`
	CustomerName      string  `json:"customer_name"`
	CustomerEmail     *string `json:"customer_email"`
	ProductID         string  `json:"product_id"`
	ProductName       string  `json:"product_name"`
	Quantity          int     `json:"quantity"`
	UnitPrice         int64   `json:"unit_price"`
	Discount          int64   `json:"discount"`
	PaidAmount        int64   `json:"paid_amount"`
	PaymentMethod     string  `json:"payment_method"`
	InstallmentMonths *int    `json:"installment_months,omitempty"`
	OrderDate         string  `json:"order_date"`
	DeliveredDate     *string `json:"delivered_date"`
	Status            string  `json:"status"`
	Store             string  `json:"store"`
}

type Product struct {
	ProductID      string `json:"product_id"`
	Name           string `json:"name"`
	Price          int64  `json:"price"`
	WarrantyMonths int    `json:"warranty_months"`
	StockTotal     int    `json:"stock_total"`
}

type ProductSummary struct {
	ProductID string `json:"product_id"`
	Name      string `json:"name"`
	Price     int64  `json:"price"`
}

type ProductStock struct {
	ProductID  string         `json:"product_id"`
	StockTotal int            `json:"stock_total"`
	ByStore    map[string]int `json:"by_store"`
}

type Store struct {
	pool *pgxpool.Pool
}

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// Migrate executes schema.sql (idempotent).
func (s *Store) Migrate(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, schemaSQL)
	return err
}

// Seed executes seed.sql (idempotent).
func (s *Store) Seed(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, seedSQL)
	return err
}

func (s *Store) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}

func (s *Store) OrderByID(ctx context.Context, id string) (*Order, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT o.id, o.customer_name, o.customer_email, o.product_id, p.name, o.quantity,
		       o.unit_price, o.discount, o.paid_amount, o.payment_method,
		       o.installment_months, TO_CHAR(o.order_date, 'YYYY-MM-DD'),
		       TO_CHAR(o.delivered_date, 'YYYY-MM-DD'), o.status, s.name
		FROM orders o
		JOIN products p ON o.product_id = p.id
		JOIN stores s ON o.store_id = s.id
		WHERE o.id = $1`, id)

	var o Order
	err := row.Scan(
		&o.OrderID, &o.CustomerName, &o.CustomerEmail, &o.ProductID, &o.ProductName, &o.Quantity,
		&o.UnitPrice, &o.Discount, &o.PaidAmount, &o.PaymentMethod,
		&o.InstallmentMonths, &o.OrderDate, &o.DeliveredDate, &o.Status, &o.Store,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &o, nil
}

func (s *Store) ProductByID(ctx context.Context, id string) (*Product, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT p.id, p.name, p.price, p.warranty_months,
		       COALESCE((SELECT SUM(qty) FROM inventory WHERE product_id = p.id), 0)
		FROM products p
		WHERE p.id = $1`, id)

	var p Product
	err := row.Scan(&p.ProductID, &p.Name, &p.Price, &p.WarrantyMonths, &p.StockTotal)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (s *Store) SearchProducts(ctx context.Context, query string, limit int) ([]ProductSummary, error) {
	if limit <= 0 {
		limit = 5
	}
	if limit > 10 {
		limit = 10
	}
	unaccented := Unaccent(query)
	words := strings.Fields(unaccented)
	if len(words) == 0 {
		return []ProductSummary{}, nil
	}

	var whereClauses []string
	var args []any
	for i, w := range words {
		whereClauses = append(whereClauses, fmt.Sprintf("p.name_unaccent LIKE $%d", i+1))
		args = append(args, "%"+w+"%")
	}
	prefixArgIdx := len(args) + 1
	args = append(args, unaccented+"%")
	limitArgIdx := len(args) + 1
	args = append(args, limit)

	querySQL := fmt.Sprintf(`
		SELECT p.id, p.name, p.price
		FROM products p
		WHERE %s
		ORDER BY
		    CASE WHEN p.name_unaccent LIKE $%d THEN 0 ELSE 1 END,
		    p.name ASC
		LIMIT $%d`, strings.Join(whereClauses, " AND "), prefixArgIdx, limitArgIdx)

	rows, err := s.pool.Query(ctx, querySQL, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]ProductSummary, 0)
	for rows.Next() {
		var item ProductSummary
		if err := rows.Scan(&item.ProductID, &item.Name, &item.Price); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ProductStock(ctx context.Context, id string) (*ProductStock, error) {
	// First check if product exists
	var dummy string
	err := s.pool.QueryRow(ctx, `SELECT id FROM products WHERE id = $1`, id).Scan(&dummy)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}

	// Only stores that hold a stock row for the product: a store without one has no data,
	// which is not the same as zero in stock.
	rows, err := s.pool.Query(ctx, `
		SELECT s.name, i.qty
		FROM inventory i
		JOIN stores s ON s.id = i.store_id
		WHERE i.product_id = $1
		ORDER BY s.name ASC`, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	byStore := make(map[string]int)
	total := 0
	for rows.Next() {
		var storeName string
		var qty int
		if err := rows.Scan(&storeName, &qty); err != nil {
			return nil, err
		}
		byStore[storeName] = qty
		total += qty
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	return &ProductStock{
		ProductID:  id,
		StockTotal: total,
		ByStore:    byStore,
	}, nil
}
