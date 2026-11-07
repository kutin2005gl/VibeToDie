package grpcapi

import (
	"context"
	"net"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	pb "nexus/order-service/internal/pb/ordersv1"
	"nexus/order-service/internal/store"
)

type memStore struct{}

func (memStore) Ping(context.Context) error { return nil }

func (memStore) OrderByID(_ context.Context, id string) (*store.Order, error) {
	switch id {
	case "DH1001":
		d, m := "2026-10-17", 6
		return &store.Order{OrderID: id, Quantity: 1, PaidAmount: 1 << 40, DeliveredDate: &d, InstallmentMonths: &m}, nil
	case "DH1002":
		return &store.Order{OrderID: id}, nil
	}
	return nil, store.ErrNotFound
}

func (memStore) ProductByID(_ context.Context, id string) (*store.Product, error) {
	if id == "P001" {
		return &store.Product{ProductID: id, Name: "iPhone", WarrantyMonths: 12, StockTotal: 14}, nil
	}
	return nil, store.ErrNotFound
}

func (memStore) SearchProducts(_ context.Context, q string, limit int) ([]store.ProductSummary, error) {
	return []store.ProductSummary{{ProductID: "P002", Name: "Galaxy " + q, Price: 1}}, nil
}

func (memStore) ProductStock(_ context.Context, id string) (*store.ProductStock, error) {
	if id == "P001" {
		return &store.ProductStock{ProductID: id, StockTotal: 14, ByStore: map[string]int{"CN Quận 1": 8}}, nil
	}
	return nil, store.ErrNotFound
}

func start(t *testing.T) pb.OrdersServiceClient {
	t.Helper()
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gs := NewGRPCServer("secret", memStore{})
	go gs.Serve(lis)
	t.Cleanup(gs.Stop)
	conn, err := grpc.NewClient(lis.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	return pb.NewOrdersServiceClient(conn)
}

func withMD(kv ...string) context.Context {
	return metadata.AppendToOutgoingContext(context.Background(), kv...)
}

var cskh = []string{"x-internal-token", "secret", "x-user-id", "u1", "x-user-departments", "cskh"}

func wantCode(t *testing.T, err error, want codes.Code) {
	t.Helper()
	if got := status.Code(err); got != want {
		t.Fatalf("code = %v (%v), want %v", got, err, want)
	}
}

func TestGetOrder(t *testing.T) {
	c := start(t)
	o, err := c.GetOrder(withMD(cskh...), &pb.GetOrderRequest{OrderId: "DH1001"})
	if err != nil {
		t.Fatal(err)
	}
	if o.PaidAmount != 1<<40 || o.GetDeliveredDate() != "2026-10-17" || o.GetInstallmentMonths() != 6 {
		t.Fatalf("unexpected order %+v", o)
	}
	o, err = c.GetOrder(withMD(cskh...), &pb.GetOrderRequest{OrderId: "DH1002"})
	if err != nil {
		t.Fatal(err)
	}
	if o.DeliveredDate != nil || o.InstallmentMonths != nil {
		t.Fatalf("optional fields should be unset: %+v", o)
	}
}

func TestOtherRPCs(t *testing.T) {
	c := start(t)
	p, err := c.GetProduct(withMD(cskh...), &pb.GetProductRequest{ProductId: "P001"})
	if err != nil || p.WarrantyMonths != 12 {
		t.Fatalf("product %+v %v", p, err)
	}
	s, err := c.SearchProducts(withMD(cskh...), &pb.SearchProductsRequest{Query: "s25"})
	if err != nil || len(s.Items) != 1 || s.Items[0].ProductId != "P002" {
		t.Fatalf("search %+v %v", s, err)
	}
	st, err := c.GetStock(withMD(cskh...), &pb.GetStockRequest{ProductId: "P001"})
	if err != nil || st.StockTotal != 14 || st.ByStore["CN Quận 1"] != 8 {
		t.Fatalf("stock %+v %v", st, err)
	}
}

func TestErrors(t *testing.T) {
	c := start(t)
	_, err := c.GetOrder(withMD(cskh...), &pb.GetOrderRequest{OrderId: "DH9999"})
	wantCode(t, err, codes.NotFound)
	_, err = c.GetOrder(withMD(cskh...), &pb.GetOrderRequest{OrderId: "bad"})
	wantCode(t, err, codes.InvalidArgument)
	_, err = c.GetStock(withMD(cskh...), &pb.GetStockRequest{ProductId: "x"})
	wantCode(t, err, codes.InvalidArgument)
	_, err = c.SearchProducts(withMD(cskh...), &pb.SearchProductsRequest{Query: "a"})
	wantCode(t, err, codes.InvalidArgument)
}

func TestAuth(t *testing.T) {
	c := start(t)
	req := &pb.GetOrderRequest{OrderId: "DH1001"}
	_, err := c.GetOrder(context.Background(), req)
	wantCode(t, err, codes.Unauthenticated)
	_, err = c.GetOrder(withMD("x-internal-token", "wrong", "x-user-id", "u1", "x-user-departments", "cskh"), req)
	wantCode(t, err, codes.Unauthenticated)
	_, err = c.GetOrder(withMD("x-internal-token", "secret", "x-user-departments", "cskh"), req)
	wantCode(t, err, codes.Unauthenticated)
	_, err = c.GetOrder(withMD("x-internal-token", "secret", "x-user-id", "u1", "x-user-departments", "it"), req)
	wantCode(t, err, codes.PermissionDenied)
	_, err = c.GetOrder(withMD("x-internal-token", "secret", "x-user-id", "u1", "x-user-departments", "it, executive"), req)
	if err != nil {
		t.Fatalf("executive should pass: %v", err)
	}
}
