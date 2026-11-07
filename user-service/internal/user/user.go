// Package user holds the account model and the errors the store and handlers share.
package user

import (
	"errors"
	"time"
)

var (
	ErrNotFound     = errors.New("user not found")
	ErrEmailTaken   = errors.New("email already registered")
	ErrInvalidToken = errors.New("invalid refresh token")
	ErrInvalidCode  = errors.New("invalid or expired link code")
)

// User is an account. Departments are the requester's permissions everywhere behind the gateway
// (X-User-Departments); an account with none can sign in but reaches no department agent.
type User struct {
	ID          string    `json:"id"`
	Email       string    `json:"email"`
	Name        string    `json:"name"`
	Departments []string  `json:"departments"`
	CreatedAt   time.Time `json:"created_at"`
}

func (u User) In(department string) bool {
	for _, d := range u.Departments {
		if d == department {
			return true
		}
	}
	return false
}

// SlackAccount is the Slack account behind a Slack sign-in, as the bot reported it when it
// redeemed the link code. It is for display only: the code, not these fields, is the credential.
type SlackAccount struct {
	UserID     string `json:"slack_user_id"`
	UserName   string `json:"user_name,omitempty"`
	RealName   string `json:"real_name,omitempty"`
	TeamID     string `json:"team_id,omitempty"`
	TeamDomain string `json:"team_domain,omitempty"`
}

// SlackLink is one live Slack sign-in. Account is nil for links made before the bot reported it.
type SlackLink struct {
	LinkedAt time.Time     `json:"linked_at"`
	Account  *SlackAccount `json:"account,omitempty"`
}
