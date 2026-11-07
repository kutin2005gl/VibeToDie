// Package bridge connects Slack to the gateway: it turns a person's message into a session,
// follows the run, and answers in the thread. It decides nothing about permissions; every call goes
// out with the token of the person who wrote, so the gateway applies that person's rights.
package bridge

import (
	"context"
	"errors"
	"log"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/render"
	"nexus/slack/internal/slackio"
	"nexus/slack/internal/store"
)

const (
	defaultProgressEvery = 3 * time.Second // Slack rate-limits chat.update
	// A thread marked running this long ago is probably left over from a crash; the gateway decides.
	staleRunning = 20 * time.Minute
)

// Thread states the bridge stores besides the ones render names.
const (
	stateRunning = "running"
	stateIdle    = "idle" // outcome unknown (gave up waiting); the gateway arbitrates the next message
)

// Gateway finds the person behind a Slack user. *nexus.Client satisfies it through FromNexus.
type Gateway interface {
	For(ctx context.Context, slackUserID string) (Person, error)
	Redeem(ctx context.Context, acct nexus.SlackAccount, code string) (nexus.User, error)
}

// Person acts as one linked staff member.
type Person interface {
	UserID() string
	CreateSession(ctx context.Context, text, provider string, origin *nexus.Origin) (nexus.Session, error)
	Answer(ctx context.Context, id int64, text string) (nexus.Session, error)
	FollowUp(ctx context.Context, id int64, text string) (nexus.Session, error)
	Decision(ctx context.Context, id int64, approve bool) (nexus.Session, error)
	Wait(ctx context.Context, id int64, onEvent func(nexus.Event)) (nexus.Session, error)
	Logout(ctx context.Context) error
}

type nexusGateway struct{ c *nexus.Client }

// FromNexus adapts the real client.
func FromNexus(c *nexus.Client) Gateway { return nexusGateway{c} }

func (g nexusGateway) For(ctx context.Context, slackUserID string) (Person, error) {
	u, err := g.c.For(ctx, slackUserID)
	if err != nil {
		return nil, err
	}
	return u, nil
}

func (g nexusGateway) Redeem(ctx context.Context, acct nexus.SlackAccount, code string) (nexus.User, error) {
	return g.c.Redeem(ctx, acct, code)
}

type Bridge struct {
	Gateway  Gateway
	Store    store.Store
	Poster   slackio.Poster
	Provider string
	WebURL   string // BOA web base URL; set, every answer gets a "Mở trên web" button

	ProgressEvery time.Duration    // minimum time between progress edits (default 3s)
	Now           func() time.Time // default time.Now

	locks keyedMutex
}

func (b *Bridge) every() time.Duration {
	if b.ProgressEvery > 0 {
		return b.ProgressEvery
	}
	return defaultProgressEvery
}

func (b *Bridge) now() time.Time {
	if b.Now != nil {
		return b.Now()
	}
	return time.Now()
}

// Message handles a direct message, and turns an @mention in a channel away to a direct message.
func (b *Bridge) Message(ctx context.Context, m slackio.Message) {
	// Bots, edits, deletions and the rest: not a person asking. This also keeps the bot from answering itself.
	if m.BotID != "" || m.Subtype != "" {
		return
	}
	text := strings.TrimSpace(m.Text)
	if text == "" && !m.Mention {
		return
	}
	// Slack redelivers an event it thinks we missed; the first delivery is the only one that runs.
	first, err := b.Store.MarkHandled(ctx, m.Channel, m.TS)
	if err != nil {
		log.Printf("bridge: mark handled: %v", err)
		return
	}
	if !first {
		return
	}
	// Others in a channel may not have the rights to see an answer (orders, customer emails), so the
	// bot works only in direct messages. It tells only the sender, whether they are linked or not.
	if m.Mention {
		b.ephemeral(ctx, m.Channel, m.User, render.DMOnly)
		return
	}

	root := m.ThreadTS
	if root == "" {
		root = m.TS
	}
	person, err := b.Gateway.For(ctx, m.User)
	switch {
	case errors.Is(err, nexus.ErrNotLinked): // link instructions, and no agent runs
		b.say(ctx, m.Channel, root, render.NotLinked)
		return
	case err != nil:
		log.Printf("bridge: look up account of %s: %v", m.User, err)
		b.say(ctx, m.Channel, root, render.Failure)
		return
	}
	b.ask(ctx, person, m, root, text)
}

func (b *Bridge) ephemeral(ctx context.Context, channel, user, text string) {
	if err := b.Poster.Ephemeral(ctx, channel, user, text); err != nil {
		log.Printf("bridge: ephemeral: %v", err)
	}
}

