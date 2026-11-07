// Package api serves user-service's HTTP endpoints. The gateway strips its /api/users prefix,
// so they are mounted at the root.
//
// The service is reachable only through the gateway, so X-User-Id is the gateway's: it deletes
// any client copy and sets it from a verified token. Private endpoints trust it and nothing else.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"net/mail"
	"regexp"
	"strings"
	"time"

	"nexus/user-service/internal/password"
	"nexus/user-service/internal/token"
	"nexus/user-service/internal/user"
)

const headerUserID = "X-User-Id"

type Store interface {
	Ping(ctx context.Context) error
	CreateUser(ctx context.Context, email, name, passwordHash string, departments []string) (user.User, error)
	UserByEmail(ctx context.Context, email string) (user.User, string, error)
	UserByID(ctx context.Context, id string) (user.User, error)
	ListUsers(ctx context.Context) ([]user.User, error)
	SetDepartments(ctx context.Context, id string, departments []string) (user.User, error)
	CreateRefresh(ctx context.Context, userID, familyID, source string, hash []byte, expiresAt time.Time) error
	RotateRefresh(ctx context.Context, oldHash, newHash []byte, expiresAt time.Time) (string, error)
	RevokeFamily(ctx context.Context, hash []byte) error
	CreateSlackLink(ctx context.Context, userID string, hash []byte, expiresAt time.Time) error
	RedeemSlackLink(ctx context.Context, hash []byte) (string, error)
	SlackLinks(ctx context.Context, userID string) ([]user.SlackLink, error)
	SaveSlackAccount(ctx context.Context, familyID string, a user.SlackAccount) error
	RevokeSlackSessions(ctx context.Context, userID string) error
}

// Where a sign-in came from; only sourceSlack counts as a Slack link.
const (
	sourceWeb   = "web"
	sourceSlack = "slack"
)

type Config struct {
	RefreshTTL time.Duration
	// LinkTTL is how long a Slack link code can be redeemed (default 10 minutes).
	LinkTTL time.Duration
	// Departments an account may be given (D-02: cskh, executive, it).
	Departments []string
	// AdminDepartment may list accounts and change their departments.
	AdminDepartment string
}

type Handler struct {
	store       Store
	tokens      *token.Issuer
	refreshTTL  time.Duration
	linkTTL     time.Duration
	departments map[string]bool
	admin       string
	// dummyHash is checked when the email is unknown, so a miss costs as long as a wrong
	// password and response time doesn't tell which emails have accounts.
	dummyHash string
}

func New(store Store, tokens *token.Issuer, cfg Config) *Handler {
	dummy, err := password.Hash("not-a-real-password")
	if err != nil {
		panic(err)
	}
	depts := map[string]bool{}
	for _, d := range cfg.Departments {
		depts[d] = true
	}
	if cfg.LinkTTL <= 0 {
		cfg.LinkTTL = 10 * time.Minute
	}
	return &Handler{
		store:       store,
		tokens:      tokens,
		refreshTTL:  cfg.RefreshTTL,
		linkTTL:     cfg.LinkTTL,
		departments: depts,
		admin:       cfg.AdminDepartment,
		dummyHash:   dummy,
	}
}

func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", h.health)
	mux.HandleFunc("POST /register", h.register)
	mux.HandleFunc("POST /login", h.login)
	mux.HandleFunc("POST /refresh", h.refresh)
	mux.HandleFunc("POST /logout", h.logout)
	mux.HandleFunc("GET /me", h.me)
	mux.HandleFunc("POST /slack-links", h.createSlackLink)
	mux.HandleFunc("GET /slack-links", h.slackLinkStatus)
	mux.HandleFunc("DELETE /slack-links", h.deleteSlackLink)
	mux.HandleFunc("POST /slack-links/redeem", h.redeemSlackLink)
	// The gateway's own route for redeem forwards with a trailing slash.
	mux.HandleFunc("POST /slack-links/redeem/", h.redeemSlackLink)
	mux.HandleFunc("GET /users", h.listUsers)
	mux.HandleFunc("PUT /users/{id}/departments", h.setDepartments)
	return mux
}

func (h *Handler) health(w http.ResponseWriter, r *http.Request) {
	if err := h.store.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "degraded", "db": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "db": "ok"})
}

