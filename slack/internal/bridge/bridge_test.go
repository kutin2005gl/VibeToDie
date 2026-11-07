package bridge

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/render"
	"nexus/slack/internal/slackio"
	"nexus/slack/internal/store"
)

// fakePerson records what the bridge asked for and answers from a script.
type fakePerson struct {
	mu       sync.Mutex
	id       string
	calls    []string
	next     *int64 // shared session id counter
	outcomes []nexus.Session
	events   []nexus.Event // sent to onEvent by every Wait
	onCreate func() error
	onFollow func() error
	onAnswer func() error
	decide   func(approve bool) (nexus.Session, error)
	logouts  int
	origins  []*nexus.Origin // of each CreateSession
}

func (p *fakePerson) UserID() string { return p.id }

func (p *fakePerson) record(format string, args ...any) {
	p.mu.Lock()
	p.calls = append(p.calls, fmt.Sprintf(format, args...))
	p.mu.Unlock()
}

func (p *fakePerson) running(id int64) nexus.Session {
	return nexus.Session{ID: id, Status: nexus.StatusRunning}
}

func (p *fakePerson) CreateSession(_ context.Context, text, provider string, origin *nexus.Origin) (nexus.Session, error) {
	p.record("create:%s:%s", provider, text)
	p.mu.Lock()
	p.origins = append(p.origins, origin)
	p.mu.Unlock()
	if p.onCreate != nil {
		if err := p.onCreate(); err != nil {
			return nexus.Session{}, err
		}
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	*p.next++
	return p.running(*p.next), nil
}

func (p *fakePerson) Answer(_ context.Context, id int64, text string) (nexus.Session, error) {
	p.record("answer:%d:%s", id, text)
	if p.onAnswer != nil {
		if err := p.onAnswer(); err != nil {
			return nexus.Session{}, err
		}
	}
	return p.running(id), nil
}

func (p *fakePerson) FollowUp(_ context.Context, id int64, text string) (nexus.Session, error) {
	p.record("followup:%d:%s", id, text)
	if p.onFollow != nil {
		if err := p.onFollow(); err != nil {
			return nexus.Session{}, err
		}
	}
	return p.running(id), nil
}

func (p *fakePerson) Wait(_ context.Context, id int64, on func(nexus.Event)) (nexus.Session, error) {
	p.record("wait:%d", id)
	for _, ev := range p.events {
		on(ev)
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	s := p.outcomes[0]
	p.outcomes = p.outcomes[1:]
	s.ID = id
	return s, nil
}

func (p *fakePerson) Decision(_ context.Context, id int64, approve bool) (nexus.Session, error) {
	p.record("decision:%d:%t", id, approve)
	if p.decide == nil {
		return nexus.Session{}, nexus.ErrNotFound
	}
	return p.decide(approve)
}

func (p *fakePerson) Logout(context.Context) error { p.logouts++; return nil }

func (p *fakePerson) count(prefix string) (n int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, c := range p.calls {
		if strings.HasPrefix(c, prefix) {
			n++
		}
	}
	return n
}

type fakeGateway struct {
	mu      sync.Mutex
	people  map[string]*fakePerson // by Slack user
	next    int64
	lookups int
	linked  []nexus.SlackAccount // every Redeem, in order
}

func (g *fakeGateway) add(slackUser, userID string, outcomes ...nexus.Session) *fakePerson {
	p := &fakePerson{id: userID, next: &g.next, outcomes: outcomes}
	g.mu.Lock()
	g.people[slackUser] = p
	g.mu.Unlock()
	return p
}

func (g *fakeGateway) For(_ context.Context, slackUser string) (Person, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.lookups++
	if p, ok := g.people[slackUser]; ok {
		return p, nil
	}
	return nil, nexus.ErrNotLinked
}

func (g *fakeGateway) Redeem(_ context.Context, acct nexus.SlackAccount, code string) (nexus.User, error) {
	g.mu.Lock()
	g.linked = append(g.linked, acct)
	g.mu.Unlock()
	if code != "GOOD" {
		return nexus.User{}, nexus.ErrInvalidCode
	}
	slackUser := acct.UserID
	g.add(slackUser, "user-"+slackUser)
	return nexus.User{ID: "user-" + slackUser, Name: "An Nguyen"}, nil
}

type sent struct {
	channel, thread, ts, text, to string
	card                          slackio.Card
}

type fakePoster struct {
	mu          sync.Mutex
	posts       []sent
	updates     []sent
	ephemerals  []sent
	n           int
	permalink   func(channel, ts string) (string, error) // nil: a link of Slack's shape
	realNames   map[string]string                        // users.info answers, by Slack user
	realNameErr error                                    // users.info fails, e.g. scope not granted
}

func (f *fakePoster) RealName(_ context.Context, user string) (string, error) {
	if f.realNameErr != nil {
		return "", f.realNameErr
	}
	return f.realNames[user], nil
}

func (f *fakePoster) Permalink(_ context.Context, channel, ts string) (string, error) {
	if f.permalink != nil {
		return f.permalink(channel, ts)
	}
	return "https://boa.slack.com/archives/" + channel + "/p" + strings.ReplaceAll(ts, ".", ""), nil
}

func (f *fakePoster) Post(_ context.Context, channel, thread, text string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.n++
	ts := fmt.Sprintf("p%d", f.n)
	f.posts = append(f.posts, sent{channel: channel, thread: thread, ts: ts, text: text})
	return ts, nil
}

func (f *fakePoster) Update(_ context.Context, channel, ts, text string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.updates = append(f.updates, sent{channel: channel, ts: ts, text: text})
	return nil
}

func (f *fakePoster) PostCard(_ context.Context, channel, thread string, c slackio.Card) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.n++
	ts := fmt.Sprintf("p%d", f.n)
	f.posts = append(f.posts, sent{channel: channel, thread: thread, ts: ts, text: c.Text, card: c})
	return ts, nil
}

func (f *fakePoster) UpdateCard(_ context.Context, channel, ts string, c slackio.Card) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.updates = append(f.updates, sent{channel: channel, ts: ts, text: c.Text, card: c})
	return nil
}

