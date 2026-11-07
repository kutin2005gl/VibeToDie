package render

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"nexus/slack/internal/nexus"
	"nexus/slack/internal/slackio"
)

var update = flag.Bool("update", false, "rewrite testdata/*.golden from the current output")

// Real sessions as GET /api/sessions/{id} returned them (traces dropped, names and addresses
// replaced): a refund email that was approved, a Coordinator run whose step was sent back, a
// clarify question, and a second turn that failed after a first one that answered.
var goldenSessions = []string{"approval", "retry", "clarify", "failed"}

func loadSession(t *testing.T, name string) nexus.Session {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", name+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var s nexus.Session
	if err := json.Unmarshal(raw, &s); err != nil {
		t.Fatal(err)
	}
	return s
}

// pending turns a decided approval back into the card staff saw before they clicked.
func pending(s nexus.Session) nexus.Session {
	s.Status = nexus.StatusWaiting
	items := append([]nexus.Item(nil), s.Items...)
	last := &items[len(items)-1]
	last.Decision = nil
	last.Actions = append([]nexus.Action(nil), last.Actions...)
	for i := range last.Actions {
		last.Actions[i].Status, last.Actions[i].Error = "", ""
	}
	s.Items = items
	return s
}

// TestGolden renders each session the way the bridge does at the end of a turn: the timeline
// rebuilt from the session, the answer and the approval card. Run with -update after a deliberate
// change and read the diff of testdata/*.golden.
func TestGolden(t *testing.T) {
	cases := map[string]nexus.Session{}
	for _, name := range goldenSessions {
		cases[name] = loadSession(t, name)
	}
	cases["approval-pending"] = pending(cases["approval"])

	for name, s := range cases {
		t.Run(name, func(t *testing.T) {
			got := golden(s)
			path := filepath.Join("testdata", name+".golden")
			if *update {
				if err := os.WriteFile(path, []byte(got), 0o644); err != nil {
					t.Fatal(err)
				}
				return
			}
			want, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("%v (run go test -run TestGolden -update)", err)
			}
			if got != strings.ReplaceAll(string(want), "\r\n", "\n") {
				t.Errorf("%s changed; run go test -run TestGolden -update and review the diff\n%s", path, got)
			}
		})
	}
}

func golden(s nexus.Session) string {
	out := Final(s)
	var b strings.Builder
	fmt.Fprintf(&b, "== state\n%s\n\n== timeline\n%s\n\n== answer\n%s\n", out.State, FromSession(s).Final(out.State), out.Text)
	card := out.Card
	if card == nil {
		if c, ok := ApprovalCard(s); ok {
			card = &c
		}
	}
	if card != nil {
		b.WriteString("\n" + cardText(*card))
	}
	return b.String()
}

func cardText(c slackio.Card) string {
	var b strings.Builder
	fmt.Fprintf(&b, "== card\nheader: %s\ntext: %s\n", c.Header, c.Text)
	for _, s := range c.Sections {
		b.WriteString("-- section\n" + s + "\n")
	}
	for _, btn := range c.Buttons {
		style := ""
		switch {
		case btn.Primary:
			style = " primary"
		case btn.Danger:
			style = " danger"
		}
		fmt.Fprintf(&b, "-- button %s %s=%s%s\n", btn.Label, btn.ActionID, btn.Value, style)
	}
	return b.String()
}
