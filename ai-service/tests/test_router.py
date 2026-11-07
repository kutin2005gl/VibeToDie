import asyncio
import json
import re

import httpx
import pytest

from app import mandates
from app.core import router
from app.core.context import RequestContext
from app.core.router import Classification, Route

CTX = RequestContext(user_id="u1", departments=("cskh",))
DEPARTMENTS = ["customer_service", "executive", "it_support", "orders"]
OPTIONS = ["policy_lookup", *DEPARTMENTS, "multi_department", "no_fitting_agent"]


def jev_answer(choice, confidence, missing=0.1, covered=0.9, redo=None, **probabilities):
    spread = {name: 0.0 for name in OPTIONS} | {choice: 1.0} | probabilities
    answer = {
        "model": "jev-1.13.0",
        "answers": {
            "route": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": spread},
            "missing_context": {"type": "noul", "noul": missing},
            "covered": {"type": "noul", "noul": covered},
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }
    if redo is not None:
        answer["answers"]["redo"] = {"type": "noul", "noul": redo}
    return answer


class FakeJev:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def system_one(self, state, questions):
        self.calls.append((state, questions))
        return self.answer


def classification(choice, confidence=0.9, missing=0.1, covered=0.9, redo=0.0):
    return Classification({}, {}, choice, confidence, missing, covered, "jev-1.13.0", {}, redo)


@pytest.mark.parametrize("c, expected", [
    (classification("policy_lookup"), Route("procedure", "knowledge")),
    (classification("orders"), Route("single", "orders")),
    (classification("multi_department"), Route("multi", "coordinator")),
    (classification("no_fitting_agent"), Route("unknown", "factory")),
    (classification("orders", confidence=0.4), Route("low_confidence", "coordinator")),
    (classification("orders", missing=0.8), Route("clarify", "coordinator")),
    (classification("policy_lookup", confidence=0.3, missing=0.9), Route("clarify", "coordinator")),
    # The coverage Noul overrides a confident department pick
    (classification("customer_service", confidence=0.76, covered=0.2), Route("unknown", "factory")),
    (classification("orders", confidence=0.4, covered=0.3), Route("unknown", "factory")),
    (classification("orders", covered=0.5), Route("single", "orders")),
    # Unknown already gets a clarify round before Factory
    (classification("orders", missing=0.9, covered=0.1), Route("unknown", "factory")),
    # A redo comes before every other branch; a low score routes as usual
    (classification("orders", redo=0.9), Route("redo", "coordinator")),
    (classification("no_fitting_agent", confidence=0.3, missing=0.9, covered=0.1, redo=0.8), Route("redo", "coordinator")),
    (classification("orders", redo=0.2), Route("single", "orders")),
])
def test_decide(c, expected):
    assert router.decide(c) == expected


@pytest.mark.parametrize("departments, route, expected", [
    (("cskh",), Route("single", "executive"), Route("forbidden", "executive")),
    (("cskh",), Route("single", "orders"), Route("single", "orders")),
    (("executive",), Route("single", "orders"), Route("single", "orders")),
    (("it",), Route("single", "orders"), Route("forbidden", "orders")),
    (("it",), Route("single", "it_support"), Route("single", "it_support")),
    (("it",), Route("procedure", "knowledge"), Route("procedure", "knowledge")),
    # Coordinator and Factory get a filtered catalog when they run, so they pass here
    (("it",), Route("multi", "coordinator"), Route("multi", "coordinator")),
    ((), Route("unknown", "factory"), Route("unknown", "factory")),
])
def test_authorize_refuses_agents_outside_the_requesters_departments(departments, route, expected):
    assert router.authorize(route, RequestContext("u1", departments)) == expected


def test_catalog_is_the_department_agents():
    assert [m.name for m in router.department_agents()] == DEPARTMENTS


def test_questions_offer_every_branch_and_department_in_english():
    asked = router.questions(router.department_agents())
    route = asked["route"]
    assert route["type"] == "choice" and list(route["criteria"]) == OPTIONS
    assert route["criteria"]["orders"] == mandates.load("orders").description
    assert asked["missing_context"]["type"] == "noul"
    # Coverage is judged against the handlers only, not the multi / none options
    covered = asked["covered"]
    assert covered["type"] == "noul" and list(covered["instructions"]["handlers"]) == ["policy_lookup", *DEPARTMENTS]
    assert not re.search("[ạảãầấậẩẫằắặẳẵẹẻẽềếệểễịỉĩọỏõồốộổỗờớợởỡụủũừứựửữỳỵỷỹđ]", json.dumps(asked, ensure_ascii=False))


def test_classify_sends_the_request_verbatim_and_maps_probabilities():
    jev = FakeJev(jev_answer("orders", 0.7, orders=0.8, customer_service=0.15, multi_department=0.05))
    c = asyncio.run(router.classify("Đơn DH1001 giao chưa?", CTX, jev))
    state, asked = jev.calls[0]
    assert state == "Đơn DH1001 giao chưa?" and set(asked) == {"route", "missing_context", "covered"}
    assert (c.choice, c.confidence, c.missing_context, c.covered, c.model) == ("orders", 0.7, 0.1, 0.9, "jev-1.13.0")
    assert c.agent_scores["orders"] == 0.8 and c.agent_scores["customer_service"] == 0.15
    assert c.route_scores == {"procedure": 0.0, "single": pytest.approx(0.95), "multi": 0.05, "unknown": 0.0}
    assert c.usage == {"input_tokens": 300, "output_tokens": 20}


def test_a_follow_up_sends_the_room_beside_the_request_and_asks_about_request():
    jev = FakeJev(jev_answer("orders", 0.7, redo=0.1))
    room = {"turns": [{"turn": 1, "request": "Tra đơn DH1001", "facts": {"order_id": "DH1001"}}]}
    asyncio.run(router.classify("Hoàn tiền cho đơn đó", CTX, jev, room))
    state, asked = jev.calls[0]
    # Same field order on every request (TypeSafe docs), the request last
    assert list(state) == ["earlier_in_room", "request"] and state["request"] == "Hoàn tiền cho đơn đó"
    assert "`request`" in asked["route"]["instructions"] and "`earlier_in_room`" in asked["route"]["instructions"]
    assert "`earlier_in_room`" in asked["missing_context"]["criteria"]["false"]
    assert "`request`" in asked["covered"]["instructions"]["question"]
    # A room's first request keeps the questions the thresholds were tuned on
    assert router.questions(router.department_agents())["missing_context"] is router._MISSING_CONTEXT


def test_the_redo_question_is_asked_only_inside_a_room():
    jev = FakeJev(jev_answer("orders", 0.7))
    asyncio.run(router.classify("Đơn DH1001 giao chưa?", CTX, jev))
    assert "redo" not in jev.calls[0][1]
    jev = FakeJev(jev_answer("orders", 0.7, redo=0.9))
    room = {"turns": [{"turn": 1, "request": "Tra đơn DH1001", "facts": {"order_id": "DH1001"}}]}
    c = asyncio.run(router.classify("làm lại đi", CTX, jev, room))
    assert "redo" in jev.calls[0][1] and c.redo == 0.9
    assert router.decide(c) == Route("redo", "coordinator")


@pytest.mark.parametrize("answer", [
    jev_answer("sales", 0.9),  # not an offered option
    {"answers": {"route": {"choice": "orders"}}},  # missing fields
    {"error": "nope"},
])
def test_classify_rejects_answers_it_cannot_use(answer):
    with pytest.raises(router.RouterError):
        asyncio.run(router.classify("x", CTX, FakeJev(answer)))


def _client(responses, seen, sleeps):
    replies = iter(responses)

    def handle(request):
        seen.append(request)
        status, body = next(replies)
        return httpx.Response(status, json=body)

    async def sleep(delay):
        sleeps.append(delay)

    return router.Jev("ts-key", transport=httpx.MockTransport(handle), sleep=sleep)


def test_jev_client_posts_state_and_questions_with_the_key():
    seen, sleeps = [], []
    jev = _client([(200, jev_answer("orders", 1.0))], seen, sleeps)
    asyncio.run(jev.system_one("hỏi", {"q": {"type": "noul"}}))
    request = seen[0]
    assert str(request.url) == router.JEV_URL and request.headers["authorization"] == "Bearer ts-key"
    assert json.loads(request.content) == {"model": router.JEV_MODEL, "state": "hỏi", "questions": {"q": {"type": "noul"}}}


def test_jev_client_retries_rate_limits_and_overload_only():
    seen, sleeps = [], []
    jev = _client([(429, {}), (529, {}), (200, jev_answer("orders", 1.0))], seen, sleeps)
    assert asyncio.run(jev.system_one("x", {}))["model"] == "jev-1.13.0"
    assert len(seen) == 3 and sleeps == [0.5, 1.0]

    seen, sleeps = [], []
    jev = _client([(401, {"detail": "bad key"})], seen, sleeps)
    with pytest.raises(router.RouterError, match="401"):
        asyncio.run(jev.system_one("x", {}))
    assert len(seen) == 1 and sleeps == []


def test_jev_needs_an_api_key(monkeypatch):
    monkeypatch.delenv(router.API_KEY_ENV, raising=False)
    with pytest.raises(router.RouterError, match=router.API_KEY_ENV):
        router.jev_from_env()
