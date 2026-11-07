package nexus

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
)

var errStreamEnded = errors.New("nexus: stream ended without a session event")

// Wait follows a run until the session stops running and returns it. It reads the SSE stream and
// passes each progress event to onEvent (may be nil); the stream ends with the `session` event.
// If the stream is unavailable or drops early, it polls Get every PollEvery. It gives up after MaxWait.
func (u *UserClient) Wait(ctx context.Context, id int64, onEvent func(Event)) (Session, error) {
	ctx, cancel := context.WithTimeout(ctx, u.c.cfg.MaxWait)
	defer cancel()

	s, err := u.stream(ctx, id, onEvent)
	if err == nil {
		return s, nil
	}
	if errors.Is(err, ErrNotFound) || errors.Is(err, ErrNotLinked) || ctx.Err() != nil {
		return Session{}, err
	}
	return u.poll(ctx, id)
}

func (u *UserClient) stream(ctx context.Context, id int64, onEvent func(Event)) (Session, error) {
	resp, err := u.send(ctx, http.MethodGet, sessionPath(id, "/events"), nil, "text/event-stream")
	if err != nil {
		return Session{}, err
	}
	defer resp.Body.Close()

	r := bufio.NewReader(resp.Body)
	var name string
	var data []string
	for {
		line, readErr := r.ReadString('\n')
		line = strings.TrimRight(line, "\r\n")
		switch {
		case line == "":
			// A blank line ends an event. A ping is a comment, so it leaves no name behind.
			if name != "" {
				payload := []byte(strings.Join(data, "\n"))
				if name == "session" {
					var s Session
					if err := json.Unmarshal(payload, &s); err != nil {
						return Session{}, err
					}
					return s, nil
				}
				if onEvent != nil {
					onEvent(Event{Name: name, Data: payload})
				}
			}
			name, data = "", nil
		case strings.HasPrefix(line, ":"): // comment, e.g. ": ping"
		case strings.HasPrefix(line, "event:"):
			name = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		case strings.HasPrefix(line, "data:"):
			data = append(data, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
		}
		if readErr != nil {
			if readErr == io.EOF {
				return Session{}, errStreamEnded
			}
			return Session{}, readErr
		}
	}
}

func (u *UserClient) poll(ctx context.Context, id int64) (Session, error) {
	tick := time.NewTicker(u.c.cfg.PollEvery)
	defer tick.Stop()
	for {
		s, err := u.Get(ctx, id)
		switch {
		case err == nil && s.Status != StatusRunning:
			return s, nil
		case errors.Is(err, ErrNotFound), errors.Is(err, ErrNotLinked):
			return Session{}, err
		}
		// Other errors (a blip at the gateway) are retried on the next tick until MaxWait.
		select {
		case <-ctx.Done():
			return Session{}, ctx.Err()
		case <-tick.C:
		}
	}
}
