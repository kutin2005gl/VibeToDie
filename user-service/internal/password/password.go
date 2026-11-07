// Package password hashes passwords with argon2id in the PHC string format, so the parameters
// travel with the hash and can be raised later without breaking existing accounts.
package password

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	"golang.org/x/crypto/argon2"
)

// OWASP's argon2id minimum: 19 MiB, 2 passes, 1 lane.
const (
	memory  = 19 * 1024
	passes  = 2
	threads = 1
	keyLen  = 32
	saltLen = 16
)

var b64 = base64.RawStdEncoding

func Hash(password string) (string, error) {
	salt := make([]byte, saltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	key := argon2.IDKey([]byte(password), salt, passes, memory, threads, keyLen)
	return fmt.Sprintf("$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argon2.Version, memory, passes, threads, b64.EncodeToString(salt), b64.EncodeToString(key)), nil
}

// Verify reports whether password matches encoded. A malformed hash never matches.
func Verify(encoded, password string) bool {
	salt, key, m, t, p, err := decode(encoded)
	if err != nil {
		return false
	}
	got := argon2.IDKey([]byte(password), salt, t, m, p, uint32(len(key)))
	return subtle.ConstantTimeCompare(got, key) == 1
}

func decode(encoded string) (salt, key []byte, m, t uint32, p uint8, err error) {
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[1] != "argon2id" {
		return nil, nil, 0, 0, 0, errors.New("not an argon2id hash")
	}
	var v int
	if _, err = fmt.Sscanf(parts[2], "v=%d", &v); err != nil || v != argon2.Version {
		return nil, nil, 0, 0, 0, errors.New("unsupported argon2 version")
	}
	if _, err = fmt.Sscanf(parts[3], "m=%d,t=%d,p=%d", &m, &t, &p); err != nil || m == 0 || t == 0 || p == 0 {
		return nil, nil, 0, 0, 0, errors.New("bad argon2 parameters")
	}
	if salt, err = b64.DecodeString(parts[4]); err != nil {
		return nil, nil, 0, 0, 0, err
	}
	if key, err = b64.DecodeString(parts[5]); err != nil || len(key) == 0 {
		return nil, nil, 0, 0, 0, errors.New("bad argon2 key")
	}
	return salt, key, m, t, p, nil
}
