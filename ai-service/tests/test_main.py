import asyncio
import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import mandates
from app.api import deps
from app.core import router
from app.core.context import RequestContext
from app.core.llm import Usage
from app.core.llm.fake import ScriptedClient, call, completion, example_for
from app.main import app
from app.schemas import RunRequest
from app.services import clients, formatting, procedure
from app.services import run as run_service
from app.store.sessions import InMemorySessionStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_MODEL", "AI_ALLOW_FAKE",
                "AI_TRUST_IDENTITY_HEADERS", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    # Tests pick agents directly; test_agent_override_is_off_by_default covers the default
    monkeypatch.setenv("AI_ALLOW_AGENT_OVERRIDE", "1")
    # ... and name their provider; test_provider_is_the_one_an_admin_chose covers the default
    monkeypatch.setenv("AI_ALLOW_PROVIDER_OVERRIDE", "1")
    store = InMemorySessionStore()
    app.dependency_overrides[deps.session_store] = lambda: store
    clients.client_for.cache_clear()
    clients.jev_client.cache_clear()
    yield
    app.dependency_overrides.pop(deps.session_store, None)


def post(**body):
    return client.post("/run", json={"task_id": 1, "text": "máy lỗi", "provider": "fake", **body})


def test_healthz_lists_no_providers_without_keys():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "providers": []}


