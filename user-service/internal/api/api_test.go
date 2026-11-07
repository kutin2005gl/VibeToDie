package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"nexus/user-service/internal/password"
	"nexus/user-service/internal/token"
	"nexus/user-service/internal/user"
)

const secret = "test-secret-that-is-at-least-32-chars"

type linkRow struct {
	userID  string
	expires time.Time
	used    bool
}

type refreshRow struct {
	userID, family, source string
	expires                time.Time
	used, revoked          bool
	created                time.Time
}

// memStore mirrors store.Store, including refresh rotation and reuse detection.
type memStore struct {
	mu      sync.Mutex
	users   map[string]user.User
	hashes  map[string]string
	refresh map[string]*refreshRow
	links   map[string]*linkRow
	slack   map[string]user.SlackAccount // by family
	next    int
}

func newMemStore() *memStore {
	return &memStore{users: map[string]user.User{}, hashes: map[string]string{}, refresh: map[string]*refreshRow{}, links: map[string]*linkRow{}, slack: map[string]user.SlackAccount{}}
}

func (m *memStore) Ping(context.Context) error { return nil }

func (m *memStore) CreateUser(_ context.Context, email, name, hash string, depts []string) (user.User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, u := range m.users {
		if u.Email == email {
			return user.User{}, user.ErrEmailTaken
		}
	}
	if depts == nil {
		depts = []string{}
	}
	m.next++
	u := user.User{ID: fmt.Sprintf("u%d", m.next), Email: email, Name: name, Departments: depts, CreatedAt: time.Now()}
	m.users[u.ID], m.hashes[u.ID] = u, hash
	return u, nil
}

func (m *memStore) UserByEmail(_ context.Context, email string) (user.User, string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, u := range m.users {
		if u.Email == email {
			return u, m.hashes[u.ID], nil
		}
	}
	return user.User{}, "", user.ErrNotFound
}

func (m *memStore) UserByID(_ context.Context, id string) (user.User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	u, ok := m.users[id]
	if !ok {
		return user.User{}, user.ErrNotFound
	}
	return u, nil
}

func (m *memStore) ListUsers(context.Context) ([]user.User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := []user.User{}
	for _, u := range m.users {
		out = append(out, u)
	}
	return out, nil
}

func (m *memStore) SetDepartments(_ context.Context, id string, depts []string) (user.User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	u, ok := m.users[id]
	if !ok {
		return user.User{}, user.ErrNotFound
	}
	u.Departments = depts
	m.users[id] = u
	return u, nil
}

func (m *memStore) CreateRefresh(_ context.Context, userID, family, source string, hash []byte, expires time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.refresh[string(hash)] = &refreshRow{userID: userID, family: family, source: source, expires: expires, created: time.Now()}
	return nil
}

func (m *memStore) SlackLinks(_ context.Context, userID string) ([]user.SlackLink, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	live := map[string]bool{}
	for _, r := range m.refresh {
		if r.userID == userID && r.source == "slack" && !r.used && !r.revoked && r.expires.After(time.Now()) {
			live[r.family] = true
		}
	}
	started := map[string]time.Time{}
	for _, r := range m.refresh {
		if s, ok := started[r.family]; live[r.family] && (!ok || r.created.Before(s)) {
			started[r.family] = r.created
		}
	}
	links := []user.SlackLink{}
	for family, at := range started {
		l := user.SlackLink{LinkedAt: at}
		if a, ok := m.slack[family]; ok {
			l.Account = &a
		}
		links = append(links, l)
	}
	sort.Slice(links, func(i, j int) bool { return links[i].LinkedAt.Before(links[j].LinkedAt) })
	return links, nil
}

func (m *memStore) SaveSlackAccount(_ context.Context, family string, a user.SlackAccount) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.slack[family] = a
	return nil
}

func (m *memStore) RevokeSlackSessions(_ context.Context, userID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, r := range m.refresh {
		if r.userID == userID && r.source == "slack" {
			r.revoked = true
		}
	}
	return nil
}

