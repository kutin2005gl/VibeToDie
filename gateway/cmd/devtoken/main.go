// devtoken prints an access token signed with JWT_SECRET, for calling the gateway before
// user-service exists. Dev only: user-service signs the real tokens.
//
//	JWT_SECRET=... JWT_ISSUER=nexus go run ./cmd/devtoken -sub u1 -departments cskh
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"nexus/gateway/internal/auth"
)

func main() {
	sub := flag.String("sub", "dev-user", "user id (sub)")
	email := flag.String("email", "", "email")
	departments := flag.String("departments", "cskh", "comma-separated departments")
	ttl := flag.Duration("ttl", time.Hour, "lifetime")
	flag.Parse()

	secret, issuer := os.Getenv("JWT_SECRET"), os.Getenv("JWT_ISSUER")
	if secret == "" || issuer == "" {
		fmt.Fprintln(os.Stderr, "JWT_SECRET and JWT_ISSUER are required")
		os.Exit(1)
	}
	var depts []string
	for _, d := range strings.Split(*departments, ",") {
		if d = strings.TrimSpace(d); d != "" {
			depts = append(depts, d)
		}
	}
	token, err := auth.NewJWTService(secret, issuer).Sign(*sub, *email, depts, *ttl)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println(token)
}
