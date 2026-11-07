package router

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"nexus/gateway/internal/auth"
	"nexus/gateway/internal/config"
	"nexus/gateway/internal/ratelimit"
)

const secret, issuer = "test-secret", "nexus"

// seen is what an upstream received, as JSON it echoes back.
type seen struct {
	Path          string `json:"path"`
	UserID        string `json:"user_id"`
	Departments   string `json:"departments"`
	Authorization string `json:"authorization"`
	RequestID     string `json:"request_id"`
	HasUserHeader bool   `json:"has_user_header"`
}

func echoUpstream(t *testing.T) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, has := r.Header["X-User-Id"]
		w.Header().Set("Access-Control-Allow-Origin", "*")
		_ = json.NewEncoder(w).Encode(seen{
			Path:          r.URL.Path,
			UserID:        r.Header.Get("X-User-Id"),
			Departments:   r.Header.Get("X-User-Departments"),
			Authorization: r.Header.Get("Authorization"),
			RequestID:     r.Header.Get("X-Request-Id"),
			HasUserHeader: has,
		})
	}))
	t.Cleanup(srv.Close)
	return srv
}

func newGateway(t *testing.T, routes ...config.RouteConfig) http.Handler {
	t.Helper()
	cfg := &config.Config{JWTSecret: secret, JWTIssuer: issuer, CORSOrigins: []string{"http://localhost:5173"}, Routes: routes}
	h, err := New(cfg, auth.NewJWTService(secret, issuer), ratelimit.NewManager())
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func route(name, prefix, upstream string, mode config.AuthMode) config.RouteConfig {
	return config.RouteConfig{Name: name, Prefix: prefix, Upstream: upstream, AuthMode: mode, Timeout: 2 * time.Second, Retry: config.RetryConfig{Attempts: 1}}
}

func token(t *testing.T, departments ...string) string {
	t.Helper()
	tok, err := auth.NewJWTService(secret, issuer).Sign("u1", "u1@example.com", departments, time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	return tok
}

func do(h http.Handler, method, path string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, strings.NewReader(""))
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) seen {
	t.Helper()
	var s seen
	if err := json.Unmarshal(rec.Body.Bytes(), &s); err != nil {
		t.Fatalf("body %q: %v", rec.Body.String(), err)
	}
	return s
}

func TestRequiredRouteForwardsVerifiedIdentity(t *testing.T) {
	h := newGateway(t, route("ai", "/api/ai", echoUpstream(t).URL, config.AuthRequired))

	rec := do(h, http.MethodPost, "/api/ai/run", map[string]string{
		"Authorization": "Bearer " + token(t, "cskh"),
		// Forged by the client: must be replaced by what the token says
		"X-User-Id":          "admin",
		"X-User-Departments": "executive",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	got := decode(t, rec)
	if got.Path != "/run" || got.UserID != "u1" || got.Departments != "cskh" {
		t.Fatalf("upstream saw %+v", got)
	}
	if got.Authorization != "" {
		t.Fatalf("bearer token reached the upstream: %q", got.Authorization)
	}
	if got.RequestID == "" || rec.Header().Get("X-Request-Id") != got.RequestID {
		t.Fatalf("request id not propagated: upstream %q, response %q", got.RequestID, rec.Header().Get("X-Request-Id"))
	}
}

func TestRequiredRouteRejectsMissingBadAndExpiredTokens(t *testing.T) {
	h := newGateway(t, route("orders", "/api/orders", echoUpstream(t).URL, config.AuthRequired))
	expired, _ := auth.NewJWTService(secret, issuer).Sign("u1", "", nil, -time.Minute)
	otherIssuer, _ := auth.NewJWTService(secret, "someone-else").Sign("u1", "", nil, time.Minute)
	otherSecret, _ := auth.NewJWTService("wrong", issuer).Sign("u1", "", nil, time.Minute)

	for name, header := range map[string]string{
		"missing":      "",
		"not bearer":   "Basic abc",
		"garbage":      "Bearer abc.def.ghi",
		"expired":      "Bearer " + expired,
		"other issuer": "Bearer " + otherIssuer,
		"other secret": "Bearer " + otherSecret,
	} {
		t.Run(name, func(t *testing.T) {
			rec := do(h, http.MethodGet, "/api/orders/DH1001", map[string]string{"Authorization": header})
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("status %d, want 401", rec.Code)
			}
		})
	}
}

func TestOptionalRouteStripsForgedIdentityForAnonymous(t *testing.T) {
	h := newGateway(t, route("user", "/api/users", echoUpstream(t).URL, config.AuthOptional))

	rec := do(h, http.MethodPost, "/api/users/login", map[string]string{"X-User-Id": "admin", "Authorization": "Bearer bad"})
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d", rec.Code)
	}
	if got := decode(t, rec); got.HasUserHeader || got.Path != "/login" {
		t.Fatalf("upstream saw %+v", got)
	}
}

func TestNoneRouteStillStripsForgedIdentity(t *testing.T) {
	h := newGateway(t, route("public", "/api/public", echoUpstream(t).URL, config.AuthNone))

	rec := do(h, http.MethodGet, "/api/public", map[string]string{"X-User-Id": "admin"})
	if got := decode(t, rec); got.HasUserHeader || got.Path != "/" {
		t.Fatalf("upstream saw %+v", got)
	}
}

func TestKeepPrefix(t *testing.T) {
	r := route("tasks", "/api/tasks", echoUpstream(t).URL, config.AuthOptional)
	r.KeepPrefix = true
	h := newGateway(t, r)

	if got := decode(t, do(h, http.MethodGet, "/api/tasks/7", nil)); got.Path != "/api/tasks/7" {
		t.Fatalf("upstream path %q", got.Path)
	}
}

func TestUpstreamDownIs502AndSlowIs504(t *testing.T) {
	dead := httptest.NewServer(http.NotFoundHandler())
	dead.Close()
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	t.Cleanup(slow.Close)
	slowRoute := route("slow", "/api/slow", slow.URL, config.AuthNone)
	slowRoute.Timeout = 50 * time.Millisecond
	h := newGateway(t, route("dead", "/api/dead", dead.URL, config.AuthNone), slowRoute)

	if rec := do(h, http.MethodGet, "/api/dead/x", nil); rec.Code != http.StatusBadGateway {
		t.Fatalf("dead upstream: status %d, want 502", rec.Code)
	}
	if rec := do(h, http.MethodGet, "/api/slow/x", nil); rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("slow upstream: status %d, want 504", rec.Code)
	}
}