func (m *memStore) RotateRefresh(_ context.Context, oldHash, newHash []byte, expires time.Time) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.refresh[string(oldHash)]
	if !ok {
		return "", user.ErrInvalidToken
	}
	if row.used && !row.revoked {
		for _, r := range m.refresh {
			if r.family == row.family {
				r.revoked = true
			}
		}
		return "", user.ErrInvalidToken
	}
	if row.used || row.revoked || !row.expires.After(time.Now()) {
		return "", user.ErrInvalidToken
	}
	row.used = true
	m.refresh[string(newHash)] = &refreshRow{userID: row.userID, family: row.family, source: row.source, expires: expires, created: time.Now()}
	return row.userID, nil
}

func (m *memStore) RevokeFamily(_ context.Context, hash []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.refresh[string(hash)]
	if !ok {
		return nil
	}
	for _, r := range m.refresh {
		if r.family == row.family {
			r.revoked = true
		}
	}
	return nil
}

func (m *memStore) CreateSlackLink(_ context.Context, userID string, hash []byte, expires time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.links[string(hash)] = &linkRow{userID: userID, expires: expires}
	return nil
}

func (m *memStore) RedeemSlackLink(_ context.Context, hash []byte) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.links[string(hash)]
	if !ok || row.used || !row.expires.After(time.Now()) {
		return "", user.ErrInvalidCode
	}
	row.used = true
	return row.userID, nil
}

func newServer(t *testing.T) (*memStore, http.Handler) {
	t.Helper()
	tokens, err := token.NewIssuer(secret, "nexus", 15*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	st := newMemStore()
	h := New(st, tokens, Config{RefreshTTL: time.Hour, Departments: []string{"cskh", "executive", "it"}, AdminDepartment: "executive"})
	return st, h.Routes()
}

// seed creates an account directly, with departments, and returns its id.
func seed(t *testing.T, st *memStore, email, pw string, depts ...string) string {
	t.Helper()
	hash, err := password.Hash(pw)
	if err != nil {
		t.Fatal(err)
	}
	u, err := st.CreateUser(context.Background(), email, "Test", hash, depts)
	if err != nil {
		t.Fatal(err)
	}
	return u.ID
}

func do(t *testing.T, h http.Handler, method, path, userID string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&buf).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, path, &buf)
	if userID != "" {
		req.Header.Set(headerUserID, userID)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func decodeBody[T any](t *testing.T, rec *httptest.ResponseRecorder) T {
	t.Helper()
	var v T
	if err := json.Unmarshal(rec.Body.Bytes(), &v); err != nil {
		t.Fatalf("decode %q: %v", rec.Body.String(), err)
	}
	return v
}

func TestRegisterCreatesAccountWithoutDepartments(t *testing.T) {
	_, h := newServer(t)
	rec := do(t, h, "POST", "/register", "", map[string]string{"email": " An@Example.com ", "password": "longenough", "name": "An"})
	if rec.Code != http.StatusCreated {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	u := decodeBody[user.User](t, rec)
	if u.Email != "an@example.com" || len(u.Departments) != 0 {
		t.Fatalf("got %+v", u)
	}
	if strings.Contains(rec.Body.String(), "argon2") {
		t.Fatal("password hash leaked in response")
	}

	rec = do(t, h, "POST", "/register", "", map[string]string{"email": "an@example.com", "password": "longenough", "name": "An"})
	if rec.Code != http.StatusConflict {
		t.Fatalf("duplicate: status %d", rec.Code)
	}
}

func TestRegisterValidates(t *testing.T) {
	_, h := newServer(t)
	for _, body := range []map[string]string{
		{"email": "not-an-email", "password": "longenough", "name": "An"},
		{"email": "a@b.co", "password": "short", "name": "An"},
		{"email": "a@b.co", "password": "longenough", "name": " "},
		{"email": "An <a@b.co>", "password": "longenough", "name": "An"},
	} {
		if rec := do(t, h, "POST", "/register", "", body); rec.Code != http.StatusBadRequest {
			t.Errorf("%v: status %d", body, rec.Code)
		}
	}
}

// The access token must pass the gateway's own checks (HS256, issuer, exp, sub) and carry what it
// forwards as X-User-Id and X-User-Departments.
func TestLoginIssuesTokenTheGatewayAccepts(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")

	rec := do(t, h, "POST", "/login", "", map[string]string{"email": "Staff@Nexus.vn", "password": "longenough"})
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body)
	}
	s := decodeBody[session](t, rec)
	if s.TokenType != "Bearer" || s.ExpiresIn != 900 || s.RefreshToken == "" || s.User.ID != id {
		t.Fatalf("session %+v", s)
	}

	var claims struct {
		Email       string   `json:"email"`
		Departments []string `json:"departments"`
		jwt.RegisteredClaims
	}
	parser := jwt.NewParser(
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithExpirationRequired(),
		jwt.WithIssuer("nexus"),
	)
	if _, err := parser.ParseWithClaims(s.AccessToken, &claims, func(*jwt.Token) (any, error) { return []byte(secret), nil }); err != nil {
		t.Fatalf("gateway would reject token: %v", err)
	}
	if claims.Subject != id || claims.Email != "staff@nexus.vn" || strings.Join(claims.Departments, ",") != "cskh" {
		t.Fatalf("claims %+v", claims)
	}
}

