// Package middleware holds the Gin middleware the gateway runs before proxying.
package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"nexus/gateway/internal/auth"
	"nexus/gateway/internal/config"
	"nexus/gateway/internal/constants"
)

// JWTAuth authenticates a Bearer token according to the route's mode:
//   - none: never looks at the token.
//   - optional: a valid token sets the identity; a missing or bad one passes as anonymous.
//   - required: no valid token, 401.
//
// In every mode client-supplied identity headers are deleted first, so a caller can't claim to
// be someone else by setting X-User-Id itself.
func JWTAuth(jwtService *auth.JWTService, mode config.AuthMode) gin.HandlerFunc {
	return func(c *gin.Context) {
		for _, h := range constants.IdentityHeaders {
			c.Request.Header.Del(h)
		}
		if mode == config.AuthNone {
			c.Next()
			return
		}

		token, ok := strings.CutPrefix(c.GetHeader("Authorization"), "Bearer ")
		if !ok || token == "" {
			if mode == config.AuthOptional {
				c.Next()
				return
			}
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing bearer token"})
			return
		}

		claims, err := jwtService.Verify(token)
		if err != nil {
			if mode == config.AuthOptional {
				c.Next()
				return
			}
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid access token"})
			return
		}

		c.Set(constants.ContextClaims, claims)
		c.Request.Header.Set(constants.HeaderUserID, claims.Subject)
		if claims.Email != "" {
			c.Request.Header.Set(constants.HeaderUserEmail, claims.Email)
		}
		if len(claims.Departments) > 0 {
			c.Request.Header.Set(constants.HeaderUserDepartments, strings.Join(claims.Departments, ","))
		}
		c.Next()
	}
}
