package render

import (
	"encoding/json"
	"regexp"
	"strconv"
	"strings"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/slackio"
)

// Answer is an agent's reply as staff read it, built from `result` (the checked final_answer) the
// way answerParts in frontend/src/api/sessions.ts builds it. `output` is the text form for clients
// that only read text: it still has claim keys and raw fields, so it is the fallback only.
type Answer struct {
	Body    []string // the answer, then "Cần xác nhận:" and "Đề xuất:" lists
	Drafts  []Draft  // messages the agent wrote for staff to read before sending
	Details []string // findings and instructions; the web folds them under "Chi tiết"
}

type Draft struct{ Title, Body string }

// Headings of the lists AnswerParts adds to the body, as the web writes them.
const (
	toConfirm = "Cần xác nhận:"
	proposed  = "Đề xuất:"
)

var (
	// Claim keys in brackets such as [order_id, paid_amount] are for the code check, not for staff.
	claimRefs = regexp.MustCompile(`\s*\[[a-z][a-z0-9_]*(?:,\s*[a-z][a-z0-9_]*)*\]`)
	newlines  = regexp.MustCompile(`\n+`)
	listMark  = regexp.MustCompile(`^\s*[-*]\s+`)
)

func plain(s string) string {
	return strings.TrimSpace(strings.ReplaceAll(claimRefs.ReplaceAllString(s, ""), "**", ""))
}

func lines(s string) []string {
	var out []string
	for _, l := range newlines.Split(s, -1) {
		if l = plain(listMark.ReplaceAllString(l, "• ")); l != "" {
			out = append(out, l)
		}
	}
	return out
}

// texts reads a list of strings, or of objects with a `text` or `action` field (findings, proposed_actions...).
func texts(v any) []string {
	list, _ := v.([]any)
	var out []string
	for _, x := range list {
		var s string
		switch t := x.(type) {
		case string:
			s = t
		case map[string]any:
			if v, ok := t["text"].(string); ok {
				s = v
			} else if v, ok := t["action"].(string); ok {
				s = v
			}
		}
		if s = plain(s); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func bullets(items []string, heading string) []string {
	if len(items) == 0 {
		return nil
	}
	var out []string
	if heading != "" {
		out = append(out, heading)
	}
	for _, t := range items {
		out = append(out, "• "+t)
	}
	return out
}

func draftsOf(r map[string]any) []Draft {
	list, _ := r["drafts"].([]any)
	var out []Draft
	for _, x := range list {
		d, _ := x.(map[string]any)
		body, _ := d["body"].(string)
		if strings.TrimSpace(body) == "" {
			continue
		}
		title := []string{"Nội bộ"}
		if d["audience"] == "customer" {
			title[0] = "Gửi khách"
		}
		for _, k := range []string{"channel", "subject"} {
			if v, _ := d[k].(string); v != "" {
				title = append(title, v)
			}
		}
		out = append(out, Draft{Title: strings.Join(title, " · "), Body: body})
	}
	return out
}

// AnswerParts splits a result into what staff read first and the rest.
func AnswerParts(r map[string]any, output string) Answer {
	// knowledge answers in `answer`, the Coordinator in `final_response`, other workers in `summary`
	var lead string
	for _, k := range []string{"answer", "final_response", "summary"} {
		if v, ok := r[k].(string); ok && strings.TrimSpace(v) != "" {
			lead = v
			break
		}
	}
	if lead == "" {
		return Answer{Body: lines(output)}
	}
	var advice []string
	if v, ok := r["recommendation"].(string); ok {
		if p := plain(v); p != "" {
			advice = append(advice, p)
		}
	}
	body := lines(lead)
	body = append(body, bullets(texts(r["open_questions"]), toConfirm)...)
	body = append(body, bullets(append(advice, texts(r["proposed_actions"])...), proposed)...)
	return Answer{
		Body:    body,
		Drafts:  draftsOf(r),
		Details: append(bullets(texts(r["findings"]), ""), bullets(texts(r["instructions"]), "")...),
	}
}

// resultOf decodes a result item's `result`; a missing or odd one reads as empty.
func resultOf(item nexus.Item) map[string]any {
	var r map[string]any
	if len(item.Result) > 0 && json.Unmarshal(item.Result, &r) == nil && r != nil {
		return r
	}
	return map[string]any{}
}

// Mrkdwn renders the answer for Slack: the body, each draft as a quote under its title, then the
// details. Citations like QD-CSKH-2026-03#2.1 are kept as written.
func (a Answer) Mrkdwn() string {
	var parts []string
	if len(a.Body) > 0 {
		body := make([]string, len(a.Body))
		for i, l := range a.Body {
			if l == toConfirm || l == proposed {
				body[i] = "*" + l + "*"
			} else {
				body[i] = Mrkdwn(l)
			}
		}
		parts = append(parts, strings.Join(body, "\n"))
	}
	for _, d := range a.Drafts {
		parts = append(parts, "*📝 "+Mrkdwn(d.Title)+"*\n"+quote(Mrkdwn(strings.TrimSpace(d.Body))))
	}
	if len(a.Details) > 0 {
		details := make([]string, len(a.Details))
		for i, l := range a.Details {
			details[i] = Mrkdwn(l)
		}
		parts = append(parts, "*Chi tiết*\n"+strings.Join(details, "\n"))
	}
	return strings.Join(parts, "\n\n")
}

// A message holds at most 50 blocks; the answer takes this many sections per message.
const sectionsPerMessage = 40

// Messages lays text out as cards of mrkdwn sections, as many as Slack's limits need. The buttons
// (the link to the web, say) go on the last one.
func Messages(text string, buttons ...slackio.Button) []slackio.Card {
	sections := Split(text, maxSection)
	var cards []slackio.Card
	for len(sections) > 0 {
		n := min(len(sections), sectionsPerMessage)
		cards = append(cards, slackio.Card{Text: notification(sections[0]), Sections: sections[:n]})
		sections = sections[n:]
	}
	if len(cards) > 0 {
		cards[len(cards)-1].Buttons = buttons
	}
	return cards
}

// notification is the plain fallback a card shows in a notification: its first line, short.
func notification(s string) string {
	first, _, _ := strings.Cut(s, "\n")
	first = strings.NewReplacer("*", "", "_", "", "&amp;", "&", "&lt;", "<", "&gt;", ">").Replace(first)
	if len(first) > 150 {
		cut := 150
		for cut > 0 && !isRuneStart(first[cut]) {
			cut--
		}
		first = first[:cut] + "…"
	}
	return first
}

// ActionOpenWeb names the link button; Slack reports its clicks too, and the bridge ignores them.
const ActionOpenWeb = "boa_open_web"

// OpenOnWeb is a button opening the room on the web, or false when no web address is configured.
func OpenOnWeb(webURL string, sessionID int64) (slackio.Button, bool) {
	if webURL == "" || sessionID == 0 {
		return slackio.Button{}, false
	}
	return slackio.Button{ActionID: ActionOpenWeb, Label: "Mở trên web",
		URL: webURL + "/rooms?session=" + strconv.FormatInt(sessionID, 10)}, true
}
