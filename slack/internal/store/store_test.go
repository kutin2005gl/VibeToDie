package store

import (
	"context"
	"errors"
	"os"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The same contract runs against both implementations. The Postgres run needs
// SLACK_TEST_DATABASE_URL (a throwaway database; the tables are emptied) and is skipped without it.
func TestStores(t *testing.T) {
	t.Run("memory", func(t *testing.T) { contract(t, NewMemory()) })
	t.Run("postgres", func(t *testing.T) {
		url := os.Getenv("SLACK_TEST_DATABASE_URL")
		if url == "" {
			t.Skip("SLACK_TEST_DATABASE_URL not set")
		}
		ctx := context.Background()
		pool, err := pgxpool.New(ctx, url)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(pool.Close)
		pg := New(pool)
		if err := pg.Migrate(ctx); err != nil {
			t.Fatal(err)
		}
		// Migrate is idempotent: a second run must not fail.
		if err := pg.Migrate(ctx); err != nil {
			t.Fatalf("second Migrate: %v", err)
		}
		if _, err := pool.Exec(ctx, `TRUNCATE slack_accounts, slack_threads, slack_handled`); err != nil {
			t.Fatal(err)
		}
		contract(t, pg)
	})
}

func contract(t *testing.T, s Store) {
	ctx := context.Background()

	t.Run("account", func(t *testing.T) {
		if _, err := s.Account(ctx, "U1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("missing account: err = %v", err)
		}
		if err := s.SaveAccount(ctx, Account{SlackUserID: "U1", UserID: "user-1", RefreshTokenEnc: []byte("a")}); err != nil {
			t.Fatal(err)
		}
		if err := s.SaveAccount(ctx, Account{SlackUserID: "U2", UserID: "user-2", RefreshTokenEnc: []byte("b")}); err != nil {
			t.Fatal(err)
		}
		a, err := s.Account(ctx, "U1")
		if err != nil || a.UserID != "user-1" || string(a.RefreshTokenEnc) != "a" || a.LinkedAt.IsZero() {
			t.Fatalf("Account = %+v, %v", a, err)
		}

		if err := s.UpdateRefreshToken(ctx, "U1", []byte("a2")); err != nil {
			t.Fatal(err)
		}
		a, _ = s.Account(ctx, "U1")
		b, _ := s.Account(ctx, "U2")
		if string(a.RefreshTokenEnc) != "a2" || string(b.RefreshTokenEnc) != "b" {
			t.Fatalf("update leaked: U1=%q U2=%q", a.RefreshTokenEnc, b.RefreshTokenEnc)
		}
		if err := s.UpdateRefreshToken(ctx, "nobody", []byte("x")); !errors.Is(err, ErrNotFound) {
			t.Fatalf("update of unlinked user: err = %v", err)
		}

		// Relinking replaces the old link.
		if err := s.SaveAccount(ctx, Account{SlackUserID: "U1", UserID: "user-9", RefreshTokenEnc: []byte("c")}); err != nil {
			t.Fatal(err)
		}
		a, _ = s.Account(ctx, "U1")
		if a.UserID != "user-9" || string(a.RefreshTokenEnc) != "c" {
			t.Fatalf("relink: %+v", a)
		}

		if err := s.DeleteAccount(ctx, "U1"); err != nil {
			t.Fatal(err)
		}
		if _, err := s.Account(ctx, "U1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("after delete: err = %v", err)
		}
		if _, err := s.Account(ctx, "U2"); err != nil {
			t.Fatalf("delete removed another user: %v", err)
		}
		if err := s.DeleteAccount(ctx, "U1"); err != nil {
			t.Fatalf("delete of missing account: %v", err)
		}
	})

	t.Run("thread", func(t *testing.T) {
		if _, err := s.Thread(ctx, "C1", "1.1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("missing thread: err = %v", err)
		}
		th := Thread{Channel: "C1", ThreadTS: "1.1", SessionID: "s1", UserID: "user-1", State: "running"}
		if err := s.SaveThread(ctx, th); err != nil {
			t.Fatal(err)
		}
		other := Thread{Channel: "C1", ThreadTS: "1.2", SessionID: "s2", UserID: "user-1"}
		if err := s.SaveThread(ctx, other); err != nil {
			t.Fatal(err)
		}
		got, err := s.Thread(ctx, "C1", "1.1")
		if err != nil || got.SessionID != "s1" || got.State != "running" || got.UpdatedAt.IsZero() {
			t.Fatalf("Thread = %+v, %v", got, err)
		}

		th.State = "waiting"
		if err := s.SaveThread(ctx, th); err != nil {
			t.Fatal(err)
		}
		got, _ = s.Thread(ctx, "C1", "1.1")
		o, _ := s.Thread(ctx, "C1", "1.2")
		if got.State != "waiting" || o.State != "" {
			t.Fatalf("state: got %q, other %q", got.State, o.State)
		}
		// Same ts in another channel is a different thread.
		if _, err := s.Thread(ctx, "C2", "1.1"); !errors.Is(err, ErrNotFound) {
			t.Fatalf("other channel: err = %v", err)
		}
	})

	t.Run("handled", func(t *testing.T) {
		first, err := s.MarkHandled(ctx, "C1", "9.1")
		if err != nil || !first {
			t.Fatalf("first = %v, %v", first, err)
		}
		again, err := s.MarkHandled(ctx, "C1", "9.1")
		if err != nil || again {
			t.Fatalf("duplicate: first = %v, %v", again, err)
		}
		if ok, _ := s.MarkHandled(ctx, "C2", "9.1"); !ok {
			t.Fatal("same ts in another channel was treated as a duplicate")
		}
	})

	t.Run("handled is first for exactly one concurrent caller", func(t *testing.T) {
		var wins atomic.Int32
		var wg sync.WaitGroup
		for range 8 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if ok, err := s.MarkHandled(ctx, "C1", "race.1"); err == nil && ok {
					wins.Add(1)
				}
			}()
		}
		wg.Wait()
		if wins.Load() != 1 {
			t.Fatalf("%d callers saw the event as first, want 1", wins.Load())
		}
	})
}
