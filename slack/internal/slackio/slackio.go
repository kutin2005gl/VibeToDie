// Package slackio is the bot's only contact with Slack. The bridge sees two small interfaces, so
// it is tested with fakes and the Slack library stays in this package.
package slackio

import "context"

// Message is a person's message the bot should consider: a direct message, or an @mention in a channel.
type Message struct {
	Channel  string
	User     string
	Text     string
	TS       string
	ThreadTS string // empty for a top-level message
	Mention  bool   // an @mention in a channel; false for a direct message

	// Set on messages from bots and on edits, deletions and other non-plain messages. The
	// bridge drops them, which also keeps the bot from answering itself.
	BotID   string
	Subtype string
}

// Command is a `/boa ...` slash command. Reply answers only the person who typed it.
type Command struct {
	Channel string
	User    string
	Text    string // everything after /boa
	Reply   func(ctx context.Context, text string) error

	// Who sent it, as Slack names them in the command payload; /boa link passes them on so the
	// web can show which Slack account is linked.
	UserName   string // handle, without @
	TeamID     string
	TeamDomain string // workspace subdomain: <domain>.slack.com
}

// Action is a click on a card button. Reply answers only the person who clicked.
type Action struct {
	Channel   string
	User      string // who clicked
	MessageTS string // the card's message
	ThreadTS  string // the thread the card sits in
	ActionID  string
	Value     string
	Reply     func(ctx context.Context, text string) error
}

// Handler receives what Events delivers. Calls run on their own goroutines, one per event.
type Handler interface {
	Message(ctx context.Context, m Message)
	Command(ctx context.Context, c Command)
	Action(ctx context.Context, a Action)
}

// Card is a message with structure: a header, mrkdwn sections and optionally a row of buttons.
// Text is the plain fallback shown in notifications.
type Card struct {
	Text     string
	Header   string
	Sections []string
	Buttons  []Button
}

type Button struct {
	ActionID string
	Value    string
	Label    string
	URL      string // set: a link button, opened in the browser (Slack still reports the click)
	Primary  bool
	Danger   bool
}

// Events delivers Slack activity to a Handler until ctx ends.
type Events interface {
	Run(ctx context.Context, h Handler) error
}

// Poster writes to Slack.
type Poster interface {
	// Post sends text into a thread (threadTS empty: top level) and returns the new message's ts.
	Post(ctx context.Context, channel, threadTS, text string) (ts string, err error)
	// Update replaces the text of a message the bot posted.
	Update(ctx context.Context, channel, ts, text string) error
	// PostCard sends a card into a thread and returns its ts.
	PostCard(ctx context.Context, channel, threadTS string, c Card) (ts string, err error)
	// UpdateCard replaces a message the bot posted with a card; a card without buttons drops the old ones.
	UpdateCard(ctx context.Context, channel, ts string, c Card) error
	// Ephemeral shows text to one person only.
	Ephemeral(ctx context.Context, channel, user, text string) error
	// Permalink is the https link to a message, for opening it from the web.
	Permalink(ctx context.Context, channel, ts string) (string, error)
	// RealName is the person's full name in Slack (users.info, scope users:read). Without the
	// scope or a name it errors or returns "": callers fall back to the handle.
	RealName(ctx context.Context, user string) (string, error)
}
