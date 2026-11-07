package nexus

import "encoding/json"

// User is the account the gateway reports for a token.
type User struct {
	ID          string   `json:"id"`
	Email       string   `json:"email"`
	Name        string   `json:"name"`
	Departments []string `json:"departments"`
}

// Session statuses.
const (
	StatusRunning = "running"
	StatusWaiting = "waiting"
	StatusDone    = "done"
	StatusFailed  = "failed"
)

// Item kinds the bridge renders.
const (
	KindRequest  = "request"
	KindClarify  = "clarify"
	KindResult   = "result"
	KindApproval = "approval"
	KindFailed   = "failed"
)

// Session is a room as ai-service returns it (README, "Session"). Only the fields the bot uses are decoded.
type Session struct {
	ID     int64  `json:"id"`
	Title  string `json:"title"`
	Status string `json:"status"`
	Items  []Item `json:"items"`
}

// Origin tells ai-service where a room was opened, so admins can find it and open it in Slack
// (README, "POST /api/sessions"). Permalink is optional.
type Origin struct {
	Kind      string `json:"kind"` // "slack"
	Channel   string `json:"channel"`
	ThreadTS  string `json:"thread_ts"`
	Permalink string `json:"permalink,omitempty"`
}

// Item is one entry of a session's thread. Fields beyond ID and Kind belong to some kinds only.
type Item struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
	At   string `json:"at,omitempty"` // RFC 3339, when the server added the item

	Body     string    `json:"body,omitempty"`     // request, reply, failed
	Question string    `json:"question,omitempty"` // clarify
	Answer   string    `json:"answer,omitempty"`   // clarify
	Output   string    `json:"output,omitempty"`   // result
	Agent    string    `json:"agent,omitempty"`    // route, result
	Branch   string    `json:"branch,omitempty"`   // route
	Actions  []Action  `json:"actions,omitempty"`  // approval
	Decision *Decision `json:"decision,omitempty"` // approval

	// Result is the checked final_answer of a result item, kept raw: its shape is the agent's output
	// schema (answer, summary, drafts, plan, steps...), read by render the way the web reads it.
	Result json.RawMessage `json:"result,omitempty"`
}

// Action is a queued high-risk tool call, with its outcome once approved.
type Action struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
	Status    string         `json:"status,omitempty"` // done | failed | sending
	Error     string         `json:"error,omitempty"`
}

type Decision struct {
	Value string `json:"value"`        // yes | no
	At    string `json:"at,omitempty"` // RFC 3339
}

// Pending is the clarify question or approval a waiting session stops on: its last item.
func (s Session) Pending() (Item, bool) {
	if s.Status != StatusWaiting || len(s.Items) == 0 {
		return Item{}, false
	}
	return s.Items[len(s.Items)-1], true
}

// Last returns the final item of the given kind, searching from the end.
func (s Session) Last(kind string) (Item, bool) {
	for i := len(s.Items) - 1; i >= 0; i-- {
		if s.Items[i].Kind == kind {
			return s.Items[i], true
		}
	}
	return Item{}, false
}

// Event is one server-sent event of a run: its name and raw JSON data.
type Event struct {
	Name string
	Data []byte
}