func (f *fakePoster) Ephemeral(_ context.Context, channel, user, text string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ephemerals = append(f.ephemerals, sent{channel: channel, to: user, text: text})
	return nil
}

// lastAnswer is every section of the last card posted: the answer of a turn, or an approval card.
func (f *fakePoster) lastAnswer() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	for i := len(f.posts) - 1; i >= 0; i-- {
		if c := f.posts[i].card; len(c.Sections) > 0 {
			return strings.Join(c.Sections, "\n")
		}
	}
	return ""
}

// lastUpdate is the text a person finally sees in the placeholder of the last post.
func (f *fakePoster) lastUpdate() string {
	if len(f.updates) == 0 {
		return ""
	}
	return f.updates[len(f.updates)-1].text
}

type rig struct {
	b  *Bridge
	g  *fakeGateway
	p  *fakePoster
	st *store.Memory
}

func newRig() *rig {
	g := &fakeGateway{people: map[string]*fakePerson{}}
	p := &fakePoster{}
	st := store.NewMemory()
	return &rig{b: &Bridge{Gateway: g, Store: st, Poster: p, Provider: "anthropic"}, g: g, p: p, st: st}
}

func dm(user, ts, thread, text string) slackio.Message {
	return slackio.Message{Channel: "D1", User: user, TS: ts, ThreadTS: thread, Text: text}
}

func result(text string) nexus.Session {
	return nexus.Session{Status: nexus.StatusDone, Items: []nexus.Item{{ID: "2", Kind: nexus.KindResult, Output: text}}}
}

func clarify(q string) nexus.Session {
	return nexus.Session{Status: nexus.StatusWaiting, Items: []nexus.Item{{ID: "2", Kind: nexus.KindClarify, Question: q}}}
}

func TestUnlinkedPersonRunsNoAgent(t *testing.T) {
	r := newRig()
	p := r.g.add("UOTHER", "other") // somebody else is linked; that must not help U1
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn 123"))

	if p.count("create") != 0 {
		t.Fatal("an unlinked person must not start a session")
	}
	if len(r.p.posts) != 1 || !strings.Contains(r.p.posts[0].text, "/boa link") || r.p.posts[0].thread != "1.1" {
		t.Fatalf("want link instructions in the thread, got %+v", r.p.posts)
	}
}

func TestMentionInChannelPointsToDMPrivately(t *testing.T) {
	r := newRig()
	r.b.Message(context.Background(), slackio.Message{Channel: "C1", User: "U1", TS: "1.1", Text: "tra đơn 123", Mention: true})

	if len(r.p.posts) != 0 {
		t.Fatalf("nothing may be posted to the channel: %+v", r.p.posts)
	}
	if len(r.p.ephemerals) != 1 || r.p.ephemerals[0].to != "U1" || r.p.ephemerals[0].text != render.DMOnly {
		t.Fatalf("want one private nudge to DM, got %+v", r.p.ephemerals)
	}
}

