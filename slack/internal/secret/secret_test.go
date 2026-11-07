package secret

import (
	"bytes"
	"encoding/base64"
	"errors"
	"testing"
)

func box(t *testing.T, fill byte) *Box {
	t.Helper()
	b, err := New(bytes.Repeat([]byte{fill}, keySize))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestRoundTrip(t *testing.T) {
	b := box(t, 1)
	sealed, err := b.Seal([]byte("refresh-token"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(sealed, []byte("refresh-token")) {
		t.Fatal("plaintext visible in sealed data")
	}
	got, err := b.Open(sealed)
	if err != nil || string(got) != "refresh-token" {
		t.Fatalf("Open = %q, %v", got, err)
	}
}

func TestSealUsesFreshNonce(t *testing.T) {
	b := box(t, 1)
	a, _ := b.Seal([]byte("x"))
	c, _ := b.Seal([]byte("x"))
	if bytes.Equal(a, c) {
		t.Fatal("two seals of the same value are identical")
	}
}

func TestWrongKey(t *testing.T) {
	sealed, _ := box(t, 1).Seal([]byte("x"))
	if _, err := box(t, 2).Open(sealed); !errors.Is(err, ErrDecrypt) {
		t.Fatalf("err = %v, want ErrDecrypt", err)
	}
}

func TestTamperedAndShort(t *testing.T) {
	b := box(t, 1)
	sealed, _ := b.Seal([]byte("x"))
	sealed[len(sealed)-1] ^= 1
	if _, err := b.Open(sealed); !errors.Is(err, ErrDecrypt) {
		t.Fatalf("tampered: err = %v", err)
	}
	if _, err := b.Open([]byte("short")); !errors.Is(err, ErrDecrypt) {
		t.Fatalf("short: err = %v", err)
	}
}

func TestParseKey(t *testing.T) {
	good := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{7}, keySize))
	if _, err := ParseKey(good); err != nil {
		t.Fatal(err)
	}
	for name, in := range map[string]string{
		"not base64": "***",
		"too short":  base64.StdEncoding.EncodeToString([]byte("short")),
		"empty":      "",
	} {
		if _, err := ParseKey(in); err == nil {
			t.Errorf("%s: want error", name)
		}
	}
	if _, err := New([]byte("short")); err == nil {
		t.Error("New accepted a short key")
	}
}
