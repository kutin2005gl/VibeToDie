// Package grpcapi serves the read-only OrdersService (proto/orders/v1) for ai-service.
package grpcapi

import (
	"context"
	"crypto/subtle"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"nexus/order-service/internal/api"
	pb "nexus/order-service/internal/pb/ordersv1"
	"nexus/order-service/internal/store"
)

const (
	mdToken       = "x-internal-token"
	mdUserID      = "x-user-id"
	mdDepartments = "x-user-departments"

	defaultSearchLimit = 5
	maxSearchLimit     = 50
)

var (
	orderIDRegex   = regexp.MustCompile(`^DH\d+$`)
	productIDRegex = regexp.MustCompile(`^P\d+$`)
)

type Server struct {
	pb.UnimplementedOrdersServiceServer
	store api.Store
}

func New(s api.Store) *Server { return &Server{store: s} }

// Register serves OrdersService on gs, guarded by the internal token and department check.
func Register(gs *grpc.Server, s api.Store) { pb.RegisterOrdersServiceServer(gs, New(s)) }

// NewGRPCServer builds a grpc.Server whose every call needs `token` and a cskh/executive requester.
func NewGRPCServer(token string, s api.Store) *grpc.Server {
	gs := grpc.NewServer(grpc.UnaryInterceptor(AuthInterceptor(token)))
	Register(gs, s)
	return gs
}

// AuthInterceptor mirrors the HTTP checkAuth: identity plus cskh/executive, with the shared secret on top.
func AuthInterceptor(token string) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, _ *grpc.UnaryServerInfo, next grpc.UnaryHandler) (any, error) {
		md, _ := metadata.FromIncomingContext(ctx)
		get := func(k string) string {
			if v := md.Get(k); len(v) > 0 {
				return strings.TrimSpace(v[0])
			}
			return ""
		}
		if subtle.ConstantTimeCompare([]byte(get(mdToken)), []byte(token)) != 1 {
			return nil, status.Error(codes.Unauthenticated, "unauthorized: bad internal token")
		}
		if get(mdUserID) == "" {
			return nil, status.Error(codes.Unauthenticated, "unauthorized: missing user id")
		}
		for _, dept := range strings.Split(get(mdDepartments), ",") {
			if d := strings.TrimSpace(dept); d == "cskh" || d == "executive" {
				return next(ctx, req)
			}
		}
		return nil, status.Error(codes.PermissionDenied, "forbidden: insufficient department permissions")
	}
}

func storeErr(err error, kind, id string) error {
	if errors.Is(err, store.ErrNotFound) {
		return status.Error(codes.NotFound, fmt.Sprintf("%s %s does not exist", kind, id))
	}
	return status.Error(codes.Internal, "database error")
}

func (s *Server) GetOrder(ctx context.Context, req *pb.GetOrderRequest) (*pb.Order, error) {
	if !orderIDRegex.MatchString(req.GetOrderId()) {
		return nil, status.Error(codes.InvalidArgument, "invalid order id format")
	}
	o, err := s.store.OrderByID(ctx, req.GetOrderId())
	if err != nil {
		return nil, storeErr(err, "order", req.GetOrderId())
	}
	out := &pb.Order{
		OrderId:       o.OrderID,
		CustomerName:  o.CustomerName,
		CustomerEmail: o.CustomerEmail,
		ProductId:     o.ProductID,
		ProductName:   o.ProductName,
		Quantity:      int32(o.Quantity),
		UnitPrice:     o.UnitPrice,
		Discount:      o.Discount,
		PaidAmount:    o.PaidAmount,
		PaymentMethod: o.PaymentMethod,
		OrderDate:     o.OrderDate,
		DeliveredDate: o.DeliveredDate,
		Status:        o.Status,
		Store:         o.Store,
	}
	if o.InstallmentMonths != nil {
		m := int32(*o.InstallmentMonths)
		out.InstallmentMonths = &m
	}
	return out, nil
}

func (s *Server) GetProduct(ctx context.Context, req *pb.GetProductRequest) (*pb.Product, error) {
	if !productIDRegex.MatchString(req.GetProductId()) {
		return nil, status.Error(codes.InvalidArgument, "invalid product id format")
	}
	p, err := s.store.ProductByID(ctx, req.GetProductId())
	if err != nil {
		return nil, storeErr(err, "product", req.GetProductId())
	}
	return &pb.Product{
		ProductId:      p.ProductID,
		Name:           p.Name,
		Price:          p.Price,
		WarrantyMonths: int32(p.WarrantyMonths),
		StockTotal:     int32(p.StockTotal),
	}, nil
}

func (s *Server) SearchProducts(ctx context.Context, req *pb.SearchProductsRequest) (*pb.SearchProductsResponse, error) {
	q := strings.TrimSpace(req.GetQuery())
	if len(q) < 2 {
		return nil, status.Error(codes.InvalidArgument, "query must be at least 2 characters")
	}
	limit := int(req.GetLimit())
	if limit <= 0 {
		limit = defaultSearchLimit
	}
	if limit > maxSearchLimit {
		limit = maxSearchLimit
	}
	items, err := s.store.SearchProducts(ctx, q, limit)
	if err != nil {
		return nil, status.Error(codes.Internal, "database error")
	}
	out := &pb.SearchProductsResponse{Items: make([]*pb.ProductSummary, 0, len(items))}
	for _, it := range items {
		out.Items = append(out.Items, &pb.ProductSummary{ProductId: it.ProductID, Name: it.Name, Price: it.Price})
	}
	return out, nil
}

func (s *Server) GetStock(ctx context.Context, req *pb.GetStockRequest) (*pb.Stock, error) {
	if !productIDRegex.MatchString(req.GetProductId()) {
		return nil, status.Error(codes.InvalidArgument, "invalid product id format")
	}
	st, err := s.store.ProductStock(ctx, req.GetProductId())
	if err != nil {
		return nil, storeErr(err, "product", req.GetProductId())
	}
	byStore := make(map[string]int32, len(st.ByStore))
	for k, v := range st.ByStore {
		byStore[k] = int32(v)
	}
	return &pb.Stock{ProductId: st.ProductID, StockTotal: int32(st.StockTotal), ByStore: byStore}, nil
}
