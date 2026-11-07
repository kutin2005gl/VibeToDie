package middleware

import (
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"nexus/gateway/internal/constants"
)

// RequestID keeps the caller's X-Request-Id or makes one, and echoes it in the response.
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		id := c.GetHeader(constants.HeaderRequestID)
		if id == "" || len(id) > 128 {
			b := make([]byte, 16)
			_, _ = rand.Read(b)
			id = hex.EncodeToString(b)
		}
		c.Set(constants.ContextRequestID, id)
		c.Request.Header.Set(constants.HeaderRequestID, id)
		c.Writer.Header().Set(constants.HeaderRequestID, id)
		c.Next()
	}
}

// Recovery turns a panic into a 500, except http.ErrAbortHandler: the proxy raises it when an
// upstream drops mid-response, and net/http must see it to cut the connection. gin.Recovery
// would swallow it and end a broken SSE stream as if it had finished.
func Recovery() gin.HandlerFunc {
	return func(c *gin.Context) {
		defer func() {
			err := recover()
			if err == nil {
				return
			}
			if err == http.ErrAbortHandler {
				panic(err)
			}
			slog.Error("panic", "error", err, "stack", string(debug.Stack()),
				"request_id", c.GetString(constants.ContextRequestID))
			if !c.Writer.Written() {
				c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "internal error"})
			} else {
				c.Abort()
			}
		}()
		c.Next()
	}
}

// Logger writes one line per request, aborted streams included.
func Logger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		defer func() {
			slog.Info("request",
				"method", c.Request.Method,
				"path", c.Request.URL.Path,
				"status", c.Writer.Status(),
				"duration_ms", time.Since(start).Milliseconds(),
				"client_ip", c.ClientIP(),
				"request_id", c.GetString(constants.ContextRequestID),
			)
		}()
		c.Next()
	}
}

// BodyLimit answers 413 when Content-Length is over max. A chunked body has no length up front,
// so it is cut at max and the proxy turns the read error into 413.
func BodyLimit(max int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.ContentLength > max {
			c.AbortWithStatusJSON(http.StatusRequestEntityTooLarge, gin.H{"error": "request body too large"})
			return
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, max)
		c.Next()
	}
}

// CORS answers preflights here, so a browser never needs a token for OPTIONS.
func CORS(origins []string) gin.HandlerFunc {
	allowed := make(map[string]bool, len(origins))
	for _, o := range origins {
		allowed[strings.TrimSpace(o)] = true
	}
	return func(c *gin.Context) {
		if origin := c.GetHeader("Origin"); allowed[origin] {
			h := c.Writer.Header()
			h.Set("Access-Control-Allow-Origin", origin)
			h.Add("Vary", "Origin")
			h.Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
			h.Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-Id, Idempotency-Key")
			h.Set("Access-Control-Expose-Headers", constants.HeaderRequestID)
			h.Set("Access-Control-Max-Age", "3600")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
