// Package store persists accounts and refresh tokens in PostgreSQL.
package store

import (
	"context"
	_ "embed"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"nexus/user-service/internal/user"
)

//go:embed schema.sql
var schema string

const columns = `id, email, name, departments, created_at`

type Store struct {
	pool *pgxpool.Pool
}

func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// Migrate applies schema.sql. Without arguments pgx sends it as one simple query, so the
// several statements in it run in order.
func (s *Store) Migrate(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, schema)
	return err
}

func (s *Store) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}

func (s *Store) CreateUser(ctx context.Context, email, name, passwordHash string, departments []string) (user.User, error) {
	if departments == nil {
		departments = []string{}
	}
	u, err := scan(s.pool.QueryRow(ctx,
		`INSERT INTO users (email, name, password_hash, departments) VALUES ($1, $2, $3, $4) RETURNING `+columns,
		email, name, passwordHash, departments))
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		return user.User{}, user.ErrEmailTaken
	}
	return u, err
}

// UserByEmail returns the account and its password hash, for sign-in.
func (s *Store) UserByEmail(ctx context.Context, email string) (user.User, string, error) {
	var u user.User
	var hash string
	err := s.pool.QueryRow(ctx, `SELECT `+columns+`, password_hash FROM users WHERE email = $1`, email).
		Scan(&u.ID, &u.Email, &u.Name, &u.Departments, &u.CreatedAt, &hash)
	if errors.Is(err, pgx.ErrNoRows) {
		return user.User{}, "", user.ErrNotFound
	}
	return u, hash, err
}

func (s *Store) UserByID(ctx context.Context, id string) (user.User, error) {
	return scan(s.pool.QueryRow(ctx, `SELECT `+columns+` FROM users WHERE id = $1`, id))
}

func (s *Store) ListUsers(ctx context.Context) ([]user.User, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+columns+` FROM users ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
	users := []user.User{}
	for rows.Next() {
		u, err := scan(rows)
		if err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, rows.Err()
}

func (s *Store) SetDepartments(ctx context.Context, id string, departments []string) (user.User, error) {
	if departments == nil {
		departments = []string{}
	}
	return scan(s.pool.QueryRow(ctx,
		`UPDATE users SET departments = $2, updated_at = now() WHERE id = $1 RETURNING `+columns,
		id, departments))
}

func (s *Store) CreateRefresh(ctx context.Context, userID, familyID, source string, hash []byte, expiresAt time.Time) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO refresh_tokens (user_id, family_id, source, token_hash, expires_at) VALUES ($1, $2, $3, $4, $5)`,
		userID, familyID, source, hash, expiresAt)
	return err
}

// RotateRefresh spends the token with oldHash and stores newHash in its family, returning the
// user id. A token already spent is a stolen copy or a replay: the whole family is revoked, so
// both the thief and the owner have to sign in again.
func (s *Store) RotateRefresh(ctx context.Context, oldHash, newHash []byte, expiresAt time.Time) (string, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)

	var id int64
	var userID, familyID, source string
	var expired, used, revoked bool
	err = tx.QueryRow(ctx,
		`SELECT id, user_id, family_id, source, expires_at <= now(), used_at IS NOT NULL, revoked_at IS NOT NULL
		 FROM refresh_tokens WHERE token_hash = $1 FOR UPDATE`, oldHash).
		Scan(&id, &userID, &familyID, &source, &expired, &used, &revoked)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", user.ErrInvalidToken
	}
	if err != nil {
		return "", err
	}
	if used && !revoked {
		if _, err := tx.Exec(ctx,
			`UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = $1 AND revoked_at IS NULL`, familyID); err != nil {
			return "", err
		}
		if err := tx.Commit(ctx); err != nil {
			return "", err
		}
		return "", user.ErrInvalidToken
	}
	if used || revoked || expired {
		return "", user.ErrInvalidToken
	}

	if _, err := tx.Exec(ctx, `UPDATE refresh_tokens SET used_at = now() WHERE id = $1`, id); err != nil {
		return "", err
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO refresh_tokens (user_id, family_id, source, token_hash, expires_at) VALUES ($1, $2, $3, $4, $5)`,
		userID, familyID, source, newHash, expiresAt); err != nil {
		return "", err
	}
	return userID, tx.Commit(ctx)
}

// RevokeFamily signs out the session the token belongs to. An unknown token is not an error.
func (s *Store) RevokeFamily(ctx context.Context, hash []byte) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE refresh_tokens SET revoked_at = now()
		 WHERE revoked_at IS NULL AND family_id = (SELECT family_id FROM refresh_tokens WHERE token_hash = $1)`, hash)
	return err
}

