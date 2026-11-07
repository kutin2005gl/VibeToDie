// Package resilience wraps the upstream transport with a circuit breaker and retries.
package resilience

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/sony/gobreaker/v2"

	"nexus/gateway/internal/config"
)

// NewTransport retries idempotent requests, then sends each attempt through a breaker that
// opens after 5 consecutive transport failures and probes again after 30s.
func NewTransport(base http.RoundTripper, service string, retry config.RetryConfig) http.RoundTripper {
	if base == nil {
		base = http.DefaultTransport
	}
	breaker := gobreaker.NewCircuitBreaker[*http.Response](gobreaker.Settings{
		Name:        service,
		MaxRequests: 5,
		Interval:    time.Minute,
		Timeout:     30 * time.Second,
		ReadyToTrip: func(c gobreaker.Counts) bool { return c.ConsecutiveFailures >= 5 },
		// An oversized client body is the client's fault; it must not open the breaker.
		IsSuccessful: func(err error) bool {
			var tooLarge *http.MaxBytesError
			return err == nil || errors.As(err, &tooLarge)
		},
		OnStateChange: func(name string, from, to gobreaker.State) {
			slog.Warn("circuit breaker", "service", name, "from", from.String(), "to", to.String())
		},
	})
	return &retryTransport{
		base:  &breakerTransport{base: base, breaker: breaker},
		retry: retry,
	}
}

type breakerTransport struct {
	base    http.RoundTripper
	breaker *gobreaker.CircuitBreaker[*http.Response]
}

func (t *breakerTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	return t.breaker.Execute(func() (*http.Response, error) { return t.base.RoundTrip(req) })
}

type retryTransport struct {
	base  http.RoundTripper
	retry config.RetryConfig
}

// RoundTrip retries only GET/HEAD/OPTIONS: a POST that timed out may already have created the
// order, so it is never sent twice.
func (t *retryTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	switch req.Method {
	case http.MethodGet, http.MethodHead, http.MethodOptions:
	default:
		return t.base.RoundTrip(req)
	}
	for attempt := 1; ; attempt++ {
		resp, err := t.base.RoundTrip(req)
		if attempt >= t.retry.Attempts || !shouldRetry(resp, err) {
			return resp, err
		}
		if resp != nil {
			resp.Body.Close()
		}
		delay := t.retry.BaseDelay << (attempt - 1)
		if t.retry.MaxDelay > 0 && delay > t.retry.MaxDelay {
			delay = t.retry.MaxDelay
		}
		select {
		case <-req.Context().Done():
			return nil, req.Context().Err()
		case <-time.After(delay):
		}
	}
}

func shouldRetry(resp *http.Response, err error) bool {
	if err != nil {
		return !errors.Is(err, context.Canceled) &&
			!errors.Is(err, context.DeadlineExceeded) &&
			!errors.Is(err, gobreaker.ErrOpenState) &&
			!errors.Is(err, gobreaker.ErrTooManyRequests)
	}
	switch resp.StatusCode {
	case http.StatusBadGateway, http.StatusServiceUnavailable, http.StatusGatewayTimeout:
		return true
	}
	return false
}
