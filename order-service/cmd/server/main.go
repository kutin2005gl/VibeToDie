package main

import (
	"context"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"nexus/order-service/internal/api"
	"nexus/order-service/internal/grpcapi"
	"nexus/order-service/internal/store"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		log.Fatal("DATABASE_URL is required")
	}

	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		log.Fatalf("connect db: %v", err)
	}
	defer pool.Close()

	st := store.New(pool)
	if err := st.Migrate(ctx); err != nil {
		log.Fatalf("migrate: %v", err)
	}

	if os.Getenv("ORDERS_SEED") == "1" || os.Getenv("ORDERS_SEED") == "true" {
		if err := st.Seed(ctx); err != nil {
			log.Fatalf("seed: %v", err)
		}
		log.Println("order-service: seed data applied successfully")
	}

	h := api.New(st)
	srv := &http.Server{
		Addr:              ":" + envOr("PORT", "8080"),
		Handler:           h.Routes(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	// gRPC for ai-service only when INTERNAL_TOKEN is set; without it the port stays closed.
	var gs interface{ GracefulStop() }
	if token := os.Getenv("INTERNAL_TOKEN"); token != "" {
		lis, err := net.Listen("tcp", ":"+envOr("GRPC_PORT", "9090"))
		if err != nil {
			log.Fatalf("grpc listen: %v", err)
		}
		g := grpcapi.NewGRPCServer(token, st)
		gs = g
		go func() {
			log.Printf("order-service gRPC listening on %s", lis.Addr())
			if err := g.Serve(lis); err != nil {
				log.Fatalf("grpc serve: %v", err)
			}
		}()
	}

	go func() {
		<-ctx.Done()
		if gs != nil {
			gs.GracefulStop()
		}
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
	}()

	log.Printf("order-service listening on %s", srv.Addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
