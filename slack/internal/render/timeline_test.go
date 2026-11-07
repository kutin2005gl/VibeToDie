package render

import (
	"encoding/json"
	"strings"
	"testing"

	"nexus/slack/internal/nexus"
)

func ev(name string, data any) nexus.Event {
	raw, _ := json.Marshal(data)
	return nexus.Event{Name: name, Data: raw}
}

type m = map[string]any

func step(id, agent, label string) m { return m{"id": id, "agent": agent, "label": label} }

// coordinatedRun is one Coordinator run as events and as the session the server saves after it:
// a first plan where a step is sent back once and another asks for a new plan, then a second plan
// whose two steps run at the same time (their events interleave), one failing without an answer
// and one skipped because it depends on the failed one.
func coordinatedRun() ([]nexus.Event, nexus.Session) {
	events := []nexus.Event{
		ev("route", m{"branch": "multi", "target": "coordinator"}),
		ev("phase", m{"phase": "plan"}),
		ev("plan", m{"steps": []m{step("a", "orders", "Tra đơn DH1014"), step("b", "customer_service", "Soạn email")}}),
		ev("step_started", m{"id": "a", "agent": "orders", "label": "Tra đơn DH1014"}),
		ev("tool_call", m{"agent": "orders", "name": "get_order", "step_id": "a"}),
		ev("step_done", m{"id": "a", "agent": "orders", "summary": "x"}),
		ev("phase", m{"phase": "review"}),
		ev("step_reviewed", m{"id": "a", "agent": "orders", "decision": "retry", "note": nil}),
		ev("step_done", m{"id": "a", "agent": "orders", "summary": "y"}),
		ev("step_reviewed", m{"id": "a", "agent": "orders", "decision": "accept", "note": "Đúng số tiền [paid_amount]."}),
		ev("step_accepted", m{"id": "a", "agent": "orders", "summary": "y"}),
		ev("step_started", m{"id": "b", "agent": "customer_service", "label": "Soạn email"}),
		ev("step_done", m{"id": "b", "agent": "customer_service", "summary": "z"}),
		ev("step_reviewed", m{"id": "b", "agent": "customer_service", "decision": "replan", "note": "Thiếu địa chỉ email."}),
		ev("step_failed", m{"id": "b", "agent": "customer_service", "reason": "replan"}),
		ev("phase", m{"phase": "plan"}),
		ev("plan", m{"steps": []m{step("c", "customer_service", "Soạn email lần 2"), step("d", "knowledge", "Tra quy định"), step("e", "orders", "Ghi chú đơn")}}),
		ev("step_started", m{"id": "c", "agent": "customer_service", "label": "Soạn email lần 2"}),
		ev("step_started", m{"id": "d", "agent": "knowledge", "label": "Tra quy định"}),
		ev("step_failed", m{"id": "d", "agent": "knowledge", "reason": "the agent's model could not run"}),
		ev("step_done", m{"id": "c", "agent": "customer_service", "summary": "w"}),
		ev("step_reviewed", m{"id": "c", "agent": "customer_service", "decision": "accept", "note": ""}),
		ev("step_accepted", m{"id": "c", "agent": "customer_service", "summary": "w"}),
		ev("step_skipped", m{"id": "e", "agent": "orders", "reason": "depends on 'd'"}),
		ev("phase", m{"phase": "finalize"}),
	}
	review := func(decision string, note any) m { return m{"decision": decision, "note": note, "seconds": 1.2} }
	result := m{
		"final_response": "Đã soạn email.",
		"plan":           m{"steps": []m{step("c", "customer_service", "Soạn email lần 2"), step("d", "knowledge", "Tra quy định"), step("e", "orders", "Ghi chú đơn")}},
		"steps": []m{
			{"id": "c", "agent": "customer_service", "status": "accepted", "answers": []m{{"result": m{}, "review": review("accept", "")}}},
			{"id": "d", "agent": "knowledge", "status": "failed", "answers": []m{}},
			{"id": "e", "agent": "orders", "status": "skipped", "answers": []m{}},
		},
		"replans": []m{{
			"plan":    m{"steps": []m{step("a", "orders", "Tra đơn DH1014"), step("b", "customer_service", "Soạn email")}},
			"failure": "step 'b'",
			"steps": []m{
				{"id": "a", "agent": "orders", "status": "accepted", "answers": []m{
					{"result": m{}, "review": review("retry", nil)},
					{"result": m{}, "review": review("accept", "Đúng số tiền [paid_amount].")},
				}},
				{"id": "b", "agent": "customer_service", "status": "failed", "answers": []m{
					{"result": m{}, "review": review("replan", "Thiếu địa chỉ email.")},
				}},
			},
		}},
	}
	raw, _ := json.Marshal(result)
	s := nexus.Session{Status: nexus.StatusDone, Items: []nexus.Item{
		{Kind: "request", Body: "Gửi email hoàn tiền DH1014"},
		{Kind: "route", Agent: "coordinator", Branch: "multi"},
		{Kind: nexus.KindResult, Agent: "coordinator", Result: raw},
	}}
	return events, s
}