func TestRetriesGetButNeverPost(t *testing.T) {
	calls := map[string]int{}
	flaky := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls[r.Method]++
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(flaky.Close)
	r := route("orders", "/api/orders", flaky.URL, config.AuthNone)
	r.Retry = config.RetryConfig{Attempts: 3, BaseDelay: time.Millisecond}
	h := newGateway(t, r)

	do(h, http.MethodGet, "/api/orders/1", nil)
	do(h, http.MethodPost, "/api/orders", nil)
	if calls[http.MethodGet] != 3 || calls[http.MethodPost] != 1 {
		t.Fatalf("calls %v, want GET 3 and POST 1", calls)
	}
}

func TestRateLimitPerUser(t *testing.T) {
	r := route("ai", "/api/ai", echoUpstream(t).URL, config.AuthRequired)
	r.RateLimit = config.RateLimit{Requests: 1, Window: time.Minute, Burst: 2}
	h := newGateway(t, r)
	auth := map[string]string{"Authorization": "Bearer " + token(t, "cskh")}

	for i := range 2 {
		if rec := do(h, http.MethodPost, "/api/ai/run", auth); rec.Code != http.StatusOK {
			t.Fatalf("request %d: status %d", i, rec.Code)
		}
	}
	if rec := do(h, http.MethodPost, "/api/ai/run", auth); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("status %d, want 429", rec.Code)
	}
}