func TestLoginRejectsBadCredentialsTheSameWay(t *testing.T) {
	st, h := newServer(t)
	seed(t, st, "staff@nexus.vn", "longenough")
	wrong := do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "wrongwrong"})
	unknown := do(t, h, "POST", "/login", "", map[string]string{"email": "nobody@nexus.vn", "password": "wrongwrong"})
	if wrong.Code != http.StatusUnauthorized || unknown.Code != http.StatusUnauthorized || wrong.Body.String() != unknown.Body.String() {
		t.Fatalf("wrong=%d %s unknown=%d %s", wrong.Code, wrong.Body, unknown.Code, unknown.Body)
	}
}

func TestRefreshRotatesAndDetectsReuse(t *testing.T) {
	st, h := newServer(t)
	seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	first := decodeBody[session](t, do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "longenough"}))

	rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": first.RefreshToken})
	if rec.Code != http.StatusOK {
		t.Fatalf("refresh: %d %s", rec.Code, rec.Body)
	}
	second := decodeBody[session](t, rec)
	if second.RefreshToken == first.RefreshToken || second.AccessToken == "" {
		t.Fatal("refresh did not rotate")
	}

	// Replaying the spent token revokes the family: the newer token stops working too.
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": first.RefreshToken}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("reuse: %d", rec.Code)
	}
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": second.RefreshToken}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("after reuse: %d", rec.Code)
	}
}

func TestRefreshCarriesCurrentDepartments(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough")
	s := decodeBody[session](t, do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "longenough"}))
	if _, err := st.SetDepartments(context.Background(), id, []string{"it"}); err != nil {
		t.Fatal(err)
	}
	s = decodeBody[session](t, do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": s.RefreshToken}))
	if strings.Join(s.User.Departments, ",") != "it" {
		t.Fatalf("departments %v", s.User.Departments)
	}
}

func TestLogoutRevokesSession(t *testing.T) {
	st, h := newServer(t)
	seed(t, st, "staff@nexus.vn", "longenough")
	s := decodeBody[session](t, do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "longenough"}))
	if rec := do(t, h, "POST", "/logout", "", map[string]string{"refresh_token": s.RefreshToken}); rec.Code != http.StatusNoContent {
		t.Fatalf("logout: %d", rec.Code)
	}
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": s.RefreshToken}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("refresh after logout: %d", rec.Code)
	}
}

func TestMeUsesGatewayIdentity(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	if rec := do(t, h, "GET", "/me", "", nil); rec.Code != http.StatusUnauthorized {
		t.Fatalf("anonymous: %d", rec.Code)
	}
	if rec := do(t, h, "GET", "/me", "ghost", nil); rec.Code != http.StatusUnauthorized {
		t.Fatalf("unknown id: %d", rec.Code)
	}
	rec := do(t, h, "GET", "/me", id, nil)
	if rec.Code != http.StatusOK || decodeBody[user.User](t, rec).ID != id {
		t.Fatalf("me: %d %s", rec.Code, rec.Body)
	}
}

