package render

import (
	"encoding/json"
	"fmt"
	"strings"

	"nexus/slack/internal/nexus"
)

// Timeline is the milestones of one run, as the placeholder message shows them in place of a bare
// "Đang xử lý…": who Jev chose, the Coordinator's plan, and for each step its start, every answer,
// the Coordinator's review (redone answers included), failure or skip. Tools and model calls are
// left out, as on the web.
//
// It is built from the run's events (Add) or from the saved session (FromSession), and both give
// the same text: steps are listed in plan order, not in the order parallel steps happened to send
// their events. The zero value is an empty timeline.
type Timeline struct {
	route string // agent Jev chose; empty when the run went straight to the Coordinator
	plans []*planBlock
	phase string // what the Coordinator does now, live only
}

type planBlock struct {
	steps   []*stepBlock
	dropped bool // replaced by a new plan
}

type stepBlock struct {
	id, agent, label string
	lines            []string
	answers          int
	lastReview       string
	running          bool
}

func (p *planBlock) step(id, agent string) *stepBlock {
	for _, s := range p.steps {
		if s.id == id {
			return s
		}
	}
	s := &stepBlock{id: id, agent: agent} // not in the plan: kept anyway, at the end
	p.steps = append(p.steps, s)
	return s
}

func (s *stepBlock) name() string {
	if s.label != "" {
		return s.label
	}
	return AgentName(s.agent)
}

func (s *stepBlock) start() {
	s.running = true
	s.lines = append(s.lines, "▶️ *"+Mrkdwn(s.name())+"* · "+Mrkdwn(AgentName(s.agent)))
}

func (s *stepBlock) answered() {
	s.running = false
	s.answers++
	s.lines = append(s.lines, "      💬 "+Mrkdwn(AgentName(s.agent))+" đã trả lời")
}

var reviewMark = map[string]string{"accept": "✅", "retry": "↩️", "replan": "🔁", "clarify": "❓"}

func (s *stepBlock) review(decision, note string) {
	s.lastReview = decision
	s.running = decision == "retry" // sent back: the agent works on it again at once
	text := strings.Join(lines(note), " ")
	if text == "" {
		text = reviewText(decision)
	}
	mark, ok := reviewMark[decision]
	if !ok {
		mark = reviewMark["accept"]
	}
	s.lines = append(s.lines, "      "+mark+" "+AgentName("coordinator")+": "+Mrkdwn(clipRunes(text, 300)))
}

func (s *stepBlock) fail() {
	s.running = false
	// A step the Coordinator sent to a new plan is told by the replan line; any other failure
	// means the step ran out of attempts without an answer that passed
	if s.lastReview != "replan" {
		s.lines = append(s.lines, "      ❌ "+notDone)
	}
}

func (s *stepBlock) skip() {
	s.running = false
	s.lines = append(s.lines, "⏭️ Bỏ qua: "+Mrkdwn(s.name())+" (bước trước nó không thành công)")
}

type planStep struct {
	ID    string `json:"id"`
	Agent string `json:"agent"`
	Label string `json:"label"`
}

func (t *Timeline) plan(steps []planStep) *planBlock {
	if p := t.current(); p != nil {
		p.dropped = true
	}
	p := &planBlock{}
	for _, s := range steps {
		p.steps = append(p.steps, &stepBlock{id: s.ID, agent: s.Agent, label: s.Label})
	}
	t.plans = append(t.plans, p)
	return p
}

func (t *Timeline) current() *planBlock {
	if len(t.plans) == 0 {
		return nil
	}
	return t.plans[len(t.plans)-1]
}

// stepOf finds the step an event is about, in the plan running now.
func (t *Timeline) stepOf(id, agent string) *stepBlock {
	p := t.current()
	if p == nil {
		p = &planBlock{}
		t.plans = append(t.plans, p)
	}
	return p.step(id, agent)
}

// Add takes one event of the run; events that are no milestone change nothing.
func (t *Timeline) Add(ev nexus.Event) {
	var d struct {
		Target   string     `json:"target"`
		Phase    string     `json:"phase"`
		Steps    []planStep `json:"steps"`
		ID       string     `json:"id"`
		Agent    string     `json:"agent"`
		Label    string     `json:"label"`
		Decision string     `json:"decision"`
		Note     string     `json:"note"`
	}
	if json.Unmarshal(ev.Data, &d) != nil {
		return
	}
	switch ev.Name {
	case "route":
		t.route = d.Target
	case "phase":
		t.phase = d.Phase
	case "plan":
		t.plan(d.Steps)
		t.phase = ""
	case "step_started":
		s := t.stepOf(d.ID, d.Agent)
		if s.label == "" {
			s.label = d.Label
		}
		s.start()
	case "step_done":
		t.stepOf(d.ID, d.Agent).answered()
	case "step_reviewed":
		t.stepOf(d.ID, d.Agent).review(d.Decision, d.Note)
	case "step_accepted":
		// An older server sends no step_done: the answer arrives when it is accepted
		if s := t.stepOf(d.ID, d.Agent); s.answers == 0 {
			s.answered()
			s.review("accept", "")
		}
	case "step_failed":
		t.stepOf(d.ID, d.Agent).fail()
	case "step_skipped":
		t.stepOf(d.ID, d.Agent).skip()
	}
}

