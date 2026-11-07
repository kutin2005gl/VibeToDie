package nexus

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"nexus/slack/internal/secret"
	"nexus/slack/internal/store"
)

// gateway is a fake of the gateway routes the client uses. Its refresh endpoint behaves like
// user-service: tokens rotate, and presenting a spent one revokes the user's whole session.
type gateway struct {
	mu           sync.Mutex
	n            int
	access       map[string]string // live access token -> user id
	refresh      map[string]string // live refresh token -> user id
	refreshCalls int
	reused       bool              // a spent refresh token was presented
	refuseAll    bool              // refresh answers 401 whatever it is given
	sessionHits  map[string]string // session path -> user id of the last caller
	bodies       map[string]string // request path -> last body
	logouts      []string
	sessions     func(r *http.Request, id int64, user string) (int, string)
	events       func(w http.ResponseWriter, r *http.Request, user string)
}

func newGateway() *gateway {
	return &gateway{access: map[string]string{}, refresh: map[string]string{}, sessionHits: map[string]string{}, bodies: map[string]string{}}
}

func (g *gateway) issue(uid string) string {
	g.n++
	at, rt := fmt.Sprintf("at-%s-%d", uid, g.n), fmt.Sprintf("rt-%s-%d", uid, g.n)
	g.access[at], g.refresh[rt] = uid, uid
	b, _ := json.Marshal(map[string]any{"access_token": at, "refresh_token": rt, "expires_in": 900, "user": map[string]any{"id": uid, "email": uid + "@x", "departments": []string{"cskh"}}})
	return string(b)
}

func (g *gateway) user(r *http.Request) (string, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	uid, ok := g.access[strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")]
	return uid, ok
}

func readBody(r *http.Request) string {
	b, _ := io.ReadAll(r.Body)
	return string(b)
}

func (g *gateway) handler() http.Handler {
	mux := http.NewServeMux()
	jsonOut := func(w http.ResponseWriter, status int, body string) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		io.WriteString(w, body)
	}

	mux.HandleFunc("POST /api/slack-links/redeem", func(w http.ResponseWriter, r *http.Request) {
		body := readBody(r)
		var in struct{ Code string }
		json.Unmarshal([]byte(body), &in)
		g.mu.Lock()
		g.bodies[r.URL.Path] = body
		g.mu.Unlock()
		uid, ok := strings.CutPrefix(in.Code, "good-")
		if !ok {
			jsonOut(w, 401, `{"error":"invalid or expired code"}`)
			return
		}
		g.mu.Lock()
		defer g.mu.Unlock()
		jsonOut(w, 200, g.issue(uid))
	})
	mux.HandleFunc("POST /api/users/refresh", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			RefreshToken string `json:"refresh_token"`
		}
		json.Unmarshal([]byte(readBody(r)), &in)
		g.mu.Lock()
		defer g.mu.Unlock()
		g.refreshCalls++
		uid, ok := g.refresh[in.RefreshToken]
		if g.refuseAll || !ok {
			if !ok {
				g.reused = true
				// A spent token revokes the whole session.
				clear(g.refresh)
				clear(g.access)
			}
			jsonOut(w, 401, `{"error":"invalid refresh token"}`)
			return
		}
		delete(g.refresh, in.RefreshToken)
		jsonOut(w, 200, g.issue(uid))
	})
	mux.HandleFunc("POST /api/users/logout", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			RefreshToken string `json:"refresh_token"`
		}
		json.Unmarshal([]byte(readBody(r)), &in)
		g.mu.Lock()
		g.logouts = append(g.logouts, in.RefreshToken)
		delete(g.refresh, in.RefreshToken)
		g.mu.Unlock()
		w.WriteHeader(204)
	})

	// Everything under /api/sessions needs a live access token, like the real gateway.
	mux.HandleFunc("/api/sessions", func(w http.ResponseWriter, r *http.Request) { g.serveSession(w, r, jsonOut) })
	mux.HandleFunc("/api/sessions/{id}", func(w http.ResponseWriter, r *http.Request) { g.serveSession(w, r, jsonOut) })
	mux.HandleFunc("/api/sessions/{id}/{tail}", func(w http.ResponseWriter, r *http.Request) { g.serveSession(w, r, jsonOut) })
	return mux
}