type credentials struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	Name     string `json:"name"`
}

// register creates an account with no department: an admin grants them afterwards.
func (h *Handler) register(w http.ResponseWriter, r *http.Request) {
	var req credentials
	if !decode(w, r, &req) {
		return
	}
	email, ok := normalizeEmail(req.Email)
	if !ok {
		writeError(w, http.StatusBadRequest, "a valid email is required")
		return
	}
	if msg := checkPassword(req.Password); msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}
	name := strings.TrimSpace(req.Name)
	if name == "" || len(name) > 100 {
		writeError(w, http.StatusBadRequest, "name is required (at most 100 characters)")
		return
	}
	hash, err := password.Hash(req.Password)
	if err != nil {
		h.internalError(w, err)
		return
	}
	u, err := h.store.CreateUser(r.Context(), email, name, hash, nil)
	if errors.Is(err, user.ErrEmailTaken) {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	if err != nil {
		h.internalError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, u)
}

func (h *Handler) login(w http.ResponseWriter, r *http.Request) {
	var req credentials
	if !decode(w, r, &req) {
		return
	}
	email, _ := normalizeEmail(req.Email)
	u, hash, err := h.store.UserByEmail(r.Context(), email)
	if err != nil && !errors.Is(err, user.ErrNotFound) {
		h.internalError(w, err)
		return
	}
	if errors.Is(err, user.ErrNotFound) {
		password.Verify(h.dummyHash, req.Password)
		writeError(w, http.StatusUnauthorized, "invalid email or password")
		return
	}
	if !password.Verify(hash, req.Password) {
		writeError(w, http.StatusUnauthorized, "invalid email or password")
		return
	}

	h.startSession(w, r, u, sourceWeb, nil)
}

// startSession opens a new sign-in (a refresh token family) for u and writes the session.
// source says where it came from, so a Slack link can be shown and cancelled later; slack, if
// known, is the Slack account behind it.
func (h *Handler) startSession(w http.ResponseWriter, r *http.Request, u user.User, source string, slack *user.SlackAccount) {
	family, err := token.NewFamily()
	if err != nil {
		h.internalError(w, err)
		return
	}
	// Before the token exists: a row without a family is harmless, a family without its row is not shown right
	if slack != nil {
		if err := h.store.SaveSlackAccount(r.Context(), family, *slack); err != nil {
			h.internalError(w, err)
			return
		}
	}
	refresh, refreshHash, err := token.NewRefresh()
	if err != nil {
		h.internalError(w, err)
		return
	}
	if err := h.store.CreateRefresh(r.Context(), u.ID, family, source, refreshHash, time.Now().Add(h.refreshTTL)); err != nil {
		h.internalError(w, err)
		return
	}
	h.writeSession(w, u, refresh)
}

type refreshRequest struct {
	RefreshToken string `json:"refresh_token"`
}

// refresh trades a refresh token for a new pair. The access token carries the departments as they
// are now, so a change made by an admin reaches the gateway at the next refresh.
func (h *Handler) refresh(w http.ResponseWriter, r *http.Request) {
	var req refreshRequest
	if !decode(w, r, &req) {
		return
	}
	if req.RefreshToken == "" {
		writeError(w, http.StatusBadRequest, "refresh_token is required")
		return
	}
	next, nextHash, err := token.NewRefresh()
	if err != nil {
		h.internalError(w, err)
		return
	}
	userID, err := h.store.RotateRefresh(r.Context(), token.HashRefresh(req.RefreshToken), nextHash, time.Now().Add(h.refreshTTL))
	if errors.Is(err, user.ErrInvalidToken) {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}
	if err != nil {
		h.internalError(w, err)
		return
	}
	u, err := h.store.UserByID(r.Context(), userID)
	if err != nil {
		h.internalError(w, err)
		return
	}
	h.writeSession(w, u, next)
}

