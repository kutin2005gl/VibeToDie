// Package token issues the access tokens the gateway verifies and the opaque refresh tokens that
// renew them.
package token

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Claims match the gateway's auth.Claims: it forwards sub as X-User-Id, email as X-User-Email
// and departments (comma-joined) as X-User-Departments. Name is for display only.
type Claims struct {
	Email       string   `json:"email,omitempty"`
	Name        string   `json:"name,omitempty"`
	Departments []string `json:"departments"`
	jwt.RegisteredClaims
}

type Issuer struct {
	secret []byte
	issuer string
	ttl    time.Duration
	now    func() time.Time
}

// NewIssuer applies the gateway's own rule: it refuses to start with a secret under 32 characters.
func NewIssuer(secret, issuer string, ttl time.Duration) (*Issuer, error) {
	if len(secret) < 32 {
		return nil, errors.New("JWT_SECRET must be at least 32 characters")
	}
	if issuer == "" {
		return nil, errors.New("JWT_ISSUER is required")
	}
	if ttl <= 0 {
		return nil, errors.New("access token TTL must be positive")
	}
	return &Issuer{secret: []byte(secret), issuer: issuer, ttl: ttl, now: time.Now}, nil
}

func (i *Issuer) TTL() time.Duration { return i.ttl }

// Issue signs an HS256 access token for one user.
func (i *Issuer) Issue(id, email, name string, departments []string) (string, error) {
	if departments == nil {
		departments = []string{}
	}
	now := i.now()
	claims := Claims{
		Email:       email,
		Name:        name,
		Departments: departments,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   id,
			Issuer:    i.issuer,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(i.ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(i.secret)
}

// NewRefresh returns a random refresh token and its SHA-256, the only form the database keeps.
func NewRefresh() (string, []byte, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", nil, err
	}
	t := base64.RawURLEncoding.EncodeToString(b)
	return t, HashRefresh(t), nil
}

func HashRefresh(t string) []byte {
	sum := sha256.Sum256([]byte(t))
	return sum[:]
}

// NewFamily names a sign-in: every refresh token rotated from it shares the id, so reuse of an
// old one can revoke the whole chain.
func NewFamily() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// linkAlphabet leaves out 0/O and 1/I: the code is read off a screen and typed into Slack.
const linkAlphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

const linkCodeLen = 10

// NewLinkCode returns a random one-time code (50 bits) and its SHA-256, the only form the
// database keeps.
func NewLinkCode() (string, []byte, error) {
	b := make([]byte, linkCodeLen)
	if _, err := rand.Read(b); err != nil {
		return "", nil, err
	}
	code := make([]byte, linkCodeLen)
	for i, v := range b {
		code[i] = linkAlphabet[int(v)%len(linkAlphabet)] // 256 is a multiple of 32: no bias
	}
	return string(code), HashLinkCode(string(code)), nil
}

// HashLinkCode hashes a code as typed: case, spaces and dashes don't matter.
func HashLinkCode(code string) []byte {
	clean := strings.NewReplacer(" ", "", "-", "").Replace(strings.ToUpper(code))
	sum := sha256.Sum256([]byte(clean))
	return sum[:]
}
