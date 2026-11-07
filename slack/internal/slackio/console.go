package slackio

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"
	"sync"
)

// Console stands in for Slack when SLACK_DRY_RUN is on, so the bridge can be tried against a real
// gateway without a Slack app. It reads one event per line and prints what the bot would send:
//
//	U1 how many orders today?        a direct message from user U1
//	U1 >1.000001 the blue one        a reply inside the thread that started at ts 1.000001
//	U1 /boa link ABCD234567          a slash command
//	U1 !approve 7 1.000001 1.000002  a click on a card's button: !approve or !reject, the session id
//	                                 (the button's value), the thread ts and the card's ts
type Console struct {
	In  io.Reader
	Out io.Writer

	mu  sync.Mutex
	seq int
}

func (c *Console) next() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.seq++
	return fmt.Sprintf("1.%06d", c.seq)
}

func (c *Console) printf(format string, args ...any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	fmt.Fprintf(c.Out, format+"\n", args...)
}

func (c *Console) Post(_ context.Context, channel, threadTS, text string) (string, error) {
	ts := c.next()
	c.printf("[post %s thread=%s ts=%s] %s", channel, threadTS, ts, text)
	return ts, nil
}

func (c *Console) Update(_ context.Context, channel, ts, text string) error {
	c.printf("[update %s ts=%s] %s", channel, ts, text)
	return nil
}

func (c *Console) PostCard(_ context.Context, channel, threadTS string, card Card) (string, error) {
	ts := c.next()
	c.printf("[post card %s thread=%s ts=%s] %s", channel, threadTS, ts, describe(card))
	return ts, nil
}

func (c *Console) UpdateCard(_ context.Context, channel, ts string, card Card) error {
	c.printf("[update card %s ts=%s] %s", channel, ts, describe(card))
	return nil
}

func describe(card Card) string {
	var b strings.Builder
	b.WriteString(card.Header)
	for _, s := range card.Sections {
		b.WriteString("\n  ")
		b.WriteString(strings.ReplaceAll(s, "\n", "\n  "))
	}
	for _, btn := range card.Buttons {
		if btn.URL != "" {
			fmt.Fprintf(&b, "\n  [link %s] %s", btn.URL, btn.Label)
			continue
		}
		fmt.Fprintf(&b, "\n  [button %s value=%s] %s", btn.ActionID, btn.Value, btn.Label)
	}
	return b.String()
}

func (c *Console) Ephemeral(_ context.Context, channel, user, text string) error {
	c.printf("[ephemeral %s to=%s] %s", channel, user, text)
	return nil
}

// Permalink makes up a link of Slack's shape, so a dry run sends the gateway what Slack would.
func (c *Console) Permalink(_ context.Context, channel, ts string) (string, error) {
	return "https://dry-run.slack.com/archives/" + channel + "/p" + strings.ReplaceAll(ts, ".", ""), nil
}

// RealName has no Slack to ask in a dry run.
func (c *Console) RealName(context.Context, string) (string, error) { return "", nil }

func (c *Console) Run(ctx context.Context, h Handler) error {
	var wg sync.WaitGroup
	defer wg.Wait()
	lines := make(chan string)
	go func() {
		defer close(lines)
		sc := bufio.NewScanner(c.In)
		for sc.Scan() {
			select {
			case lines <- sc.Text():
			case <-ctx.Done():
				return
			}
		}
	}()
	for {
		select {
		case <-ctx.Done():
			return nil
		case line, ok := <-lines:
			if !ok {
				return nil
			}
			user, rest, found := strings.Cut(strings.TrimSpace(line), " ")
			if !found || user == "" {
				continue
			}
			channel := "D-" + user
			if cmd, isCmd := strings.CutPrefix(rest, "/boa"); isCmd {
				wg.Add(1)
				go func() {
					defer wg.Done()
					h.Command(ctx, Command{Channel: channel, User: user, Text: strings.TrimSpace(cmd), Reply: func(_ context.Context, text string) error {
						c.printf("[command reply to=%s] %s", user, text)
						return nil
					}})
				}()
				continue
			}
			if verb, args, isAction := strings.Cut(rest, " "); isAction && strings.HasPrefix(verb, "!") {
				if f := strings.Fields(args); len(f) == 3 {
					a := Action{Channel: channel, User: user, ActionID: "boa_" + strings.TrimPrefix(verb, "!"), Value: f[0],
						ThreadTS: f[1], MessageTS: f[2], Reply: func(_ context.Context, text string) error {
							c.printf("[action reply to=%s] %s", user, text)
							return nil
						}}
					wg.Add(1)
					go func() { defer wg.Done(); h.Action(ctx, a) }()
				}
				continue
			}
			m := Message{Channel: channel, User: user, Text: rest, TS: c.next()}
			if after, isThread := strings.CutPrefix(rest, ">"); isThread {
				m.ThreadTS, m.Text, _ = strings.Cut(after, " ")
				m.Text = strings.TrimSpace(m.Text)
			}
			wg.Add(1)
			go func() { defer wg.Done(); h.Message(ctx, m) }()
		}
	}
}
