package render

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/slackio"
)

// Button action ids; the bridge reacts to these and to nothing else.
const (
	ActionApprove = "boa_approve"
	ActionReject  = "boa_reject"
)

// Slack allows 3000 characters in a section and 50 blocks in a message. An email body is shown whole
// (the approver must see what goes out), so a long one takes several sections up to this cap.
const (
	maxSection = 2800
	maxBody    = 20000
)

// actionTitle mirrors frontend/src/api/sessions.ts so the card reads the same on the web and in Slack.
var actionTitle = map[string]string{"send_email": "Gửi email cho khách?"}

// ApprovalCard renders the session's last approval item: the actions waiting for a decision with
// Duyệt / Từ chối buttons, or, once decided, the same details with what happened.
func ApprovalCard(s nexus.Session) (slackio.Card, bool) {
	item, ok := s.Last(nexus.KindApproval)
	if !ok {
		return slackio.Card{}, false
	}
	args := mergedArguments(item.Actions)
	email := text(args["body"]) != ""

	var sections []string
	sections = append(sections, "*"+Mrkdwn(approvalTitle(item.Actions))+"*")
	if email {
		sections = append(sections, "*Đến:* "+Mrkdwn(firstText(args, "to", "email"))+"\n*Tiêu đề:* "+Mrkdwn(text(args["subject"])))
		for _, part := range Split(Mrkdwn(clip(text(args["body"]))), maxSection) {
			sections = append(sections, quote(part))
		}
	} else if facts := factLines(item.Actions); facts != "" {
		sections = append(sections, facts)
	}

	card := slackio.Card{Sections: sections}
	if item.Decision == nil {
		card.Header = "Cần bạn duyệt"
		card.Text = "🔒 Cần bạn duyệt: " + approvalTitle(item.Actions)
		note := "_Đồng ý thì hệ thống thực hiện đúng hành động trên, một lần. Hệ thống không chuyển tiền._"
		if email {
			note = "_Đồng ý thì hệ thống gửi đúng email trên cho khách, một lần. Hệ thống không chuyển tiền._"
		}
		card.Sections = append(card.Sections, note)
		id := strconv.FormatInt(s.ID, 10)
		card.Buttons = []slackio.Button{
			{ActionID: ActionApprove, Value: id, Label: "Duyệt", Primary: true},
			{ActionID: ActionReject, Value: id, Label: "Từ chối", Danger: true},
		}
		return card, true
	}

	header, outcome := decided(item)
	card.Header = header
	card.Text = header + ": " + approvalTitle(item.Actions)
	card.Sections = append(card.Sections, outcome)
	if at := decidedAt(*item.Decision); at != "" {
		card.Sections = append(card.Sections, at)
	}
	return card, true
}

// vietnam is the shops' time zone (no daylight saving). A fixed zone needs no tzdata in the image.
var vietnam = time.FixedZone("ICT", 7*60*60)

// decidedAt says when the owner decided, as the web card does; "" when the server sent no time.
// Only the owner of a session can decide it, so the card speaks to them.
func decidedAt(d nexus.Decision) string {
	at, err := time.Parse(time.RFC3339, d.At)
	if err != nil {
		return ""
	}
	verb := "duyệt"
	if d.Value != "yes" {
		verb = "từ chối"
	}
	return "_Bạn " + verb + " lúc " + at.In(vietnam).Format("15:04") + "_"
}

// decided is the header and the result lines of a settled card. Nothing is retried by the system,
// so a failed or unknown outcome tells the person to check by hand (FR-19).
func decided(item nexus.Item) (header, body string) {
	if item.Decision.Value != "yes" {
		return "Không thực hiện", "🚫 Bạn đã từ chối. Hệ thống không thực hiện hành động nào."
	}
	var lines []string
	failed, unknown := false, false
	for _, a := range item.Actions {
		label := actionLabel(a.Name)
		switch a.Status {
		case "done":
			lines = append(lines, "✅ "+label+": đã thực hiện.")
		case "failed":
			failed = true
			line := "❌ " + label + ": không thành công."
			if a.Error != "" {
				line += " " + Mrkdwn(a.Error)
			}
			lines = append(lines, line+" Hệ thống không tự thử lại; hãy kiểm tra rồi xử lý bằng tay.")
		default: // "sending" or nothing yet: the service stopped midway
			unknown = true
			lines = append(lines, "⚠️ "+label+": chưa rõ kết quả. Hãy kiểm tra (ví dụ hộp thư đã gửi) trước khi làm lại bằng tay.")
		}
	}
	switch {
	case failed:
		header = "Thực hiện lỗi"
	case unknown:
		header = "Chưa rõ kết quả"
	default:
		header = "Đã duyệt"
	}
	if len(lines) == 0 {
		lines = []string{"✅ Đã duyệt."}
	}
	return header, strings.Join(lines, "\n")
}

func actionLabel(name string) string {
	if name == "send_email" {
		return "Gửi email cho khách"
	}
	return Mrkdwn(name)
}

func approvalTitle(actions []nexus.Action) string {
	titles := make([]string, 0, len(actions))
	for _, a := range actions {
		if t, ok := actionTitle[a.Name]; ok {
			titles = append(titles, t)
		} else {
			titles = append(titles, a.Name)
		}
	}
	return strings.Join(titles, ", ")
}

// mergedArguments overlays every action's arguments, as the web does to find the email fields.
func mergedArguments(actions []nexus.Action) map[string]any {
	out := map[string]any{}
	for _, a := range actions {
		for k, v := range a.Arguments {
			out[k] = v
		}
	}
	return out
}

// factLines lists each argument of each action as "name: value", in a stable order.
func factLines(actions []nexus.Action) string {
	var lines []string
	for _, a := range actions {
		keys := make([]string, 0, len(a.Arguments))
		for k := range a.Arguments {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			lines = append(lines, fmt.Sprintf("*%s:* %s", Mrkdwn(k), Mrkdwn(clipLine(text(a.Arguments[k])))))
		}
	}
	return strings.Join(lines, "\n")
}

func firstText(args map[string]any, keys ...string) string {
	for _, k := range keys {
		if v := text(args[k]); v != "" {
			return v
		}
	}
	return ""
}

// text shows an argument as the web does: strings as they are, anything else as JSON.
func text(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	}
	b, err := json.Marshal(v)
	if err != nil {
		return ""
	}
	return string(b)
}

func clip(s string) string {
	if len(s) <= maxBody {
		return s
	}
	cut := maxBody
	for cut > 0 && !isRuneStart(s[cut]) {
		cut--
	}
	return s[:cut] + "\n… (thư dài, xem đầy đủ trên web BOA trước khi duyệt)"
}

func clipLine(s string) string {
	if len(s) <= 500 {
		return s
	}
	cut := 500
	for cut > 0 && !isRuneStart(s[cut]) {
		cut--
	}
	return s[:cut] + "…"
}

// quote marks every line as a block quote so the mail body stands apart from the rest of the card.
func quote(s string) string {
	return "> " + strings.ReplaceAll(s, "\n", "\n> ")
}
