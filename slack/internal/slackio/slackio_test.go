package slackio

import (
	"bytes"
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/slack-go/slack"
	"github.com/slack-go/slack/slackevents"
)

func TestToMessage(t *testing.T) {
	im := slackevents.EventsAPIEvent{InnerEvent: slackevents.EventsAPIInnerEvent{Data: &slackevents.MessageEvent{
		ChannelType: "im", Channel: "D1", User: "U1", Text: "hi", TimeStamp: "1.1", SubType: "message_changed", BotID: "B1"}}}
	m, ok := toMessage(im)
	if !ok || m.Mention || m.Subtype != "message_changed" || m.BotID != "B1" || m.Channel != "D1" {
		t.Fatalf("im: %+v %v", m, ok)
	}

	channel := slackevents.EventsAPIEvent{InnerEvent: slackevents.EventsAPIInnerEvent{Data: &slackevents.MessageEvent{ChannelType: "channel", Channel: "C1"}}}
	if _, ok := toMessage(channel); ok {
		t.Error("plain channel messages are not subscribed and must be ignored")
	}

	mention := slackevents.EventsAPIEvent{InnerEvent: slackevents.EventsAPIInnerEvent{Data: &slackevents.AppMentionEvent{
		Channel: "C1", User: "U1", Text: "<@UBOT> tra đơn 5", TimeStamp: "2.2", ThreadTimeStamp: "1.1"}}}
	m, ok = toMessage(mention)
	if !ok || !m.Mention || m.Text != "tra đơn 5" || m.ThreadTS != "1.1" {
		t.Fatalf("mention: %+v %v", m, ok)
	}
}

func TestToActions(t *testing.T) {
	var cb slack.InteractionCallback
	cb.Type = slack.InteractionTypeBlockActions
	cb.Channel.ID, cb.User.ID = "D1", "U2"
	cb.Message.Timestamp, cb.Message.ThreadTimestamp = "3.3", "1.1"
	cb.ActionCallback.BlockActions = []*slack.BlockAction{{ActionID: "boa_approve", Value: "146"}}
	acts := toActions(cb)
	if len(acts) != 1 {
		t.Fatalf("actions: %+v", acts)
	}
	// The clicker, not the room owner, so the decision goes out with the clicker's token
	a := acts[0]
	if a.Channel != "D1" || a.User != "U2" || a.MessageTS != "3.3" || a.ThreadTS != "1.1" || a.ActionID != "boa_approve" || a.Value != "146" || a.Reply == nil {
		t.Fatalf("action: %+v", a)
	}
}

type recorder struct {
	mu   sync.Mutex
	msgs []Message
	cmds []Command
	acts []Action
}

func (r *recorder) Message(_ context.Context, m Message) {
	r.mu.Lock()
	r.msgs = append(r.msgs, m)
	r.mu.Unlock()
}
func (r *recorder) Command(_ context.Context, c Command) {
	r.mu.Lock()
	r.cmds = append(r.cmds, c)
	r.mu.Unlock()
}

func (r *recorder) Action(_ context.Context, a Action) {
	r.mu.Lock()
	r.acts = append(r.acts, a)
	r.mu.Unlock()
}

func TestConsoleParsesLines(t *testing.T) {
	in := "U1 xin chào\nU2 >1.000001 trả lời\nU1 /boa link ABC\nU1 !approve 7 1.000001 1.000002\n"
	var out bytes.Buffer
	c := &Console{In: strings.NewReader(in), Out: &out}
	r := &recorder{}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := c.Run(ctx, r); err != nil {
		t.Fatal(err)
	}

	if len(r.msgs) != 2 || len(r.cmds) != 1 {
		t.Fatalf("msgs %+v cmds %+v", r.msgs, r.cmds)
	}
	byUser := map[string]Message{}
	for _, m := range r.msgs {
		byUser[m.User] = m
	}
	if byUser["U1"].Text != "xin chào" || byUser["U1"].ThreadTS != "" {
		t.Errorf("U1: %+v", byUser["U1"])
	}
	if byUser["U2"].ThreadTS != "1.000001" || byUser["U2"].Text != "trả lời" {
		t.Errorf("U2: %+v", byUser["U2"])
	}
	if r.cmds[0].Text != "link ABC" || r.cmds[0].User != "U1" {
		t.Errorf("command: %+v", r.cmds[0])
	}
	if len(r.acts) != 1 || r.acts[0].ActionID != "boa_approve" || r.acts[0].Value != "7" ||
		r.acts[0].ThreadTS != "1.000001" || r.acts[0].MessageTS != "1.000002" {
		t.Errorf("action: %+v", r.acts)
	}
	if _, err := c.Post(ctx, "D-U1", "1.1", "chào"); err != nil || !strings.Contains(out.String(), "chào") {
		t.Errorf("post output: %q %v", out.String(), err)
	}
}