func (g *gateway) serveSession(w http.ResponseWriter, r *http.Request, jsonOut func(http.ResponseWriter, int, string)) {
	uid, ok := g.user(r)
	if !ok {
		jsonOut(w, 401, `{"error":"unauthorized"}`)
		return
	}
	body := readBody(r)
	g.mu.Lock()
	g.sessionHits[r.URL.Path] = uid
	g.bodies[r.URL.Path] = body
	g.mu.Unlock()

	if strings.HasSuffix(r.URL.Path, "/events") && g.events != nil {
		g.events(w, r, uid)
		return
	}
	id, _ := strconv.ParseInt(r.PathValue("id"), 10, 64)
	status, out := 200, ""
	if g.sessions != nil {
		status, out = g.sessions(r, id, uid)
	} else {
		out = fmt.Sprintf(`{"id":%d,"title":%q,"status":"done","items":[]}`, id, uid)
	}
	jsonOut(w, status, out)
}

type env struct {
	g      *gateway
	client *Client
	st     *store.Memory
	box    *secret.Box
}

func newEnv(t *testing.T, g *gateway) *env {
	t.Helper()
	srv := httptest.NewServer(g.handler())
	t.Cleanup(srv.Close)
	box, err := secret.New(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	st := store.NewMemory()
	c := New(Config{BaseURL: srv.URL, Store: st, Box: box, PollEvery: 5 * time.Millisecond, MaxWait: 2 * time.Second})
	return &env{g: g, client: c, st: st, box: box}
}

func (e *env) link(t *testing.T, slackID, uid string) *UserClient {
	t.Helper()
	if _, err := e.client.Redeem(context.Background(), SlackAccount{UserID: slackID}, "good-"+uid); err != nil {
		t.Fatal(err)
	}
	u, err := e.client.For(context.Background(), slackID)
	if err != nil {
		t.Fatal(err)
	}
	return u
}

// storedRefresh is the refresh token currently kept for a Slack user, decrypted.
func (e *env) storedRefresh(t *testing.T, slackID string) string {
	t.Helper()
	a, err := e.st.Account(context.Background(), slackID)
	if err != nil {
		t.Fatal(err)
	}
	plain, err := e.box.Open(a.RefreshTokenEnc)
	if err != nil {
		t.Fatal(err)
	}
	return string(plain)
}

func TestRedeemSealsTokenAndRejectsBadCode(t *testing.T) {
	e := newEnv(t, newGateway())
	ctx := context.Background()

	if _, err := e.client.Redeem(ctx, SlackAccount{UserID: "U1"}, "nonsense"); !errors.Is(err, ErrInvalidCode) {
		t.Fatalf("bad code: want ErrInvalidCode, got %v", err)
	}
	if _, err := e.client.For(ctx, "U1"); !errors.Is(err, ErrNotLinked) {
		t.Fatalf("bad code must not link: %v", err)
	}

	user, err := e.client.Redeem(ctx, SlackAccount{UserID: "U1"}, "good-alice")
	if err != nil || user.ID != "alice" {
		t.Fatalf("redeem: %+v %v", user, err)
	}
	a, _ := e.st.Account(ctx, "U1")
	if a.UserID != "alice" || strings.Contains(string(a.RefreshTokenEnc), "rt-alice") {
		t.Fatalf("account must be linked with a sealed token: %+v", a)
	}
}

func TestTwoUsersKeepTheirOwnIdentity(t *testing.T) {
	e := newEnv(t, newGateway())
	ctx := context.Background()
	alice, bob := e.link(t, "UA", "alice"), e.link(t, "UB", "bob")

	for i := 0; i < 3; i++ { // alternate, so a shared token would show up
		a, err := alice.Get(ctx, 1)
		if err != nil || a.Title != "alice" {
			t.Fatalf("alice saw %+v %v", a, err)
		}
		b, err := bob.Get(ctx, 2)
		if err != nil || b.Title != "bob" {
			t.Fatalf("bob saw %+v %v", b, err)
		}
	}
	if e.g.sessionHits["/api/sessions/1"] != "alice" || e.g.sessionHits["/api/sessions/2"] != "bob" {
		t.Fatalf("gateway saw %v", e.g.sessionHits)
	}
}

func TestConcurrentCallsRefreshOnce(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice") // no access token cached yet: the first calls must refresh

	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := u.Get(context.Background(), 1)
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if g.refreshCalls != 1 {
		t.Fatalf("want 1 refresh, got %d", g.refreshCalls)
	}
	if g.reused {
		t.Fatal("a spent refresh token was reused")
	}
	// The stored token is the live one, so the next process start can refresh again.
	if _, live := g.refresh[e.storedRefresh(t, "UA")]; !live {
		t.Fatal("store does not hold the newest refresh token")
	}
}

func TestRotatedTokenIsStoredBeforeUse(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	// At the moment the gateway sees the access token, the store must already hold its refresh token.
	g.sessions = func(r *http.Request, id int64, user string) (int, string) {
		stored := e.storedRefresh(t, "UA")
		g.mu.Lock()
		_, live := g.refresh[stored]
		g.mu.Unlock()
		if !live {
			t.Error("access token used before its refresh token was stored")
		}
		return 200, `{"id":1,"status":"done"}`
	}
	if _, err := u.Get(context.Background(), 1); err != nil {
		t.Fatal(err)
	}
}

func TestRefreshRejectedRemovesLink(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	g.refuseAll = true

	_, err := u.Get(context.Background(), 1)
	if !errors.Is(err, ErrNotLinked) || !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("want ErrNotLinked and ErrUnauthorized, got %v", err)
	}
	if _, err := e.st.Account(context.Background(), "UA"); !errors.Is(err, store.ErrNotFound) {
		t.Fatalf("link must be removed, got %v", err)
	}
	if _, err := e.client.For(context.Background(), "UA"); !errors.Is(err, ErrNotLinked) {
		t.Fatalf("For after unlink: %v", err)
	}
}