func TestAdminSetsDepartments(t *testing.T) {
	st, h := newServer(t)
	admin := seed(t, st, "boss@nexus.vn", "longenough", "executive")
	staff := seed(t, st, "staff@nexus.vn", "longenough", "cskh")

	if rec := do(t, h, "PUT", "/users/"+staff+"/departments", staff, map[string]any{"departments": []string{"executive"}}); rec.Code != http.StatusForbidden {
		t.Fatalf("non-admin: %d", rec.Code)
	}
	if rec := do(t, h, "GET", "/users", staff, nil); rec.Code != http.StatusForbidden {
		t.Fatalf("non-admin list: %d", rec.Code)
	}
	if rec := do(t, h, "PUT", "/users/"+staff+"/departments", admin, map[string]any{"departments": []string{"sales"}}); rec.Code != http.StatusBadRequest {
		t.Fatalf("unknown department: %d", rec.Code)
	}
	if rec := do(t, h, "PUT", "/users/"+admin+"/departments", admin, map[string]any{"departments": []string{"cskh"}}); rec.Code != http.StatusConflict {
		t.Fatalf("self-demotion: %d", rec.Code)
	}
	if rec := do(t, h, "PUT", "/users/nope/departments", admin, map[string]any{"departments": []string{}}); rec.Code != http.StatusNotFound {
		t.Fatalf("missing user: %d", rec.Code)
	}

	rec := do(t, h, "PUT", "/users/"+staff+"/departments", admin, map[string]any{"departments": []string{"cskh", "it", "cskh"}})
	if rec.Code != http.StatusOK {
		t.Fatalf("set: %d %s", rec.Code, rec.Body)
	}
	if got := strings.Join(decodeBody[user.User](t, rec).Departments, ","); got != "cskh,it" {
		t.Fatalf("departments %s", got)
	}
	if rec := do(t, h, "GET", "/users", admin, nil); rec.Code != http.StatusOK || len(decodeBody[[]user.User](t, rec)) != 2 {
		t.Fatalf("list: %d %s", rec.Code, rec.Body)
	}
}

func linkCode(t *testing.T, h http.Handler, userID string) string {
	t.Helper()
	rec := do(t, h, "POST", "/slack-links", userID, nil)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create link: %d %s", rec.Code, rec.Body)
	}
	return decodeBody[struct {
		Code      string    `json:"code"`
		ExpiresAt time.Time `json:"expires_at"`
	}](t, rec).Code
}

func TestSlackLinkRequiresSignIn(t *testing.T) {
	_, h := newServer(t)
	if rec := do(t, h, "POST", "/slack-links", "", nil); rec.Code != http.StatusUnauthorized {
		t.Fatalf("anonymous: %d", rec.Code)
	}
}

func TestSlackLinkRedeemGivesOwnSessionWithCurrentDepartments(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	code := linkCode(t, h, id)
	if len(code) != 10 {
		t.Fatalf("code %q", code)
	}
	// An admin changes departments between creating the code and redeeming it.
	if _, err := st.SetDepartments(context.Background(), id, []string{"it"}); err != nil {
		t.Fatal(err)
	}

	// Typed by hand: lowercase and a dash don't matter.
	typed := strings.ToLower(code[:5] + "-" + code[5:])
	rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": typed})
	if rec.Code != http.StatusOK {
		t.Fatalf("redeem: %d %s", rec.Code, rec.Body)
	}
	s := decodeBody[session](t, rec)
	if s.AccessToken == "" || s.RefreshToken == "" || s.TokenType != "Bearer" || s.ExpiresIn != 900 {
		t.Fatalf("session %+v", s)
	}
	claims := &token.Claims{}
	if _, err := jwt.ParseWithClaims(s.AccessToken, claims, func(*jwt.Token) (any, error) { return []byte(secret), nil }); err != nil {
		t.Fatal(err)
	}
	if claims.Subject != id || len(claims.Departments) != 1 || claims.Departments[0] != "it" {
		t.Fatalf("claims %+v", claims)
	}

	// The token it returns is a normal refresh token.
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": s.RefreshToken}); rec.Code != http.StatusOK {
		t.Fatalf("refresh: %d", rec.Code)
	}
}

func TestSlackLinkSessionIsSeparateFromWebSession(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	web := decodeBody[session](t, do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "longenough"}))
	bot := decodeBody[session](t, do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": linkCode(t, h, id)}))

	do(t, h, "POST", "/logout", "", map[string]string{"refresh_token": bot.RefreshToken})
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": web.RefreshToken}); rec.Code != http.StatusOK {
		t.Fatalf("web session after unlink: %d", rec.Code)
	}
}

