package render

import (
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"testing"
)

// The frontend lives beside slack/ in the repo; a checkout or image without it skips these tests.
var frontend = filepath.Join("..", "..", "..", "frontend", "src")

func readFrontend(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(frontend, path))
	if err != nil {
		t.Skipf("frontend not found: %v", err)
	}
	return string(b)
}

// tsConst is the string a `const NAME = '...'` holds.
func tsConst(t *testing.T, src, name string) string {
	t.Helper()
	m := regexp.MustCompile(`(?m)^const ` + name + ` = '([^']*)'`).FindStringSubmatch(src)
	if m == nil {
		t.Fatalf("const %s not found in the frontend", name)
	}
	return m[1]
}

// tsTable reads a `const NAME: Record<string, string> = { key: 'value', ... }` table. Keys may be
// bare, quoted or a [CONST] naming one of consts.
func tsTable(t *testing.T, src, name string, consts map[string]string) map[string]string {
	t.Helper()
	m := regexp.MustCompile(`(?s)const ` + name + `: Record<string, string> = \{(.*?)\}`).FindStringSubmatch(src)
	if m == nil {
		t.Fatalf("table %s not found in the frontend", name)
	}
	out := map[string]string{}
	entry := regexp.MustCompile(`(?:'([^']*)'|\[(\w+)\]|(\w+)):\s*'([^']*)'`)
	for _, e := range entry.FindAllStringSubmatch(m[1], -1) {
		key := e[1] + e[3]
		if e[2] != "" {
			key = consts[e[2]]
		}
		out[key] = e[4]
	}
	return out
}

func TestAgentNamesMatchFrontend(t *testing.T) {
	src := readFrontend(t, "mocks/agentCatalog.ts")
	web := map[string]string{}
	for _, m := range regexp.MustCompile(`id: '(\w+)', name: '([^']+)'`).FindAllStringSubmatch(src, -1) {
		web[m[1]] = m[2]
	}
	if !reflect.DeepEqual(web, agentNames) {
		t.Errorf("agent names differ\nweb: %v\ngo:  %v", web, agentNames)
	}
}

func TestLabelsMatchFrontend(t *testing.T) {
	src := readFrontend(t, "api/sessions.ts")
	consts := map[string]string{}
	for name, goValue := range map[string]string{"NOT_DONE": notDone, "ROUTING": routing, "REPLANNED": replanned, "STOPPED": stopped} {
		consts[name] = tsConst(t, src, name)
		if consts[name] != goValue {
			t.Errorf("%s: web %q, go %q", name, consts[name], goValue)
		}
	}
	for name, goTable := range map[string]map[string]string{"REVIEWED": reviewed, "failedText": failedText, "actionTitle": actionTitle} {
		if web := tsTable(t, src, name, consts); !reflect.DeepEqual(web, goTable) {
			t.Errorf("%s differs\nweb: %v\ngo:  %v", name, web, goTable)
		}
	}
	// Headings and draft titles the web writes inline
	for _, s := range []string{toConfirm, proposed, "Gửi khách", "Nội bộ"} {
		if !regexp.MustCompile(`'` + regexp.QuoteMeta(s) + `'`).MatchString(src) {
			t.Errorf("%q not found in the frontend", s)
		}
	}
}
