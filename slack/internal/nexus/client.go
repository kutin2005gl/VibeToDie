// Package nexus is the bot's client of the gateway. Every call is made with the token of the
// Slack user who asked, so the bot never has more rights than that person has on the web.
package nexus

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"regexp"
	"strconv"
	"sync"
	"time"

	"nexus/slack/internal/secret"
	"nexus/slack/internal/store"
)

const (
	// A token this close to expiring is refreshed before use, not during the call.
	expirySkew     = 30 * time.Second
	callTimeout    = 30 * time.Second
	defaultPoll    = 2 * time.Second
	defaultMaxWait = 15 * time.Minute
)

// Config wires a Client. Store and Box are required.
type Config struct {
	BaseURL string // gateway, no trailing slash
	Store   store.Store
	Box     *secret.Box
	HTTP    *http.Client // default: no overall timeout (streams are long); calls get their own

	PollEvery time.Duration // Wait: poll interval when the stream is unavailable (default 2s)
	MaxWait   time.Duration // Wait: give up after this long (default 15m)
}

// Client holds what is shared by all users; For gives the per-person view.
type Client struct {
	cfg Config

	mu    sync.Mutex
	users map[string]*UserClient
}

func New(cfg Config) *Client {
	if cfg.HTTP == nil {
		cfg.HTTP = &http.Client{}
	}
	if cfg.PollEvery <= 0 {
		cfg.PollEvery = defaultPoll
	}
	if cfg.MaxWait <= 0 {
		cfg.MaxWait = defaultMaxWait
	}
	return &Client{cfg: cfg, users: map[string]*UserClient{}}
}

// UserClient makes calls as one linked person. It keeps the access token in memory and refreshes
// it from the stored refresh token. Refresh tokens rotate and reusing an old one revokes the whole
// session, so refreshes of one user never overlap (mu) and the new token is stored before it is used.
type UserClient struct {
	c           *Client
	slackUserID string
	userID      string

	mu      sync.Mutex // guards access, expires and every refresh
	access  string
	expires time.Time
}

// For returns the client of a linked Slack user, or ErrNotLinked.
func (c *Client) For(ctx context.Context, slackUserID string) (*UserClient, error) {
	acct, err := c.cfg.Store.Account(ctx, slackUserID)
	if errors.Is(err, store.ErrNotFound) {
		return nil, ErrNotLinked
	}
	if err != nil {
		return nil, err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	u := c.users[slackUserID]
	if u == nil || u.userID != acct.UserID {
		// First use, or the Slack user relinked to another account: the cached token is not theirs.
		u = &UserClient{c: c, slackUserID: slackUserID, userID: acct.UserID}
		c.users[slackUserID] = u
	}
	return u, nil
}

// drop forgets the cached client of a Slack user.
func (c *Client) drop(slackUserID string) {
	c.mu.Lock()
	delete(c.users, slackUserID)
	c.mu.Unlock()
}

type tokens struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
	User         User   `json:"user"`
}

// SlackAccount is who is linking, as the /boa command reported it. user-service keeps it with the
// new session so the web can say which Slack account is linked; it grants nothing.
type SlackAccount struct {
	UserID     string `json:"slack_user_id"`
	UserName   string `json:"user_name,omitempty"`
	RealName   string `json:"real_name,omitempty"` // full name; needs users:read, left out without it
	TeamID     string `json:"team_id,omitempty"`
	TeamDomain string `json:"team_domain,omitempty"`
}

// slackUserID is the shape of a real Slack user id. The dry-run console uses names like "alice",
// which user-service would refuse, so those link without an account.
var slackUserID = regexp.MustCompile(`^[UW][A-Z0-9]{2,30}$`)