func TestSlackLinkCodeIsOneTime(t *testing.T) {
	st, h := newServer(t)
	code := linkCode(t, h, seed(t, st, "staff@nexus.vn", "longenough", "cskh"))
	if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": code}); rec.Code != http.StatusOK {
		t.Fatalf("first: %d", rec.Code)
	}
	if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": code}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("reuse: %d", rec.Code)
	}
}

func TestSlackLinkCodeExpires(t *testing.T) {
	st, h := newServer(t)
	code := linkCode(t, h, seed(t, st, "staff@nexus.vn", "longenough", "cskh"))
	for _, row := range st.links {
		if row.expires.Before(time.Now().Add(9*time.Minute)) || row.expires.After(time.Now().Add(11*time.Minute)) {
			t.Fatalf("ttl: expires %v", row.expires)
		}
		row.expires = time.Now().Add(-time.Second)
	}
	if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": code}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("expired: %d", rec.Code)
	}
}

func TestSlackLinkRejectsWrongCode(t *testing.T) {
	st, h := newServer(t)
	linkCode(t, h, seed(t, st, "staff@nexus.vn", "longenough", "cskh"))
	for _, code := range []string{"AAAAAAAAAA", "x"} {
		if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": code}); rec.Code != http.StatusUnauthorized {
			t.Fatalf("%q: %d", code, rec.Code)
		}
	}
	if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": " "}); rec.Code != http.StatusBadRequest {
		t.Fatalf("blank: %d", rec.Code)
	}
}

type linkStatus struct {
	Linked   bool             `json:"linked"`
	LinkedAt time.Time        `json:"linked_at"`
	Links    []user.SlackLink `json:"links"`
}

func TestSlackLinkStatusAndUnlink(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	web := decodeBody[session](t, do(t, h, "POST", "/login", "", map[string]string{"email": "staff@nexus.vn", "password": "longenough"}))

	// A web sign-in alone is not a Slack link.
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); s.Linked {
		t.Fatal("linked before any redeem")
	}

	bot := decodeBody[session](t, do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": linkCode(t, h, id)}))
	// Rotation keeps it linked, and keeps the original start time.
	first := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil))
	if !first.Linked || first.LinkedAt.IsZero() {
		t.Fatalf("after redeem: %+v", first)
	}
	rotated := decodeBody[session](t, do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": bot.RefreshToken}))
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); !s.Linked || !s.LinkedAt.Equal(first.LinkedAt) {
		t.Fatalf("after rotate: %+v want since %v", s, first.LinkedAt)
	}

	if rec := do(t, h, "DELETE", "/slack-links", id, nil); rec.Code != http.StatusNoContent {
		t.Fatalf("unlink: %d", rec.Code)
	}
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); s.Linked {
		t.Fatal("still linked after unlink")
	}
	// The bot's token no longer works; the web session does.
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": rotated.RefreshToken}); rec.Code != http.StatusUnauthorized {
		t.Fatalf("bot refresh after unlink: %d", rec.Code)
	}
	if rec := do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": web.RefreshToken}); rec.Code != http.StatusOK {
		t.Fatalf("web refresh after unlink: %d", rec.Code)
	}
	// Idempotent, and linking again works.
	if rec := do(t, h, "DELETE", "/slack-links", id, nil); rec.Code != http.StatusNoContent {
		t.Fatalf("second unlink: %d", rec.Code)
	}
	do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": linkCode(t, h, id)})
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); !s.Linked {
		t.Fatal("relink did not show as linked")
	}
}

func TestSlackLinkStatusIsPerUserAndNeedsSignIn(t *testing.T) {
	st, h := newServer(t)
	a := seed(t, st, "a@nexus.vn", "longenough", "cskh")
	b := seed(t, st, "b@nexus.vn", "longenough", "cskh")
	do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": linkCode(t, h, a)})

	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", b, nil)); s.Linked {
		t.Fatal("b sees a's link")
	}
	// b unlinking must not touch a.
	do(t, h, "DELETE", "/slack-links", b, nil)
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", a, nil)); !s.Linked {
		t.Fatal("b's unlink cancelled a's link")
	}
	for _, method := range []string{"GET", "DELETE"} {
		if rec := do(t, h, method, "/slack-links", "", nil); rec.Code != http.StatusUnauthorized {
			t.Fatalf("%s anonymous: %d", method, rec.Code)
		}
	}
}