def test_healthz_lists_profiles_whose_keys_resolve(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    assert client.get("/healthz").json()["providers"] == ["anthropic", "fake"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-x")
    assert client.get("/healthz").json()["providers"] == ["anthropic", "openai", "fake"]


def test_agent_override_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AI_ALLOW_AGENT_OVERRIDE")
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    resp = post(agent="orders")
    assert resp.status_code == 422 and "AI_ALLOW_AGENT_OVERRIDE" in resp.json()["detail"]


def test_fake_provider_requires_opt_in():
    assert post().status_code == 503


@pytest.mark.parametrize("agent", ["customer_service", "orders", "knowledge", "it_support"])
def test_fake_provider_runs_any_worker_mandate(monkeypatch, agent):
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    resp = post(agent=agent)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["provider"], body["model"], body["agent"]) == ("fake", "fake", agent)
    assert "FAKE" in body["output"]
    assert body["result"]["status"] == "done" and body["pending_actions"] == []
    assert body["route"] is None  # the client named the agent, so Jev did not run


@pytest.mark.parametrize("agent, status", [("coordinator", 422), ("factory", 422), ("nope", 422)])
def test_only_worker_agents_run_here(monkeypatch, agent, status):
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    assert post(agent=agent).status_code == status


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_real_provider_without_key_is_503(provider):
    resp = post(provider=provider, agent="customer_service")
    assert resp.status_code == 503


def test_openai_requires_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    resp = post(provider="openai", agent="customer_service")
    assert resp.status_code == 503
    assert "OPENAI_MODEL" in resp.json()["detail"]


def test_rejects_unknown_provider_and_empty_text():
    assert post(provider="gemini").status_code == 422
    assert post(text="").status_code == 422


def test_run_wires_mandate_tools_and_tier(monkeypatch):
    """orders on the anthropic profile: standard tier, mandate effort, real stub tools."""
    mandate = mandates.load("orders")
    final = example_for(mandate.output_schema)
    final.update(summary="Đơn DH1001 đã giao ngày 17/10.", findings=[{"text": "Giao ngày 2026-10-17", "claims": ["delivered_date"]}])
    final["claims"] = [{"key": "delivered_date", "kind": "fact", "value": "2026-10-17",
                        "ref": {"call_id": "lookup_order", "path": "delivered_date"}, "derived_from": [], "reasoning": None}]
    scripted = ScriptedClient([
        completion(call("c1", "lookup_order", {"order_id": "DH1001"})),
        completion(call("c2", "final_answer", final)),
    ])
    picked = []

    def fake_client_for(config):
        picked.append(config)
        return scripted

    monkeypatch.setattr(clients, "client_for", fake_client_for)
    resp = post(provider="anthropic", agent="orders", text="Khách đơn DH1001 báo máy lỗi")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (picked[0].model, picked[0].effort) == ("claude-sonnet-5-5", "medium")
    assert body["model"] == "claude-sonnet-5-5" and body["steps"] == 2
    assert body["result"]["claims"][0]["ref"] == {"call_id": "lookup_order", "path": "delivered_date"}
    assert "- Giao ngày 2026-10-17 [delivered_date]" in body["output"]  # the cited claim stays visible
    # The system prompt is the mandate; the request is wrapped as untrusted data
    system, user = scripted.seen[0][0][:2]
    assert system.content == mandate.system_prompt
    assert "<untrusted_input>\nKhách đơn DH1001 báo máy lỗi\n</untrusted_input>" in user.content
    # Only implemented tools from the allowlist are offered, plus final_answer
    offered = [spec["function"]["name"] for spec in scripted.seen[0][1]]
    assert offered == ["lookup_order", "lookup_product", "search_products", "lookup_stock", "search_sop", "final_answer"]
    tool_result = scripted.seen[1][0][-1]
    assert '"delivered_date": "2026-10-17"' in tool_result.content


def test_customer_service_does_not_look_up_orders_itself(monkeypatch):
    """Order and product facts belong to orders; customer_service gets them by consult or from the task."""
    scripted = ScriptedClient([completion(call("c1", "final_answer", example_for(mandates.load("customer_service").output_schema)))])
    monkeypatch.setattr(clients, "client_for", lambda config: scripted)
    assert post(provider="anthropic", agent="customer_service").status_code == 200
    offered = [spec["function"]["name"] for spec in scripted.seen[0][1]]
    assert offered == ["search_sop", "send_email", "final_answer"]


def _orders_final(paid):
    final = example_for(mandates.load("orders").output_schema)
    final["claims"] = [{"key": "paid", "kind": "fact", "value": paid,
                        "ref": {"call_id": "lookup_order", "path": "paid_amount"}, "derived_from": [], "reasoning": None}]
    return final


def test_claim_that_contradicts_the_tool_result_is_sent_back_to_the_model(monkeypatch):
    scripted = ScriptedClient([
        completion(call("c1", "lookup_order", {"order_id": "DH1001"})),
        completion(call("c2", "final_answer", _orders_final(19990000))),
        completion(call("c3", "final_answer", _orders_final(21990000))),
    ])
    monkeypatch.setattr(clients, "client_for", lambda config: scripted)
    resp = post(provider="anthropic", agent="orders", text="Đơn DH1001 khách trả bao nhiêu")
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == 3 and resp.json()["result"]["claims"][0]["value"] == 21990000
    rejection = scripted.seen[2][0][-1]
    assert rejection.is_error and "claim 'paid'" in rejection.content and "21990000" in rejection.content


def test_run_reports_each_model_call_with_its_cost_and_each_tool_call_with_its_data(monkeypatch):
    scripted = ScriptedClient([
        completion(call("c1", "lookup_order", {"order_id": "DH1001"}), content="Looking it up", usage=Usage(1000, 100)),
        completion(call("c2", "final_answer", _orders_final(21990000)), usage=Usage(2000, 200)),
    ])
    monkeypatch.setattr(clients, "client_for", lambda config: scripted)
    events = []
    req = RunRequest(task_id=1, text="Đơn DH1001", provider="anthropic", agent="orders")
    asyncio.run(run_service.run(req, RequestContext(user_id="u1", departments=("cskh",)),
                                lambda event, data: events.append((event, data))))
    calls = [data for event, data in events if event == "llm_call"]
    assert [(c["model"], c["prompt_tokens"], c["completion_tokens"]) for c in calls] == [
        ("claude-sonnet-5-5", 1000, 100), ("claude-sonnet-5-5", 2000, 200)]
    assert calls[0]["text"] == "Looking it up" and calls[0]["cost_usd"] == pytest.approx((1000 * 2 + 100 * 10) / 1e6)
    tool_call = next(data for event, data in events if event == "tool_call")
    assert json.loads(tool_call["arguments"]) == {"order_id": "DH1001"}
    tool_result = next(data for event, data in events if event == "tool_result")
    assert '"delivered_date"' in tool_result["content"] and not tool_result["is_error"]
    assert events[-1] == ("agent_finished", {"agent": "orders", "status": "done", "reason": "", "steps": 2,
                                             "prompt_tokens": 3000, "completion_tokens": 300})


def test_run_fails_when_the_model_keeps_citing_what_the_tools_did_not_return(monkeypatch):
    wrong = [completion(call(f"c{i}", "final_answer", _orders_final(1))) for i in range(5)]
    scripted = ScriptedClient([completion(call("c0", "lookup_order", {"order_id": "DH1001"})), *wrong])
    monkeypatch.setattr(clients, "client_for", lambda config: scripted)
    resp = post(provider="anthropic", agent="orders")
    assert resp.status_code == 502 and "final_answer" in resp.json()["detail"]


def test_failed_run_is_502(monkeypatch):
    monkeypatch.setattr(clients, "client_for", lambda config: ScriptedClient([completion(content="text"), completion(content="text")]))
    resp = post(provider="anthropic", agent="customer_service")
    assert resp.status_code == 502 and "final_answer" in resp.json()["detail"]


class FakeJev:
    def __init__(self, choice, confidence, missing=0.1, covered=0.9, error=None, redo=0.0):
        self.answer = {
            "model": "jev-1.13.0",
            "answers": {
                "route": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {choice: 1.0}},
                "missing_context": {"type": "noul", "noul": missing},
                "covered": {"type": "noul", "noul": covered},
                "redo": {"type": "noul", "noul": redo},
            },
            "usage": {"input_tokens": 300, "output_tokens": 20},
        }
        self.error = error
        self.states = []

    async def system_one(self, state, questions):
        self.states.append(state)
        if self.error:
            raise router.RouterError(self.error)
        return self.answer