func TestTimelineFromEventsAndFromSessionAgree(t *testing.T) {
	events, s := coordinatedRun()
	live := &Timeline{}
	for _, e := range events {
		live.Add(e)
	}
	saved := FromSession(s)
	if live.String() != saved.String() {
		t.Fatalf("events and saved session disagree:\n--- events\n%s\n--- session\n%s", live, saved)
	}
	if live.Final(StateDone) != saved.Final(StateDone) {
		t.Fatal("final texts disagree")
	}

	got := live.String()
	for _, want := range []string{
		"↪️ Chuyển cho Điều phối",
		"📋 Điều phối lập kế hoạch 2 bước",
		"▶️ *Tra đơn DH1014* · Đơn hàng",
		"↩️ Điều phối: Cần làm lại phần này.",
		"✅ Điều phối: Đúng số tiền.",        // the note, without claim keys
		"🔁 Điều phối: Thiếu địa chỉ email.", // sent to a new plan: no "not done" line for it
		"🔁 " + replanned,
		"📋 Điều phối lập kế hoạch 3 bước",
		"✅ Điều phối: Đã duyệt.", // no note: the decision's label
		"❌ " + notDone,           // d failed without an answer
		"⏭️ Bỏ qua: Ghi chú đơn (bước trước nó không thành công)",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q in\n%s", want, got)
		}
	}
	if strings.Count(got, notDone) != 1 || strings.Contains(got, "get_order") {
		t.Errorf("one failed step, and no tools:\n%s", got)
	}
	// Plan order, not event order: c's lines come before d's although d failed first
	if strings.Index(got, "Soạn email lần 2") > strings.Index(got, "Tra quy định") {
		t.Errorf("steps out of plan order:\n%s", got)
	}
}

func TestTimelineLiveSaysWhatHappensNow(t *testing.T) {
	tl := &Timeline{}
	if got := tl.Live(); got != "⏳ "+routing {
		t.Fatalf("before routing: %q", got)
	}
	tl.Add(ev("route", m{"branch": "single", "target": "orders"}))
	if got := tl.Live(); !strings.HasSuffix(got, "⏳ Đơn hàng đang xử lý…") || !strings.HasPrefix(got, "↪️ Chuyển cho Đơn hàng") {
		t.Fatalf("worker: %q", got)
	}

	tl = &Timeline{}
	tl.Add(ev("phase", m{"phase": "plan"})) // a clarify answer goes straight to the Coordinator
	if got := tl.Live(); got != "⏳ Điều phối đang lập kế hoạch…" {
		t.Fatalf("planning: %q", got)
	}
	tl.Add(ev("plan", m{"steps": []m{step("a", "orders", "Tra đơn"), step("b", "knowledge", "Tra quy định")}}))
	tl.Add(ev("step_started", m{"id": "a", "agent": "orders"}))
	tl.Add(ev("step_started", m{"id": "b", "agent": "knowledge"}))
	if got := tl.Live(); !strings.HasSuffix(got, "⏳ Đang làm: Tra đơn, Tra quy định") {
		t.Fatalf("parallel steps: %q", got)
	}
	tl.Add(ev("step_done", m{"id": "a", "agent": "orders"}))
	tl.Add(ev("step_done", m{"id": "b", "agent": "knowledge"}))
	tl.Add(ev("phase", m{"phase": "review"}))
	if got := tl.Live(); !strings.HasSuffix(got, "⏳ Điều phối đang xem lại câu trả lời…") {
		t.Fatalf("review: %q", got)
	}
	tl.Add(ev("route", []int{1})) // bad data changes nothing
	if final := tl.Final(StateApproval); strings.Contains(final, "⏳") || !strings.HasSuffix(final, closing[StateApproval]) {
		t.Fatalf("final: %q", final)
	}
}

func TestFromSessionReadsTheLastTurnOnly(t *testing.T) {
	_, first := coordinatedRun()
	s := nexus.Session{Status: nexus.StatusDone, Items: append(first.Items,
		nexus.Item{Kind: "request", Body: "Đơn DH1014 giao chưa?"},
		nexus.Item{Kind: "route", Agent: "orders", Branch: "single"},
		nexus.Item{Kind: nexus.KindResult, Agent: "orders", Result: json.RawMessage(`{"summary":"Đã giao.","plan":{"steps":[{"id":"x"}]}}`)},
	)}
	if got := FromSession(s).String(); got != "↪️ Chuyển cho Đơn hàng" {
		t.Fatalf("got %q", got)
	}
	if got := FromSession(nexus.Session{}).Final(StateFailed); got != closing[StateFailed] {
		t.Fatalf("empty session: %q", got)
	}
}

func TestLongTimelineFitsOneMessage(t *testing.T) {
	tl := &Timeline{}
	tl.Add(ev("route", m{"target": "coordinator"}))
	tl.Add(ev("plan", m{"steps": []m{step("a", "orders", "Tra đơn")}}))
	tl.Add(ev("step_started", m{"id": "a", "agent": "orders"}))
	for i := 0; i < 200; i++ {
		tl.Add(ev("step_done", m{"id": "a", "agent": "orders"}))
		tl.Add(ev("step_reviewed", m{"id": "a", "agent": "orders", "decision": "retry", "note": strings.Repeat("dài ", 20)}))
	}
	got := tl.String()
	if len(got) > maxChunk || !strings.HasPrefix(got, "↪️ Chuyển cho Điều phối\n…\n") {
		t.Fatalf("%d bytes, starts %q", len(got), got[:40])
	}
}
