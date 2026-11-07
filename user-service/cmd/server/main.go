package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"nexus/user-service/internal/api"
	"nexus/user-service/internal/password"
	"nexus/user-service/internal/store"
	"nexus/user-service/internal/token"
	"nexus/user-service/internal/user"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	dbURL := os.Getenv("DATABASE_URL")
	if dbURL == "" {
		log.Fatal("DATABASE_URL is required")
	}
	accessTTL := durationEnv("ACCESS_TOKEN_TTL", 15*time.Minute)
	refreshTTL := durationEnv("REFRESH_TOKEN_TTL", 7*24*time.Hour)
	tokens, err := token.NewIssuer(os.Getenv("JWT_SECRET"), os.Getenv("JWT_ISSUER"), accessTTL)
	if err != nil {
		log.Fatal(err)
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

	admin := envOr("ADMIN_DEPARTMENT", "executive")
	if err := bootstrapAdmin(ctx, st, admin); err != nil {
		log.Fatalf("bootstrap admin: %v", err)
	}

	h := api.New(st, tokens, api.Config{
		RefreshTTL:      refreshTTL,
		Departments:     splitList(envOr("DEPARTMENTS", "cskh,executive,it")),
		AdminDepartment: admin,
	})
	srv := &http.Server{
		Addr:              ":" + envOr("PORT", "8080"),
		Handler:           h.Routes(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
	}()

	log.Printf("user-service listening on %s", srv.Addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

// bootstrapAdmin creates the first admin from BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD
// when no account has that email yet, so a fresh database has someone who can grant departments.
// An existing account is left as it is.
func bootstrapAdmin(ctx context.Context, st *store.Store, department string) error {
	email := strings.ToLower(strings.TrimSpace(os.Getenv("BOOTSTRAP_ADMIN_EMAIL")))
	pw := os.Getenv("BOOTSTRAP_ADMIN_PASSWORD")
	if email == "" || pw == "" {
		return nil
	}
	if len(pw) < 8 {
		return errors.New("BOOTSTRAP_ADMIN_PASSWORD must be at least 8 characters")
	}
	_, _, err := st.UserByEmail(ctx, email)
	if err == nil {
		return nil
	}
	if !errors.Is(err, user.ErrNotFound) {
		return err
	}
	hash, err := password.Hash(pw)
	if err != nil {
		return err
	}
	_, err = st.CreateUser(ctx, email, "Admin", hash, []string{department})
	if errors.Is(err, user.ErrEmailTaken) {
		return nil
	}
	if err == nil {
		log.Printf("created admin %s (%s)", email, department)
	}
	return err
}

func splitList(s string) []string {
	var out []string
	for _, v := range strings.Split(s, ",") {
		if v = strings.TrimSpace(v); v != "" {
			out = append(out, v)
		}
	}
	return out
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	d, err := time.ParseDuration(v)
	if err != nil || d <= 0 {
		log.Fatalf("%s: bad duration %q", key, v)
	}
	return d
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