// Redeem trades a link code (made on the web) for a session of its own, seals the refresh token
// and links it to the Slack user. A relink replaces that Slack user's earlier session, which is
// then revoked so the web no longer lists it. The code is never logged.
func (c *Client) Redeem(ctx context.Context, acct SlackAccount, code string) (User, error) {
	body := map[string]any{"code": code}
	if slackUserID.MatchString(acct.UserID) {
		body["slack"] = acct
	}
	var t tokens
	err := c.post(ctx, "/api/slack-links/redeem", body, &t)
	var api *APIError
	if errors.As(err, &api) && api.Status == http.StatusUnauthorized {
		return User{}, ErrInvalidCode
	}
	if err != nil {
		return User{}, err
	}
	sealed, err := c.cfg.Box.Seal([]byte(t.RefreshToken))
	if err != nil {
		return User{}, err
	}

	// Hold the old link's lock, so a refresh in flight can't store its rotated token over the new one.
	var previous []byte
	if u, err := c.For(ctx, acct.UserID); err == nil {
		u.mu.Lock()
		defer u.mu.Unlock()
		if old, err := c.cfg.Store.Account(ctx, acct.UserID); err == nil {
			previous = old.RefreshTokenEnc
		}
	}
	link := store.Account{SlackUserID: acct.UserID, UserID: t.User.ID, RefreshTokenEnc: sealed}
	if err := c.cfg.Store.SaveAccount(ctx, link); err != nil {
		return User{}, err
	}
	c.drop(acct.UserID)
	if previous != nil {
		// Best effort: the new link works either way; an unrevoked old session just expires on its own.
		if err := c.revoke(ctx, previous); err != nil {
			log.Printf("nexus: revoke previous session of %s: %v", acct.UserID, err)
		}
	}
	return t.User, nil
}

// revoke signs out the session a sealed refresh token belongs to.
func (c *Client) revoke(ctx context.Context, sealed []byte) error {
	refresh, err := c.cfg.Box.Open(sealed)
	if err != nil {
		return err
	}
	return c.post(ctx, "/api/users/logout", map[string]string{"refresh_token": string(refresh)}, nil)
}