func TestLinkedMentionInChannelRunsNoAgent(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("đơn 123 đang giao"))
	ctx := context.Background()
	r.b.Message(ctx, slackio.Message{Channel: "C1", User: "U1", TS: "1.1", Text: "tra đơn 123", Mention: true})
	r.b.Message(ctx, slackio.Message{Channel: "C1", User: "U1", TS: "1.2", ThreadTS: "1.1", Text: "", Mention: true})
	// A redelivery nudges no second time.
	r.b.Message(ctx, slackio.Message{Channel: "C1", User: "U1", TS: "1.1", Text: "tra đơn 123", Mention: true})

	if len(p.calls) != 0 {
		t.Fatalf("a mention must not reach the gateway: %v", p.calls)
	}
	if len(r.p.posts) != 0 || len(r.p.updates) != 0 {
		t.Fatalf("nothing may be posted to the channel: posts %+v updates %+v", r.p.posts, r.p.updates)
	}
	if len(r.p.ephemerals) != 2 {
		t.Fatalf("want one private nudge per mention, got %+v", r.p.ephemerals)
	}
	if _, err := r.st.Thread(ctx, "C1", "1.1"); err == nil {
		t.Fatal("a mention must not open a thread")
	}
}

func TestBotsAndEditsAreIgnored(t *testing.T) {
	r := newRig()
	r.g.add("U1", "u1", result("x"))
	ctx := context.Background()

	for _, m := range []slackio.Message{
		{Channel: "D1", User: "U1", TS: "1.1", Text: "hi", BotID: "B1"},
		{Channel: "D1", User: "U1", TS: "1.2", Text: "hi", Subtype: "message_changed"},
		{Channel: "D1", User: "U1", TS: "1.3", Text: "   "},
	} {
		r.b.Message(ctx, m)
	}
	if r.g.lookups != 0 || len(r.p.posts) != 0 {
		t.Fatalf("ignored messages must do nothing: lookups=%d posts=%+v", r.g.lookups, r.p.posts)
	}
}

func TestDuplicateEventRunsOnce(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("xong"))
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn 123"))
	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn 123")) // Slack redelivery

	if p.count("create") != 1 {
		t.Fatalf("want 1 session, calls: %v", p.calls)
	}
}

func TestAnswerIsShownWithCitation(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("**Hoàn tiền trong 7 ngày.**\nCăn cứ: QD-CSKH-2026-03#2.1 <b>"))
	r.b.Message(context.Background(), dm("U1", "1.1", "", "quy định hoàn tiền?"))

	if p.calls[0] != "create:anthropic:quy định hoàn tiền?" {
		t.Fatalf("calls: %v", p.calls)
	}
	got := r.p.lastAnswer()
	if !strings.Contains(got, "QD-CSKH-2026-03#2.1") || !strings.Contains(got, "Hoàn tiền trong 7 ngày.") || strings.Contains(got, "<b>") {
		t.Fatalf("answer text: %q", got)
	}
	// The placeholder, in the thread of the question, stays as the record of the run; the answer is
	// a new message in the same thread.
	last := r.p.updates[len(r.p.updates)-1]
	if r.p.posts[0].text != render.Working || r.p.posts[0].thread != "1.1" || last.ts != r.p.posts[0].ts ||
		!strings.Contains(last.text, "Xong") {
		t.Fatalf("posts %+v updates %+v", r.p.posts, r.p.updates)
	}
	if answer := r.p.posts[len(r.p.posts)-1]; answer.ts == r.p.posts[0].ts || answer.thread != "1.1" {
		t.Fatalf("the answer must be its own message in the thread: %+v", answer)
	}
	th, err := r.st.Thread(context.Background(), "D1", "1.1")
	if err != nil || th.State != render.StateDone || th.SessionID != "1" || th.UserID != "u1" {
		t.Fatalf("thread %+v %v", th, err)
	}
}

func TestPlaceholderBecomesTheTimeline(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("Đơn đã giao."))
	p.events = []nexus.Event{
		{Name: "route", Data: []byte(`{"branch":"single","target":"orders"}`)},
		{Name: "tool_call", Data: []byte(`{"agent":"orders","name":"get_order"}`)},
	}
	r.b.Message(context.Background(), dm("U1", "1.1", "", "đơn 123 giao chưa?"))

	if got := r.p.lastUpdate(); got != "↪️ Chuyển cho Đơn hàng\n✅ Xong. Kết quả ở tin bên dưới." {
		t.Fatalf("placeholder: %q", got)
	}
}