def _routed(monkeypatch, jev, worker_completions=(), **body):
    """Jev routes the request, then the target worker runs; returns (response, models used, worker)."""
    worker = ScriptedClient(worker_completions)
    models = []

    def fake_client_for(config):
        models.append(config.model)
        return worker

    monkeypatch.setattr(clients, "jev_client", lambda: jev)
    monkeypatch.setattr(clients, "client_for", fake_client_for)
    return post(**{"provider": "anthropic", "text": "Đơn DH1001 giao chưa"} | body), models, worker


def test_jev_routes_single_to_the_chosen_department_agent(monkeypatch):
    jev = FakeJev("orders", 0.9)
    monkeypatch.setattr(procedure, "retrieve", lambda text, ctx: pytest.fail("searched before a single-branch run"))
    resp, models, worker = _routed(monkeypatch, jev, [
        completion(call("c1", "final_answer", example_for(mandates.load("orders").output_schema)),
                   usage=Usage(prompt_tokens=50, completion_tokens=5)),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert jev.states == ["Đơn DH1001 giao chưa"] and models == ["claude-sonnet-5-5"]
    assert body["agent"] == "orders" and body["route"]["branch"] == "single"
    assert body["route"]["agent_scores"]["orders"] == 1.0 and body["route"]["model"] == "jev-1.13.0"
    # Jev is billed apart from the LLM, so its tokens stay in route
    assert body["input_tokens"] == 50 and body["route"]["usage"] == {"input_tokens": 300, "output_tokens": 20}
    assert len(worker.seen) == 1 and "<retrieved" not in worker.seen[0][0][-1].content


def test_a_follow_up_routes_and_runs_with_the_room_and_cites_its_facts(monkeypatch):
    jev = FakeJev("orders", 0.9)
    final = _orders_final("DH1001")
    final["claims"][0]["ref"] = {"call_id": "room:t1", "path": "order_id"}
    worker = ScriptedClient([completion(call("c1", "final_answer", final))])
    monkeypatch.setattr(clients, "jev_client", lambda: jev)
    monkeypatch.setattr(clients, "client_for", lambda config: worker)
    room = {"turns": [{"turn": 1, "request": "Tra đơn DH1001", "agent": "orders", "outcome": "done",
                       "summary": "Đơn DH1001 đã giao.", "facts": {"order_id": "DH1001"}, "open_questions": []}]}
    req = RunRequest(task_id=1, text="Khách trả bao nhiêu cho đơn đó?", provider="anthropic")
    out = asyncio.run(run_service.run(req, RequestContext(user_id="u1", departments=("cskh",)), room=room))
    # Code accepted the claim citing the earlier turn: one model call, no rejection
    assert out["agent"] == "orders" and out["steps"] == 1
    assert jev.states == [{"earlier_in_room": room, "request": "Khách trả bao nhiêu cho đơn đó?"}]
    task = worker.seen[0][0][-1].content
    assert "<room_context>" in task and '"DH1001"' in task
    # The tags are also named in <task>: compare the blocks themselves
    assert task.index("\n<room_context>\n") < task.index("\n<untrusted_input>\n")


def test_jev_routes_policy_questions_to_knowledge(monkeypatch):
    final = example_for(mandates.load("knowledge").output_schema)
    resp, _, _ = _routed(monkeypatch, FakeJev("policy_lookup", 0.9), [completion(call("c1", "final_answer", final))],
                         text="đổi máy lỗi trong bao nhiêu ngày")
    assert resp.status_code == 200, resp.text
    assert resp.json()["agent"] == "knowledge" and resp.json()["route"]["branch"] == "procedure"


@pytest.mark.parametrize("jev", [
    FakeJev("no_fitting_agent", 0.9),
    FakeJev("customer_service", 0.8, covered=0.1),
])
def test_the_unknown_branch_asks_the_user_before_requesting_an_agent(monkeypatch, jev):
    want = decision("plan", "request_agent", agent_request={"capability": "warranty by IMEI", "example_task": "t"})
    ask = decision("plan", "clarify", clarify_question="Bạn cần tra thông tin gì theo IMEI?")
    resp, _, llm = _routed(monkeypatch, jev, [completion(call("c1", "final_answer", want)),
                                             completion(call("c2", "final_answer", ask))])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["agent"], body["route"]["branch"]) == ("coordinator", "unknown")
    assert body["result"]["decision"] == "clarify"
    assert "<origin>\nunknown\n</origin>" in llm.seen[0][0][-1].content
    # Code refused the request for an agent: no clarify round had been used
    assert "ask the user one clarify question" in llm.seen[1][0][-1].content


def test_run_without_saved_sessions_reports_a_missing_agent_without_factory(monkeypatch):
    want = decision("plan", "request_agent", agent_request={"capability": "warranty by IMEI", "example_task": "t"})
    answers = [{"question": "Tra gì?", "answer": "Bảo hành theo IMEI"}]
    resp, _, llm = _routed(monkeypatch, FakeJev("orders", 0.9), [completion(call("c1", "final_answer", want))],
                           clarifications=answers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent"] == "coordinator" and body["result"]["decision"] == "request_agent"
    assert len(llm.seen) == 1


def decision(phase, decision, **fields):
    empty = {"plan": None, "clarify_question": None, "agent_request": None, "feedback": None, "note": None,
             "final_response": None}
    return {"summary": "s", "open_questions": [], "phase": phase, "decision": decision} | empty | fields


@pytest.mark.parametrize("jev, origin", [
    (FakeJev("multi_department", 0.9), "multi"),
    (FakeJev("orders", 0.3), "low_confidence"),
])
def test_coordinator_runs_the_multi_and_low_confidence_branches(monkeypatch, jev, origin):
    plan = {"steps": [{"id": "a", "agent": "knowledge", "label": "l", "task": "t", "depends_on": [], "deliverables": []}]}
    usage = Usage(prompt_tokens=10, completion_tokens=1)
    # A knowledge step searches with its search_sop tool; the runtime searches first only on the procedure branch
    monkeypatch.setattr(procedure, "retrieve", lambda text, ctx: pytest.fail("searched before a Coordinator step"))
    resp, models, llm = _routed(monkeypatch, jev, [
        completion(call("c1", "final_answer", decision("plan", "plan", plan=plan)), usage=usage),
        completion(call("w1", "final_answer", example_for(mandates.load("knowledge").output_schema)), usage=usage),
        completion(call("c2", "final_answer", decision("review", "accept")), usage=usage),
        completion(call("c3", "final_answer", decision("finalize", "complete", final_response="Xong.")), usage=usage),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["agent"], body["route"]["branch"], body["output"]) == ("coordinator", origin, "Xong.")
    assert body["result"]["decision"] == "complete" and body["result"]["final_response"] == "Xong."
    assert body["result"]["plan"] == plan and body["result"]["steps"][0]["status"] == "accepted"
    assert (body["input_tokens"], body["output_tokens"], body["steps"]) == (40, 4, 4)
    assert f"<origin>\n{origin}\n</origin>" in llm.seen[0][0][-1].content
    assert "<retrieved" not in llm.seen[1][0][-1].content and "<deliverables>" in llm.seen[1][0][-1].content
    # The catalog holds only workers the cskh demo user may use; the workers they may not use are
    # listed apart, and non-workers appear in neither
    task = llm.seen[0][0][-1].content
    catalog = task.split("<agent_catalog>")[1].split("</agent_catalog>")[0]
    unavailable = task.split("<unavailable_agents>")[1].split("</unavailable_agents>")[0]
    assert '"name": "knowledge"' in catalog and '"name": "executive"' not in catalog
    assert '"name": "executive"' in unavailable and '"name": "knowledge"' not in unavailable
    assert '"name": "factory"' not in task and '"name": "coordinator"' not in task


def test_the_clarify_branch_lets_the_coordinator_ask(monkeypatch):
    ask = decision("plan", "clarify", clarify_question="Mã đơn là gì?")
    resp, _, llm = _routed(monkeypatch, FakeJev("orders", 0.9, missing=0.9), [completion(call("c1", "final_answer", ask))])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["agent"], body["route"]["branch"], body["output"]) == ("coordinator", "clarify", "Mã đơn là gì?")
    assert body["result"]["decision"] == "clarify" and body["result"]["clarify_question"] == "Mã đơn là gì?"
    task = llm.seen[0][0][-1].content
    assert "<origin>\nclarify\n</origin>" in task and "<clarify_rounds_used>\n0\n" in task


def test_answers_go_straight_to_the_coordinator_without_jev(monkeypatch):
    jev = FakeJev("orders", 0.9)
    ask = decision("plan", "clarify", clarify_question="Khách mua ở cửa hàng nào?")
    answers = [{"question": "Mã đơn là gì?", "answer": "DH1001"}]
    resp, _, llm = _routed(monkeypatch, jev, [completion(call("c1", "final_answer", ask))], clarifications=answers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert jev.states == [] and body["route"] is None
    assert (body["agent"], body["output"]) == ("coordinator", "Khách mua ở cửa hàng nào?")
    task = llm.seen[0][0][-1].content
    assert "<origin>\nclarified\n</origin>" in task and "<clarify_rounds_used>\n1\n" in task
    assert '"answer": "DH1001"' in task.split("<clarifications>")[1]


@pytest.mark.parametrize("body", [
    {"agent": "orders", "clarifications": [{"question": "Mã đơn?", "answer": "DH1001"}]},
    {"clarifications": [{"question": "Mã đơn?", "answer": "DH1001"}] * 3},
    {"clarifications": [{"question": "Mã đơn?", "answer": ""}]},
])
def test_bad_clarifications_are_422(body):
    assert post(provider="anthropic", **body).status_code == 422


def test_an_escalated_single_run_goes_to_the_coordinator(monkeypatch):
    escalated = example_for(mandates.load("customer_service").output_schema) | {
        "status": "escalate", "open_questions": ["cần phòng vận hành kiểm tra kho"]}
    usage = Usage(prompt_tokens=10, completion_tokens=1)
    resp, _, llm = _routed(monkeypatch, FakeJev("customer_service", 0.9), [
        completion(call("w1", "final_answer", escalated), usage=usage),
        completion(call("c1", "final_answer", decision("plan", "clarify", clarify_question="Cửa hàng nào?")), usage=usage),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["agent"], body["route"]["branch"], body["output"]) == ("coordinator", "single", "Cửa hàng nào?")
    assert body["result"] == {"decision": "clarify", "clarify_question": "Cửa hàng nào?", "plan": None, "steps": [],
                              "replans": []}
    assert (body["input_tokens"], body["steps"]) == (20, 2)
    task = llm.seen[1][0][-1].content
    assert "<origin>\nescalated\n</origin>" in task and '"agent": "customer_service"' in task
    assert "cần phòng vận hành kiểm tra kho" in task


def test_a_worker_whose_model_cannot_call_tools_fails_its_step_without_retries(monkeypatch):
    plan = {"steps": [{"id": "a", "agent": "knowledge", "label": "l", "task": "t", "depends_on": [], "deliverables": []}]}
    resp, _, llm = _routed(monkeypatch, FakeJev("multi_department", 0.9), [
        completion(call("c1", "final_answer", decision("plan", "plan", plan=plan))),
        # A provider that writes tool calls as text: the worker never calls final_answer
        completion(content="<invoke name=\"search_sop\">"), completion(content="<invoke name=\"search_sop\">"),
        completion(call("c2", "final_answer", decision("finalize", "cannot_complete", final_response="Chưa tra được."))),
    ])
    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["decision"] == "cannot_complete" and result["final_response"] == "Chưa tra được."
    [record] = result["steps"]
    assert (record["status"], record["attempts"]) == ("failed", 1)
    assert record["reason"] == "the agent's model could not run: model ended without calling final_answer"
    # No retry: plan, the worker's two turns, finalize
    assert len(llm.seen) == 4


def test_a_coordinator_that_cannot_decide_is_502(monkeypatch):
    resp, _, _ = _routed(monkeypatch, FakeJev("multi_department", 0.9), [completion(content="text"), completion(content="text")])
    assert resp.status_code == 502 and "coordinator plan failed" in resp.json()["detail"]


def test_route_to_an_agent_the_requester_may_not_use_is_refused(monkeypatch):
    """The demo user is cskh: even a confident (or steered) executive pick never runs."""
    resp, models, worker = _routed(monkeypatch, FakeJev("executive", 1.0))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["route"]["branch"], body["agent"], body["steps"], body["result"]) == ("forbidden", "executive", 0, {})
    assert "executive" in body["output"] and models == [] and worker.seen == []


def test_agent_override_still_checks_departments(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_FAKE", "1")
    assert post(agent="executive").status_code == 403
    monkeypatch.setenv("AI_TRUST_IDENTITY_HEADERS", "1")
    resp = client.post("/run", json={"task_id": 1, "text": "x", "provider": "fake", "agent": "executive"},
                       headers={"x-user-id": "u9", "x-user-departments": "executive"})
    assert resp.status_code == 200, resp.text


def test_routing_needs_the_typesafe_key(monkeypatch):
    monkeypatch.delenv(router.API_KEY_ENV, raising=False)
    clients.jev_client.cache_clear()
    resp = post(provider="anthropic")
    assert resp.status_code == 503 and router.API_KEY_ENV in resp.json()["detail"]
    assert client.post("/route", json={"text": "x"}).status_code == 503


def test_route_endpoint_only_asks_jev(monkeypatch):
    jev = FakeJev("orders", 0.9, missing=0.8)
    monkeypatch.setattr(clients, "jev_client", lambda: jev)
    monkeypatch.setattr(clients, "client_for", lambda config: pytest.fail("no agent may run"))
    resp = client.post("/route", json={"text": "Đơn đó giao chưa?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["branch"], body["target"], body["choice"]) == ("clarify", "coordinator", "orders")
    assert jev.states == ["Đơn đó giao chưa?"]
    assert client.post("/route", json={"text": ""}).status_code == 422


def test_jev_failure_is_502(monkeypatch):
    resp, models, _ = _routed(monkeypatch, FakeJev("orders", 0.9, error="jev returned 500: boom"))
    assert resp.status_code == 502 and "jev returned 500" in resp.json()["detail"] and models == []


def stream(**body):
    """POST /run asking for server-sent events; returns the response and its (event, data) pairs."""
    resp = client.post("/run", json={"task_id": 1, "text": "Đơn DH1001 giao chưa", "provider": "anthropic", **body},
                       headers={"Accept": "text/event-stream"})
    events = []
    for block in resp.text.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return resp, events


def test_run_streams_progress_then_the_same_result(monkeypatch):
    final = example_for(mandates.load("orders").output_schema)
    worker = ScriptedClient([completion(call("c1", "lookup_order", {"order_id": "DH1001"})),
                             completion(call("c2", "final_answer", final))])
    monkeypatch.setattr(clients, "jev_client", lambda: FakeJev("orders", 0.9))
    monkeypatch.setattr(clients, "client_for", lambda config: worker)
    resp, events = stream()
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in events] == ["route", "step", "tool_call", "tool_result", "step", "tool_call",
                                            "tool_result", "done"]
    assert events[0][1] == {"branch": "single", "target": "orders"}
    assert events[2][1] == {"agent": "orders", "step": 1, "id": "c1", "name": "lookup_order"}
    assert events[3][1] == {"agent": "orders", "step": 1, "id": "c1", "is_error": False}
    done = events[-1][1]
    assert done["agent"] == "orders" and done["steps"] == 2 and done["result"] == final


def test_a_quiet_stream_gets_ping_comments_until_the_result(monkeypatch):
    async def slow_run(req, ctx, emit):
        await asyncio.sleep(0.2)
        return {"provider": "fake", "model": "", "output": "xong", "input_tokens": 0, "output_tokens": 0,
                "agent": "orders", "steps": 0, "result": {}, "pending_actions": [], "route": None}

    monkeypatch.setattr(run_service, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(run_service, "run", slow_run)
    resp = client.post("/run", json={"task_id": 1, "text": "x", "provider": "anthropic"},
                       headers={"Accept": "text/event-stream"})
    blocks = resp.text.strip().split("\n\n")
    assert blocks[0] == ": ping" and blocks[-1].startswith("event: done")
    assert all(b == ": ping" for b in blocks[:-1])


def test_streamed_coordinator_reports_every_agent(monkeypatch):
    plan = {"steps": [{"id": "a", "agent": "knowledge", "label": "l", "task": "t", "depends_on": [], "deliverables": []}]}
    llm = ScriptedClient([
        completion(call("c1", "final_answer", decision("plan", "plan", plan=plan))),
        completion(call("w1", "final_answer", example_for(mandates.load("knowledge").output_schema))),
        completion(call("c2", "final_answer", decision("review", "accept"))),
        completion(call("c3", "final_answer", decision("finalize", "complete", final_response="Xong."))),
    ])
    monkeypatch.setattr(clients, "jev_client", lambda: FakeJev("multi_department", 0.9))
    monkeypatch.setattr(clients, "client_for", lambda config: llm)
    _, events = stream()
    assert [data["agent"] for name, data in events if name == "step"] == [
        "coordinator", "knowledge", "coordinator", "coordinator"]
    # The Coordinator's own milestones go out on the same stream, between the agents' steps
    milestones = [(name, data.get("agent")) for name, data in events if name in ("plan", "step_started", "step_accepted")]
    assert milestones == [("plan", None), ("step_started", "knowledge"), ("step_accepted", "knowledge")]
    assert events[-1][0] == "done" and events[-1][1]["output"] == "Xong."


def test_streamed_failures_are_error_events(monkeypatch):
    monkeypatch.setattr(clients, "jev_client", lambda: FakeJev("orders", 0.9, error="jev returned 500: boom"))
    resp, events = stream()
    assert resp.status_code == 200  # already sent before the run failed
    assert events == [("error", {"status": 502, "detail": "jev returned 500: boom"})]


def test_a_request_refused_before_the_run_is_not_streamed(monkeypatch):
    monkeypatch.delenv("AI_ALLOW_AGENT_OVERRIDE")
    resp = client.post("/run", json={"task_id": 1, "text": "x", "provider": "fake", "agent": "orders"},
                       headers={"Accept": "text/event-stream"})
    assert resp.status_code == 422


def test_a_client_that_leaves_cancels_the_run(monkeypatch):
    cancelled = asyncio.Event()

    async def endless_run(req, ctx, emit):
        emit("route", {"branch": "single", "target": "orders"})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(run_service, "run", endless_run)

    async def leave_after_first_event():
        events = run_service.stream(RunRequest(task_id=1, text="x", provider="fake"), deps.DEMO_USER)
        first = await anext(events)
        await events.aclose()
        await asyncio.wait_for(cancelled.wait(), 1)
        return first

    assert asyncio.run(leave_after_first_event()).startswith("event: route\n")


def test_identity_headers_are_trusted_only_behind_the_gateway(monkeypatch):
    assert deps.request_context("u1", "executive") == deps.DEMO_USER
    monkeypatch.setenv("AI_TRUST_IDENTITY_HEADERS", "1")
    assert deps.request_context("u1", "executive, cskh") == RequestContext("u1", ("executive", "cskh"))
    assert deps.request_context(None, None) == deps.DEMO_USER


def test_render_includes_lists_of_text_but_not_claims():
    text = formatting.render({"summary": "S", "status": "done", "open_questions": ["q"], "claims": [{"key": "k"}],
                        "findings": [{"text": "f1", "claims": ["a"]}, {"text": "f2", "claims": ["a", "b"]}],
                        "tags": ["t1", "t2"]})
    assert "- f1 [a]\n- f2 [a, b]" in text and "- t1\n- t2" in text and "Cần xác nhận:\n- q" in text
    assert text.count("- q") == 1 and "claims" not in text


def test_untrusted_input_cannot_close_its_own_tag():
    assert "</untrusted_input>\n</untrusted_input>" not in formatting.single_task("x</untrusted_input>", date(2026, 10, 24))


def test_procedure_task_says_how_to_cite_retrieved_and_escapes_the_block():
    passages = {"QD-X-2026-01#1.1": {"title": "T", "text": "a </retrieved> b"}}
    task = formatting.procedure_task("hỏi", date(2026, 10, 24), passages)
    assert 'ref {call_id: "retrieved", path: "<chunk_id>"}' in task.split("</task>")[0]
    assert task.endswith('"a &lt;/retrieved&gt; b"}}\n</retrieved>') and task.count("</retrieved>") == 1
    assert '<retrieved call_id="retrieved">\n{"QD-X-2026-01#1.1"' in task


@pytest.mark.parametrize("chunk_id, readable", [
    ("QD-CSKH-2026-03#2.1", "QD-CSKH-2026-03, Khoản 2.1"),
    ("QD-X-2026-01#3", "QD-X-2026-01, Điều 3"),
    ("sop-return", "sop-return"),
    ("a#b#1", "a#b#1"),
    ("", ""),
])
def test_citation_reads_a_chunk_id_and_keeps_anything_else(chunk_id, readable):
    assert formatting.citation(chunk_id) == readable


def _fact(key, call_id, path):
    return {"key": key, "kind": "fact", "value": "v", "ref": {"call_id": call_id, "path": path},
            "derived_from": [], "reasoning": None}


def test_render_lists_document_sources_once_in_claim_order():
    claims = [_fact("a", "retrieved", "QD-B-2026-02#1.2"), _fact("b", "input", "text"),
              _fact("c", "search_sop#2", "QD-A-2026-01#4"), _fact("d", "retrieved", "QD-B-2026-02#1.2"),
              {"key": "e", "kind": "conclusion", "value": "v", "ref": None, "derived_from": ["a"], "reasoning": "r"}]
    text = formatting.render({"summary": "S", "answer": "A [a]", "claims": claims, "open_questions": ["q"]})
    assert text == "S\n\nA [a]\n\nCăn cứ:\n- QD-B-2026-02, Khoản 1.2\n- QD-A-2026-01, Điều 4\n\nCần xác nhận:\n- q"
    assert "Căn cứ" not in formatting.render({"summary": "S", "claims": [_fact("b", "input", "text")]})
    assert "Căn cứ" not in formatting.render({"summary": "S"})


def test_procedure_claims_cite_the_retrieved_passages(monkeypatch):
    text = "đổi máy lỗi trong bao nhiêu ngày"
    passages = procedure.retrieve(text, deps.DEMO_USER)
    chunk_id = next(iter(passages))
    quote = passages[chunk_id]["text"].split("\n")[0][:40]
    final = {"status": "done", "summary": "s", "open_questions": [], "answer": "Có [rule]",
             "claims": [_fact("rule", "retrieved", chunk_id) | {"value": quote}]}
    resp, _, llm = _routed(monkeypatch, FakeJev("policy_lookup", 0.9), [completion(call("c1", "final_answer", final))],
                           text=text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["status"] == "done" and len(llm.seen) == 1
    assert f"Căn cứ:\n- {formatting.citation(chunk_id)}" in body["output"]
    # The model saw the passages in the user message; the mandate (system prompt) stays static
    system, user = llm.seen[0][0][:2]
    assert '<retrieved call_id="retrieved">' in user.content and f'"{chunk_id}"' in user.content
    assert "<retrieved call_id" not in system.content
    assert chunk_id.startswith("QD-CSKH-2026-03#")


@pytest.mark.parametrize("text", [
    "công thức nấu phở bò",
    # Only the BOD charter covers this, and cskh may not see it
    "hạn mức phê duyệt DOA của Tổng giám đốc",
])
def test_procedure_without_a_relevant_passage_is_blocked_without_calling_the_model(monkeypatch, text):
    resp, models, llm = _routed(monkeypatch, FakeJev("policy_lookup", 0.9), text=text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["status"] == "blocked" and body["output"] == procedure.NO_BASIS
    assert body["route"]["branch"] == "procedure" and body["agent"] == "knowledge"
    assert (body["input_tokens"], body["output_tokens"], body["steps"]) == (0, 0, 0)
    assert models == [] and llm.seen == []
    assert "QC-BOD" not in resp.text


def test_bod_passages_reach_executive_but_never_cskh():
    question = "hạn mức phê duyệt DOA của Tổng giám đốc"
    executive = procedure.retrieve(question, RequestContext("u1", ("executive",)))
    assert next(iter(executive)).startswith("QC-BOD-2026-01#")
    assert procedure.retrieve(question, deps.DEMO_USER) == {}


@pytest.mark.parametrize("wrong", [
    {"ref": {"call_id": "retrieved", "path": "QC-BOD-2026-01#2.1"}},  # a passage not in <retrieved>
    {"value": "đổi máy trong 7 ngày"},  # not a quote from the passage
])
def test_procedure_claim_citing_outside_the_retrieved_passage_is_sent_back(monkeypatch, wrong):
    text = "đổi máy lỗi trong bao nhiêu ngày"
    passages = procedure.retrieve(text, deps.DEMO_USER)
    chunk_id = next(iter(passages))
    good = _fact("rule", "retrieved", chunk_id) | {"value": passages[chunk_id]["text"][:40]}

    def final(claim):
        return {"status": "done", "summary": "s", "open_questions": [], "answer": "Có [rule]", "claims": [claim]}

    resp, _, llm = _routed(monkeypatch, FakeJev("policy_lookup", 0.9), [
        completion(call("c1", "final_answer", final(good | wrong))),
        completion(call("c2", "final_answer", final(good))),
    ], text=text)
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["status"] == "done" and len(llm.seen) == 2
    rejection = llm.seen[1][0][-1]
    assert rejection.is_error and "claim 'rule'" in rejection.content


def test_every_run_is_told_today_in_the_store_time_zone(monkeypatch):
    # 23:30 UTC on 23/10 is already 24/10 in Vietnam
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 23, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(formatting, "datetime", Clock)
    assert formatting.today() == date(2026, 10, 24)
    resp, _, llm = _routed(monkeypatch, FakeJev("orders", 0.9), [
        completion(call("c1", "final_answer", example_for(mandates.load("orders").output_schema))),
    ])
    assert resp.status_code == 200, resp.text
    assert "<today>\n2026-10-24." in llm.seen[0][0][-1].content
