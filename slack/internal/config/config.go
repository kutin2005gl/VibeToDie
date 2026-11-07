// Package config reads the bot's settings from the environment.
package config

import (
	"errors"
	"strings"

	"nexus/slack/internal/secret"
)

type Config struct {
	BotToken    string // xoxb-...
	AppToken    string // xapp-... (Socket Mode)
	TokenKey    []byte // encrypts refresh tokens at rest
	DatabaseURL string
	NexusURL    string // gateway base URL, no trailing slash
	Provider    string // model provider sent with new sessions
	WebURL      string // BOA web base URL for "Mở trên web" links, no trailing slash; empty: no link
	DryRun      bool   // log instead of calling Slack
}

// Load reads the settings through getenv (os.Getenv in production). It reports every
// problem at once, so one start shows the whole list. Messages name the variable, never its value.
func Load(getenv func(string) string) (Config, error) {
	var problems []string
	need := func(key string) string {
		v := strings.TrimSpace(getenv(key))
		if v == "" {
			problems = append(problems, key+" is required")
		}
		return v
	}

	c := Config{
		DatabaseURL: need("SLACK_DATABASE_URL"),
		NexusURL:    strings.TrimRight(need("NEXUS_URL"), "/"),
		Provider:    strings.TrimSpace(getenv("NEXUS_PROVIDER")),
		WebURL:      strings.TrimRight(strings.TrimSpace(getenv("BOA_WEB_URL")), "/"),
		DryRun:      isTrue(getenv("SLACK_DRY_RUN")),
	}
	if c.Provider == "" {
		c.Provider = "anthropic"
	}
	if c.WebURL != "" && !strings.HasPrefix(c.WebURL, "http://") && !strings.HasPrefix(c.WebURL, "https://") {
		problems = append(problems, "BOA_WEB_URL must start with http:// or https://")
	}

	if keyText := need("SLACK_TOKEN_KEY"); keyText != "" {
		key, err := secret.ParseKey(keyText)
		if err != nil {
			problems = append(problems, "SLACK_TOKEN_KEY "+err.Error())
		}
		c.TokenKey = key
	}

	// Dry run never talks to Slack, so it needs neither token.
	if !c.DryRun {
		c.BotToken = need("SLACK_BOT_TOKEN")
		c.AppToken = need("SLACK_APP_TOKEN")
		if c.BotToken != "" && !strings.HasPrefix(c.BotToken, "xoxb-") {
			problems = append(problems, "SLACK_BOT_TOKEN must start with xoxb-")
		}
		if c.AppToken != "" && !strings.HasPrefix(c.AppToken, "xapp-") {
			problems = append(problems, "SLACK_APP_TOKEN must start with xapp-")
		}
	}

	if len(problems) > 0 {
		return Config{}, errors.New("invalid configuration: " + strings.Join(problems, "; "))
	}
	return c, nil
}

func isTrue(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}