func TestExpiredAccessTokenIsRefreshedAndCallRetried(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	if _, err := u.Get(context.Background(), 1); err != nil {
		t.Fatal(err)
	}

	g.mu.Lock()
	clear(g.access) // the gateway stops accepting the cached token (for example the session was revoked and reissued)
	g.mu.Unlock()
	if _, err := u.Get(context.Background(), 1); err != nil {
		t.Fatalf("a refused access token with a live refresh token should refresh and retry: %v", err)
	}
	if g.refreshCalls != 2 || g.reused {
		t.Fatalf("refresh calls %d, reused %v", g.refreshCalls, g.reused)
	}
}

func TestErrorsAreTyped(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	ctx := context.Background()
	g.sessions = func(r *http.Request, id int64, user string) (int, string) {
		switch id {
		case 404:
			return 404, `{"detail":"session not found"}`
		case 409:
			return 409, `{"detail":"session is still running"}`
		case 410:
			return 409, `{"detail":"room is full: start a new room"}`
		case 202:
			return 202, ``
		}
		return 200, fmt.Sprintf(`{"id":%d,"status":"waiting"}`, id)
	}

	if _, err := u.Get(ctx, 404); !errors.Is(err, ErrNotFound) {
		t.Fatalf("404: %v", err)
	}
	_, err := u.FollowUp(ctx, 409, "x")
	if !errors.Is(err, ErrConflict) || IsRoomFull(err) {
		t.Fatalf("409: %v", err)
	}
	_, err = u.FollowUp(ctx, 410, "x")
	if !errors.Is(err, ErrConflict) || !IsRoomFull(err) {
		t.Fatalf("room is full: %v", err)
	}
	if err := u.Stop(ctx, 202); err != nil {
		t.Fatalf("stop: %v", err)
	}
	if err := u.Stop(ctx, 409); !errors.Is(err, ErrConflict) {
		t.Fatalf("stop conflict: %v", err)
	}
}

