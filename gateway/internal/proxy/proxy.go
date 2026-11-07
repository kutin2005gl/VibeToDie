// Package proxy forwards a route's requests to its upstream service.
package proxy

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/sony/gobreaker/v2"

	"nexus/gateway/internal/config"
	"nexus/gateway/internal/constants"
	"nexus/gateway/internal/resilience"
)

type Proxy struct {
	proxy         *httputil.ReverseProxy
	timeout       time.Duration
	streamTimeout time.Duration
}

// New builds the proxy for one route. transport is nil in production (http.DefaultTransport
// behind the breaker and retries); tests pass their own.
func New(route config.RouteConfig, transport http.RoundTripper) (*Proxy, error) {
	target, err := url.Parse(route.Upstream)
	if err != nil || target.Scheme == "" || target.Host == "" {
		return nil, errors.New("route " + route.Name + ": bad upstream " + route.Upstream)
	}

	rp := &httputil.ReverseProxy{
		Transport: resilience.NewTransport(transport, route.Name, route.Retry),
		Rewrite: func(pr *httputil.ProxyRequest) {
			if !route.KeepPrefix {
				pr.Out.URL.Path = strings.TrimPrefix(pr.In.URL.Path, route.Prefix)
				pr.Out.URL.RawPath = ""
				if pr.Out.URL.Path == "" {
					pr.Out.URL.Path = "/"
				}
			}
			pr.SetURL(target)
			pr.SetXForwarded()

			// Services trust the gateway's identity headers, not the token: drop a Bearer token.
			// Other schemes (a payment webhook's API key) are the service's to check.
			if strings.HasPrefix(pr.In.Header.Get("Authorization"), "Bearer ") {
				pr.Out.Header.Del("Authorization")
			}
			// JWTAuth deleted the identity headers before setting its own; copy only those that
			// have a value, so "anonymous" reaches the service as absent, not as an empty header.
			for _, h := range constants.IdentityHeaders {
				if v := pr.In.Header.Get(h); v != "" {
					pr.Out.Header.Set(h, v)
				} else {
					pr.Out.Header.Del(h)
				}
			}
		},
		// The gateway answers CORS itself; an upstream's own headers would be sent twice.
		ModifyResponse: func(resp *http.Response) error {
			for k := range resp.Header {
				if strings.HasPrefix(k, "Access-Control-") {
					resp.Header.Del(k)
				}
			}
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			status := http.StatusBadGateway
			var tooLarge *http.MaxBytesError
			switch {
			case errors.As(err, &tooLarge):
				status = http.StatusRequestEntityTooLarge
			case errors.Is(err, context.DeadlineExceeded):
				status = http.StatusGatewayTimeout
			case errors.Is(err, gobreaker.ErrOpenState), errors.Is(err, gobreaker.ErrTooManyRequests):
				status = http.StatusServiceUnavailable
			case errors.Is(err, context.Canceled):
				// Client went away; nobody reads the answer.
				return
			}
			slog.Error("proxy error", "route", route.Name, "status", status, "error", err,
				"request_id", r.Header.Get(constants.HeaderRequestID))
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"error":"` + http.StatusText(status) + `"}`))
		},
	}
	if route.StreamTimeout > 0 {
		// Flush each event as it arrives, even if the upstream forgets the SSE content type.
		rp.FlushInterval = -1
	}
	return &Proxy{proxy: rp, timeout: route.Timeout, streamTimeout: route.StreamTimeout}, nil
}

// ServeHTTP bounds the request by the route's timeout, or its stream timeout for an SSE
// request. The server sets no WriteTimeout, so this is the only limit.
//
// If the upstream drops mid-stream, ReverseProxy panics with http.ErrAbortHandler so net/http
// cuts the connection and the client sees a broken stream rather than a clean end; the
// router's Recovery lets that panic through.
func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	timeout := p.timeout
	if p.streamTimeout > 0 && strings.Contains(r.Header.Get("Accept"), "text/event-stream") {
		timeout = p.streamTimeout
	}
	if timeout > 0 {
		ctx, cancel := context.WithTimeout(r.Context(), timeout)
		defer cancel()
		r = r.WithContext(ctx)
	}
	p.proxy.ServeHTTP(w, r)
}