func (b *Bridge) say(ctx context.Context, channel, threadTS, text string) {
	if _, err := b.Poster.Post(ctx, channel, threadTS, text); err != nil {
		log.Printf("bridge: post: %v", err)
	}
}

// ask sends the message to the gateway and then follows the run. The thread's lock covers only
// the part that reads and writes the thread's session, so a second message arriving while the
// run goes on gets "busy" at once instead of waiting minutes.
func (b *Bridge) ask(ctx context.Context, person Person, m slackio.Message, root, text string) {
	unlock := b.locks.lock(m.Channel + "/" + root)
	session, placeholder, ok := b.submit(ctx, person, m, root, text)
	unlock()
	if !ok {
		return
	}
	b.follow(ctx, person, m.Channel, root, placeholder, session)
}

// submit chooses between a new session, a clarify answer and a follow-up, and records the thread.
func (b *Bridge) submit(ctx context.Context, person Person, m slackio.Message, root, text string) (nexus.Session, string, bool) {
	th, err := b.Store.Thread(ctx, m.Channel, root)
	known := err == nil
	if err != nil && !errors.Is(err, store.ErrNotFound) {
		log.Printf("bridge: load thread: %v", err)
		b.say(ctx, m.Channel, root, render.Failure)
		return nexus.Session{}, "", false
	}
	if known && th.UserID != person.UserID() {
		b.say(ctx, m.Channel, root, render.OthersThread)
		return nexus.Session{}, "", false
	}
	if known && th.State == stateRunning && b.now().Sub(th.UpdatedAt) < staleRunning {
		b.say(ctx, m.Channel, root, render.Busy)
		return nexus.Session{}, "", false
	}

	placeholder, err := b.Poster.Post(ctx, m.Channel, root, render.Working)
	if err != nil {
		log.Printf("bridge: post placeholder: %v", err)
		return nexus.Session{}, "", false
	}
	fail := func(text string) (nexus.Session, string, bool) {
		b.update(ctx, m.Channel, placeholder, text)
		return nexus.Session{}, "", false
	}

	var session nexus.Session
	var note string
	switch {
	case !known:
		session, err = person.CreateSession(ctx, text, b.Provider, b.origin(ctx, m.Channel, root))
	case th.State == render.StateClarify:
		session, err = b.parseID(th.SessionID, func(id int64) (nexus.Session, error) { return person.Answer(ctx, id, text) })
	default:
		session, err = b.parseID(th.SessionID, func(id int64) (nexus.Session, error) { return person.FollowUp(ctx, id, text) })
		switch {
		case nexus.IsRoomFull(err):
			note = render.RoomFull
		case errors.Is(err, nexus.ErrNotFound):
			note = render.GoneSession
		}
		if note != "" {
			session, err = person.CreateSession(ctx, text, b.Provider, b.origin(ctx, m.Channel, root))
		}
	}

	switch {
	case err == nil:
	case errors.Is(err, nexus.ErrNotLinked), errors.Is(err, nexus.ErrUnauthorized):
		return fail(render.Relink)
	case errors.Is(err, nexus.ErrConflict):
		if known && th.State == render.StateApproval {
			return fail(render.ApprovalNotice)
		}
		return fail(render.Busy)
	default:
		log.Printf("bridge: submit for %s: %v", m.User, err)
		return fail(render.Failure)
	}

	err = b.Store.SaveThread(ctx, store.Thread{Channel: m.Channel, ThreadTS: root,
		SessionID: strconv.FormatInt(session.ID, 10), UserID: person.UserID(), State: stateRunning})
	if err != nil {
		log.Printf("bridge: save thread: %v", err)
	}
	if note != "" {
		b.update(ctx, m.Channel, placeholder, note+"\n"+render.Working)
	}
	return session, placeholder, true
}

// origin is where a new room comes from, recorded with it so admins can open the thread from the
// web. Without a permalink the room still opens: the link is a convenience, not a condition.
func (b *Bridge) origin(ctx context.Context, channel, root string) *nexus.Origin {
	o := &nexus.Origin{Kind: "slack", Channel: channel, ThreadTS: root}
	link, err := b.Poster.Permalink(ctx, channel, root)
	if err != nil {
		log.Printf("bridge: permalink of %s/%s: %v", channel, root, err)
		return o
	}
	// ai-service accepts only Slack's own https links (they are shown as links on the admin page)
	if u, err := url.Parse(link); err == nil && u.Scheme == "https" && strings.HasSuffix(u.Hostname(), ".slack.com") {
		o.Permalink = link
	}
	return o
}

