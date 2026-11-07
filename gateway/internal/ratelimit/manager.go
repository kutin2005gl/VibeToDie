// Package ratelimit keeps one token bucket per key and evicts idle ones.
package ratelimit

import (
	"sync"
	"time"

	"golang.org/x/time/rate"
)

type entry struct {
	limiter  *rate.Limiter
	lastSeen time.Time
}

type Manager struct {
	mu      sync.Mutex
	entries map[string]*entry
}

func NewManager() *Manager {
	return &Manager{entries: make(map[string]*entry)}
}

// Get returns the bucket for key, creating it on first use.
func (m *Manager) Get(key string, limit rate.Limit, burst int) *rate.Limiter {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.entries[key]
	if !ok {
		e = &entry{limiter: rate.NewLimiter(limit, burst)}
		m.entries[key] = e
	}
	e.lastSeen = time.Now()
	return e.limiter
}

// Cleanup drops buckets idle longer than idle, so one-off IPs don't grow the map forever.
func (m *Manager) Cleanup(idle time.Duration) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	removed := 0
	for k, e := range m.entries {
		if time.Since(e.lastSeen) > idle {
			delete(m.entries, k)
			removed++
		}
	}
	return removed
}

// StartCleanup runs Cleanup every interval until stop is closed.
func (m *Manager) StartCleanup(interval, idle time.Duration, stop <-chan struct{}) {
	go func() {
		t := time.NewTicker(interval)
		defer t.Stop()
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				m.Cleanup(idle)
			}
		}
	}()
}
