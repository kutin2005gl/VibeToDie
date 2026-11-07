package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"nexus/gateway/internal/auth"
	"nexus/gateway/internal/config"
	"nexus/gateway/internal/ratelimit"
	"nexus/gateway/internal/router"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		fatal("load config", err)
	}

	limits := ratelimit.NewManager()
	limits.StartCleanup(10*time.Minute, 30*time.Minute, ctx.Done())

	handler, err := router.New(cfg, auth.NewJWTService(cfg.JWTSecret, cfg.JWTIssuer), limits)
	if err != nil {
		fatal("build router", err)
	}

	// No Read/WriteTimeout: each route bounds its own request (ai runs take minutes).
	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
	}()

	for _, r := range cfg.Routes {
		slog.Info("route", "name", r.Name, "prefix", r.Prefix, "upstream", r.Upstream, "auth", r.AuthMode)
	}
	slog.Info("gateway listening", "addr", srv.Addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fatal("serve", err)
	}
}

func fatal(msg string, err error) {
	slog.Error(msg, "error", err)
	os.Exit(1)
}