func TestRequestBodies(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	ctx := context.Background()

	u.CreateSession(ctx, "hello", "anthropic", nil)
	u.CreateSession(ctx, "from slack", "", &Origin{Kind: "slack", Channel: "D1", ThreadTS: "1.2"})
	u.Answer(ctx, 7, "the blue one")
	u.FollowUp(ctx, 7, "and more")
	u.Decision(ctx, 7, true)
	for path, want := range map[string]string{
		"/api/sessions":            `{"origin":{"kind":"slack","channel":"D1","thread_ts":"1.2"},"text":"from slack"}`,
		"/api/sessions/7/answer":   `{"answer":"the blue one"}`,
		"/api/sessions/7/messages": `{"text":"and more"}`,
		"/api/sessions/7/decision": `{"approve":true}`,
	} {
		if got := g.bodies[path]; got != want {
			t.Errorf("%s: sent %s, want %s", path, got, want)
		}
	}
}

func TestLogoutRevokesAndUnlinks(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	rt := e.storedRefresh(t, "UA")

	if err := u.Logout(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(g.logouts) != 1 || g.logouts[0] != rt {
		t.Fatalf("gateway logout calls: %v", g.logouts)
	}
	if _, err := e.client.For(context.Background(), "UA"); !errors.Is(err, ErrNotLinked) {
		t.Fatalf("still linked: %v", err)
	}
}

func sse(w http.ResponseWriter, lines ...string) {
	w.Header().Set("Content-Type", "text/event-stream")
	for _, l := range lines {
		io.WriteString(w, l+"\n")
	}
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}
}

func TestWaitReadsStreamUntilSessionEvent(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	g.events = func(w http.ResponseWriter, r *http.Request, user string) {
		if r.Header.Get("Accept") != "text/event-stream" {
			t.Errorf("Accept = %q", r.Header.Get("Accept"))
		}
		sse(w,
			": ping", "",
			"event: route", `data: {"agent":"order"}`, "",
			": ping", "",
			"event: step_started", `data: {"id":"s1"}`, "",
			"event: session", `data: {"id":5,`, `data: "status":"done","items":[{"id":"2","kind":"result","output":"xong"}]}`, "")
	}

	var seen []string
	s, err := u.Wait(context.Background(), 5, func(ev Event) { seen = append(seen, ev.Name+" "+string(ev.Data)) })
	if err != nil {
		t.Fatal(err)
	}
	if s.Status != StatusDone || len(s.Items) != 1 || s.Items[0].Output != "xong" {
		t.Fatalf("session: %+v", s)
	}
	want := []string{`route {"agent":"order"}`, `step_started {"id":"s1"}`}
	if strings.Join(seen, "|") != strings.Join(want, "|") {
		t.Fatalf("events %q, want %q", seen, want)
	}
}