func (b *Bridge) parseID(raw string, call func(int64) (nexus.Session, error)) (nexus.Session, error) {
	id, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return nexus.Session{}, nexus.ErrNotFound // a row we cannot use: start over with a new session
	}
	return call(id)
}

// follow waits for the run and turns the placeholder into its timeline, which stays in the thread
// as the record of the run. The answer comes as a new message below it, with a link to the room on
// the web, and an approval card as a message of its own after that, as on the web.
func (b *Bridge) follow(ctx context.Context, person Person, channel, root, placeholder string, session nexus.Session) {
	timeline := &render.Timeline{}
	var last time.Time
	shown := render.Working
	onEvent := func(ev nexus.Event) {
		timeline.Add(ev)
		text := timeline.Live()
		if text == shown {
			return
		}
		if now := b.now(); last.IsZero() || now.Sub(last) >= b.every() {
			last, shown = now, text
			b.update(ctx, channel, placeholder, text)
		}
	}

	final, err := session, error(nil)
	if session.Status == nexus.StatusRunning {
		final, err = person.Wait(ctx, session.ID, onEvent)
	}
	state := stateIdle
	switch {
	case err == nil:
		out := render.Final(final)
		state = out.State
		if timeline.Empty() {
			// No event came (the stream was down, or the run was over before we asked): what was saved
			timeline = render.FromSession(final)
		}
		b.update(ctx, channel, placeholder, timeline.Final(out.State))
		b.post(ctx, channel, root, final.ID, out)
	case errors.Is(err, nexus.ErrNotLinked), errors.Is(err, nexus.ErrUnauthorized):
		b.update(ctx, channel, placeholder, render.Relink)
	case errors.Is(err, context.DeadlineExceeded):
		b.update(ctx, channel, placeholder, render.TooSlow)
	case ctx.Err() != nil:
		return // shutting down; the run goes on and the thread stays running until the next message
	default:
		log.Printf("bridge: wait for session %d: %v", session.ID, err)
		b.update(ctx, channel, placeholder, render.Failure)
	}

	unlock := b.locks.lock(channel + "/" + root)
	defer unlock()
	err = b.Store.SaveThread(ctx, store.Thread{Channel: channel, ThreadTS: root,
		SessionID: strconv.FormatInt(session.ID, 10), UserID: person.UserID(), State: state})
	if err != nil {
		log.Printf("bridge: save thread: %v", err)
	}
}

// post sends a turn's outcome into the thread: the answer, then the approval card if any.
func (b *Bridge) post(ctx context.Context, channel, root string, sessionID int64, out render.Outcome) {
	if out.Text != "" {
		var buttons []slackio.Button
		if link, ok := render.OpenOnWeb(b.WebURL, sessionID); ok {
			buttons = append(buttons, link)
		}
		for _, card := range render.Messages(out.Text, buttons...) {
			if _, err := b.Poster.PostCard(ctx, channel, root, card); err != nil {
				log.Printf("bridge: post answer: %v", err)
				return
			}
		}
	}
	if out.Card != nil {
		if _, err := b.Poster.PostCard(ctx, channel, root, *out.Card); err != nil {
			log.Printf("bridge: post card: %v", err)
		}
	}
}

func (b *Bridge) update(ctx context.Context, channel, ts, text string) {
	if err := b.Poster.Update(ctx, channel, ts, text); err != nil {
		log.Printf("bridge: update: %v", err)
	}
}