func TestCORSPreflightNeedsNoTokenAndUpstreamHeadersAreDropped(t *testing.T) {
	h := newGateway(t, route("ai", "/api/ai", echoUpstream(t).URL, config.AuthRequired))

	rec := do(h, http.MethodOptions, "/api/ai/run", map[string]string{"Origin": "http://localhost:5173"})
	if rec.Code != http.StatusNoContent || rec.Header().Get("Access-Control-Allow-Origin") != "http://localhost:5173" {
		t.Fatalf("preflight: status %d, headers %v", rec.Code, rec.Header())
	}

	rec = do(h, http.MethodPost, "/api/ai/run", map[string]string{"Origin": "http://localhost:5173", "Authorization": "Bearer " + token(t)})
	if got := rec.Header().Values("Access-Control-Allow-Origin"); len(got) != 1 || got[0] != "http://localhost:5173" {
		t.Fatalf("Access-Control-Allow-Origin %v", got)
	}
}

func TestHealthReportsEachUpstream(t *testing.T) {
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	t.Cleanup(up.Close)
	h := newGateway(t,
		route("ai", "/api/ai", up.URL, config.AuthRequired),
		route("orders", "/api/orders", "http://127.0.0.1:1", config.AuthRequired),
	)

	rec := do(h, http.MethodGet, "/healthz", nil)
	var body struct {
		Status    string            `json:"status"`
		Upstreams map[string]string `json:"upstreams"`
	}
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	if rec.Code != http.StatusOK || body.Status != "degraded" || body.Upstreams["ai"] != "ok" || body.Upstreams["orders"] != "down" {
		t.Fatalf("status %d, body %s", rec.Code, rec.Body)
	}
}

func TestBodyOverLimitIs413(t *testing.T) {
	var calls int
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_, _ = io.Copy(io.Discard, r.Body)
	}))
	t.Cleanup(up.Close)
	r := route("ai", "/api/ai", up.URL, config.AuthNone)
	r.MaxBody = 10
	h := newGateway(t, r)

	post := func(body string, chunked bool) int {
		req := httptest.NewRequest(http.MethodPost, "/api/ai/run", strings.NewReader(body))
		if chunked {
			req.ContentLength = -1
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec.Code
	}
	if code := post("small", false); code != http.StatusOK {
		t.Fatalf("small body: status %d", code)
	}
	if code := post(strings.Repeat("x", 11), false); code != http.StatusRequestEntityTooLarge || calls != 1 {
		t.Fatalf("declared length: status %d, upstream calls %d", code, calls)
	}
	if code := post(strings.Repeat("x", 1000), true); code != http.StatusRequestEntityTooLarge {
		t.Fatalf("chunked body: status %d, want 413", code)
	}
}

// The Slack redeem route has its own prefix beside /api/users (the router can't nest a static
// path under that wildcard); its upstream carries the path the prefix strip drops.
func TestSlackRedeemRoutePath(t *testing.T) {
	up := echoUpstream(t)
	h := newGateway(t,
		route("user", "/api/users", up.URL, config.AuthOptional),
		route("slack-redeem", "/api/slack-links/redeem", up.URL+"/slack-links/redeem", config.AuthNone))

	for path, want := range map[string]string{
		"/api/slack-links/redeem": "/slack-links/redeem/",
		"/api/users/slack-links":  "/slack-links",
	} {
		rec := do(h, http.MethodPost, path, map[string]string{"X-User-Id": "forged"})
		if rec.Code != http.StatusOK {
			t.Fatalf("%s: status %d", path, rec.Code)
		}
		if got := decode(t, rec); got.Path != want || got.HasUserHeader {
			t.Fatalf("%s: upstream saw %+v, want path %q", path, got, want)
		}
	}
}
