package password

import (
	"strings"
	"testing"
)

func TestHashVerify(t *testing.T) {
	h, err := Hash("correct horse")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(h, "$argon2id$v=19$m=19456,t=2,p=1$") {
		t.Fatalf("unexpected format %s", h)
	}
	if !Verify(h, "correct horse") {
		t.Fatal("right password rejected")
	}
	if Verify(h, "wrong horse") {
		t.Fatal("wrong password accepted")
	}
	if h2, _ := Hash("correct horse"); h2 == h {
		t.Fatal("same salt twice")
	}
}

func TestVerifyRejectsMalformed(t *testing.T) {
	for _, h := range []string{"", "plain", "$argon2i$v=19$m=1,t=1,p=1$AA$AA", "$argon2id$v=19$m=0,t=1,p=1$AA$AA", "$argon2id$v=19$m=1,t=1,p=1$!!$AA"} {
		if Verify(h, "x") {
			t.Errorf("%q matched", h)
		}
	}
}
