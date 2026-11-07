// Package render turns sessions and progress events into the Vietnamese text staff read in Slack.
package render

import (
	"regexp"
	"strings"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/slackio"
)

// Slack shows at most about 4000 characters of a message's text; longer answers are split.
const maxChunk = 3500

// State is what the bridge remembers about a thread after a turn.
const (
	StateClarify  = "clarify"
	StateApproval = "approval"
	StateDone     = "done"
	StateFailed   = "failed"
)

// Outcome is a finished turn as shown to staff: the answer as a new message under the timeline,
// and, when the turn waits on an approval, the card as a message of its own after it.
type Outcome struct {
	State string
	Text  string        // mrkdwn; empty when an approval card is all there is to show
	Card  *slackio.Card // the approval card
}

// Final renders a session that stopped running. The answer is built from the result the way the
// web builds it (AnswerParts), so citations like QD-CSKH-2026-03#2.1 reach the reader unchanged.
func Final(s nexus.Session) Outcome {
	if item, ok := s.Pending(); ok {
		switch item.Kind {
		case nexus.KindClarify:
			return Outcome{State: StateClarify, Text: "❓ *Mình cần hỏi thêm:*\n" + Mrkdwn(item.Question) +
				"\n\n_Hãy trả lời ngay trong thread này._"}
		case nexus.KindApproval:
			out := Outcome{State: StateApproval, Text: turnAnswer(s)}
			if card, ok := ApprovalCard(s); ok {
				out.Card = &card
			} else if out.Text == "" {
				out.Text = ApprovalNotice
			}
			return out
		}
	}
	if s.Status == nexus.StatusFailed {
		body := "không rõ nguyên nhân"
		if item, ok := s.Last(nexus.KindFailed); ok && strings.TrimSpace(item.Body) != "" {
			body = item.Body
			if t, ok := failedText[body]; ok {
				body = t
			}
		}
		return Outcome{State: StateFailed, Text: "⚠️ *Không xử lý được yêu cầu:* " + Mrkdwn(body) +
			"\n\n_Bạn có thể gửi lại câu hỏi để thử lần nữa._"}
	}
	if text := turnAnswer(s); text != "" {
		return Outcome{State: StateDone, Text: text}
	}
	return Outcome{State: StateDone, Text: "Đã xử lý xong nhưng không có nội dung để hiển thị. Xem chi tiết trên web BOA."}
}

// turnAnswer is the answer of the session's last result item, or "" when it has none.
func turnAnswer(s nexus.Session) string {
	item, ok := s.Last(nexus.KindResult)
	if !ok {
		return ""
	}
	return AnswerParts(resultOf(item), item.Output).Mrkdwn()
}

var (
	bold    = regexp.MustCompile(`\*\*(.+?)\*\*`)
	heading = regexp.MustCompile(`(?m)^#{1,6}\s+(.+?)\s*$`)
)

// Mrkdwn converts the Markdown a model writes into Slack's dialect and escapes the three
// characters Slack treats as markup. Text such as DOC-ID#khoản is left alone.
func Mrkdwn(s string) string {
	s = strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;").Replace(s)
	s = heading.ReplaceAllString(s, "*$1*")
	return bold.ReplaceAllString(s, "*$1*")
}

// Chunks splits text for Slack's size limit, preferring line breaks.
func Chunks(text string) []string { return Split(text, maxChunk) }

// Split cuts text into pieces of at most max bytes, preferring line breaks.
func Split(text string, max int) []string {
	var out []string
	for len(text) > max {
		cut := strings.LastIndex(text[:max], "\n")
		if cut < max/2 {
			cut = max
			for cut > 0 && !isRuneStart(text[cut]) { // never cut inside a UTF-8 character
				cut--
			}
		}
		out = append(out, strings.TrimRight(text[:cut], "\n"))
		text = strings.TrimLeft(text[cut:], "\n")
	}
	return append(out, text)
}

func isRuneStart(b byte) bool { return b&0xC0 != 0x80 }
