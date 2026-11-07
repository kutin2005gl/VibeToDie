import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import session_store
from app.main import app
from app.services import run as run_service
from app.store.sessions import InMemorySessionStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    monkeypatch.setenv("AI_TRUST_IDENTITY_HEADERS", "1")
    monkeypatch.setenv("AI_ALLOW_PROVIDER_OVERRIDE", "1")
    store = InMemorySessionStore()
    app.dependency_overrides[session_store] = lambda: store
    yield
    app.dependency_overrides.clear()


def user(uid: str) -> dict[str, str]:
    return {"X-User-Id": uid, "X-User-Departments": "cskh"}


def outcome(result: dict | None = None, pending: list | None = None, route: dict | None = None) -> dict:
    return {"provider": "fake", "model": "fake", "output": "answer", "input_tokens": 0, "output_tokens": 0,
            "agent": "customer_service", "steps": 1, "result": result or {"status": "done"},
            "pending_actions": pending or [], "route": route}


def scripted(monkeypatch, *outcomes):
    """Replace the /run flow with `outcomes`, one per call; returns the requests it got."""
    seen = []

    async def run(req, ctx, emit=None, **_):
        seen.append(req)
        out = outcomes[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(run_service, "run", run)
    return seen


def create(uid="u1", text="máy lỗi loa"):
    return client.post("/api/sessions", json={"text": text, "provider": "fake"}, headers=user(uid))


def get(session_id: int, uid="u1"):
    return client.get(f"/api/sessions/{session_id}", headers=user(uid))


def kinds(session: dict) -> list[str]:
    return [i["kind"] for i in session["items"]]


def test_create_answers_running_then_saves_the_run_for_its_owner_only(monkeypatch):
    scripted(monkeypatch, outcome(route={"branch": "single"}))
    resp = create()
    # The run goes on after the response: the client sees it running and polls
    assert resp.status_code == 201 and resp.json()["status"] == "running"
    assert kinds(resp.json()) == ["request"]

    s = get(resp.json()["id"]).json()
    assert s["status"] == "done" and kinds(s) == ["request", "route", "result"]
    assert [x["id"] for x in client.get("/api/sessions", headers=user("u1")).json()] == [s["id"]]
    assert client.get("/api/sessions", headers=user("u2")).json() == []


def test_another_users_session_is_not_found(monkeypatch):
    scripted(monkeypatch, outcome())
    sid = create("u1").json()["id"]
    assert get(sid, "u2").status_code == 404
    answer = client.post(f"/api/sessions/{sid}/answer", json={"answer": "x"}, headers=user("u2"))
    assert answer.status_code == 404


def test_bad_provider_is_refused_before_anything_is_saved(monkeypatch):
    monkeypatch.delenv("AI_ALLOW_FAKE")
    assert create().status_code == 503
    assert client.get("/api/sessions", headers=user("u1")).json() == []


def test_clarify_answer_is_saved_then_rerun_with_the_question(monkeypatch):
    seen = scripted(monkeypatch, outcome({"decision": "clarify", "clarify_question": "Đơn nào?"},
                                         route={"branch": "clarify"}), outcome())
    sid = create().json()["id"]
    assert get(sid).json()["status"] == "waiting"

    resp = client.post(f"/api/sessions/{sid}/answer", json={"answer": "DH1001"}, headers=user("u1"))
    assert resp.status_code == 200 and resp.json()["status"] == "running"
    assert resp.json()["clarifications"] == [{"question": "Đơn nào?", "answer": "DH1001"}]

    s = get(sid).json()
    assert s["status"] == "done" and kinds(s) == ["request", "route", "clarify", "reply", "result"]
    assert s["items"][2]["answer"] == "DH1001"
    assert [(c.question, c.answer) for c in seen[1].clarifications] == [("Đơn nào?", "DH1001")]


def test_answer_without_a_question_is_a_conflict(monkeypatch):
    scripted(monkeypatch, outcome())
    sid = create().json()["id"]
    resp = client.post(f"/api/sessions/{sid}/answer", json={"answer": "x"}, headers=user("u1"))
    assert resp.status_code == 409


def test_approval_is_decided_once(monkeypatch):
    scripted(monkeypatch, outcome(pending=[{"id": "c1", "name": "issue_refund", "arguments": {}}]))
    sid = create().json()["id"]
    assert get(sid).json()["status"] == "waiting"

    decide = lambda: client.post(f"/api/sessions/{sid}/decision", json={"approve": True}, headers=user("u1"))
    first = decide()
    assert first.status_code == 200 and first.json()["status"] == "done"
    assert first.json()["items"][-1]["decision"]["value"] == "yes"
    assert decide().status_code == 409


EMAIL = {"order_id": "DH1002", "to": "binh.tran@example.com", "subject": "Xin lỗi", "body": "Kính gửi Anh/Chị Bình"}


def mail(monkeypatch, error: str | None = None) -> list:
    """Replace sending with a record of each attempt; `error` makes every attempt fail."""
    from app.core.tools import ToolError
    from app.tools import mailer
    attempts = []

    async def send(to, subject, body, key):
        attempts.append((to, subject, key))
        if error:
            raise ToolError(error, "Check by hand.")

    monkeypatch.setattr(mailer, "send", send)
    return attempts


def test_an_approved_action_runs_once(monkeypatch):
    attempts = mail(monkeypatch)
    scripted(monkeypatch, outcome(pending=[{"id": "c1", "name": "send_email", "arguments": EMAIL}]))
    sid = create().json()["id"]
    decide = lambda: client.post(f"/api/sessions/{sid}/decision", json={"approve": True}, headers=user("u1"))
    approval = decide().json()["items"][-1]
    assert approval["actions"][0]["status"] == "done"
    assert attempts == [("binh.tran@example.com", "Xin lỗi", f"{sid}:{approval['id']}:0")]
    assert decide().status_code == 409 and len(attempts) == 1


def test_a_rejected_action_never_runs(monkeypatch):
    attempts = mail(monkeypatch)
    scripted(monkeypatch, outcome(pending=[{"id": "c1", "name": "send_email", "arguments": EMAIL}]))
    sid = create().json()["id"]
    approval = client.post(f"/api/sessions/{sid}/decision", json={"approve": False}, headers=user("u1")).json()["items"][-1]
    assert "status" not in approval["actions"][0] and attempts == []


def test_a_failed_action_is_recorded_and_not_retried(monkeypatch):
    attempts = mail(monkeypatch, error="sending failed: timeout")
    scripted(monkeypatch, outcome(pending=[{"id": "c1", "name": "send_email", "arguments": EMAIL}]))
    sid = create().json()["id"]
    resp = client.post(f"/api/sessions/{sid}/decision", json={"approve": True}, headers=user("u1"))
    [action] = resp.json()["items"][-1]["actions"]
    assert resp.json()["status"] == "done" and action["status"] == "failed" and "timeout" in action["error"]
    assert len(attempts) == 1
    assert get(sid).json()["items"][-1]["actions"][0]["status"] == "failed"


def test_failed_run_is_saved_as_failed(monkeypatch):
    scripted(monkeypatch, HTTPException(status_code=502, detail="provider down"))
    s = get(create().json()["id"]).json()
    assert s["status"] == "failed"
    assert (s["items"][-1]["kind"], s["items"][-1]["body"]) == ("failed", "provider down")


def test_runs_cut_off_by_a_restart_are_failed():
    store = InMemorySessionStore()

    async def scenario():
        cut = await store.create("u1", ["cskh"], "t", "fake", [])
        waiting = await store.create("u1", ["cskh"], "t", "fake", [])
        waiting.status = "waiting"
        await store.save(waiting)
        assert await store.fail_running("restarted") == 1
        return await store.get("u1", cut.id), await store.get("u1", waiting.id)

    cut, waiting = asyncio.run(scenario())
    assert cut.status == "failed" and cut.items[-1]["body"] == "restarted"
    assert waiting.status == "waiting"


def sse(text: str) -> list[tuple[str, dict]]:
    """Events of an SSE body, skipping comments (heartbeats)."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if not line.startswith(":"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_events_of_a_finished_run_is_the_saved_session(monkeypatch):
    scripted(monkeypatch, outcome())
    sid = create().json()["id"]
    resp = client.get(f"/api/sessions/{sid}/events", headers=user("u1"))
    assert resp.headers["content-type"].startswith("text/event-stream")
    [(event, data)] = sse(resp.text)
    assert event == "session" and data["status"] == "done"


def test_a_running_session_whose_run_is_gone_is_failed_when_followed():
    # As when saving the result failed: the database says running, this process has no such run
    store = app.dependency_overrides[session_store]()
    s = asyncio.run(store.create("u1", ["cskh"], "t", "fake", [{"id": "1", "kind": "request", "at": "x", "body": "b"}]))
    [(event, data)] = sse(client.get(f"/api/sessions/{s.id}/events", headers=user("u1")).text)
    assert event == "session" and data["status"] == "failed"
    assert data["items"][-1]["kind"] == "failed"
    # Saved, so the client stops reconnecting to a run that will never end
    assert get(s.id).json()["status"] == "failed"


def test_a_finished_session_can_be_deleted_by_its_owner_only(monkeypatch):
    scripted(monkeypatch, outcome(), outcome())
    sid = create("u1").json()["id"]
    assert client.delete(f"/api/sessions/{sid}", headers=user("u2")).status_code == 404
    assert client.delete(f"/api/sessions/{sid}", headers=user("u1")).status_code == 204
    assert get(sid).status_code == 404
    assert client.get("/api/sessions", headers=user("u1")).json() == []
    # A new session never takes the deleted one's id
    assert create("u1").json()["id"] != sid


def test_stopping_a_run_cancels_its_work_and_saves_the_session_as_stopped(monkeypatch):
    from app.core.context import RequestContext
    from app.services import sessions as session_service
    from app.services.progress import PROGRESS
    from app.store.sessions import STOPPED

    finished = []

    async def endless(req, ctx, emit=None, **_):
        try:
            await asyncio.sleep(3600)  # a model call that takes forever
        finally:
            finished.append("cancelled")

    monkeypatch.setattr(run_service, "run", endless)
    store = InMemorySessionStore()

    async def scenario():
        s = await store.create("u1", ["cskh"], "t", "fake", [{"id": "1", "kind": "request", "at": "x", "body": "b"}])
        PROGRESS.start(s.id)
        run = asyncio.create_task(session_service._run(store, RequestContext(user_id="u1", departments=("cskh",)), s))
        await asyncio.sleep(0.01)  # the work has started
        assert PROGRESS.stop(s.id)
        await run
        assert not PROGRESS.stop(s.id)  # nothing runs any more
        return await store.get("u1", s.id)

    saved = asyncio.run(scenario())
    assert finished == ["cancelled"]  # the model call itself was cut short, nothing more is spent
    assert saved.status == "failed" and saved.items[-1]["body"] == STOPPED


def test_stopping_a_session_that_is_not_running_is_a_conflict(monkeypatch):
    scripted(monkeypatch, outcome())
    sid = create().json()["id"]
    assert client.post(f"/api/sessions/{sid}/stop", headers=user("u1")).status_code == 409
    assert client.post(f"/api/sessions/{sid}/stop", headers=user("u2")).status_code == 404


def test_a_running_session_cannot_be_deleted():
    store = app.dependency_overrides[session_store]()
    s = asyncio.run(store.create("u1", ["cskh"], "t", "fake", []))
    assert client.delete(f"/api/sessions/{s.id}", headers=user("u1")).status_code == 409
    assert asyncio.run(store.get("u1", s.id)) is not None


def test_events_of_another_users_session_is_not_found(monkeypatch):
    scripted(monkeypatch, outcome())
    sid = create("u1").json()["id"]
    assert client.get(f"/api/sessions/{sid}/events", headers=user("u2")).status_code == 404


def test_the_run_saves_the_tools_it_called_as_trace(monkeypatch):
    async def run(req, ctx, emit, **_):
        emit("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order"})
        emit("tool_result", {"agent": "orders", "step": 1, "id": "c1", "is_error": True})
        return outcome()
    monkeypatch.setattr(run_service, "run", run)
    s = get(create().json()["id"]).json()
    assert s["items"][-1]["trace"] == [{"agent": "orders", "name": "lookup_order", "id": "c1", "ok": False}]


ADMIN = {"X-User-Id": "boss", "X-User-Departments": "executive"}


def llm_call(cost):
    return {"agent": "orders", "step": 1, "model": "m", "prompt_tokens": 1000, "completion_tokens": 100,
            "cost_usd": cost, "duration_ms": 5, "attempts": 1, "finish_reason": "tool_calls", "text": "Looking"}


def test_admins_get_the_full_trace_and_the_cost_split_evenly_among_departments(monkeypatch):
    async def run(req, ctx, emit, **_):
        emit("llm_call", llm_call(0.002))
        emit("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order",
                           "arguments": '{"order_id": "DH1001"}'})
        emit("tool_result", {"agent": "orders", "step": 1, "id": "c1", "is_error": True, "content": "no order DH1001"})
        emit("llm_call", llm_call(None))
        return outcome()
    monkeypatch.setattr(run_service, "run", run)
    two = {"X-User-Id": "u1", "X-User-Departments": "cskh,it"}
    sid = client.post("/api/sessions", json={"text": "x", "provider": "fake"}, headers=two).json()["id"]

    # Staff never see what the tools got and returned
    assert "DH1001" not in client.get(f"/api/sessions/{sid}", headers=two).text
    assert client.get("/api/admin/usage", headers=two).status_code == 403

    usage = {u["department"]: u for u in client.get("/api/admin/usage", headers=ADMIN).json()}
    assert set(usage) == {"cskh", "it"}
    assert usage["cskh"]["cost_usd"] == pytest.approx(0.001) and usage["it"]["input_tokens"] == pytest.approx(1000)
    assert usage["cskh"]["sessions"] == 1 and usage["cskh"]["unpriced_calls"] == 1
    [u1] = client.get("/api/admin/usage/it", headers=ADMIN).json()
    assert u1["user_id"] == "u1" and u1["output_tokens"] == pytest.approx(100)
    [room] = client.get("/api/admin/users/u1/sessions", headers=ADMIN).json()
    assert (room["id"], room["runs"], room["cost_usd"], room["deleted_at"]) == (sid, 1, pytest.approx(0.002), None)

    detail = client.get(f"/api/admin/sessions/{sid}", headers=ADMIN).json()
    [only] = detail["runs"]
    assert [e["event"] for e in only["trace"]] == ["llm_call", "tool_call", "tool_result", "llm_call"]
    assert only["trace"][1]["arguments"] == '{"order_id": "DH1001"}' and only["trace"][2]["content"] == "no order DH1001"
    assert client.get("/api/admin/sessions/999", headers=ADMIN).status_code == 404


def test_a_session_deleted_by_staff_stays_for_admins(monkeypatch):
    async def run(req, ctx, emit, **_):
        emit("llm_call", llm_call(0.002))
        return outcome()
    monkeypatch.setattr(run_service, "run", run)
    sid = create().json()["id"]
    assert client.delete(f"/api/sessions/{sid}", headers=user("u1")).status_code == 204
    [room] = client.get("/api/admin/users/u1/sessions", headers=ADMIN).json()
    assert room["deleted_at"] is not None
    assert client.get("/api/admin/usage", headers=ADMIN).json()[0]["cost_usd"] == pytest.approx(0.002)
    assert [e["event"] for e in client.get(f"/api/admin/sessions/{sid}", headers=ADMIN).json()["runs"][0]["trace"]] == [
        "llm_call"]


def test_a_failed_run_keeps_its_trace_and_each_run_is_saved_once(monkeypatch):
    scripted(monkeypatch, HTTPException(status_code=502, detail="provider down"))
    sid = create().json()["id"]
    [only] = client.get(f"/api/admin/sessions/{sid}", headers=ADMIN).json()["runs"]
    assert only["trace"][-1]["event"] == "run_failed" and only["trace"][-1]["body"] == "provider down"

    store = app.dependency_overrides[session_store]()
    usage = {"input_tokens": 10, "output_tokens": 1, "cost_usd": 0.5, "unpriced_calls": 0}
    asyncio.run(store.save_run(sid, 0, only["started_at"], [], usage))
    asyncio.run(store.save_run(sid, 0, only["started_at"], [], usage))  # a retry replaces the run
    assert client.get("/api/admin/usage", headers=ADMIN).json()[0]["cost_usd"] == pytest.approx(0.5)


def test_sessions_saved_without_departments_are_billed_to_the_unknown_department():
    store = app.dependency_overrides[session_store]()
    asyncio.run(store.create("u1", [], "t", "fake", []))
    [unknown] = client.get("/api/admin/usage", headers=ADMIN).json()
    assert unknown["department"] == "-" and unknown["sessions"] == 1


@pytest.mark.parametrize("departments, shown", [
    (("cskh",), [("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order"})]),
    (("executive",), [("llm_call", llm_call(0.1)),
                      ("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order", "arguments": "{}"})]),
])
def test_an_admin_following_their_own_room_gets_every_event_and_field(monkeypatch, departments, shown):
    from app.core.context import RequestContext
    from app.services import sessions as session_service
    from app.services.progress import PROGRESS

    async def run(req, ctx, emit, **_):
        emit("llm_call", llm_call(0.1))
        emit("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order", "arguments": "{}"})
        return outcome()
    monkeypatch.setattr(run_service, "run", run)
    published = []
    monkeypatch.setattr(PROGRESS, "publish", lambda sid, event, data: published.append((event, data)))
    store = InMemorySessionStore()

    async def scenario():
        s = await store.create("u1", list(departments), "t", "fake", [{"id": "1", "kind": "request", "at": "x", "body": "b"}])
        PROGRESS.start(s.id)
        await session_service._run(store, RequestContext(user_id="u1", departments=departments), s)

    asyncio.run(scenario())
    assert published == shown


def roomed(monkeypatch, *outcomes):
    """Like `scripted`, also recording the room context each run read (None on a room's first request)."""
    seen = []

    async def run(req, ctx, emit=None, room=None, **_):
        seen.append((req, room))
        out = outcomes[len(seen) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(run_service, "run", run)
    return seen


def message(sid, text="Hoàn tiền cho đơn đó", uid="u1"):
    return client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=user(uid))


def fact(key, value):
    return {"key": key, "kind": "fact", "value": value, "ref": {"call_id": "lookup_order", "path": key},
            "derived_from": [], "reasoning": None}


def test_a_follow_up_runs_a_new_turn_that_reads_the_earlier_ones(monkeypatch):
    seen = roomed(monkeypatch, outcome({"status": "done", "summary": "Đơn DH1001 đã giao.",
                                        "claims": [fact("order_id", "DH1001")]}, route={"branch": "single"}),
                  outcome(route={"branch": "single"}))
    sid = create(text="Tra đơn DH1001").json()["id"]

    resp = message(sid)
    assert resp.status_code == 200 and resp.json()["status"] == "running"
    s = get(sid).json()
    assert s["status"] == "done" and kinds(s) == ["request", "route", "result", "request", "route", "result"]
    assert seen[0][1] is None and seen[1][0].text == "Hoàn tiền cho đơn đó"
    [earlier] = seen[1][1]["turns"]
    assert earlier["facts"] == {"order_id": "DH1001"} and earlier["summary"] == "Đơn DH1001 đã giao."
    assert [t["turn"] for t in s["turns"]] == [1, 2]

    # Each turn's run is kept apart for admins, none replaced
    assert [r["run"] for r in client.get(f"/api/admin/sessions/{sid}", headers=ADMIN).json()["runs"]] == [0, 1]


def test_a_follow_up_waits_for_the_turn_to_finish(monkeypatch):
    roomed(monkeypatch, outcome({"decision": "clarify", "clarify_question": "Đơn nào?"}, route={"branch": "clarify"}))
    sid = create().json()["id"]
    assert message(sid).status_code == 409  # the clarify question is answered with /answer
    assert message(sid, uid="u2").status_code == 404


def test_a_follow_up_after_a_failed_turn_knows_it_failed(monkeypatch):
    seen = roomed(monkeypatch, HTTPException(status_code=502, detail="provider down"), outcome())
    sid = create().json()["id"]
    assert message(sid, "Thử lại").status_code == 200
    [failed] = seen[1][1]["turns"]
    assert (failed["outcome"], failed["summary"]) == ("failed", "provider down")


def test_clarify_rounds_start_again_on_each_turn(monkeypatch):
    seen = roomed(monkeypatch, outcome({"decision": "clarify", "clarify_question": "Đơn nào?"}), outcome(),
                  outcome({"decision": "clarify", "clarify_question": "Khách nào?"}), outcome())
    sid = create().json()["id"]
    client.post(f"/api/sessions/{sid}/answer", json={"answer": "DH1001"}, headers=user("u1"))
    message(sid)
    resp = client.post(f"/api/sessions/{sid}/answer", json={"answer": "Anh A"}, headers=user("u1"))
    assert resp.status_code == 200
    assert [(c.question, c.answer) for c in seen[3][0].clarifications] == [("Khách nào?", "Anh A")]
    # The answered turn's run text is its own request, not the room's first
    assert seen[3][0].text == "Hoàn tiền cho đơn đó"
    runs = client.get(f"/api/admin/sessions/{sid}", headers=ADMIN).json()["runs"]
    assert [r["run"] for r in runs] == [0, 1, 2, 3]


def test_the_approval_decision_is_kept_for_later_turns(monkeypatch):
    seen = roomed(monkeypatch, outcome(pending=[{"id": "c1", "name": "issue_refund", "arguments": {}}]), outcome())
    sid = create().json()["id"]
    assert message(sid).status_code == 409  # still awaiting approval
    client.post(f"/api/sessions/{sid}/decision", json={"approve": False}, headers=user("u1"))
    message(sid)
    assert seen[1][1]["turns"][0]["outcome"] == "rejected"


def test_a_full_room_takes_no_more_requests(monkeypatch):
    from app.core import compaction
    monkeypatch.setattr(compaction, "MAX_TURNS", 2)
    roomed(monkeypatch, outcome(), outcome())
    sid = create().json()["id"]
    assert message(sid).status_code == 200
    resp = message(sid)
    assert resp.status_code == 409 and "full" in resp.json()["detail"]


def test_clients_following_a_run_never_get_admin_events_or_data():
    assert run_service.public("llm_call", llm_call(0.1)) is None
    assert run_service.public("agent_finished", {"agent": "orders"}) is None
    assert run_service.public("tool_call", {"id": "c1", "name": "lookup_order", "arguments": "{}"}) == {
        "id": "c1", "name": "lookup_order"}


def test_admin_analytics_sums_the_traces_of_the_window(monkeypatch):
    async def run(req, ctx, emit, **_):
        emit("llm_call", llm_call(0.002))
        emit("tool_call", {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order", "arguments": "{}"})
        emit("tool_result", {"agent": "orders", "step": 1, "id": "c1", "is_error": True, "content": "no order"})
        emit("llm_call", llm_call(None))
        return outcome()
    monkeypatch.setattr(run_service, "run", run)
    create()
    assert client.get("/api/admin/analytics", headers=user("u1")).status_code == 403
    assert client.get("/api/admin/analytics?days=0", headers=ADMIN).status_code == 422

    report = client.get("/api/admin/analytics?days=3", headers=ADMIN).json()
    assert report["stats"] == {"llm_calls": 2, "tool_calls": 1, "errors": 1, "input_tokens": 2000,
                               "output_tokens": 200, "cost_usd": pytest.approx(0.002), "unpriced_calls": 1,
                               "agents": 1, "rooms": 1, "runs": 1, "models": 1}
    assert len(report["per_day"]) == 3
    today = report["per_day"][-1]
    assert today["runs"] == 1 and today["by_agent"] == {"orders": 4}
    assert today["by_type"] == {"llm_call": 2, "tool_call": 1, "tool_result": 1}
    [agent] = report["per_agent"]
    assert (agent["agent"], agent["sessions"], agent["tool_calls"], agent["errors"]) == ("orders", 1, 1, 1)
    assert report["top_tools"] == [{"name": "lookup_order", "count": 1}]
    assert report["per_model"][0]["calls"] == 2 and report["per_room"][0]["runs"] == 1


def test_analytics_leaves_out_runs_before_the_window():
    from datetime import datetime, timedelta, timezone
    from app.services import analytics
    old = datetime.now(timezone.utc) - timedelta(days=10)
    usage = {"input_tokens": 5, "output_tokens": 1, "cost_usd": 1.0, "unpriced_calls": 0}
    runs = [{"session_id": 1, "title": "t", "run": 0, "started_at": old, "events": [], **usage}]
    report = analytics.build(runs, 7)
    assert report["stats"]["runs"] == 0 and report["stats"]["cost_usd"] == 0


def test_admin_agents_lists_the_mandates_with_their_models():
    assert client.get("/api/admin/agents", headers=user("u1")).status_code == 403
    agents = {a["name"]: a for a in client.get("/api/admin/agents", headers=ADMIN).json()}
    orders = agents["orders"]
    assert "lookup_order" in orders["tools"] and orders["model_tier"] == "standard" and orders["departments"]
    assert orders["prompt"].startswith("#") or "Orders agent" in orders["prompt"]
    assert all(isinstance(model, str) for model in orders["models"].values()) and orders["models"]
    assert "coordinator" in agents and not any(name.startswith("_") for name in agents)


def test_provider_is_the_one_an_admin_chose(monkeypatch):
    monkeypatch.delenv("AI_ALLOW_PROVIDER_OVERRIDE")
    seen = []

    async def run(req, ctx, emit=None, **_):
        seen.append(req.provider)
        return outcome()
    monkeypatch.setattr(run_service, "run", run)

    assert client.get("/api/admin/provider", headers=user("u1")).status_code == 403
    assert client.put("/api/admin/provider", json={"provider": "fake"}, headers=user("u1")).status_code == 403
    assert client.put("/api/admin/provider", json={"provider": "nope"}, headers=ADMIN).status_code == 422
    assert client.get("/api/admin/provider", headers=ADMIN).json()["provider"] == "deepseek"

    done = client.put("/api/admin/provider", json={"provider": "fake"}, headers=ADMIN).json()
    assert done["provider"] == "fake" and "fake" in done["available"]

    # Staff cannot pick another one; a clarify answer or follow-up later runs on the new choice too
    sid = client.post("/api/sessions", json={"text": "x", "provider": "anthropic"}, headers=user("u1")).json()["id"]
    assert get(sid).json()["provider"] == "fake" and seen == ["fake"]


# --- "làm lại": continue the last request that failed, or run it again -----------------------------

REDO = "làm lại đi"
REDO_ROUTE = {"branch": "redo", "target": "coordinator"}


def resumable(detail="coordinator review failed", marker=1):
    return run_service.ResumableFailure(detail, {"coordinator": {"marker": marker}, "origin": "multi", "route": None,
                                                 "escalation": None, "notes": None})


def redoable(monkeypatch, *outcomes, resumed=()):
    """Like `roomed`, but a request saying REDO is handed to `on_redo`, as Jev would; `resume` is scripted too."""
    log = {"runs": [], "resumes": []}
    queue, resume_queue = list(outcomes), list(resumed)

    async def run(req, ctx, emit=None, room=None, own=None, on_redo=None):
        log["runs"].append((req.text, [(c.question, c.answer) for c in req.clarifications], room))
        if req.text == REDO and on_redo is not None:
            return await on_redo(REDO_ROUTE)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    async def resume(req, ctx, saved, emit=None, room=None, own=None):
        log["resumes"].append((req.text, saved["coordinator"]))
        out = resume_queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(run_service, "run", run)
    monkeypatch.setattr(run_service, "resume", resume)
    return log


def stored(sid):
    return asyncio.run(app.dependency_overrides[session_store]().get("u1", sid))


def test_redo_after_a_failed_turn_continues_it_from_the_checkpoint(monkeypatch):
    log = redoable(monkeypatch, resumable(), resumed=[outcome()])
    sid = create().json()["id"]
    s = stored(sid)
    assert s.status == "failed" and s.checkpoint["coordinator"] == {"marker": 1} and s.checkpoint["text"] == "máy lỗi loa"

    assert message(sid, REDO).status_code == 200
    assert log["resumes"] == [("máy lỗi loa", {"marker": 1})]
    assert [r[0] for r in log["runs"]] == ["máy lỗi loa", REDO]  # the request is not planned again
    s = stored(sid)
    assert s.status == "done" and s.checkpoint is None
    # The thread says what the turn did, and the room remembers the request, not the words "làm lại"
    assert s.items[-1]["kind"] == "result" and s.turns[-1]["request"] == "máy lỗi loa"


def test_redo_after_a_done_turn_runs_the_request_again_without_the_last_turn_in_the_room(monkeypatch):
    log = redoable(monkeypatch, outcome(), outcome())
    sid = create().json()["id"]
    assert message(sid, REDO).status_code == 200
    assert log["resumes"] == []
    assert [(r[0], r[2]) for r in log["runs"][1:]] == [(REDO, log["runs"][1][2]), ("máy lỗi loa", None)]
    assert stored(sid).status == "done"


def test_redo_twice_still_redoes_the_first_request(monkeypatch):
    log = redoable(monkeypatch, outcome(), outcome(), outcome())
    sid = create().json()["id"]
    message(sid, REDO)
    message(sid, REDO)
    assert [r[0] for r in log["runs"] if r[0] != REDO] == ["máy lỗi loa"] * 3


def test_redo_after_the_checkpoint_went_stale_runs_the_request_again(monkeypatch):
    log = redoable(monkeypatch, resumable(), outcome())
    sid = create().json()["id"]
    s = stored(sid)
    s.checkpoint["at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    asyncio.run(app.dependency_overrides[session_store]().save(s))
    message(sid, REDO)
    assert log["resumes"] == [] and [r[0] for r in log["runs"]] == ["máy lỗi loa", REDO, "máy lỗi loa"]


def test_redo_runs_the_request_again_with_its_clarify_answers(monkeypatch):
    log = redoable(monkeypatch, outcome({"decision": "clarify", "clarify_question": "Đơn nào?"}), outcome(), outcome())
    sid = create().json()["id"]
    client.post(f"/api/sessions/{sid}/answer", json={"answer": "DH1001"}, headers=user("u1"))
    message(sid, REDO)
    assert log["runs"][-1][:2] == ("máy lỗi loa", [("Đơn nào?", "DH1001")])


def test_a_resumed_run_that_fails_again_leaves_a_new_checkpoint(monkeypatch):
    log = redoable(monkeypatch, resumable(marker=1), resumed=[resumable(marker=2), outcome()])
    sid = create().json()["id"]
    message(sid, REDO)
    s = stored(sid)
    assert s.status == "failed" and s.checkpoint["coordinator"] == {"marker": 2} and s.checkpoint["text"] == "máy lỗi loa"
    message(sid, REDO)
    assert log["resumes"][-1] == ("máy lỗi loa", {"marker": 2}) and stored(sid).status == "done"


def test_a_follow_up_that_is_not_a_redo_drops_the_checkpoint(monkeypatch):
    log = redoable(monkeypatch, resumable(), outcome())
    sid = create().json()["id"]
    message(sid, "Hoàn tiền cho đơn đó")
    assert log["resumes"] == [] and stored(sid).checkpoint is None


def test_no_response_carries_the_checkpoint(monkeypatch):
    redoable(monkeypatch, resumable())
    created = create()
    sid = created.json()["id"]
    assert stored(sid).checkpoint is not None
    assert "checkpoint" not in created.json() and "checkpoint" not in get(sid).json()
    assert all("checkpoint" not in s for s in client.get("/api/sessions", headers=user("u1")).json())
    assert "checkpoint" not in message(sid, "Hoàn tiền").json()
    events = client.get(f"/api/sessions/{sid}/events", headers=user("u1")).text
    assert "checkpoint" not in events


SLACK_ORIGIN = {"kind": "slack", "channel": "D012AB3CD", "thread_ts": "1730700000.123456",
                "permalink": "https://boa-team.slack.com/archives/D012AB3CD/p1730700000123456"}


def test_a_room_records_where_it_was_opened(monkeypatch):
    scripted(monkeypatch, outcome(), outcome())
    web = create().json()
    assert (web["source"], web["origin"]) == ("web", {})
    slack = client.post("/api/sessions", json={"text": "x", "provider": "fake", "origin": SLACK_ORIGIN},
                        headers=user("u1")).json()
    assert (slack["source"], slack["origin"]) == ("slack", SLACK_ORIGIN)
    # Kept with the room, also after its run saved it
    assert get(slack["id"]).json()["origin"] == SLACK_ORIGIN


def test_admins_see_where_rooms_were_opened_and_filter_by_it(monkeypatch):
    scripted(monkeypatch, outcome(), outcome())
    web = create().json()["id"]
    no_link = {k: v for k, v in SLACK_ORIGIN.items() if k != "permalink"}
    slack = client.post("/api/sessions", json={"text": "x", "provider": "fake", "origin": no_link},
                        headers=user("u1")).json()["id"]

    rooms = {r["id"]: r for r in client.get("/api/admin/users/u1/sessions", headers=ADMIN).json()}
    assert (rooms[web]["source"], rooms[slack]["source"], rooms[slack]["origin"]) == ("web", "slack", no_link)
    assert [r["id"] for r in client.get("/api/admin/users/u1/sessions?source=slack", headers=ADMIN).json()] == [slack]
    assert [r["id"] for r in client.get("/api/admin/users/u1/sessions?source=web", headers=ADMIN).json()] == [web]
    assert client.get("/api/admin/users/u1/sessions?source=teams", headers=ADMIN).status_code == 422
    detail = client.get(f"/api/admin/sessions/{slack}", headers=ADMIN).json()
    assert (detail["source"], detail["origin"]) == ("slack", no_link)

    # Staff, the room's owner included, never read rooms through the admin API
    assert client.get("/api/admin/users/u1/sessions", headers=user("u1")).status_code == 403
    assert client.get(f"/api/admin/sessions/{slack}", headers=user("u1")).status_code == 403


@pytest.mark.parametrize("bad", [
    {**SLACK_ORIGIN, "kind": "teams"},
    {**SLACK_ORIGIN, "channel": "d01; drop"},
    {**SLACK_ORIGIN, "channel": "C" * 33},
    {**SLACK_ORIGIN, "thread_ts": "yesterday"},
    {**SLACK_ORIGIN, "permalink": "javascript:alert(1)"},
    {**SLACK_ORIGIN, "permalink": "https://slack.com.evil.example/archives/x"},
    {**SLACK_ORIGIN, "permalink": "https://boa.slack.com/" + "x" * 500},
    {**SLACK_ORIGIN, "extra": "field"},
    {"kind": "slack", "channel": "D012AB3CD"},
])
def test_a_malformed_origin_is_refused_before_anything_is_saved(monkeypatch, bad):
    scripted(monkeypatch)
    resp = client.post("/api/sessions", json={"text": "x", "provider": "fake", "origin": bad}, headers=user("u1"))
    assert resp.status_code == 422
    assert client.get("/api/sessions", headers=user("u1")).json() == []
