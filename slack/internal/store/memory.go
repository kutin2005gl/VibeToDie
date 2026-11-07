package store

import (
	"context"
	"sync"
	"time"
)

// Memory is an in-process Store for tests of the packages above it.
type Memory struct {
	mu       sync.Mutex
	accounts map[string]Account
	threads  map[[2]string]Thread
	handled  map[[2]string]bool
}

func NewMemory() *Memory {
	return &Memory{
		accounts: map[string]Account{},
		threads:  map[[2]string]Thread{},
		handled:  map[[2]string]bool{},
	}
}

func (m *Memory) SaveAccount(_ context.Context, a Account) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	a.RefreshTokenEnc = append([]byte(nil), a.RefreshTokenEnc...)
	a.LinkedAt = time.Now()
	m.accounts[a.SlackUserID] = a
	return nil
}

func (m *Memory) Account(_ context.Context, slackUserID string) (Account, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	a, ok := m.accounts[slackUserID]
	if !ok {
		return Account{}, ErrNotFound
	}
	a.RefreshTokenEnc = append([]byte(nil), a.RefreshTokenEnc...)
	return a, nil
}

func (m *Memory) UpdateRefreshToken(_ context.Context, slackUserID string, enc []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	a, ok := m.accounts[slackUserID]
	if !ok {
		return ErrNotFound
	}
	a.RefreshTokenEnc = append([]byte(nil), enc...)
	m.accounts[slackUserID] = a
	return nil
}

func (m *Memory) DeleteAccount(_ context.Context, slackUserID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.accounts, slackUserID)
	return nil
}

func (m *Memory) SaveThread(_ context.Context, t Thread) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	t.UpdatedAt = time.Now()
	m.threads[[2]string{t.Channel, t.ThreadTS}] = t
	return nil
}

func (m *Memory) Thread(_ context.Context, channel, threadTS string) (Thread, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.threads[[2]string{channel, threadTS}]
	if !ok {
		return Thread{}, ErrNotFound
	}
	return t, nil
}

func (m *Memory) MarkHandled(_ context.Context, channel, ts string) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	k := [2]string{channel, ts}
	if m.handled[k] {
		return false, nil
	}
	m.handled[k] = true
	return true, nil
}
