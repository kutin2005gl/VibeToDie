"""Router (Jev): asks TypeSafe's Jev where a staff request goes, then picks the target in code.

Jev is a System One decision model, not an LLM: one request carries the `state` (the staff request,
verbatim) and typed questions, and the answer is probabilities plus a confidence. Questions and
criteria are English, the language Jev reads best; department choices come from the mandates'
`description`, so an agent Factory adds is routable without code changes. `decide` holds the branch
rules as plain code (PLAN-lite §Router).
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app import mandates
from app.core.context import RequestContext

DEPARTMENT = "_department"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
# Pinned: thresholds are tuned against this version, and the jev-latest alias moves between releases
JEV_MODEL = "jev-1.14.0"
API_KEY_ENV = "TYPESAFE_API_KEY"

POLICY = "policy_lookup"
MULTI = "multi_department"
NO_AGENT = "no_fitting_agent"
LOW_CONFIDENCE = "low_confidence"
CLARIFY = "clarify"
FORBIDDEN = "forbidden"
# The request only asks to do the room's last request again (the session decides how)
REDO = "redo"
# Placeholders until the router eval is measured
THRESHOLD = 0.5
CLARIFY_AT = 0.7
# A `covered` Noul at or below this means no handler fits (TypeSafe's suggested starting "no" level)
UNCOVERED_AT = 0.3
# Placeholder until the router eval has redo cases
REDO_AT = 0.7

_ROUTE_INSTRUCTIONS = "Which handler should take this request from a store employee?"
_BRANCH_CRITERIA = {
    POLICY: (
        "Use when the request only asks about internal processes, policies or guides that the SOP "
        "documents answer, without data about a specific order, customer, device, ticket or account."
    ),
    MULTI: (
        "Use when the request needs work from more than one of the department handlers listed here, "
        "for example looking up an order, calculating a refund and drafting a reply to the customer."
    ),
    NO_AGENT: "Use when none of the other handlers covers the core of the request.",
}
_MISSING_CONTEXT = {
    "type": "noul",
    "instructions": "Does the employee still need to give more details before anyone can act on this request?",
    "criteria": {
        "true": (
            "It points to a specific order, customer, device, ticket or account without any id, name or "
            "detail to find it (for example 'this order', 'that customer', 'my ticket'), or it asks to "
            "reply to or analyze a message it does not include."
        ),
        "false": (
            "It names what it is about, or it is a general request. Data the company's systems already "
            "hold (orders, products, prices, stock, sales figures, policies) is never missing: the "
            "handlers look it up. A request that quotes the customer's message is not missing it."
        ),
    },
}
# A later request of a room: the state is an object, the request beside what the room did before.
# The first request keeps the plain-text state and the questions above, which the thresholds were tuned on.
_ROOM_NOTE = (
    " `request` is the employee's new request; `earlier_in_room` is what their earlier requests in the "
    "same chat asked and got, there only to tell what `request` refers to."
)
_ROOM_MISSING_CONTEXT = {
    "type": "noul",
    "instructions": "Does the employee still need to give more details before anyone can act on `request`?"
                    + _ROOM_NOTE,
    "criteria": {
        "true": (
            "`request` points to a specific order, customer, device, ticket or account without any id, name or "
            "detail to find it, and `earlier_in_room` does not say which one either; or it asks to reply to or "
            "analyze a message that neither includes."
        ),
        "false": (
            "`request` names what it is about, `earlier_in_room` makes clear what it refers to (for example "
            "'that order' after an earlier request about one order), or it is a general request. Data the "
            "company's systems already hold is never missing: the handlers look it up."
        ),
    },
}
_ROOM_REDO = {
    "type": "noul",
    "instructions": "Does `request` only ask to do the latest request of `earlier_in_room` again?" + _ROOM_NOTE,
    "criteria": {
        "true": (
            "`request` asks to retry, redo, run again or try again what was asked last (for example "
            "'làm lại đi', 'thử lại', 'chạy lại giúp mình', 'try again'), adding nothing new to it."
        ),
        "false": (
            "`request` asks for something new, or asks to redo it with a change (another tone, length, "
            "order, customer or step), or refers to an earlier request without asking to run it again."
        ),
    },
}
# A Choice handles "none of the above" poorly (TypeSafe docs), so coverage gets its own Noul
_COVERED_QUESTION = "Can one or more of these handlers do the core of the request?"
_COVERED_CRITERIA = {
    "true": "At least one handler's description covers the main work the request asks for.",
    "false": "The main work the request asks for is something none of the handlers' descriptions covers.",
}
# Statuses worth retrying: rate limit and TypeSafe overload
_RETRYABLE = (429, 529)
_ATTEMPTS = 3


class RouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class Classification:
    # The `classify` interface of PLAN-lite: procedure / single / multi / unknown
    route_scores: dict[str, float]
    # Probability of each department agent being the single handler
    agent_scores: dict[str, float]
    # Jev's top choice among POLICY, MULTI, NO_AGENT and the department agents, and its confidence
    choice: str
    confidence: float
    # Probability that the request lacks information only the employee can give
    missing_context: float
    # Probability that some handler covers the core of the request
    covered: float
    model: str
    usage: dict[str, int]
    # Probability that the request only asks to redo the room's last request (asked only inside a room)
    redo: float = 0.0


@dataclass(frozen=True)
class Route:
    # procedure | single | multi | unknown | low_confidence | clarify | forbidden | redo
    branch: str
    # The mandate the request goes to
    target: str


class Jev:
    """Minimal client for `POST /v1/systemone`."""

    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=10.0, transport=transport
        )
        self._sleep = sleep

    async def system_one(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        body = {"model": JEV_MODEL, "state": state, "questions": questions}
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                resp = await self._http.post(JEV_URL, json=body)
            except httpx.HTTPError as e:
                raise RouterError(f"jev unreachable: {e}") from e
            if resp.status_code in _RETRYABLE and attempt < _ATTEMPTS:
                await self._sleep(0.5 * 2 ** (attempt - 1))
                continue
            if resp.status_code != 200:
                raise RouterError(f"jev returned {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise AssertionError("unreachable")


def jev_from_env() -> Jev:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RouterError(f"{API_KEY_ENV} is not set")
    return Jev(key)


def department_agents() -> list[mandates.Mandate]:
    loaded = (mandates.load(name) for name in mandates.names())
    return [mandate for mandate in loaded if DEPARTMENT in mandate.includes]


def questions(catalog: list[mandates.Mandate], with_room: bool = False) -> dict[str, Any]:
    """One Choice over the branches and every department agent, plus the missing-context and coverage Nouls.

    `with_room`: the state is `{earlier_in_room, request}`, so the questions name `request`.
    """
    handlers = {POLICY: _BRANCH_CRITERIA[POLICY]} | {m.name: m.description for m in catalog}
    criteria = handlers | {MULTI: _BRANCH_CRITERIA[MULTI], NO_AGENT: _BRANCH_CRITERIA[NO_AGENT]}
    route, covered, missing = _ROUTE_INSTRUCTIONS, _COVERED_QUESTION, _MISSING_CONTEXT
    if with_room:
        route = route.replace("this request", "`request`") + _ROOM_NOTE
        covered = covered.replace("the request", "`request`") + _ROOM_NOTE
        missing = _ROOM_MISSING_CONTEXT
    asked = {
        "route": {"type": "choice", "instructions": route, "criteria": criteria},
        "missing_context": missing,
        "covered": {
            "type": "noul",
            "instructions": {"question": covered, "handlers": handlers},
            "criteria": _COVERED_CRITERIA,
        },
    }
    if with_room:
        asked["redo"] = _ROOM_REDO
    return asked


async def classify(text: str, ctx: RequestContext, jev: Jev, room: dict[str, Any] | None = None,
                   catalog: list[mandates.Mandate] | None = None) -> Classification:
    """Ask Jev about `text`; the catalog is every department agent until agents map to `ctx.departments`.

    `room` is the context of the room's earlier requests; Jev reads it beside `text`, always in the
    same field order (TypeSafe docs), to tell what a follow-up refers to. `catalog` replaces the
    department agents, e.g. with the requester's own agents added.
    """
    catalog = department_agents() if catalog is None else catalog
    asked = questions(catalog, with_room=room is not None)
    state: Any = text if room is None else {"earlier_in_room": room, "request": text}
    result = await jev.system_one(state, asked)
    try:
        route = result["answers"]["route"]
        probabilities = {name: float(route["probabilities"].get(name, 0.0)) for name in asked["route"]["criteria"]}
        choice, confidence = route["choice"], float(route["confidence"])
        missing = float(result["answers"]["missing_context"]["noul"])
        covered = float(result["answers"]["covered"]["noul"])
        redo = float(result["answers"]["redo"]["noul"]) if "redo" in asked else 0.0
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise RouterError(f"unexpected jev answer: {e!r}") from e
    if choice not in probabilities:
        raise RouterError(f"jev chose {choice!r}, which was not offered")

    agents = {m.name: probabilities[m.name] for m in catalog}
    return Classification(
        route_scores={
            "procedure": probabilities[POLICY],
            "single": sum(agents.values()),
            "multi": probabilities[MULTI],
            "unknown": probabilities[NO_AGENT],
        },
        agent_scores=agents,
        choice=choice,
        confidence=confidence,
        missing_context=missing,
        covered=covered,
        model=str(result.get("model", JEV_MODEL)),
        usage=dict(result.get("usage") or {}),
        redo=redo,
    )


def decide(
    c: Classification,
    threshold: float = THRESHOLD,
    clarify_at: float = CLARIFY_AT,
    uncovered_at: float = UNCOVERED_AT,
    redo_at: float = REDO_AT,
) -> Route:
    """The branch rules. Coordinator asks the user when context is missing or Jev is unsure."""
    if c.redo >= redo_at:
        # The session looks at how the last request ended to resume it or run it again
        return Route(REDO, "coordinator")
    if c.covered <= uncovered_at:
        # Factory runs only after one clarify round (PLAN-lite §Clarify), so missing context is asked there
        return Route("unknown", "factory")
    if c.missing_context >= clarify_at:
        return Route(CLARIFY, "coordinator")
    if c.confidence < threshold:
        return Route(LOW_CONFIDENCE, "coordinator")
    if c.choice == POLICY:
        return Route("procedure", "knowledge")
    if c.choice == MULTI:
        return Route("multi", "coordinator")
    if c.choice == NO_AGENT:
        return Route("unknown", "factory")
    return Route("single", c.choice)


def authorize(route: Route, ctx: RequestContext, own: list[mandates.Mandate] | None = None) -> Route:
    """Refuse a route straight to an agent the requester may not use, whatever Jev answered.

    Jev sees every department agent so a request outside the requester's scope is named as such
    instead of drifting to the nearest allowed agent. Coordinator and Factory get only the agents the
    requester may use when they run, so their routes pass through here unchanged. `own` are the
    requester's own agents, theirs to use.
    """
    if route.branch not in ("single", "procedure"):
        return route
    if any(m.name == route.target for m in own or ()):
        return route
    if mandates.load(route.target).usable_by(ctx.departments):
        return route
    return Route(FORBIDDEN, route.target)
