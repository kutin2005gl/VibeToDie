package bridge

import (
	"context"
	"strings"
	"sync"
	"testing"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/render"
	"nexus/slack/internal/slackio"
)

func emailApproval(decision, status string) nexus.Session {
	item := nexus.Item{ID: "3", Kind: nexus.KindApproval, Actions: []nexus.Action{{Name: "send_email",
		Arguments: map[string]any{"to": "khach@example.com", "subject": "Hoàn tiền đơn 123", "body": "Chào anh,\nđơn 123 đã được hoàn tiền."},
		Status:    status}}}
	st := nexus.StatusWaiting
	if decision != "" {
		item.Decision = &nexus.Decision{Value: decision}
		st = nexus.StatusDone
	}
	return nexus.Session{Status: st, Items: []nexus.Item{{ID: "1", Kind: nexus.KindRequest}, item}}
}

type clicks struct {
	mu      sync.Mutex
	replies []string
}

// action is a click on the card, the message after the placeholder (p1).
func (c *clicks) action(user, actionID string) slackio.Action {
	return slackio.Action{Channel: "D1", User: user, MessageTS: "p2", ThreadTS: "1.1", ActionID: actionID, Value: "1",
		Reply: func(_ context.Context, text string) error {
			c.mu.Lock()
			c.replies = append(c.replies, text)
			c.mu.Unlock()
			return nil
		}}
}

// askForApproval has U1 send a request whose run stops on an approval card.
func askForApproval(t *testing.T, r *rig) *fakePerson {
	t.Helper()
	p := r.g.add("U1", "u1", emailApproval("", ""))
	r.b.Message(context.Background(), dm("U1", "1.1", "", "gửi mail hoàn tiền đơn 123"))
	last := r.p.posts[len(r.p.posts)-1]
	if len(last.card.Buttons) != 2 || last.ts != "p2" || last.thread != "1.1" {
		t.Fatalf("want a card with two buttons as its own message in the thread, got %+v", last)
	}
	if got := r.p.lastUpdate(); !strings.Contains(got, "chờ bạn duyệt") {
		t.Fatalf("the placeholder should say the run waits on the card: %q", got)
	}
	return p
}

func TestApprovalIsShownAsCard(t *testing.T) {
	r := newRig()
	askForApproval(t, r)

	card := r.p.posts[len(r.p.posts)-1].card
	all := strings.Join(card.Sections, "\n")
	for _, want := range []string{"Gửi email cho khách?", "khach@example.com", "Hoàn tiền đơn 123", "đơn 123 đã được hoàn tiền."} {
		if !strings.Contains(all, want) {
			t.Errorf("card misses %q:\n%s", want, all)
		}
	}
	if card.Buttons[0].ActionID != render.ActionApprove || card.Buttons[1].ActionID != render.ActionReject || card.Buttons[0].Value != "1" {
		t.Errorf("buttons: %+v", card.Buttons)
	}
	th, _ := r.st.Thread(context.Background(), "D1", "1.1")
	if th.State != render.StateApproval {
		t.Errorf("thread state %q", th.State)
	}
}

func TestApproveUsesTheTokenOfWhoClicked(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	owner.decide = func(bool) (nexus.Session, error) { return emailApproval("yes", "done"), nil }
	other := r.g.add("U2", "u2") // another staff member; the gateway does not know this session for them
	ctx := context.Background()
	var c clicks

	r.b.Action(ctx, c.action("U2", render.ActionApprove))
	if other.count("decision") != 1 || owner.count("decision") != 0 {
		t.Fatalf("the click must go out as U2 and only U2: owner %v other %v", owner.calls, other.calls)
	}
	if len(c.replies) != 1 || c.replies[0] != render.NotYourApproval {
		t.Fatalf("replies %q", c.replies)
	}
	if th, _ := r.st.Thread(ctx, "D1", "1.1"); th.State != render.StateApproval {
		t.Fatalf("a refused click must leave the card open, state %q", th.State)
	}

	r.b.Action(ctx, c.action("U1", render.ActionApprove))
	if owner.count("decision:1:true") != 1 {
		t.Fatalf("owner calls: %v", owner.calls)
	}
	done := r.p.updates[len(r.p.updates)-1]
	if done.ts != "p2" || len(done.card.Buttons) != 0 || done.card.Header != "Đã duyệt" ||
		!strings.Contains(strings.Join(done.card.Sections, "\n"), "Gửi email cho khách: đã thực hiện") {
		t.Fatalf("settled card: %+v", done.card)
	}
}

func TestRejectSendsFalse(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	owner.decide = func(bool) (nexus.Session, error) { return emailApproval("no", ""), nil }
	var c clicks

	r.b.Action(context.Background(), c.action("U1", render.ActionReject))

	if owner.count("decision:1:false") != 1 {
		t.Fatalf("calls: %v", owner.calls)
	}
	if got := r.p.updates[len(r.p.updates)-1].card; got.Header != "Không thực hiện" || len(got.Buttons) != 0 {
		t.Fatalf("card: %+v", got)
	}
}

func TestClickingTwiceDecidesOnce(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	owner.decide = func(bool) (nexus.Session, error) { return emailApproval("yes", "done"), nil }
	var c clicks

	var wg sync.WaitGroup
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); r.b.Action(context.Background(), c.action("U1", render.ActionApprove)) }()
	}
	wg.Wait()
	r.b.Action(context.Background(), c.action("U1", render.ActionApprove)) // and once more, later

	if owner.count("decision") != 1 {
		t.Fatalf("Decision must be called once, calls: %v", owner.calls)
	}
	if len(c.replies) != 2 || c.replies[0] != render.AlreadyDecided {
		t.Fatalf("replies %q", c.replies)
	}
}

func TestConflictFromGatewaySaysAlreadyHandled(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	owner.decide = func(bool) (nexus.Session, error) { return nexus.Session{}, nexus.ErrConflict } // decided on the web
	var c clicks

	r.b.Action(context.Background(), c.action("U1", render.ActionApprove))

	if len(c.replies) != 1 || c.replies[0] != render.AlreadyDecided {
		t.Fatalf("replies %q", c.replies)
	}
}

func TestUnlinkedClickerDecidesNothing(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	var c clicks

	r.b.Action(context.Background(), c.action("UNOBODY", render.ActionApprove))

	if owner.count("decision") != 0 || len(c.replies) != 1 {
		t.Fatalf("calls %v replies %q", owner.calls, c.replies)
	}
}

func TestFailedOrUnknownSendIsSaidPlainly(t *testing.T) {
	for status, want := range map[string]string{"failed": "không thành công", "sending": "chưa rõ kết quả"} {
		r := newRig()
		owner := askForApproval(t, r)
		owner.decide = func(bool) (nexus.Session, error) { return emailApproval("yes", status), nil }
		var c clicks

		r.b.Action(context.Background(), c.action("U1", render.ActionApprove))

		got := strings.Join(r.p.updates[len(r.p.updates)-1].card.Sections, "\n")
		if !strings.Contains(got, want) || strings.Contains(got, "đã thực hiện") {
			t.Errorf("%s: %q", status, got)
		}
	}
}

func TestMessageWhileWaitingForApprovalPointsToTheCard(t *testing.T) {
	r := newRig()
	owner := askForApproval(t, r)
	owner.onFollow = func() error { return nexus.ErrConflict }

	r.b.Message(context.Background(), dm("U1", "1.2", "1.1", "xong chưa?"))

	if got := r.p.lastUpdate(); got != render.ApprovalNotice {
		t.Fatalf("got %q", got)
	}
}
