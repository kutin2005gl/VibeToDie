// Package router builds the Gin engine: global middleware, /healthz and one proxy per route.
package router

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"nexus/gateway/internal/auth"
	"nexus/gateway/internal/config"
	"nexus/gateway/internal/middleware"
	"nexus/gateway/internal/proxy"
	"nexus/gateway/internal/ratelimit"
)

func New(cfg *config.Config, jwtService *auth.JWTService, limits *ratelimit.Manager) (*gin.Engine, error) {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	// Client IP for rate limiting and logs comes from X-Forwarded-For only behind these proxies.
	if err := r.SetTrustedProxies(cfg.TrustedProxies); err != nil {
		return nil, err
	}
	r.Use(middleware.Recovery(), middleware.RequestID(), middleware.Logger(), middleware.CORS(cfg.CORSOrigins))

	r.GET("/healthz", health(cfg.Routes))

	for _, route := range cfg.Routes {
		p, err := proxy.New(route, nil)
		if err != nil {
			return nil, err
		}
		handlers := []gin.HandlerFunc{middleware.JWTAuth(jwtService, route.AuthMode)}
		if route.RateLimit.Requests > 0 && route.RateLimit.Window > 0 {
			handlers = append(handlers, middleware.RateLimit(limits, route.Name, route.RateLimit))
		}
		maxBody := route.MaxBody
		if maxBody == 0 {
			maxBody = config.DefaultMaxBody
		}
		handlers = append(handlers, middleware.BodyLimit(maxBody), gin.WrapH(p))
		// The bare prefix too: "/api/orders" alone doesn't match "/api/orders/*path".
		r.Any(route.Prefix, handlers...)
		r.Any(route.Prefix+"/*path", handlers...)
	}
	return r, nil
}

// health reports the gateway as up and each upstream's own /healthz. It is always 200: an
// upstream being down is something to show, not a reason to restart the gateway.
func health(routes []config.RouteConfig) gin.HandlerFunc {
	client := &http.Client{Timeout: 2 * time.Second}
	return func(c *gin.Context) {
		// Several routes may share one upstream (tasks and backend); probe each once.
		upstreams := map[string]string{}
		var unique []string
		for _, r := range routes {
			if _, ok := upstreams[r.Upstream]; !ok {
				upstreams[r.Upstream] = ""
				unique = append(unique, r.Upstream)
			}
		}
		var mu sync.Mutex
		var wg sync.WaitGroup
		for _, u := range unique {
			wg.Go(func() {
				status := probe(c.Request.Context(), client, u)
				mu.Lock()
				upstreams[u] = status
				mu.Unlock()
			})
		}
		wg.Wait()

		result := make(map[string]string, len(routes))
		overall := "ok"
		for _, r := range routes {
			result[r.Name] = upstreams[r.Upstream]
			if upstreams[r.Upstream] != "ok" {
				overall = "degraded"
			}
		}
		c.JSON(http.StatusOK, gin.H{"status": overall, "upstreams": result})
	}
}

func probe(ctx context.Context, client *http.Client, upstream string) string {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, upstream+"/healthz", nil)
	if err != nil {
		return "down"
	}
	resp, err := client.Do(req)
	if err != nil {
		return "down"
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "down"
	}
	return "ok"
}
