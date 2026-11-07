package middleware

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"nexus/gateway/internal/auth"
	"nexus/gateway/internal/config"
	"nexus/gateway/internal/constants"
	"nexus/gateway/internal/ratelimit"
)

// RateLimit gives each route its own token bucket per user (when JWTAuth found one) or per IP,
// so it must run after JWTAuth.
func RateLimit(manager *ratelimit.Manager, route string, cfg config.RateLimit) gin.HandlerFunc {
	limit := rate.Limit(float64(cfg.Requests) / cfg.Window.Seconds())
	burst := max(cfg.Burst, 1)
	return func(c *gin.Context) {
		if !manager.Get(key(c, route), limit, burst).Allow() {
			c.Header("Retry-After", strconv.Itoa(int(max(1, 1/float64(limit)))))
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "rate limit exceeded"})
			return
		}
		c.Next()
	}
}

func key(c *gin.Context, route string) string {
	if v, ok := c.Get(constants.ContextClaims); ok {
		if claims, ok := v.(*auth.Claims); ok {
			return route + ":user:" + claims.Subject
		}
	}
	return route + ":ip:" + c.ClientIP()
}