func TestTimelineFromSavedSessionWhenNoEventCame(t *testing.T) {
	r := newRig()
	done := result("Đơn đã giao.")
	done.Items = append([]nexus.Item{{ID: "1", Kind: nexus.KindRequest}, {ID: "2", Kind: "route", Agent: "orders"}}, done.Items...)
	r.g.add("U1", "u1", done)
	r.b.Message(context.Background(), dm("U1", "1.1", "", "đơn 123 giao chưa?"))

	if got := r.p.lastUpdate(); !strings.HasPrefix(got, "↪️ Chuyển cho Đơn hàng\n") {
		t.Fatalf("placeholder: %q", got)
	}
}

func TestAnswerLinksToTheRoomOnTheWeb(t *testing.T) {
	r := newRig()
	r.g.add("U1", "u1", result("xong"), result("xong"))
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "hỏi"))
	if b := r.p.posts[len(r.p.posts)-1].card.Buttons; len(b) != 0 {
		t.Fatalf("no BOA_WEB_URL: no button, got %+v", b)
	}

	r.b.WebURL = "https://boa.example.com"
	r.b.Message(ctx, dm("U1", "2.1", "", "hỏi lần nữa"))
	b := r.p.posts[len(r.p.posts)-1].card.Buttons
	if len(b) != 1 || b[0].URL != "https://boa.example.com/rooms?session=2" || b[0].ActionID != render.ActionOpenWeb {
		t.Fatalf("buttons %+v", b)
	}
	// Slack reports a click on a link button too; it decides nothing
	r.b.Action(ctx, slackio.Action{Channel: "D1", User: "U1", ActionID: render.ActionOpenWeb, Value: ""})
	if r.g.people["U1"].count("decision") != 0 {
		t.Fatal("a link click must not reach the gateway")
	}
}

func TestClarifyReplyAnswersTheSameSession(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", clarify("Đơn nào?"), result("Đơn 123 đã giao."))
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn giúp mình"))
	if got := r.p.lastAnswer(); !strings.Contains(got, "Đơn nào?") {
		t.Fatalf("clarify question not shown: %q", got)
	}
	r.b.Message(ctx, dm("U1", "1.2", "1.1", "đơn 123")) // reply in the thread

	if p.count("create") != 1 || p.count("answer:1:đơn 123") != 1 || p.count("followup") != 0 {
		t.Fatalf("calls: %v", p.calls)
	}
	if got := r.p.lastAnswer(); !strings.Contains(got, "Đơn 123 đã giao.") {
		t.Fatalf("final: %q", got)
	}
}

func TestFollowUpAfterDone(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("một"), result("hai"))
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "câu 1"))
	r.b.Message(ctx, dm("U1", "1.2", "1.1", "câu 2"))

	if p.count("create") != 1 || p.count("followup:1:câu 2") != 1 {
		t.Fatalf("calls: %v", p.calls)
	}
}

func TestRoomFullOpensANewSession(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("một"), result("hai"))
	ctx := context.Background()
	r.b.Message(ctx, dm("U1", "1.1", "", "câu 1"))
	p.onFollow = func() error { return &nexus.APIError{Status: 409, Detail: "room is full: start a new room"} }

	r.b.Message(ctx, dm("U1", "1.2", "1.1", "câu 2"))

	if p.count("create") != 2 {
		t.Fatalf("calls: %v", p.calls)
	}
	th, _ := r.st.Thread(ctx, "D1", "1.1")
	if th.SessionID != "2" {
		t.Fatalf("thread should move to the new session: %+v", th)
	}
	if !strings.Contains(r.p.updates[len(r.p.updates)-2].text, render.RoomFull) {
		t.Fatalf("the new session is not explained: %+v", r.p.updates)
	}
}