// SlackLinks returns the live Slack sign-ins of userID, oldest first, each with when it started and
// the Slack account the bot reported for it. A sign-in is live while its newest refresh token is
// unspent, unrevoked and unexpired.
func (s *Store) SlackLinks(ctx context.Context, userID string) ([]user.SlackLink, error) {
	rows, err := s.pool.Query(ctx,
		`SELECT f.started, a.slack_user_id, coalesce(a.user_name, ''), coalesce(a.real_name, ''), coalesce(a.team_id, ''), coalesce(a.team_domain, '')
		 FROM (SELECT family_id, min(created_at) AS started FROM refresh_tokens
		       WHERE family_id IN (
		         SELECT family_id FROM refresh_tokens
		         WHERE user_id = $1 AND source = 'slack' AND used_at IS NULL AND revoked_at IS NULL AND expires_at > now())
		       GROUP BY family_id) f
		 LEFT JOIN slack_accounts a ON a.family_id = f.family_id
		 ORDER BY f.started`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	links := []user.SlackLink{}
	for rows.Next() {
		var l user.SlackLink
		var slackID *string
		var acct user.SlackAccount
		if err := rows.Scan(&l.LinkedAt, &slackID, &acct.UserName, &acct.RealName, &acct.TeamID, &acct.TeamDomain); err != nil {
			return nil, err
		}
		if slackID != nil {
			acct.UserID = *slackID
			l.Account = &acct
		}
		links = append(links, l)
	}
	return links, rows.Err()
}

// SaveSlackAccount records which Slack account the sign-in familyID belongs to.
func (s *Store) SaveSlackAccount(ctx context.Context, familyID string, a user.SlackAccount) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO slack_accounts (family_id, slack_user_id, user_name, real_name, team_id, team_domain) VALUES ($1, $2, $3, $4, $5, $6)
		 ON CONFLICT (family_id) DO UPDATE SET slack_user_id = $2, user_name = $3, real_name = $4, team_id = $5, team_domain = $6`,
		familyID, a.UserID, a.UserName, a.RealName, a.TeamID, a.TeamDomain)
	return err
}

// RevokeSlackSessions signs out every Slack sign-in of userID; web sign-ins are untouched.
func (s *Store) RevokeSlackSessions(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE refresh_tokens SET revoked_at = now()
		 WHERE user_id = $1 AND source = 'slack' AND revoked_at IS NULL`, userID)
	return err
}

// CreateSlackLink stores the hash of a code that userID can redeem until expiresAt.
func (s *Store) CreateSlackLink(ctx context.Context, userID string, hash []byte, expiresAt time.Time) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO slack_link_codes (code_hash, user_id, expires_at) VALUES ($1, $2, $3)`,
		hash, userID, expiresAt)
	return err
}

// RedeemSlackLink spends the code and returns its user id. One statement, so two redeems of the
// same code can't both win.
func (s *Store) RedeemSlackLink(ctx context.Context, hash []byte) (string, error) {
	var userID string
	err := s.pool.QueryRow(ctx,
		`UPDATE slack_link_codes SET used_at = now()
		 WHERE code_hash = $1 AND used_at IS NULL AND expires_at > now() RETURNING user_id`, hash).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", user.ErrInvalidCode
	}
	return userID, err
}

func scan(row pgx.Row) (user.User, error) {
	var u user.User
	err := row.Scan(&u.ID, &u.Email, &u.Name, &u.Departments, &u.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return user.User{}, user.ErrNotFound
	}
	return u, err
}