// Action handles a click on Duyệt / Từ chối. The decision goes out with the token of the person who
// clicked, so the gateway answers 404 to anyone but the owner of the session and nobody can approve
// for somebody else. Clicking twice calls the gateway once: the thread leaves the approval state
// under a lock, and a late 409 is told "already handled".
func (b *Bridge) Action(ctx context.Context, a slackio.Action) {
	approve := a.ActionID == render.ActionApprove
	if !approve && a.ActionID != render.ActionReject {
		return
	}
	reply := func(text string) {
		if a.Reply == nil {
			return
		}
		if err := a.Reply(ctx, text); err != nil {
			log.Printf("bridge: action reply: %v", err)
		}
	}
	id, err := strconv.ParseInt(a.Value, 10, 64)
	if err != nil {
		return
	}
	person, err := b.Gateway.For(ctx, a.User)
	switch {
	case errors.Is(err, nexus.ErrNotLinked):
		reply(render.NotLinkedStatus)
		return
	case err != nil:
		log.Printf("bridge: look up account of %s: %v", a.User, err)
		reply(render.Failure)
		return
	}

	unlock := b.locks.lock("decision/" + a.Value)
	defer unlock()
	th, err := b.Store.Thread(ctx, a.Channel, a.ThreadTS)
	known := err == nil
	if known && th.SessionID == a.Value && th.State != render.StateApproval {
		reply(render.AlreadyDecided)
		return
	}

	session, err := person.Decision(ctx, id, approve)
	switch {
	case err == nil:
	case errors.Is(err, nexus.ErrNotFound):
		reply(render.NotYourApproval)
		return
	case errors.Is(err, nexus.ErrConflict):
		reply(render.AlreadyDecided)
		return
	case errors.Is(err, nexus.ErrNotLinked), errors.Is(err, nexus.ErrUnauthorized):
		reply(render.Relink)
		return
	default:
		log.Printf("bridge: decision on session %d by %s: %v", id, a.User, err)
		reply(render.Failure) // the buttons stay: the gateway refuses a second decision with 409
		return
	}

	if known && th.SessionID == a.Value {
		th.State = render.StateDone
		th.UpdatedAt = b.now()
		unlockThread := b.locks.lock(a.Channel + "/" + a.ThreadTS)
		err := b.Store.SaveThread(ctx, th)
		unlockThread()
		if err != nil {
			log.Printf("bridge: save thread: %v", err)
		}
	}
	card, ok := render.ApprovalCard(session)
	if !ok {
		return
	}
	if err := b.Poster.UpdateCard(ctx, a.Channel, a.MessageTS, card); err != nil {
		log.Printf("bridge: update card: %v", err)
	}
}

// Command handles `/boa link | unlink | status | help`. Replies are visible only to the sender.
func (b *Bridge) Command(ctx context.Context, c slackio.Command) {
	reply := func(text string) {
		if err := c.Reply(ctx, text); err != nil {
			log.Printf("bridge: command reply: %v", err)
		}
	}
	verb, arg, _ := strings.Cut(strings.TrimSpace(c.Text), " ")
	switch strings.ToLower(verb) {
	case "link":
		code := strings.TrimSpace(arg)
		if code == "" {
			reply(render.LinkUsage)
			return
		}
		acct := nexus.SlackAccount{UserID: c.User, UserName: c.UserName, TeamID: c.TeamID, TeamDomain: c.TeamDomain}
		// Only for display: when Slack refuses (scope users:read not granted) the web shows the handle
		if name, err := b.Poster.RealName(ctx, c.User); err != nil {
			log.Printf("bridge: real name of %s: %v", c.User, err)
		} else {
			acct.RealName = name
		}
		user, err := b.Gateway.Redeem(ctx, acct, code) // the code is never logged
		switch {
		case errors.Is(err, nexus.ErrInvalidCode):
			reply(render.InvalidCode)
		case err != nil:
			log.Printf("bridge: link %s: %v", c.User, err)
			reply(render.LinkFailed)
		default:
			who := user.Name
			if who == "" {
				who = user.Email
			}
			reply(render.Linked(who))
		}
	case "unlink":
		person, err := b.Gateway.For(ctx, c.User)
		switch {
		case errors.Is(err, nexus.ErrNotLinked):
			reply(render.NotLinkedStatus)
		case err != nil:
			log.Printf("bridge: unlink %s: %v", c.User, err)
			reply(render.LinkFailed)
		default:
			if err := person.Logout(ctx); err != nil {
				log.Printf("bridge: logout %s: %v", c.User, err)
				reply(render.UnlinkedPartial)
				return
			}
			reply(render.Unlinked)
		}
	case "status":
		_, err := b.Gateway.For(ctx, c.User)
		switch {
		case err == nil:
			reply(render.LinkedStatus())
		case errors.Is(err, nexus.ErrNotLinked):
			reply(render.NotLinkedStatus)
		default:
			log.Printf("bridge: status %s: %v", c.User, err)
			reply(render.LinkFailed)
		}
	default:
		reply(render.Help)
	}
}

// keyedMutex hands out one lock per key and forgets keys nobody holds or waits for.
type keyedMutex struct {
	mu sync.Mutex
	m  map[string]*keyLock
}

type keyLock struct {
	mu   sync.Mutex
	refs int
}

func (k *keyedMutex) lock(key string) (unlock func()) {
	k.mu.Lock()
	if k.m == nil {
		k.m = map[string]*keyLock{}
	}
	l := k.m[key]
	if l == nil {
		l = &keyLock{}
		k.m[key] = l
	}
	l.refs++
	k.mu.Unlock()

	l.mu.Lock()
	return func() {
		l.mu.Unlock()
		k.mu.Lock()
		if l.refs--; l.refs == 0 {
			delete(k.m, key)
		}
		k.mu.Unlock()
	}
}