// FromSession rebuilds the timeline of the session's last turn (from its last request or clarify
// answer on) from what the server saved: the route item and the Coordinator's plan, steps and
// dropped plans in the result.
func FromSession(s nexus.Session) *Timeline {
	t := &Timeline{}
	start := 0
	for i, item := range s.Items {
		if item.Kind == "request" || item.Kind == "reply" {
			start = i + 1
		}
	}
	for _, item := range s.Items[start:] {
		switch item.Kind {
		case "route":
			t.route = item.Agent
		case nexus.KindResult:
			if item.Agent != "coordinator" {
				continue
			}
			var run savedRun
			if json.Unmarshal(item.Result, &run) != nil || run.Plan == nil {
				continue
			}
			for _, rp := range run.Replans {
				t.plan(rp.Plan.Steps).apply(rp.Steps)
			}
			t.plan(run.Plan.Steps).apply(run.Steps)
		}
	}
	return t
}

type savedRun struct {
	Plan    *savedPlan    `json:"plan"`
	Steps   []savedStep   `json:"steps"`
	Replans []savedReplan `json:"replans"`
}

type savedPlan struct {
	Steps []planStep `json:"steps"`
}

type savedReplan struct {
	Plan  savedPlan   `json:"plan"`
	Steps []savedStep `json:"steps"`
}

// savedStep is a step record of the Coordinator (ai/app/core/coordinator.py, Outcome.steps).
type savedStep struct {
	ID      string `json:"id"`
	Agent   string `json:"agent"`
	Status  string `json:"status"` // accepted | failed | skipped | clarify
	Answers []struct {
		Review *struct {
			Decision string `json:"decision"`
			Note     string `json:"note"`
		} `json:"review"`
	} `json:"answers"`
}

// apply replays saved step records as the events they came from would have.
func (p *planBlock) apply(records []savedStep) {
	for _, r := range records {
		s := p.step(r.ID, r.Agent)
		if r.Status == "skipped" {
			s.skip()
			continue
		}
		s.start()
		for _, a := range r.Answers {
			s.answered()
			if a.Review != nil {
				s.review(a.Review.Decision, a.Review.Note)
			}
		}
		if r.Status == "failed" {
			s.fail()
		}
	}
}

// Empty reports whether no milestone has been seen.
func (t *Timeline) Empty() bool { return t.route == "" && len(t.plans) == 0 }

// String is every milestone, one per line.
func (t *Timeline) String() string {
	var out []string
	if t.route != "" {
		out = append(out, "↪️ Chuyển cho "+Mrkdwn(AgentName(t.route)))
	}
	for _, p := range t.plans {
		if len(p.steps) > 0 {
			out = append(out, fmt.Sprintf("📋 %s lập kế hoạch %d bước", AgentName("coordinator"), len(p.steps)))
		}
		for _, s := range p.steps {
			out = append(out, s.lines...)
		}
		if p.dropped {
			out = append(out, "🔁 "+replanned)
		}
	}
	return fit(out)
}

var phaseText = map[string]string{
	"plan":     "Điều phối đang lập kế hoạch…",
	"review":   "Điều phối đang xem lại câu trả lời…",
	"finalize": "Điều phối đang tổng hợp kết quả…",
}

// Live is the timeline while the run goes on, ending with what is happening now.
func (t *Timeline) Live() string {
	return strings.TrimLeft(t.String()+"\n⏳ "+t.now(), "\n")
}

func (t *Timeline) now() string {
	if p := t.current(); p != nil {
		var working []string
		for _, s := range p.steps {
			if s.running {
				working = append(working, Mrkdwn(s.name()))
			}
		}
		if len(working) > 0 {
			return "Đang làm: " + strings.Join(working, ", ")
		}
	}
	if text, ok := phaseText[t.phase]; ok {
		return text
	}
	switch {
	case len(t.plans) > 0:
		return "Điều phối đang xem xét…"
	case t.route == "":
		return routing
	case t.route == "coordinator":
		return phaseText["plan"]
	}
	return Mrkdwn(AgentName(t.route)) + " đang xử lý…"
}

// closing is the last line of a finished run's timeline: where the turn stopped.
var closing = map[string]string{
	StateDone:     "✅ Xong. Kết quả ở tin bên dưới.",
	StateClarify:  "❓ Cần bạn trả lời thêm (tin bên dưới).",
	StateApproval: "🔒 Đang chờ bạn duyệt (thẻ bên dưới).",
	StateFailed:   "⚠️ Không hoàn thành (xem tin bên dưới).",
}

// Final is the timeline of a run that stopped in the given state (one of the State constants).
func (t *Timeline) Final(state string) string {
	end, ok := closing[state]
	if !ok {
		end = closing[StateDone]
	}
	return strings.TrimLeft(t.String()+"\n"+end, "\n")
}

// fit joins lines and, past one message's worth, drops the oldest lines after the first.
func fit(lines []string) string {
	text := strings.Join(lines, "\n")
	for len(text) > maxChunk && len(lines) > 2 {
		lines = append(lines[:1], lines[2:]...)
		text = lines[0] + "\n…\n" + strings.Join(lines[1:], "\n")
	}
	return text
}

func clipRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}