func TestBusyThreadIsNotSubmittedAgain(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1")
	ctx := context.Background()
	r.st.SaveThread(ctx, store.Thread{Channel: "D1", ThreadTS: "1.1", SessionID: "1", UserID: "u1", State: stateRunning})

	r.b.Message(ctx, dm("U1", "1.2", "1.1", "còn đó không?"))
	if len(p.calls) != 0 || r.p.posts[0].text != render.Busy {
		t.Fatalf("calls %v posts %+v", p.calls, r.p.posts)
	}

	// The gateway can also say so (a run started from the web, say).
	r.st.SaveThread(ctx, store.Thread{Channel: "D1", ThreadTS: "1.1", SessionID: "1", UserID: "u1", State: render.StateDone})
	p.onFollow = func() error { return &nexus.APIError{Status: 409, Detail: "session is still running"} }
	r.b.Message(ctx, dm("U1", "1.3", "1.1", "còn đó không?"))
	if got := r.p.lastUpdate(); got != render.Busy {
		t.Fatalf("got %q", got)
	}
}

func TestSomeoneElsesThreadIsRefused(t *testing.T) {
	r := newRig()
	r.g.add("U1", "u1", result("x"))
	b := r.g.add("U2", "u2")
	ctx := context.Background()
	r.b.Message(ctx, dm("U1", "1.1", "", "hỏi"))

	// A DM holds one person, but the thread table must not trust that.
	r.b.Message(ctx, dm("U2", "1.2", "1.1", "chen ngang"))

	if len(b.calls) != 0 || r.p.posts[len(r.p.posts)-1].text != render.OthersThread {
		t.Fatalf("calls %v posts %+v", b.calls, r.p.posts)
	}
}

func TestFailedRunSaysSoInVietnamese(t *testing.T) {
	r := newRig()
	r.g.add("U1", "u1", nexus.Session{Status: nexus.StatusFailed, Items: []nexus.Item{{Kind: nexus.KindFailed, Body: "model unavailable"}}})
	r.b.Message(context.Background(), dm("U1", "1.1", "", "hỏi"))

	got := r.p.lastAnswer()
	if !strings.Contains(got, "Không xử lý được") || !strings.Contains(got, "model unavailable") || !strings.Contains(got, "thử lần nữa") {
		t.Fatalf("got %q", got)
	}
}

func TestExpiredLinkAsksToRelink(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1")
	p.onCreate = func() error { return fmt.Errorf("%w: %w", nexus.ErrNotLinked, nexus.ErrUnauthorized) }
	r.b.Message(context.Background(), dm("U1", "1.1", "", "hỏi"))

	if got := r.p.lastUpdate(); got != render.Relink {
		t.Fatalf("got %q", got)
	}
}

func TestProgressEditsAreThrottled(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("xong"))
	for i := 1; i <= 7; i++ {
		p.events = append(p.events, nexus.Event{Name: "step_started", Data: []byte(fmt.Sprintf(`{"label":"bước %d"}`, i))})
	}
	clock := time.Unix(1000, 0)
	r.b.Now = func() time.Time { clock = clock.Add(time.Second); return clock } // each call is one second later
	r.b.ProgressEvery = 3 * time.Second

	r.b.Message(context.Background(), dm("U1", "1.1", "", "hỏi"))

	progress := len(r.p.updates) - 1 // the last update is the finished timeline
	if progress < 1 || progress > 3 {
		t.Fatalf("7 events over ~7s at one edit per 3s should give 2 or 3 edits, got %d: %+v", progress, r.p.updates)
	}
}

func TestLinkCommand(t *testing.T) {
	r := newRig()
	ctx := context.Background()
	var replies []string
	cmd := func(user, text string) {
		r.b.Command(ctx, slackio.Command{Channel: "D1", User: user, Text: text, Reply: func(_ context.Context, s string) error {
			replies = append(replies, s)
			return nil
		}})
	}

	cmd("U1", "link")
	cmd("U1", "link WRONG")
	cmd("U1", "status")
	cmd("U1", "link GOOD")
	cmd("U1", "status")
	cmd("U1", "unlink")
	cmd("U1", "")

	want := []string{render.LinkUsage, render.InvalidCode, render.NotLinkedStatus, render.Linked("An Nguyen"), render.LinkedStatus()}
	for i, w := range want {
		if replies[i] != w {
			t.Errorf("reply %d = %q, want %q", i, replies[i], w)
		}
	}
	if replies[5] != render.Unlinked || replies[6] != render.Help {
		t.Errorf("unlink/help replies: %q / %q", replies[5], replies[6])
	}
	if r.g.people["U1"].logouts != 1 {
		t.Error("unlink must log the person out at the gateway")
	}
}

