package slackio

import (
	"context"
	"errors"
	"log"
	"strings"
	"sync"

	"github.com/slack-go/slack"
	"github.com/slack-go/slack/slackevents"
	"github.com/slack-go/slack/socketmode"
)

// Socket talks to Slack over Socket Mode: the bot opens the connection, so it needs no public URL.
// It is both the Events source and the Poster.
type Socket struct {
	api    *slack.Client
	socket *socketmode.Client
}

func NewSocket(botToken, appToken string) *Socket {
	api := slack.New(botToken, slack.OptionAppLevelToken(appToken))
	return &Socket{api: api, socket: socketmode.New(api)}
}

func (s *Socket) Post(ctx context.Context, channel, threadTS, text string) (string, error) {
	opts := []slack.MsgOption{slack.MsgOptionText(text, false)}
	if threadTS != "" {
		opts = append(opts, slack.MsgOptionTS(threadTS))
	}
	_, ts, err := s.api.PostMessageContext(ctx, channel, opts...)
	return ts, err
}

func (s *Socket) Update(ctx context.Context, channel, ts, text string) error {
	_, _, _, err := s.api.UpdateMessageContext(ctx, channel, ts, slack.MsgOptionText(text, false))
	return err
}

func (s *Socket) PostCard(ctx context.Context, channel, threadTS string, c Card) (string, error) {
	opts := []slack.MsgOption{slack.MsgOptionText(c.Text, false), slack.MsgOptionBlocks(blocks(c)...)}
	if threadTS != "" {
		opts = append(opts, slack.MsgOptionTS(threadTS))
	}
	_, ts, err := s.api.PostMessageContext(ctx, channel, opts...)
	return ts, err
}

func (s *Socket) UpdateCard(ctx context.Context, channel, ts string, c Card) error {
	_, _, _, err := s.api.UpdateMessageContext(ctx, channel, ts, slack.MsgOptionText(c.Text, false), slack.MsgOptionBlocks(blocks(c)...))
	return err
}

// decisionBlockID names the row of buttons; Slack wants a block id on every actions block.
const decisionBlockID = "boa_card_buttons"

func blocks(c Card) []slack.Block {
	var out []slack.Block
	if c.Header != "" {
		out = append(out, slack.NewHeaderBlock(slack.NewTextBlockObject(slack.PlainTextType, c.Header, true, false)))
	}
	for _, text := range c.Sections {
		out = append(out, slack.NewSectionBlock(slack.NewTextBlockObject(slack.MarkdownType, text, false, false), nil, nil))
	}
	if len(c.Buttons) > 0 {
		var els []slack.BlockElement
		for _, b := range c.Buttons {
			btn := slack.NewButtonBlockElement(b.ActionID, b.Value, slack.NewTextBlockObject(slack.PlainTextType, b.Label, true, false))
			btn.URL = b.URL
			switch {
			case b.Primary:
				btn.Style = slack.StylePrimary
			case b.Danger:
				btn.Style = slack.StyleDanger
			}
			els = append(els, btn)
		}
		out = append(out, slack.NewActionBlock(decisionBlockID, els...))
	}
	return out
}

func (s *Socket) Permalink(ctx context.Context, channel, ts string) (string, error) {
	return s.api.GetPermalinkContext(ctx, &slack.PermalinkParameters{Channel: channel, Ts: ts})
}

func (s *Socket) RealName(ctx context.Context, user string) (string, error) {
	u, err := s.api.GetUserInfoContext(ctx, user)
	if err != nil {
		return "", err
	}
	if n := strings.TrimSpace(u.Profile.RealName); n != "" {
		return n, nil
	}
	return strings.TrimSpace(u.RealName), nil
}

func (s *Socket) Ephemeral(ctx context.Context, channel, user, text string) error {
	_, err := s.api.PostEphemeralContext(ctx, channel, user, slack.MsgOptionText(text, false))
	return err
}

