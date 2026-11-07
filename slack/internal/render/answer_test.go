package render

import (
	"encoding/json"
	"strings"
	"testing"

	"nexus/slack/internal/nexus"
)

func resultItem(t *testing.T, agent string, result any, output string) nexus.Item {
	t.Helper()
	raw, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	return nexus.Item{ID: "9", Kind: nexus.KindResult, Agent: agent, Output: output, Result: raw}
}

func TestAnswerIsBuiltFromResultLikeTheWeb(t *testing.T) {
	item := resultItem(t, "customer_service", map[string]any{
		"summary":          "Đơn DH1014 được hoàn **1.200.000đ** [order_id, paid_amount].\n- Theo QD-CSKH-2026-03#2.1",
		"claims":           []any{map[string]any{"text": "không được hiện"}},
		"open_questions":   []any{"Khách nhận tiền qua tài khoản nào? [bank]"},
		"recommendation":   "Gọi lại khách trong hôm nay",
		"proposed_actions": []any{map[string]any{"action": "Gửi email xác nhận"}},
		"drafts": []any{
			map[string]any{"audience": "customer", "channel": "email", "subject": "Hoàn tiền DH1014", "body": "Chào anh,\nđã hoàn tiền."},
			map[string]any{"audience": "internal", "body": "  "}, // empty: dropped
		},
		"findings": []any{map[string]any{"text": "Đơn đã thanh toán đủ [paid_amount]"}},
	}, "raw output [order_id] must not be used")

	out := Final(nexus.Session{Status: nexus.StatusDone, Items: []nexus.Item{item}})
	got := out.Text
	for _, want := range []string{
		"Đơn DH1014 được hoàn 1.200.000đ.", "• Theo QD-CSKH-2026-03#2.1",
		"*Cần xác nhận:*\n• Khách nhận tiền qua tài khoản nào?",
		"*Đề xuất:*\n• Gọi lại khách trong hôm nay\n• Gửi email xác nhận",
		"*📝 Gửi khách · email · Hoàn tiền DH1014*\n> Chào anh,\n> đã hoàn tiền.",
		"*Chi tiết*\n• Đơn đã thanh toán đủ",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q in\n%s", want, got)
		}
	}
	for _, bad := range []string{"[order_id", "[bank]", "[paid_amount]", "**", "raw output", "không được hiện", "Nội bộ"} {
		if strings.Contains(got, bad) {
			t.Errorf("%q must not be shown:\n%s", bad, got)
		}
	}
}

func TestAnswerLeadOrder(t *testing.T) {
	// knowledge: answer; Coordinator: final_response; workers: summary. The first one set wins.
	r := map[string]any{"answer": "", "final_response": "Kết luận", "summary": "Tóm tắt"}
	if got := AnswerParts(r, "").Body; len(got) != 1 || got[0] != "Kết luận" {
		t.Fatalf("body %q", got)
	}
	// No lead at all (a run that did not happen): the output, cleaned the same way
	if got := AnswerParts(map[string]any{}, "**Chưa có quyền** [x]").Body; len(got) != 1 || got[0] != "Chưa có quyền" {
		t.Fatalf("fallback %q", got)
	}
}

func TestApprovalTurnShowsAnswerAndCard(t *testing.T) {
	s := nexus.Session{ID: 4, Status: nexus.StatusWaiting, Items: []nexus.Item{
		{Kind: nexus.KindRequest},
		resultItem(t, "customer_service", map[string]any{"summary": "Đã soạn email hoàn tiền."}, ""),
		{Kind: nexus.KindApproval, Actions: []nexus.Action{{Name: "send_email", Arguments: map[string]any{"to": "a@b.vn", "body": "x"}}}},
	}}
	out := Final(s)
	if out.State != StateApproval || out.Card == nil || !strings.Contains(out.Text, "Đã soạn email hoàn tiền.") {
		t.Fatalf("outcome %+v", out)
	}
}

func TestServerReasonsAreRetold(t *testing.T) {
	s := nexus.Session{Status: nexus.StatusFailed, Items: []nexus.Item{{Kind: nexus.KindFailed, Body: "run stopped by staff"}}}
	if got := Final(s).Text; !strings.Contains(got, "Bạn đã dừng lượt chạy này.") || strings.Contains(got, "stopped") {
		t.Fatalf("got %q", got)
	}
}

func TestMessagesSplitAndLinkGoesLast(t *testing.T) {
	link, ok := OpenOnWeb("https://boa.example.com", 42)
	if !ok || link.URL != "https://boa.example.com/rooms?session=42" || link.Label != "Mở trên web" {
		t.Fatalf("link %+v", link)
	}
	if _, ok := OpenOnWeb("", 42); ok {
		t.Fatal("no web address configured: no link")
	}

	text := strings.Repeat(strings.Repeat("ệ", 900)+"\n", 50*2) // ~270 kB: more than one message
	cards := Messages(text, link)
	if len(cards) < 2 {
		t.Fatalf("want several messages, got %d", len(cards))
	}
	for i, c := range cards {
		if len(c.Sections) > sectionsPerMessage || c.Text == "" {
			t.Fatalf("card %d: %d sections, text %q", i, len(c.Sections), c.Text)
		}
		for _, sec := range c.Sections {
			if len(sec) > maxSection {
				t.Fatalf("section of %d bytes", len(sec))
			}
		}
		if (len(c.Buttons) == 1) != (i == len(cards)-1) {
			t.Fatalf("the link belongs on the last message only (card %d: %+v)", i, c.Buttons)
		}
	}
}

func TestDecidedCardSaysWhen(t *testing.T) {
	for value, want := range map[string]string{"yes": "Bạn duyệt lúc 14:05", "no": "Bạn từ chối lúc 14:05"} {
		s := approvalSession(nexus.Action{Name: "send_email", Status: "done", Arguments: map[string]any{"to": "a@b.vn", "body": "x"}})
		s.Items[0].Decision = &nexus.Decision{Value: value, At: "2026-11-04T07:05:09.123456+00:00"}
		card, _ := ApprovalCard(s)
		if got := strings.Join(card.Sections, "\n"); !strings.Contains(got, want) {
			t.Errorf("%s: want %q in\n%s", value, want, got)
		}
	}
	s := approvalSession(nexus.Action{Name: "send_email", Status: "done"})
	s.Items[0].Decision = &nexus.Decision{Value: "yes"}
	if card, _ := ApprovalCard(s); strings.Contains(strings.Join(card.Sections, "\n"), "lúc") {
		t.Error("no time from the server: say nothing about it")
	}
}
