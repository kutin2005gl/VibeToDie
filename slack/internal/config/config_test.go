package config

import (
	"bytes"
	"encoding/base64"
	"strings"
	"testing"
)

func env(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

func valid() map[string]string {
	return map[string]string{
		"SLACK_BOT_TOKEN":    "xoxb-1",
		"SLACK_APP_TOKEN":    "xapp-1",
		"SLACK_TOKEN_KEY":    base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32)),
		"SLACK_DATABASE_URL": "postgres://x",
		"NEXUS_URL":          "http://gateway:8080/",
	}
}

func TestLoadValid(t *testing.T) {
	c, err := Load(env(valid()))
	if err != nil {
		t.Fatal(err)
	}
	if c.NexusURL != "http://gateway:8080" {
		t.Errorf("NexusURL = %q, trailing slash kept", c.NexusURL)
	}
	if c.Provider != "anthropic" || c.DryRun || len(c.TokenKey) != 32 || c.WebURL != "" {
		t.Errorf("defaults wrong: %+v", c)
	}
}

func TestWebURLIsOptionalAndTrimmed(t *testing.T) {
	m := valid()
	m["BOA_WEB_URL"] = " https://boa.example.com/ "
	c, err := Load(env(m))
	if err != nil || c.WebURL != "https://boa.example.com" {
		t.Fatalf("WebURL = %q, err %v", c.WebURL, err)
	}
}

func TestLoadReportsEveryMissingValue(t *testing.T) {
	_, err := Load(env(nil))
	if err == nil {
		t.Fatal("want error")
	}
	for _, k := range []string{"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_TOKEN_KEY", "SLACK_DATABASE_URL", "NEXUS_URL"} {
		if !strings.Contains(err.Error(), k) {
			t.Errorf("error does not mention %s: %v", k, err)
		}
	}
}

func TestLoadRejectsBadValues(t *testing.T) {
	cases := map[string]struct{ key, val, want string }{
		"bot prefix": {"SLACK_BOT_TOKEN", "xapp-1", "xoxb-"},
		"app prefix": {"SLACK_APP_TOKEN", "xoxb-1", "xapp-"},
		"key size":   {"SLACK_TOKEN_KEY", base64.StdEncoding.EncodeToString([]byte("short")), "32 bytes"},
		"key text":   {"SLACK_TOKEN_KEY", "***", "base64"},
		"web url":    {"BOA_WEB_URL", "boa.example.com", "http"},
	}
	for name, tc := range cases {
		m := valid()
		m[tc.key] = tc.val
		if _, err := Load(env(m)); err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s: err = %v, want mention of %q", name, err, tc.want)
		}
	}
}

func TestDryRunNeedsNoSlackTokens(t *testing.T) {
	m := valid()
	delete(m, "SLACK_BOT_TOKEN")
	delete(m, "SLACK_APP_TOKEN")
	m["SLACK_DRY_RUN"] = "1"
	m["NEXUS_PROVIDER"] = "fake"
	c, err := Load(env(m))
	if err != nil {
		t.Fatal(err)
	}
	if !c.DryRun || c.Provider != "fake" {
		t.Errorf("got %+v", c)
	}
}

func TestErrorNeverEchoesSecrets(t *testing.T) {
	m := valid()
	m["SLACK_BOT_TOKEN"] = "xoxb-supersecret"
	m["SLACK_APP_TOKEN"] = "bad-supersecret"
	_, err := Load(env(m))
	if err == nil || strings.Contains(err.Error(), "supersecret") {
		t.Fatalf("err = %v", err)
	}
}
