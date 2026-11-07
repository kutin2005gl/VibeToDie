// Package config reads the gateway's environment and its route table.
package config

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Port           string
	JWTSecret      string
	JWTIssuer      string
	CORSOrigins    []string
	TrustedProxies []string
	Routes         []RouteConfig
}

type RouteConfig struct {
	Name     string `yaml:"name"`
	Prefix   string `yaml:"prefix"`
	Upstream string `yaml:"upstream"`
	// KeepPrefix forwards the path as is; by default the prefix is stripped (/api/ai/run → /run).
	KeepPrefix bool          `yaml:"keep_prefix"`
	Timeout    time.Duration `yaml:"timeout"`
	// StreamTimeout, when set, makes the route a streaming one: SSE requests (Accept:
	// text/event-stream) get this limit instead of Timeout and every write is flushed at once.
	StreamTimeout time.Duration `yaml:"stream_timeout"`
	// MaxBody caps the request body in bytes (413 above it); 0 means DefaultMaxBody.
	MaxBody   int64       `yaml:"max_body"`
	Retry     RetryConfig `yaml:"retry"`
	RateLimit RateLimit   `yaml:"rate_limit"`
	AuthMode  AuthMode    `yaml:"auth_mode"`
}

type RetryConfig struct {
	Attempts  int           `yaml:"attempts"`
	BaseDelay time.Duration `yaml:"base_delay"`
	MaxDelay  time.Duration `yaml:"max_delay"`
}

// RateLimit allows Requests per Window, per user when signed in, else per IP. Zero disables it.
type RateLimit struct {
	Requests int           `yaml:"requests"`
	Window   time.Duration `yaml:"window"`
	Burst    int           `yaml:"burst"`
}

type AuthMode string

const (
	AuthNone     AuthMode = "none"
	AuthOptional AuthMode = "optional"
	AuthRequired AuthMode = "required"
)

// DefaultMaxBody is a route's body limit when it sets none: chat messages and JSON forms are
// far smaller.
const DefaultMaxBody int64 = 1 << 20

// MinSecretLen is the shortest JWT_SECRET accepted: HS256 needs a key of at least 256 bits.
const MinSecretLen = 32

func Load() (*Config, error) {
	cfg := &Config{
		Port:           envOr("PORT", "8080"),
		JWTSecret:      os.Getenv("JWT_SECRET"),
		JWTIssuer:      os.Getenv("JWT_ISSUER"),
		CORSOrigins:    splitList(envOr("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://wails.localhost")),
		TrustedProxies: splitList(os.Getenv("TRUSTED_PROXIES")),
	}
	if cfg.JWTSecret == "" || cfg.JWTIssuer == "" {
		return nil, errors.New("JWT_SECRET and JWT_ISSUER are required")
	}
	if len(cfg.JWTSecret) < MinSecretLen {
		return nil, fmt.Errorf("JWT_SECRET must be at least %d characters", MinSecretLen)
	}

	data, err := os.ReadFile(envOr("ROUTES_FILE", "configs/routes.yaml"))
	if err != nil {
		return nil, err
	}
	routes, err := ParseRoutes(data)
	if err != nil {
		return nil, err
	}
	cfg.Routes = routes
	return cfg, nil
}

// ParseRoutes reads the route table, expanding ${VAR} in upstreams.
func ParseRoutes(data []byte) ([]RouteConfig, error) {
	var file struct {
		Routes []RouteConfig `yaml:"routes"`
	}
	if err := yaml.Unmarshal(data, &file); err != nil {
		return nil, err
	}
	for i := range file.Routes {
		r := &file.Routes[i]
		r.Upstream = os.ExpandEnv(r.Upstream)
		if r.Upstream == "" {
			return nil, fmt.Errorf("route %q: upstream is empty", r.Name)
		}
		if !strings.HasPrefix(r.Prefix, "/") || strings.HasSuffix(r.Prefix, "/") {
			return nil, fmt.Errorf("route %q: prefix must start with / and not end with /", r.Name)
		}
		switch r.AuthMode {
		case AuthNone, AuthOptional, AuthRequired:
		case "":
			r.AuthMode = AuthRequired
		default:
			return nil, fmt.Errorf("route %q: unknown auth_mode %q", r.Name, r.AuthMode)
		}
		if r.MaxBody < 0 {
			return nil, fmt.Errorf("route %q: max_body is negative", r.Name)
		}
		if r.Retry.Attempts < 1 {
			r.Retry.Attempts = 1
		}
	}
	return file.Routes, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// splitList turns "a, b,,c" into [a b c]; an empty string gives nil.
func splitList(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if part = strings.TrimSpace(part); part != "" {
			out = append(out, part)
		}
	}
	return out
}
