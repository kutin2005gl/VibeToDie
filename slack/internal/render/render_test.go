package render

import (
	"strings"
	"testing"
	"unicode/utf8"

	"nexus/slack/internal/nexus"
)

func TestFinalKeepsCitations(t *testing.T) {
	s := nexus.Session{Status: nexus.StatusDone, Items: []nexus.Item{{Kind: nexus.KindResult, Output: "## Hoàn tiền\n**7 ngày**\nCăn cứ: QD-CSKH-2026-03, Khoản 2.1 (QD-CSKH-2026-03#2.1) & <hết>"}}}
	got := Final(s)
	if got.State != StateDone {
		t.Fatalf("state %q", got.State)
	}
	// Bold is dropped as on the web; a heading still stands out
	for _, want := range []string{"QD-CSKH-2026-03#2.1", "*Hoàn tiền*", "7 ngày", "&amp;", "&lt;hết&gt;"} {
		if !strings.Contains(got.Text, want) {
			t.Errorf("missing %q in %q", want, got.Text)
		}
	}
}

func TestFinalStates(t *testing.T) {
	clarify := nexus.Session{Status: nexus.StatusWaiting, Items: []nexus.Item{{Kind: nexus.KindClarify, Question: "Đơn nào?"}}}
	if o := Final(clarify); o.State != StateClarify || !strings.Contains(o.Text, "Đơn nào?") {
		t.Errorf("clarify: %+v", o)
	}
	approval := nexus.Session{Status: nexus.StatusWaiting, Items: []nexus.Item{{Kind: nexus.KindApproval}}}
	if o := Final(approval); o.State != StateApproval {
		t.Errorf("approval: %+v", o)
	}
	failed := nexus.Session{Status: nexus.StatusFailed}
	if o := Final(failed); o.State != StateFailed || !strings.Contains(o.Text, "thử lần nữa") {
		t.Errorf("failed: %+v", o)
	}
	if o := Final(nexus.Session{Status: nexus.StatusDone}); o.State != StateDone || o.Text == "" {
		t.Errorf("empty result: %+v", o)
	}
}

func TestChunksSplitOnLinesAndKeepRunes(t *testing.T) {
	line := strings.Repeat("ệ", 100) + "\n"
	text := strings.Repeat(line, 100)
	parts := Chunks(text)
	if len(parts) < 2 {
		t.Fatal("long text must be split")
	}
	for _, p := range parts {
		if len(p) > maxChunk || !utf8.ValidString(p) {
			t.Fatalf("bad chunk of %d bytes", len(p))
		}
	}
	if joined := strings.Join(parts, "\n"); strings.Count(joined, "ệ") != 10000 {
		t.Fatal("text was lost")
	}
	if got := Chunks("ngắn"); len(got) != 1 || got[0] != "ngắn" {
		t.Fatalf("short text: %q", got)
	}
	if got := Chunks(strings.Repeat("ệ", 3000)); !utf8.ValidString(got[0]) {
		t.Fatal("cut inside a character")
	}
}