func TestSlackLinkRedeemAcceptsGatewayTrailingSlash(t *testing.T) {
	st, h := newServer(t)
	code := linkCode(t, h, seed(t, st, "staff@nexus.vn", "longenough", "cskh"))
	if rec := do(t, h, "POST", "/slack-links/redeem/", "", map[string]string{"code": code}); rec.Code != http.StatusOK {
		t.Fatalf("trailing slash: %d", rec.Code)
	}
}

func TestSlackLinkShowsTheSlackAccount(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	slack := map[string]string{"slack_user_id": "U012ABC", "user_name": "nhattin", "real_name": "Nhật Tín", "team_id": "T0XYZ", "team_domain": "boa-team"}
	bot := decodeBody[session](t, do(t, h, "POST", "/slack-links/redeem", "", map[string]any{"code": linkCode(t, h, id), "slack": slack}))
	// An old bot that sends only the code still links; the account is just unknown.
	do(t, h, "POST", "/slack-links/redeem", "", map[string]string{"code": linkCode(t, h, id)})

	// Both links may start in the same clock tick, so find them by their account, not by position.
	known := func(s linkStatus) (withAccount *user.SlackAccount, without int) {
		for _, l := range s.Links {
			if l.Account != nil {
				withAccount = l.Account
			} else {
				without++
			}
		}
		return
	}
	s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil))
	if !s.Linked || len(s.Links) != 2 || s.LinkedAt.IsZero() {
		t.Fatalf("status: %+v", s)
	}
	want := user.SlackAccount{UserID: "U012ABC", UserName: "nhattin", RealName: "Nhật Tín", TeamID: "T0XYZ", TeamDomain: "boa-team"}
	if a, none := known(s); a == nil || *a != want || none != 1 {
		t.Fatalf("links: %+v", s.Links)
	}

	// Rotation keeps the account; unlinking clears the list.
	do(t, h, "POST", "/refresh", "", map[string]string{"refresh_token": bot.RefreshToken})
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); len(s.Links) != 2 {
		t.Fatalf("after rotate: %+v", s)
	} else if a, _ := known(s); a == nil || *a != want {
		t.Fatalf("rotation lost the account: %+v", s.Links)
	}
	do(t, h, "DELETE", "/slack-links", id, nil)
	if s := decodeBody[linkStatus](t, do(t, h, "GET", "/slack-links", id, nil)); s.Linked || len(s.Links) != 0 {
		t.Fatalf("after unlink: %+v", s)
	}
}

func TestRedeemRejectsBadSlackAccountWithoutSpendingTheCode(t *testing.T) {
	st, h := newServer(t)
	id := seed(t, st, "staff@nexus.vn", "longenough", "cskh")
	code := linkCode(t, h, id)
	bad := []map[string]string{
		{"user_name": "no id"},
		{"slack_user_id": "not-an-id"},
		{"slack_user_id": "U012ABC", "team_id": "x"},
		{"slack_user_id": "U012ABC", "team_domain": "evil.com/x"},
		{"slack_user_id": "U012ABC", "team_domain": "Boa"},
		{"slack_user_id": "U012ABC", "user_name": "a\nb"},
		{"slack_user_id": "U012ABC", "user_name": strings.Repeat("a", 81)},
		{"slack_user_id": "U012ABC", "real_name": strings.Repeat("a", 81)},
		{"slack_user_id": "U012ABC", "real_name": "ab"},
	}
	for _, slack := range bad {
		if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]any{"code": code, "slack": slack}); rec.Code != http.StatusBadRequest {
			t.Fatalf("%v: %d", slack, rec.Code)
		}
	}
	ok := map[string]string{"slack_user_id": "U012ABC", "user_name": "Nhật Tín"}
	if rec := do(t, h, "POST", "/slack-links/redeem", "", map[string]any{"code": code, "slack": ok}); rec.Code != http.StatusOK {
		t.Fatalf("code was spent by a rejected request: %d", rec.Code)
	}
}