func TestWaitFallsBackToPolling(t *testing.T) {
	cases := map[string]func(w http.ResponseWriter, r *http.Request, user string){
		"stream unavailable": func(w http.ResponseWriter, r *http.Request, user string) { w.WriteHeader(http.StatusBadGateway) },
		"stream drops early": func(w http.ResponseWriter, r *http.Request, user string) {
			sse(w, "event: route", `data: {"agent":"order"}`, "") // then EOF, no session event
		},
	}
	for name, events := range cases {
		t.Run(name, func(t *testing.T) {
			g := newGateway()
			e := newEnv(t, g)
			u := e.link(t, "UA", "alice")
			g.events = events
			var polls atomic.Int32
			g.sessions = func(r *http.Request, id int64, user string) (int, string) {
				if polls.Add(1) < 3 {
					return 200, `{"id":5,"status":"running"}`
				}
				return 200, `{"id":5,"status":"waiting","items":[{"id":"2","kind":"clarify","question":"which?"}]}`
			}

			s, err := u.Wait(context.Background(), 5, nil)
			if err != nil {
				t.Fatal(err)
			}
			if polls.Load() != 3 || s.Status != StatusWaiting {
				t.Fatalf("polls=%d session=%+v", polls.Load(), s)
			}
			if p, ok := s.Pending(); !ok || p.Question != "which?" {
				t.Fatalf("pending: %+v %v", p, ok)
			}
		})
	}
}

func TestWaitGivesUpAfterMaxWait(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	e.client.cfg.MaxWait = 60 * time.Millisecond
	u := e.link(t, "UA", "alice")
	g.events = func(w http.ResponseWriter, r *http.Request, user string) { w.WriteHeader(http.StatusBadGateway) }
	g.sessions = func(r *http.Request, id int64, user string) (int, string) {
		return 200, `{"id":5,"status":"running"}`
	}

	_, err := u.Wait(context.Background(), 5, nil)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("want deadline exceeded, got %v", err)
	}
}

func TestWaitOnOthersSessionIsNotFound(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	u := e.link(t, "UA", "alice")
	g.events = func(w http.ResponseWriter, r *http.Request, user string) {
		w.WriteHeader(404)
		io.WriteString(w, `{"detail":"session not found"}`)
	}
	if _, err := u.Wait(context.Background(), 5, nil); !errors.Is(err, ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestRedeemSendsTheSlackAccount(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	ctx := context.Background()
	acct := SlackAccount{UserID: "U012ABC", UserName: "nhattin", TeamID: "T0XYZ", TeamDomain: "boa-team"}
	if _, err := e.client.Redeem(ctx, acct, "good-alice"); err != nil {
		t.Fatal(err)
	}
	var got struct {
		Code  string
		Slack *SlackAccount
	}
	json.Unmarshal([]byte(g.bodies["/api/slack-links/redeem"]), &got)
	if got.Code != "good-alice" || got.Slack == nil || *got.Slack != acct {
		t.Fatalf("redeem body: %s", g.bodies["/api/slack-links/redeem"])
	}

	// A dry-run console name is not a Slack id: link without an account rather than be refused.
	if _, err := e.client.Redeem(ctx, SlackAccount{UserID: "alice"}, "good-alice"); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(g.bodies["/api/slack-links/redeem"], "slack") {
		t.Fatalf("console redeem sent an account: %s", g.bodies["/api/slack-links/redeem"])
	}
}

func TestRelinkRevokesThePreviousSession(t *testing.T) {
	g := newGateway()
	e := newEnv(t, g)
	ctx := context.Background()
	u := e.link(t, "U1", "alice")
	if _, err := u.Get(ctx, 1); err != nil { // refreshes once, so the stored token has rotated
		t.Fatal(err)
	}
	old := e.storedRefresh(t, "U1")

	if _, err := e.client.Redeem(ctx, SlackAccount{UserID: "U1"}, "good-bob"); err != nil {
		t.Fatal(err)
	}
	if len(g.logouts) != 1 || g.logouts[0] != old {
		t.Fatalf("logouts %v, want the previous token %q", g.logouts, old)
	}
	if a, _ := e.st.Account(ctx, "U1"); a.UserID != "bob" {
		t.Fatalf("link after relink: %+v", a)
	}
	// The new link works; the first link of another Slack user revokes nothing.
	if _, err := e.client.Redeem(ctx, SlackAccount{UserID: "U2"}, "good-carol"); err != nil || len(g.logouts) != 1 {
		t.Fatalf("first link of U2: %v, logouts %v", err, g.logouts)
	}
}
