package nexus

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

var (
	// ErrNotLinked means the Slack user has no linked account (never linked, unlinked, or the
	// refresh token was refused and the link was removed).
	ErrNotLinked = errors.New("nexus: slack user is not linked")
	// ErrInvalidCode means a link code was wrong, expired or already used.
	ErrInvalidCode = errors.New("nexus: link code is invalid, expired or already used")

	// The HTTP statuses the bridge reacts to.
	ErrUnauthorized = errors.New("nexus: unauthorized")
	ErrNotFound     = errors.New("nexus: not found")
	ErrConflict     = errors.New("nexus: conflict")
)

// roomFull is the detail ai-service gives when a room has used up its turns.
const roomFull = "room is full"

// APIError is a non-2xx answer from the gateway. It unwraps to ErrUnauthorized, ErrNotFound or
// ErrConflict for 401, 404 and 409; other statuses have no sentinel.
type APIError struct {
	Status int
	Detail string
}

func (e *APIError) Error() string {
	if e.Detail == "" {
		return fmt.Sprintf("nexus: gateway answered %d", e.Status)
	}
	return fmt.Sprintf("nexus: gateway answered %d: %s", e.Status, e.Detail)
}

func (e *APIError) Unwrap() error {
	switch e.Status {
	case http.StatusUnauthorized:
		return ErrUnauthorized
	case http.StatusNotFound:
		return ErrNotFound
	case http.StatusConflict:
		return ErrConflict
	}
	return nil
}

// IsRoomFull reports a 409 because the room reached its turn limit; the bridge opens a new session.
func IsRoomFull(err error) bool {
	var api *APIError
	// ai-service says "room is full: start a new room"; match its start, so a reworded hint still counts
	return errors.As(err, &api) && api.Status == http.StatusConflict &&
		strings.HasPrefix(strings.ToLower(api.Detail), roomFull)
}

// apiError reads an error body. FastAPI sends {"detail": ...}, the Go services {"error": ...}.
func apiError(resp *http.Response) *APIError {
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	e := &APIError{Status: resp.StatusCode}
	var body struct {
		Detail json.RawMessage `json:"detail"`
		Error  string          `json:"error"`
	}
	if json.Unmarshal(raw, &body) != nil {
		return e
	}
	e.Detail = body.Error
	if len(body.Detail) > 0 {
		var text string
		if json.Unmarshal(body.Detail, &text) == nil {
			e.Detail = text
		} else {
			e.Detail = string(body.Detail) // validation errors come as a list
		}
	}
	return e
}