func TestUnlinkWhenNotLinked(t *testing.T) {
	r := newRig()
	var got string
	r.b.Command(context.Background(), slackio.Command{User: "U9", Text: "unlink", Reply: func(_ context.Context, s string) error { got = s; return nil }})
	if got != render.NotLinkedStatus {
		t.Fatalf("got %q", got)
	}
}

func TestNewRoomRecordsItsSlackThread(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("xong"), result("tiếp"))
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn 123"))
	r.b.Message(ctx, dm("U1", "1.2", "1.1", "còn đơn 124?")) // same thread: a follow-up, no new room

	if len(p.origins) != 1 {
		t.Fatalf("want one new room, calls: %v", p.calls)
	}
	want := nexus.Origin{Kind: "slack", Channel: "D1", ThreadTS: "1.1", Permalink: "https://boa.slack.com/archives/D1/p11"}
	if got := p.origins[0]; got == nil || *got != want {
		t.Fatalf("origin: %+v, want %+v", got, want)
	}
}

func TestRoomOpensWithoutAPermalinkSlackWontGive(t *testing.T) {
	for name, permalink := range map[string]func(string, string) (string, error){
		"error":     func(string, string) (string, error) { return "", fmt.Errorf("slack: message_not_found") },
		"not slack": func(string, string) (string, error) { return "https://evil.example/archives/D1", nil },
		"not https": func(string, string) (string, error) { return "http://boa.slack.com/archives/D1/p11", nil },
	} {
		t.Run(name, func(t *testing.T) {
			r := newRig()
			r.p.permalink = permalink
			p := r.g.add("U1", "u1", result("xong"))
			r.b.Message(context.Background(), dm("U1", "1.1", "", "tra đơn 123"))

			want := nexus.Origin{Kind: "slack", Channel: "D1", ThreadTS: "1.1"}
			if len(p.origins) != 1 || p.origins[0] == nil || *p.origins[0] != want {
				t.Fatalf("origins: %+v, calls: %v", p.origins, p.calls)
			}
		})
	}
}

func TestRoomOpenedWhenTheOldOneIsFullKeepsTheThread(t *testing.T) {
	r := newRig()
	p := r.g.add("U1", "u1", result("xong"), result("phòng mới"))
	p.onFollow = func() error { return &nexus.APIError{Status: 409, Detail: "room is full: start a new room"} }
	ctx := context.Background()

	r.b.Message(ctx, dm("U1", "1.1", "", "tra đơn 123"))
	r.b.Message(ctx, dm("U1", "1.2", "1.1", "còn đơn 124?"))

	if len(p.origins) != 2 || p.origins[1] == nil || p.origins[1].ThreadTS != "1.1" {
		t.Fatalf("origins: %+v, calls: %v", p.origins, p.calls)
	}
}

func TestLinkCommandPassesTheSlackAccount(t *testing.T) {
	r := newRig()
	r.b.Command(context.Background(), slackio.Command{Channel: "D1", User: "U1", Text: "link GOOD",
		UserName: "nhattin", TeamID: "T9", TeamDomain: "boa-team",
		Reply: func(context.Context, string) error { return nil }})
	want := nexus.SlackAccount{UserID: "U1", UserName: "nhattin", TeamID: "T9", TeamDomain: "boa-team"}
	if len(r.g.linked) != 1 || r.g.linked[0] != want {
		t.Fatalf("redeemed as %+v, want %+v", r.g.linked, want)
	}
}

func TestLinkCommandPassesTheRealName(t *testing.T) {
	r := newRig()
	r.p.realNames = map[string]string{"U1": "Huỳnh Phúc Hoàng Nhật"}
	link := func(user string) {
		r.b.Command(context.Background(), slackio.Command{Channel: "D1", User: user, Text: "link GOOD", UserName: "nhattin",
			Reply: func(context.Context, string) error { return nil }})
	}
	link("U1")
	if got := r.g.linked[0].RealName; got != "Huỳnh Phúc Hoàng Nhật" {
		t.Fatalf("real name = %q", got)
	}

	// Scope not granted: the link still works, just without the name.
	r.p.realNameErr = errors.New("missing_scope")
	link("U2")
	if len(r.g.linked) != 2 || r.g.linked[1].RealName != "" || r.g.linked[1].UserName != "nhattin" {
		t.Fatalf("without scope: %+v", r.g.linked)
	}
	if _, err := r.g.For(context.Background(), "U2"); err != nil {
		t.Fatalf("link failed because the name was unavailable: %v", err)
	}
}