// Logout revokes the person's session at the gateway and removes the link. The link goes first, so
// a failing gateway never leaves the person linked; the error then says only the revocation failed.
func (u *UserClient) Logout(ctx context.Context) error {
	u.mu.Lock()
	defer u.mu.Unlock()
	acct, err := u.c.cfg.Store.Account(ctx, u.slackUserID)
	if errors.Is(err, store.ErrNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	if err := u.c.cfg.Store.DeleteAccount(ctx, u.slackUserID); err != nil {
		return err
	}
	u.c.drop(u.slackUserID)
	if err := u.c.revoke(ctx, acct.RefreshTokenEnc); err != nil {
		return fmt.Errorf("link removed, session not revoked: %w", err)
	}
	return nil
}

// token returns a usable access token, refreshing when it is missing or about to expire.
func (u *UserClient) token(ctx context.Context) (string, error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.access != "" && time.Until(u.expires) > expirySkew {
		return u.access, nil
	}
	return u.refreshLocked(ctx)
}

// stale marks a token the gateway refused. If another call already replaced it, nothing changes.
func (u *UserClient) stale(token string) {
	u.mu.Lock()
	if u.access == token {
		u.access = ""
	}
	u.mu.Unlock()
}

func (u *UserClient) refreshLocked(ctx context.Context) (string, error) {
	st, box := u.c.cfg.Store, u.c.cfg.Box
	acct, err := st.Account(ctx, u.slackUserID)
	if errors.Is(err, store.ErrNotFound) {
		return "", ErrNotLinked
	}
	if err != nil {
		return "", err
	}
	refresh, err := box.Open(acct.RefreshTokenEnc)
	if err != nil {
		return "", err // wrong key or damaged data: the link may be fine, so keep it
	}

	var t tokens
	err = u.c.post(ctx, "/api/users/refresh", map[string]string{"refresh_token": string(refresh)}, &t)
	var api *APIError
	if errors.As(err, &api) && api.Status == http.StatusUnauthorized {
		// Expired, revoked, or reused: the person has to link again.
		if derr := st.DeleteAccount(ctx, u.slackUserID); derr != nil {
			return "", derr
		}
		u.access = ""
		u.c.drop(u.slackUserID)
		return "", fmt.Errorf("%w: %w", ErrNotLinked, ErrUnauthorized)
	}
	if err != nil {
		return "", err
	}

	// The old refresh token is spent now. Store the new one before anything uses the access token.
	sealed, err := box.Seal([]byte(t.RefreshToken))
	if err != nil {
		return "", err
	}
	if err := st.UpdateRefreshToken(ctx, u.slackUserID, sealed); errors.Is(err, store.ErrNotFound) {
		return "", ErrNotLinked // unlinked while the refresh was in flight
	} else if err != nil {
		return "", fmt.Errorf("store rotated refresh token: %w", err)
	}
	u.access = t.AccessToken
	u.expires = time.Now().Add(time.Duration(t.ExpiresIn) * time.Second)
	return u.access, nil
}

// CreateSession opens a room; origin, when set, records the Slack thread it belongs to.
func (u *UserClient) CreateSession(ctx context.Context, text, provider string, origin *Origin) (Session, error) {
	body := map[string]any{"text": text}
	if provider != "" {
		body["provider"] = provider
	}
	if origin != nil {
		body["origin"] = origin
	}
	var s Session
	err := u.call(ctx, http.MethodPost, "/api/sessions", body, &s)
	return s, err
}

func (u *UserClient) Answer(ctx context.Context, id int64, text string) (Session, error) {
	var s Session
	err := u.call(ctx, http.MethodPost, sessionPath(id, "/answer"), map[string]string{"answer": text}, &s)
	return s, err
}

func (u *UserClient) FollowUp(ctx context.Context, id int64, text string) (Session, error) {
	var s Session
	err := u.call(ctx, http.MethodPost, sessionPath(id, "/messages"), map[string]string{"text": text}, &s)
	return s, err
}

func (u *UserClient) Get(ctx context.Context, id int64) (Session, error) {
	var s Session
	err := u.call(ctx, http.MethodGet, sessionPath(id, ""), nil, &s)
	return s, err
}

func (u *UserClient) Decision(ctx context.Context, id int64, approve bool) (Session, error) {
	var s Session
	err := u.call(ctx, http.MethodPost, sessionPath(id, "/decision"), map[string]bool{"approve": approve}, &s)
	return s, err
}

// Stop cancels a running turn (202, no body). A session that is not running is a conflict.
func (u *UserClient) Stop(ctx context.Context, id int64) error {
	return u.call(ctx, http.MethodPost, sessionPath(id, "/stop"), nil, nil)
}

func sessionPath(id int64, tail string) string {
	return "/api/sessions/" + strconv.FormatInt(id, 10) + tail
}

// call sends one request as this user and decodes a JSON answer into out (when not nil).
func (u *UserClient) call(ctx context.Context, method, path string, in, out any) error {
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	resp, err := u.send(ctx, method, path, in, "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// send makes an authorized request. A 401 means the access token died early (the gateway checks
// it, and a session can be revoked), so it refreshes once and tries again. The caller closes the
// body of a nil-error response; a non-2xx answer is returned as *APIError.
func (u *UserClient) send(ctx context.Context, method, path string, in any, accept string) (*http.Response, error) {
	payload, err := encode(in)
	if err != nil {
		return nil, err
	}
	for attempt := 0; ; attempt++ {
		tok, err := u.token(ctx)
		if err != nil {
			return nil, err
		}
		resp, err := u.c.do(ctx, method, path, payload, tok, accept)
		if err != nil {
			return nil, err
		}
		if resp.StatusCode == http.StatusUnauthorized && attempt == 0 {
			resp.Body.Close()
			u.stale(tok)
			continue
		}
		if resp.StatusCode/100 != 2 {
			defer resp.Body.Close()
			return nil, apiError(resp)
		}
		return resp, nil
	}
}

// post is an anonymous JSON call (redeem, refresh, logout): the credential is in the body.
func (c *Client) post(ctx context.Context, path string, in, out any) error {
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	payload, err := encode(in)
	if err != nil {
		return err
	}
	resp, err := c.do(ctx, http.MethodPost, path, payload, "", "")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		return apiError(resp)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func (c *Client) do(ctx context.Context, method, path string, payload []byte, bearer, accept string) (*http.Response, error) {
	var body io.Reader
	if payload != nil {
		body = bytes.NewReader(payload)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.cfg.BaseURL+path, body)
	if err != nil {
		return nil, err
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	if accept != "" {
		req.Header.Set("Accept", accept)
	}
	return c.cfg.HTTP.Do(req)
}

func encode(in any) ([]byte, error) {
	if in == nil {
		return nil, nil
	}
	return json.Marshal(in)
}

// UserID is the BOA account this client acts as.
func (u *UserClient) UserID() string { return u.userID }
