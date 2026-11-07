// Package auth verifies the access tokens user-service signs (HS256, shared secret).
package auth

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

var ErrInvalidToken = errors.New("invalid token")

// Claims user-service puts in an access token. Subject is the user id.
type Claims struct {
	Email       string   `json:"email,omitempty"`
	Departments []string `json:"departments"`
	jwt.RegisteredClaims
}

type JWTService struct {
	secret []byte
	issuer string
}

func NewJWTService(secret, issuer string) *JWTService {
	return &JWTService{secret: []byte(secret), issuer: issuer}
}

// Verify checks the signing method, signature, expiry and issuer.
func (j *JWTService) Verify(token string) (*Claims, error) {
	claims := &Claims{}
	parser := jwt.NewParser(
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithExpirationRequired(),
		jwt.WithIssuer(j.issuer),
	)
	parsed, err := parser.ParseWithClaims(token, claims, func(*jwt.Token) (any, error) { return j.secret, nil })
	if err != nil || !parsed.Valid || claims.Subject == "" {
		return nil, ErrInvalidToken
	}
	return claims, nil
}

// Sign issues a token; only tests and cmd/devtoken use it, user-service signs the real ones.
func (j *JWTService) Sign(subject, email string, departments []string, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := Claims{
		Email:       email,
		Departments: departments,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   subject,
			Issuer:    j.issuer,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(j.secret)
}
