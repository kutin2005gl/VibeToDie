package router

import (
	"bufio"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"nexus/gateway/internal/config"
)

// Streams need a real server: ReverseProxy only aborts a broken stream under net/http.
func streamGateway(t *testing.T, upstream http.HandlerFunc, timeout, streamTimeout time.Duration) *httptest.Server {
	t.Helper()
	up := httptest.NewServer(upstream)
	t.Cleanup(up.Close)
	r := route("ai", "/api/ai", up.URL, config.AuthNone)
	r.Timeout, r.StreamTimeout = timeout, streamTimeout
	gw := httptest.NewServer(newGateway(t, r))
	t.Cleanup(gw.Close)
	return gw
}

func postSSE(t *testing.T, url string) *http.Response {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, url, strings.NewReader(`{}`))
	req.Header.Set("Accept", "text/event-stream")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { resp.Body.Close() })
	return resp
}

func TestStreamEventsArriveBeforeUpstreamFinishes(t *testing.T) {
	release := make(chan struct{})
	gw := streamGateway(t, func(w http.ResponseWriter, r *http.Request) {
		// No SSE content type on purpose: the streaming route must flush anyway
		_, _ = io.WriteString(w, "data: step 1\n\n")
		w.(http.Flusher).Flush()
		<-release
		_, _ = io.WriteString(w, "data: done\n\n")
	}, time.Second, time.Minute)

	resp := postSSE(t, gw.URL+"/api/ai/run")
	line := make(chan string, 1)
	go func() {
		s, _ := bufio.NewReader(resp.Body).ReadString('\n')
		line <- s
	}()
	select {
	case got := <-line:
		if got != "data: step 1\n" {
			t.Fatalf("first line %q", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("first event held back until the upstream finished")
	}
	close(release)
}

func TestStreamGetsStreamTimeoutNotRouteTimeout(t *testing.T) {
	gw := streamGateway(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		for range 4 {
			_, _ = io.WriteString(w, "data: tick\n\n")
			w.(http.Flusher).Flush()
			time.Sleep(50 * time.Millisecond)
		}
		_, _ = io.WriteString(w, "data: done\n\n")
	}, 50*time.Millisecond, 5*time.Second)

	body, err := io.ReadAll(postSSE(t, gw.URL+"/api/ai/run").Body)
	if err != nil || !strings.HasSuffix(string(body), "data: done\n\n") {
		t.Fatalf("stream cut by the route timeout: %q, %v", body, err)
	}
}

func TestStreamDroppedByUpstreamIsBrokenForClient(t *testing.T) {
	gw := streamGateway(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: step 1\n\n")
		w.(http.Flusher).Flush()
		panic(http.ErrAbortHandler) // upstream dies mid-stream
	}, time.Second, time.Minute)

	body, err := io.ReadAll(postSSE(t, gw.URL+"/api/ai/run").Body)
	if err == nil {
		t.Fatalf("stream ended cleanly after the upstream died: %q", body)
	}
}
