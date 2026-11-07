// Package store persists the bot's state: linked accounts, threads and handled events.
package store

import (
	"context"
	_ "embed"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed schema.sql
var schema string

var ErrNotFound = errors.New("store: not found")

// Account links a Slack user to a Nexus user. RefreshTokenEnc is already sealed by package secret.
type Account struct {
	SlackUserID     string
	UserID          string
	RefreshTokenEnc []byte
	LinkedAt        time.Time
}

// Thread ties a Slack thread to a session. State is whatever the bridge last saw
// (for example "waiting"); the store does not interpret it.
type Thread struct {
	Channel   string
	ThreadTS  string
	SessionID string
	UserID    string
	State     string
	UpdatedAt time.Time
}

// Store is what the bridge needs. Postgres is the real one; Memory serves tests.
type Store interface {
	// SaveAccount links (or relinks) a Slack user, replacing any earlier link.
	SaveAccount(ctx context.Context, a Account) error
	Account(ctx context.Context, slackUserID string) (Account, error)
	// UpdateRefreshToken replaces the sealed token after a rotation.
	UpdateRefreshToken(ctx context.Context, slackUserID string, enc []byte) error
	DeleteAccount(ctx context.Context, slackUserID string) error

	// SaveThread inserts or replaces the thread's row.
	SaveThread(ctx context.Context, t Thread) error
	Thread(ctx context.Context, channel, threadTS string) (Thread, error)

	// MarkHandled records an event and reports whether this call was the first to see it.
	MarkHandled(ctx context.Context, channel, ts string) (first bool, err error)
}

type Postgres struct {
	pool *pgxpool.Pool
}

func New(pool *pgxpool.Pool) *Postgres {
	return &Postgres{pool: pool}
}

// Migrate applies schema.sql. Without arguments pgx sends it as one simple query, so the
// several statements in it run in order.
func (s *Postgres) Migrate(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, schema)
	return err
}

func (s *Postgres) SaveAccount(ctx context.Context, a Account) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO slack_accounts (slack_user_id, user_id, refresh_token_enc) VALUES ($1, $2, $3)
		 ON CONFLICT (slack_user_id) DO UPDATE
		 SET user_id = EXCLUDED.user_id, refresh_token_enc = EXCLUDED.refresh_token_enc, linked_at = now()`,
		a.SlackUserID, a.UserID, a.RefreshTokenEnc)
	return err
}

func (s *Postgres) Account(ctx context.Context, slackUserID string) (Account, error) {
	var a Account
	err := s.pool.QueryRow(ctx,
		`SELECT slack_user_id, user_id, refresh_token_enc, linked_at FROM slack_accounts WHERE slack_user_id = $1`,
		slackUserID).Scan(&a.SlackUserID, &a.UserID, &a.RefreshTokenEnc, &a.LinkedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Account{}, ErrNotFound
	}
	return a, err
}

func (s *Postgres) UpdateRefreshToken(ctx context.Context, slackUserID string, enc []byte) error {
	tag, err := s.pool.Exec(ctx,
		`UPDATE slack_accounts SET refresh_token_enc = $2 WHERE slack_user_id = $1`, slackUserID, enc)
	if err == nil && tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return err
}

func (s *Postgres) DeleteAccount(ctx context.Context, slackUserID string) error {
	_, err := s.pool.Exec(ctx, `DELETE FROM slack_accounts WHERE slack_user_id = $1`, slackUserID)
	return err
}

func (s *Postgres) SaveThread(ctx context.Context, t Thread) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO slack_threads (channel, thread_ts, session_id, user_id, state) VALUES ($1, $2, $3, $4, $5)
		 ON CONFLICT (channel, thread_ts) DO UPDATE
		 SET session_id = EXCLUDED.session_id, user_id = EXCLUDED.user_id, state = EXCLUDED.state, updated_at = now()`,
		t.Channel, t.ThreadTS, t.SessionID, t.UserID, t.State)
	return err
}

func (s *Postgres) Thread(ctx context.Context, channel, threadTS string) (Thread, error) {
	var t Thread
	err := s.pool.QueryRow(ctx,
		`SELECT channel, thread_ts, session_id, user_id, state, updated_at FROM slack_threads
		 WHERE channel = $1 AND thread_ts = $2`, channel, threadTS).
		Scan(&t.Channel, &t.ThreadTS, &t.SessionID, &t.UserID, &t.State, &t.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Thread{}, ErrNotFound
	}
	return t, err
}

func (s *Postgres) MarkHandled(ctx context.Context, channel, ts string) (bool, error) {
	tag, err := s.pool.Exec(ctx,
		`INSERT INTO slack_handled (channel, ts) VALUES ($1, $2) ON CONFLICT DO NOTHING`, channel, ts)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() == 1, nil
}
