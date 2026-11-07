package slackio

import (
	"regexp"
	"strings"
)

// Slack sends message text in its own markup: links as <url|label>, mentions as <@U123>, and &, <, >
// escaped. The web sends what the person typed, and the router and agents read the text as it is,
// so the same request must reach the gateway the same way from both (an address written as
// <mailto:a@b.vn|a@b.vn> was read as unverified data and the run took another path).
var (
	slackToken = regexp.MustCompile(`<([^<>]*)>`)
	unescape   = strings.NewReplacer("&lt;", "<", "&gt;", ">", "&amp;", "&")
	// spaces left where a mention was cut out, kept to one so the sentence reads as typed
	gap = regexp.MustCompile(`[ \t]{2,}`)
)

// PlainText turns Slack markup back into the text the person typed.
func PlainText(s string) string {
	removed := false
	s = slackToken.ReplaceAllStringFunc(s, func(tok string) string {
		inner := tok[1 : len(tok)-1]
		target, label, hasLabel := strings.Cut(inner, "|")
		switch {
		case strings.HasPrefix(target, "@"), // a person: <@U123> or <@U123|name>
			strings.HasPrefix(target, "!") && !hasLabel: // <!here>, <!channel>, <!everyone>
			removed = true
			return ""
		case strings.HasPrefix(target, "!"): // <!subteam^S1|@team>, <!date^…|fallback>
			return label
		case strings.HasPrefix(target, "#"): // <#C123|general>
			if hasLabel {
				return "#" + label
			}
			removed = true
			return ""
		case !hasLabel:
			return target
		case sameLink(target, label):
			return label // Slack linked what the person typed: keep it as typed
		default:
			return label + " (" + target + ")"
		}
	})
	if removed {
		lines := strings.Split(s, "\n")
		for i, l := range lines {
			lines[i] = strings.TrimSpace(gap.ReplaceAllString(l, " "))
		}
		s = strings.Join(lines, "\n")
	}
	return strings.TrimSpace(unescape.Replace(s))
}

// sameLink reports whether label is the text Slack turned into target: an address or a bare domain.
func sameLink(target, label string) bool {
	for _, scheme := range []string{"mailto:", "tel:", "https://", "http://"} {
		if strings.TrimPrefix(target, scheme) == label {
			return true
		}
	}
	return target == label
}