// logout revokes the session the refresh token belongs to. The access token stays valid until it
// expires (the gateway does not ask user-service), which is why its TTL is short.
func (h *Handler) logout(w http.ResponseWriter, r *http.Request) {
	var req refreshRequest
	if !decode(w, r, &req) {
		return
	}
	if req.RefreshToken != "" {
		if err := h.store.RevokeFamily(r.Context(), token.HashRefresh(req.RefreshToken)); err != nil {
			h.internalError(w, err)
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) me(w http.ResponseWriter, r *http.Request) {
	u, ok := h.requester(w, r)
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, u)
}

// createSlackLink gives the requester a one-time code to send to the Slack bot. Only the hash is
// stored, so the code can't be read back later.
func (h *Handler) createSlackLink(w http.ResponseWriter, r *http.Request) {
	u, ok := h.requester(w, r)
	if !ok {
		return
	}
	code, hash, err := token.NewLinkCode()
	if err != nil {
		h.internalError(w, err)
		return
	}
	expires := time.Now().Add(h.linkTTL)
	if err := h.store.CreateSlackLink(r.Context(), u.ID, hash, expires); err != nil {
		h.internalError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusCreated, map[string]any{"code": code, "expires_at": expires})
}

type redeemRequest struct {
	Code  string             `json:"code"`
	Slack *user.SlackAccount `json:"slack"` // optional: who is linking, shown on the web
}

// Slack ids and the workspace subdomain; the web builds a profile URL from team_domain, so it is
// checked strictly. user_name is free text, only kept short and free of control characters.
var (
	slackUserIDPattern = regexp.MustCompile(`^[UW][A-Z0-9]{2,30}$`)
	slackTeamIDPattern = regexp.MustCompile(`^[TE][A-Z0-9]{2,30}$`)
	slackDomainPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{0,62}$`)
)

const maxSlackUserName = 80

func validSlackAccount(a *user.SlackAccount) bool {
	if !slackUserIDPattern.MatchString(a.UserID) {
		return false
	}
	if a.TeamID != "" && !slackTeamIDPattern.MatchString(a.TeamID) {
		return false
	}
	if a.TeamDomain != "" && !slackDomainPattern.MatchString(a.TeamDomain) {
		return false
	}
	return shortPlainText(a.UserName) && shortPlainText(a.RealName)
}

// shortPlainText accepts empty text, or text of at most maxSlackUserName characters with no control characters.
func shortPlainText(s string) bool {
	if len([]rune(s)) > maxSlackUserName {
		return false
	}
	for _, c := range s {
		if c < 0x20 || c == 0x7f {
			return false
		}
	}
	return true
}

// redeemSlackLink trades a code for a session of its own, separate from the web sign-in that made
// the code, so unlinking the bot (logout) doesn't end the web session. The code is the only
// credential: a wrong, spent and expired code all answer the same 401.
func (h *Handler) redeemSlackLink(w http.ResponseWriter, r *http.Request) {
	var req redeemRequest
	if !decode(w, r, &req) {
		return
	}
	if strings.TrimSpace(req.Code) == "" {
		writeError(w, http.StatusBadRequest, "code is required")
		return
	}
	// Checked before the code is spent, so a bad payload doesn't cost the person their code
	if req.Slack != nil && !validSlackAccount(req.Slack) {
		writeError(w, http.StatusBadRequest, "invalid slack account")
		return
	}
	userID, err := h.store.RedeemSlackLink(r.Context(), token.HashLinkCode(req.Code))
	if errors.Is(err, user.ErrInvalidCode) {
		writeError(w, http.StatusUnauthorized, err.Error())
		return
	}
	if err != nil {
		h.internalError(w, err)
		return
	}
	u, err := h.store.UserByID(r.Context(), userID)
	if err != nil {
		h.internalError(w, err)
		return
	}
	h.startSession(w, r, u, sourceSlack, req.Slack)
}

// slackLinkStatus tells the requester whether a Slack account is linked to them.
func (h *Handler) slackLinkStatus(w http.ResponseWriter, r *http.Request) {
	u, ok := h.requester(w, r)
	if !ok {
		return
	}
	links, err := h.store.SlackLinks(r.Context(), u.ID)
	if err != nil {
		h.internalError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	if len(links) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{"linked": false, "links": links})
		return
	}
	// linked_at stays the oldest link, as before; links lists each one (oldest first)
	writeJSON(w, http.StatusOK, map[string]any{"linked": true, "linked_at": links[0].LinkedAt, "links": links})
}

// deleteSlackLink cancels the requester's Slack link: the bot's next refresh gets 401 and it drops
// the account. Web sign-ins stay. Idempotent: nothing linked is still 204.
func (h *Handler) deleteSlackLink(w http.ResponseWriter, r *http.Request) {
	u, ok := h.requester(w, r)
	if !ok {
		return
	}
	if err := h.store.RevokeSlackSessions(r.Context(), u.ID); err != nil {
		h.internalError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) listUsers(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.requireAdmin(w, r); !ok {
		return
	}
	users, err := h.store.ListUsers(r.Context())
	if err != nil {
		h.internalError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, users)
}

type departmentsRequest struct {
	Departments []string `json:"departments"`
}

func (h *Handler) setDepartments(w http.ResponseWriter, r *http.Request) {
	admin, ok := h.requireAdmin(w, r)
	if !ok {
		return
	}
	var req departmentsRequest
	if !decode(w, r, &req) {
		return
	}
	if req.Departments == nil {
		writeError(w, http.StatusBadRequest, `body must be {"departments": [...]}`)
		return
	}
	depts := []string{}
	seen := map[string]bool{}
	for _, d := range req.Departments {
		d = strings.TrimSpace(d)
		if !h.departments[d] {
			writeError(w, http.StatusBadRequest, "unknown department: "+d)
			return
		}
		if !seen[d] {
			seen[d] = true
			depts = append(depts, d)
		}
	}
	id := r.PathValue("id")
	// An admin removing their own admin department could leave no one able to undo it.
	if id == admin.ID && !seen[h.admin] {
		writeError(w, http.StatusConflict, "cannot remove your own "+h.admin+" department")
		return
	}
	u, err := h.store.SetDepartments(r.Context(), id, depts)
	if errors.Is(err, user.ErrNotFound) {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	if err != nil {
		h.internalError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

// requester loads the account named by the gateway's X-User-Id; 401 without one.
func (h *Handler) requester(w http.ResponseWriter, r *http.Request) (user.User, bool) {
	id := r.Header.Get(headerUserID)
	if id == "" {
		writeError(w, http.StatusUnauthorized, "sign in required")
		return user.User{}, false
	}
	u, err := h.store.UserByID(r.Context(), id)
	if errors.Is(err, user.ErrNotFound) {
		// A valid token for a deleted account.
		writeError(w, http.StatusUnauthorized, "sign in required")
		return user.User{}, false
	}
	if err != nil {
		h.internalError(w, err)
		return user.User{}, false
	}
	return u, true
}

// requireAdmin checks the departments stored now, not the token's X-User-Departments, so a
// revoked admin loses access at once rather than when their access token expires.
func (h *Handler) requireAdmin(w http.ResponseWriter, r *http.Request) (user.User, bool) {
	u, ok := h.requester(w, r)
	if !ok {
		return user.User{}, false
	}
	if !u.In(h.admin) {
		writeError(w, http.StatusForbidden, "requires the "+h.admin+" department")
		return user.User{}, false
	}
	return u, true
}

type session struct {
	AccessToken  string    `json:"access_token"`
	TokenType    string    `json:"token_type"`
	ExpiresIn    int       `json:"expires_in"`
	RefreshToken string    `json:"refresh_token"`
	User         user.User `json:"user"`
}

func (h *Handler) writeSession(w http.ResponseWriter, u user.User, refresh string) {
	access, err := h.tokens.Issue(u.ID, u.Email, u.Name, u.Departments)
	if err != nil {
		h.internalError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, session{
		AccessToken:  access,
		TokenType:    "Bearer",
		ExpiresIn:    int(h.tokens.TTL().Seconds()),
		RefreshToken: refresh,
		User:         u,
	})
}

func normalizeEmail(s string) (string, bool) {
	s = strings.ToLower(strings.TrimSpace(s))
	if len(s) > 254 {
		return "", false
	}
	addr, err := mail.ParseAddress(s)
	if err != nil || addr.Address != s {
		return "", false
	}
	return s, true
}

func checkPassword(p string) string {
	if len(p) < 8 || len(p) > 128 {
		return "password must be 8 to 128 characters"
	}
	return ""
}

func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<12)).Decode(v); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

func (h *Handler) internalError(w http.ResponseWriter, err error) {
	log.Printf("internal error: %v", err)
	writeError(w, http.StatusInternalServerError, "internal error")
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
