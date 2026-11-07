package config

import (
	"os"
	"strings"
	"testing"
)

func TestShippedRoutesParse(t *testing.T) {
	for _, k := range []string{"USER_SERVICE", "ORDERS_SERVICE", "AI_SERVICE", "TASKS_SERVICE"} {
		t.Setenv(k, "http://"+strings.ToLower(k)+":8080")
	}
	data, err := os.ReadFile("../../configs/routes.yaml")
	if err != nil {
		t.Fatal(err)
	}
	routes, err := ParseRoutes(data)
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]RouteConfig{}
	for _, r := range routes {
		byName[r.Name] = r
	}
	if ai := byName["ai"]; ai.Upstream != "http://ai_service:8080" || ai.AuthMode != AuthRequired || ai.Retry.Attempts != 1 {
		t.Fatalf("ai route %+v", ai)
	}
	if !byName["tasks"].KeepPrefix || byName["tasks"].AuthMode != AuthRequired || byName["user"].AuthMode != AuthOptional {
		t.Fatalf("routes %+v", byName)
	}
	if !byName["orders"].KeepPrefix || !byName["products"].KeepPrefix {
		t.Fatalf("orders/products route keep_prefix %+v", byName)
	}
}

func TestParseRoutesRejectsBadConfig(t *testing.T) {
	t.Setenv("UP", "http://up")
	for name, extra := range map[string]string{
		"unset upstream": "prefix: /a\n    upstream: ${NOT_SET}",
		"trailing slash": "prefix: /a/\n    upstream: ${UP}",
		"no leading /":   "prefix: a\n    upstream: ${UP}",
		"unknown auth":   "prefix: /a\n    upstream: ${UP}\n    auth_mode: maybe",
		"negative body":  "prefix: /a\n    upstream: ${UP}\n    max_body: -1",
	} {
		t.Run(name, func(t *testing.T) {
			_, err := ParseRoutes([]byte("routes:\n  - name: a\n    " + extra + "\n"))
			if err == nil || !strings.HasPrefix(err.Error(), `route "a"`) {
				t.Fatalf("want a route error, got %v", err)
			}
		})
	}
}

func TestAuthDefaultsToRequired(t *testing.T) {
	t.Setenv("UP", "http://up")
	routes, err := ParseRoutes([]byte("routes:\n  - name: a\n    prefix: /a\n    upstream: ${UP}\n"))
	if err != nil || routes[0].AuthMode != AuthRequired || routes[0].Retry.Attempts != 1 {
		t.Fatalf("routes %+v, err %v", routes, err)
	}
}

func TestLoadRejectsShortSecret(t *testing.T) {
	t.Setenv("JWT_SECRET", strings.Repeat("s", MinSecretLen-1))
	t.Setenv("JWT_ISSUER", "nexus")
	if _, err := Load(); err == nil || !strings.Contains(err.Error(), "at least") {
		t.Fatalf("want a secret length error, got %v", err)
	}
}
