package render

import (
	"strings"
	"testing"
	"unicode/utf8"

	"nexus/slack/internal/nexus"
)

func approvalSession(actions ...nexus.Action) nexus.Session {
	return nexus.Session{ID: 7, Status: nexus.StatusWaiting, Items: []nexus.Item{{Kind: nexus.KindApproval, Actions: actions}}}
}

func TestApprovalCardForEmail(t *testing.T) {
	s := approvalSession(nexus.Action{Name: "send_email", Arguments: map[string]any{
		"to": "a@b.vn", "subject": "Về đơn <123>", "body": "Dòng 1\nDòng 2"}})
	out := Final(s)
	if out.State != StateApproval || out.Card == nil {
		t.Fatalf("outcome %+v", out)
	}
	c := *out.Card
	all := strings.Join(c.Sections, "\n")
	for _, want := range []string{"*Gửi email cho khách?*", "*Đến:* a@b.vn", "Về đơn &lt;123&gt;", "> Dòng 1\n> Dòng 2"} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in\n%s", want, all)
		}
	}
	if len(c.Buttons) != 2 || c.Buttons[0].Value != "7" || !c.Buttons[0].Primary || !c.Buttons[1].Danger {
		t.Errorf("buttons %+v", c.Buttons)
	}
}

func TestApprovalCardForOtherActionListsArguments(t *testing.T) {
	s := approvalSession(nexus.Action{Name: "issue_refund", Arguments: map[string]any{"order_id": "DH-1", "amount": 150000}})
	card, ok := ApprovalCard(s)
	if !ok {
		t.Fatal("no card")
	}
	all := strings.Join(card.Sections, "\n")
	if !strings.Contains(all, "*issue_refund*") || !strings.Contains(all, "*amount:* 150000") || !strings.Contains(all, "*order_id:* DH-1") {
		t.Errorf("sections:\n%s", all)
	}
	if strings.Index(all, "amount") > strings.Index(all, "order_id") {
		t.Error("arguments must come in a stable (sorted) order")
	}
}

func TestLongEmailIsShownWholeInSeveralSections(t *testing.T) {
	body := strings.Repeat("Kính gửi quý khách, đơn hàng đã được xử lý.\n", 200) // ~9000 bytes
	card, _ := ApprovalCard(approvalSession(nexus.Action{Name: "send_email", Arguments: map[string]any{"to": "a@b.vn", "subject": "s", "body": body}}))
	for _, sec := range card.Sections {
		if len(sec) > 3000 || !utf8.ValidString(sec) {
			t.Fatalf("section of %d bytes breaks Slack's limit or UTF-8", len(sec))
		}
	}
	if got := strings.Count(strings.Join(card.Sections, ""), "đã được xử lý"); got != 200 {
		t.Errorf("the whole body must reach the approver, saw %d of 200 lines", got)
	}
	if len(card.Sections) > 45 {
		t.Errorf("%d sections leaves no room under Slack's 50 blocks", len(card.Sections))
	}
}

func TestSettledCards(t *testing.T) {
	cases := []struct {
		decision, status, header, want string
	}{
		{"yes", "done", "Đã duyệt", "đã thực hiện"},
		{"yes", "failed", "Thực hiện lỗi", "không tự thử lại"},
		{"yes", "sending", "Chưa rõ kết quả", "chưa rõ kết quả"},
		{"no", "", "Không thực hiện", "từ chối"},
	}
	for _, c := range cases {
		s := approvalSession(nexus.Action{Name: "send_email", Status: c.status, Error: "SMTP 550", Arguments: map[string]any{"to": "a@b.vn", "body": "x"}})
		s.Items[0].Decision = &nexus.Decision{Value: c.decision}
		s.Status = nexus.StatusDone
		card, ok := ApprovalCard(s)
		if !ok || card.Header != c.header || len(card.Buttons) != 0 || !strings.Contains(strings.Join(card.Sections, "\n"), c.want) {
			t.Errorf("%s/%s: %+v", c.decision, c.status, card)
		}
	}
	if card, _ := ApprovalCard(approvalSession(nexus.Action{Name: "send_email", Status: "failed", Error: "SMTP 550"})); strings.Contains(card.Text, "550") {
		t.Error("an error text must not leak into the notification text")
	}
}