// Run reads socket events and hands each to h on its own goroutine, after acknowledging it
// (Slack resends an event that is not acknowledged within three seconds). It returns when ctx
// ends, once the handlers still running have finished.
func (s *Socket) Run(ctx context.Context, h Handler) error {
	var wg sync.WaitGroup
	defer wg.Wait()

	runErr := make(chan error, 1)
	go func() { runErr <- s.socket.RunContext(ctx) }()

	for {
		select {
		case <-ctx.Done():
			return nil
		case err := <-runErr:
			if err != nil && !errors.Is(err, context.Canceled) {
				return err
			}
			return nil
		case evt := <-s.socket.Events:
			switch evt.Type {
			case socketmode.EventTypeConnected:
				log.Print("slack: connected")
			case socketmode.EventTypeEventsAPI:
				if evt.Request != nil {
					s.socket.Ack(*evt.Request)
				}
				api, ok := evt.Data.(slackevents.EventsAPIEvent)
				if !ok {
					continue
				}
				if m, ok := toMessage(api); ok {
					wg.Add(1)
					go func() { defer wg.Done(); h.Message(ctx, m) }()
				}
			case socketmode.EventTypeSlashCommand:
				if evt.Request != nil {
					s.socket.Ack(*evt.Request) // empty ack; the answer goes to response_url
				}
				cmd, ok := evt.Data.(slack.SlashCommand)
				if !ok {
					continue
				}
				c := Command{Channel: cmd.ChannelID, User: cmd.UserID, Text: PlainText(cmd.Text), Reply: replyTo(cmd.ResponseURL),
					UserName: cmd.UserName, TeamID: cmd.TeamID, TeamDomain: cmd.TeamDomain}
				wg.Add(1)
				go func() { defer wg.Done(); h.Command(ctx, c) }()
			case socketmode.EventTypeInteractive:
				if evt.Request != nil {
					s.socket.Ack(*evt.Request) // without it Slack marks the button as failed after 3 s
				}
				cb, ok := evt.Data.(slack.InteractionCallback)
				if !ok || cb.Type != slack.InteractionTypeBlockActions {
					continue
				}
				for _, a := range toActions(cb) {
					wg.Add(1)
					go func() { defer wg.Done(); h.Action(ctx, a) }()
				}
			}
		}
	}
}

func replyTo(responseURL string) func(context.Context, string) error {
	return func(ctx context.Context, text string) error {
		return slack.PostWebhookContext(ctx, responseURL, &slack.WebhookMessage{Text: text, ResponseType: slack.ResponseTypeEphemeral})
	}
}

func toActions(cb slack.InteractionCallback) []Action {
	var out []Action
	for _, a := range cb.ActionCallback.BlockActions {
		out = append(out, Action{Channel: cb.Channel.ID, User: cb.User.ID, MessageTS: cb.Message.Timestamp,
			ThreadTS: cb.Message.ThreadTimestamp, ActionID: a.ActionID, Value: a.Value, Reply: replyTo(cb.ResponseURL)})
	}
	return out
}

func toMessage(api slackevents.EventsAPIEvent) (Message, bool) {
	switch ev := api.InnerEvent.Data.(type) {
	case *slackevents.MessageEvent:
		if ev.ChannelType != "im" { // channels are served through app_mention only
			return Message{}, false
		}
		return Message{Channel: ev.Channel, User: ev.User, Text: PlainText(ev.Text), TS: ev.TimeStamp, ThreadTS: ev.ThreadTimeStamp,
			BotID: ev.BotID, Subtype: ev.SubType}, true
	case *slackevents.AppMentionEvent:
		return Message{Channel: ev.Channel, User: ev.User, Text: PlainText(ev.Text),
			TS: ev.TimeStamp, ThreadTS: ev.ThreadTimeStamp, Mention: true, BotID: ev.BotID}, true
	}
	return Message{}, false
}
