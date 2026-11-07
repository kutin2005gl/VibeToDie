"""The /run flow: route the request with Jev, then run a worker agent or the Coordinator."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app import mandates
from app.core import compaction, router
from app.core.agent import AgentLoop, RunFinished, StepStarted, ToolCallFinished, ToolCallStarted
from app.core.context import RequestContext
from app.core.contract import verifier
from app.core.coordinator import Coordinator, CoordinatorError, Verify, current_step
from app.core.llm import Completion, Message, ModelClient, ModelConfig, SystemMessage, Usage, UserMessage
from app.schemas import RunRequest, RunResult
from app.services import clients
from app.services import factory
from app.services import procedure
from app.services.factory import OwnAgents
from app.services.formatting import RETRIEVED, procedure_task, render, single_task, today
from app.tools import build_tools

log = logging.getLogger(__name__)

COORDINATOR = "coordinator"
# Router branches the Coordinator runs. On unknown it asks the user once, then may request an agent
# from Factory (coordinate)
COORDINATED_BRANCHES = ("multi", router.LOW_CONFIDENCE, router.CLARIFY, "unknown")
# The branch whose question is searched in the documents before the agent runs
PROCEDURE_BRANCH = "procedure"

# A stream idle this long gets an SSE comment, so a proxy does not cut it during a long model call
HEARTBEAT_SECONDS = 15
# Model text, tool arguments and tool results are cut to this in the trace kept for admins
TRACE_CHARS = 4000
# Progress kept for admins only: staff following a run never receive these events or fields
ADMIN_EVENTS = ("llm_call", "agent_finished")
ADMIN_FIELDS = ("arguments", "content", "text")


def is_admin(ctx: RequestContext) -> bool:
    """Whether the requester is in the admin department (ADMIN_DEPARTMENT, as in user-service)."""
    return os.environ.get("ADMIN_DEPARTMENT", "executive") in ctx.departments

# Receives progress while a run goes on: an SSE event name and its JSON data
Emit = Callable[[str, dict[str, Any]], None]


def _ignore(event: str, data: dict[str, Any]) -> None:
    pass


def public(event: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """`data` as a client following the run may see it; None for an event kept for admins."""
    if event in ADMIN_EVENTS:
        return None
    return {k: v for k, v in data.items() if k not in ADMIN_FIELDS}


async def jev_route(text: str, ctx: RequestContext, room: dict[str, Any] | None = None,
                    own: OwnAgents | None = None) -> dict[str, Any]:
    """Jev's answers for `text`, and the branch and target code picks from them for this requester.

    `room` is the room context of earlier turns, so Jev can tell what a follow-up refers to. `own`
    adds the requester's own agents to the ones Jev chooses from.
    """
    try:
        jev = clients.jev_client()
    except router.RouterError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    mine = own.agents if own else []
    try:
        scores = await router.classify(text, ctx, jev, room, router.department_agents() + mine)
    except router.RouterError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    picked = router.authorize(router.decide(scores), ctx, mine)
    # Jev's tokens are billed apart from the LLM's, so they stay here instead of input_tokens
    return {"branch": picked.branch, "target": picked.target, "choice": scores.choice,
            "confidence": scores.confidence, "missing_context": scores.missing_context, "covered": scores.covered,
            "redo": scores.redo,
            "route_scores": scores.route_scores, "agent_scores": scores.agent_scores,
            "model": scores.model, "usage": scores.usage}


async def stream(req: RunRequest, ctx: RequestContext) -> AsyncIterator[str]:
    """Run `req` as server-sent events: progress, then `done` with the /run result or `error`.

    The response is already 200 once the first event is sent, so failures arrive as an `error`
    event carrying the status /run would have answered. If the client goes away, the run is
    cancelled.
    """
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def emit(event: str, data: dict[str, Any]) -> None:
        shown = public(event, data)
        if shown is not None:
            queue.put_nowait((event, shown))

    async def work() -> None:
        try:
            result = await run(req, ctx, emit)
            emit("done", RunResult(**result).model_dump())
        except HTTPException as e:
            emit("error", {"status": e.status_code, "detail": e.detail})
        except Exception:
            log.exception("streamed run failed")
            emit("error", {"status": 500, "detail": "internal error"})

    task = asyncio.create_task(work())
    try:
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if event in ("done", "error"):
                return
    finally:
        task.cancel()


class ResumableFailure(HTTPException):
    """A Coordinator run that failed with a checkpoint: sessions keep it so the run can be continued."""

    def __init__(self, detail: str, checkpoint: dict[str, Any]) -> None:
        super().__init__(status_code=502, detail=detail)
        self.checkpoint = checkpoint


async def run(req: RunRequest, ctx: RequestContext, emit: Emit = _ignore,
              room: dict[str, Any] | None = None, own: OwnAgents | None = None,
              on_redo: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Run `req` for the requester: the agent the client named, or the one Jev routes it to.

    `room` is the room context of earlier turns (`compaction.room_view`), read by Jev and every agent.
    `own` are the requester's own agents; without it (no saved sessions) Factory is not offered.
    `on_redo` runs when Jev finds the request only asks to do the last one again: it gets the route and
    returns the result (the session knows how the last request ended). Without it such a request is
    handled by the Coordinator like any unclear one.
    """
    clients.check_provider(req.provider)
    if req.clarifications:
        # Jev routed this request on its first turn and only the Coordinator asks, so it takes the answers
        if req.agent is not None:
            raise HTTPException(status_code=422, detail="clarifications cannot be combined with agent")
        return await coordinate(req, ctx, None, emit, origin="clarified", room=room, own=own)

    route: dict[str, Any] | None = None
    agent = req.agent
    if agent is None:
        route = await jev_route(req.text, ctx, room, own)
        agent = route["target"]
        emit("route", {"branch": route["branch"], "target": agent})
        if route["branch"] == router.REDO:
            if on_redo is not None:
                return await on_redo(route)
            route = {**route, "branch": router.LOW_CONFIDENCE}

    mine = {m.name: m for m in own.agents} if own else {}
    try:
        mandate = mine.get(agent) or mandates.load(agent)
    except mandates.MandateError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if route is not None and route["branch"] == router.FORBIDDEN:
        # Refused in code whatever Jev answered, so a steered request never reaches the agent
        return not_run(req.provider, agent, route, (
            f"Yêu cầu này thuộc phạm vi của phòng ban {', '.join(mandate.departments)}; "
            "tài khoản của bạn chưa có quyền. Hãy liên hệ quản lý nếu cần."
        ))
    if "claims" not in mandate.output_schema["properties"]:
        if route is None:
            raise HTTPException(status_code=422, detail=f"agent {agent!r} is not a worker agent")
        if route["branch"] in COORDINATED_BRANCHES:
            return await coordinate(req, ctx, route, emit, origin=route["branch"], room=room, own=own)
        # No branch routes to another non-worker today: report the route without running it
        return not_run(req.provider, agent, route,
                       f"Jev xếp yêu cầu vào nhánh {route['branch']}, cần {agent} xử lý; luồng này chưa được nối.")
    if route is None and not mandate.usable_by(ctx.departments):
        raise HTTPException(status_code=403, detail=f"departments {list(ctx.departments)} may not use agent {agent!r}")

    room_block = compaction.block(room) if room else ""
    task = single_task(req.text, today(), room_block)
    sources: dict[str, Any] = {**(compaction.sources(room) if room else {}), "input": {"text": req.text}}
    if route is not None and route["branch"] == PROCEDURE_BRANCH:
        # Search first, with the requester's permissions: no passage above the threshold means no model call
        passages = procedure.retrieve(req.text, ctx)
        if not passages:
            return not_run(req.provider, agent, route, procedure.NO_BASIS,
                           {"status": "blocked", "summary": procedure.NO_BASIS, "claims": [],
                            "answer": procedure.NO_BASIS, "open_questions": []})
        task = procedure_task(req.text, today(), passages, room_block)
        # Same shape as a search_sop result, so ref.path = chunk_id resolves to the passage text
        sources[RETRIEVED] = passages

    llm, model = clients.model_for(req.provider, mandate)
    messages: list[Message] = [SystemMessage(content=mandate.system_prompt), UserMessage(content=task)]
    finished = await run_agent(llm, ctx, mandate, messages, verifier(sources=sources), emit,
                               clients.config_for(req.provider, mandate))
    if finished.status != "done" or finished.final is None:
        raise HTTPException(status_code=502, detail=f"run {finished.status}: {finished.reason}")
    if route is not None and finished.final.get("status") == "escalate":
        # Out of the agent's scope: Coordinator plans the rest, reusing the work already checked by code
        escalation = {"agent": mandate.name, "summary": finished.final.get("summary"),
                      "claims": finished.final.get("claims"), "open_questions": finished.final.get("open_questions")}
        return await coordinate(req, ctx, route, emit, origin="escalated", escalation=escalation, spent=finished,
                                room=room, own=own)

    return {
        "provider": req.provider,
        "model": model,
        "output": render(finished.final),
        "input_tokens": finished.usage.prompt_tokens,
        "output_tokens": finished.usage.completion_tokens,
        "agent": mandate.name,
        "steps": finished.steps,
        "result": finished.final,
        "pending_actions": [
            {"id": call.id, "name": call.name, "arguments": json.loads(call.arguments)}
            for call in finished.pending_actions
        ],
        "route": route,
    }


def _clip(text: str) -> str:
    return text if len(text) <= TRACE_CHARS else text[:TRACE_CHARS] + "…"


def _tagged(emit: Emit, step_id: str | None) -> Emit:
    """`emit` adding the Coordinator step a run belongs to, so steps running at the same time are told apart."""
    if step_id is None:
        return emit
    return lambda event, data: emit(event, {**data, "step_id": step_id})


async def run_agent(llm: ModelClient, ctx: RequestContext, mandate: mandates.Mandate,
                    messages: list[Message], verify: Verify, emit: Emit = _ignore,
                    config: ModelConfig | None = None) -> RunFinished:
    """Run `mandate` to the end on `llm`, its tools acting with the requester's permissions.

    `config` prices each model call; without one (the fake provider) calls cost nothing known.
    """
    emit = _tagged(emit, current_step.get())
    loop = AgentLoop(llm, build_tools(mandate.tools, ctx), mandate.output_schema, verify=verify)
    finished: RunFinished | None = None
    step = 0
    async for event in loop.run(messages):
        if isinstance(event, StepStarted):
            step = event.step
            emit("step", {"agent": mandate.name, "step": event.step, "max_steps": event.max_steps})
        elif isinstance(event, Completion):
            cost = None if config is None else config.cost(event.usage, datetime.now(timezone.utc))
            emit("llm_call", {"agent": mandate.name, "step": step, "model": config.model if config else "fake",
                              "prompt_tokens": event.usage.prompt_tokens,
                              "completion_tokens": event.usage.completion_tokens, "cost_usd": cost,
                              "duration_ms": event.duration_ms, "attempts": event.attempts,
                              "finish_reason": event.finish_reason, "text": _clip(event.message.content)})
        elif isinstance(event, ToolCallStarted):
            emit("tool_call", {"agent": mandate.name, "step": event.step, "id": event.call.id,
                               "name": event.call.name, "arguments": _clip(event.call.arguments)})
        elif isinstance(event, ToolCallFinished):
            emit("tool_result", {"agent": mandate.name, "step": event.step, "id": event.call_id,
                                 "is_error": event.result.is_error, "content": _clip(event.result.content)})
        elif isinstance(event, RunFinished):
            finished = event
            emit("agent_finished", {"agent": mandate.name, "status": event.status, "reason": event.reason,
                                    "steps": event.steps, "prompt_tokens": event.usage.prompt_tokens,
                                    "completion_tokens": event.usage.completion_tokens})
    assert finished is not None
    return finished


async def coordinate(req: RunRequest, ctx: RequestContext, route: dict[str, Any] | None, emit: Emit, origin: str,
                     escalation: dict[str, Any] | None = None, spent: RunFinished | None = None,
                     room: dict[str, Any] | None = None, own: OwnAgents | None = None,
                     notes: dict[str, Any] | None = None, ask_factory: bool = True,
                     checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the Coordinator over every worker agent the requester may use; `spent` is an escalated worker run.

    `checkpoint` is a failed run's (`ResumableFailure`): the Coordinator continues it instead of planning.

    `own` adds the requester's own agents, and lets a `request_agent` go to Factory once (`ask_factory`).
    `notes` are extra plan-phase blocks for the Coordinator, such as the agent just approved.
    """
    coordinator = mandates.load(COORDINATOR)
    workers = [m for m in map(mandates.load, mandates.names()) if "claims" in m.output_schema["properties"]]
    catalog = [m for m in workers if m.usable_by(ctx.departments)] + (own.agents if own else [])
    unavailable = [m for m in workers if not m.usable_by(ctx.departments)]

    async def run(mandate: mandates.Mandate, messages: list[Message], verify: Verify) -> RunFinished:
        return await run_agent(clients.model_for(req.provider, mandate)[0], ctx, mandate, messages, verify, emit,
                               clients.config_for(req.provider, mandate))

    clarifications = [c.model_dump() for c in req.clarifications]
    runner = Coordinator(coordinator, catalog, run, today(), unavailable, on_event=emit,
                         room=compaction.block(room) if room else "",
                         room_sources=compaction.sources(room) if room else None)
    try:
        if checkpoint is not None:
            gone = {s["agent"] for s in checkpoint["plan"]["steps"]} - {m.name for m in catalog}
            if gone:
                raise HTTPException(status_code=409, detail=f"the saved plan needs agents that are not available now: {sorted(gone)}")
            outcome = await runner.resume(req.text, origin, checkpoint, escalation, clarifications, notes)
        else:
            outcome = await runner.run(req.text, origin, escalation, clarifications, notes)
    except CoordinatorError as e:
        if e.checkpoint is not None:
            raise ResumableFailure(str(e), {"coordinator": e.checkpoint, "origin": origin, "route": route,
                                            "escalation": escalation, "notes": notes}) from e
        raise HTTPException(status_code=502, detail=str(e)) from e
    if outcome.decision == "request_agent" and own is not None and ask_factory:
        proposal = await factory.draft(req.text, [c.model_dump() for c in req.clarifications], outcome.agent_request,
                                       catalog, unavailable, ctx, own, run)
        if proposal.status == "done" and proposal.final is not None:
            if proposal.final["decision"] == "use_existing":
                # The Coordinator missed an agent it has: one more plan with it named, and no second Factory
                hint = {"name": proposal.final["existing_agent"], "agent_request": outcome.agent_request,
                        "reason": proposal.final["summary"]}
                return await coordinate(req, ctx, route, emit, origin, escalation, spent, room, own,
                                        {**(notes or {}), "factory_hint": hint}, ask_factory=False)
            # create waits for the requester's approval (sessions), reject tells them why
            mandate = mandates.load(factory.FACTORY)
            return {"provider": req.provider, "model": clients.model_for(req.provider, mandate)[1],
                    "output": proposal.final["summary"],
                    "input_tokens": outcome.usage.prompt_tokens + proposal.usage.prompt_tokens,
                    "output_tokens": outcome.usage.completion_tokens + proposal.usage.completion_tokens,
                    "agent": factory.FACTORY, "steps": outcome.model_steps + proposal.steps,
                    "result": proposal.final, "pending_actions": [], "route": route}
        # Factory could not design one: the staff member still sees what is missing
        log.warning("factory %s: %s", proposal.status, proposal.reason)
    _, model = clients.model_for(req.provider, coordinator)
    usage = outcome.usage if spent is None else Usage(outcome.usage.prompt_tokens + spent.usage.prompt_tokens,
                                                      outcome.usage.completion_tokens + spent.usage.completion_tokens)
    text_key = {"clarify": "clarify_question", "request_agent": "agent_request"}.get(outcome.decision, "final_response")
    return {
        "provider": req.provider,
        "model": model,
        "output": outcome.output,
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "agent": COORDINATOR,
        "steps": outcome.model_steps + (spent.steps if spent else 0),
        "result": {"decision": outcome.decision,
                   text_key: outcome.agent_request if outcome.decision == "request_agent" else outcome.output,
                   "plan": outcome.plan, "steps": outcome.steps, "replans": outcome.replans},
        "pending_actions": outcome.pending_actions,
        "route": route,
    }


async def resume(req: RunRequest, ctx: RequestContext, saved: dict[str, Any], emit: Emit = _ignore,
                 room: dict[str, Any] | None = None, own: OwnAgents | None = None) -> dict[str, Any]:
    """Continue the Coordinator run that failed with `saved` (a `ResumableFailure`'s checkpoint)."""
    return await coordinate(req, ctx, saved["route"], emit, saved["origin"], saved["escalation"], room=room, own=own,
                            notes=saved["notes"], checkpoint=saved["coordinator"])


def not_run(provider: str, agent: str, route: dict[str, Any], output: str,
            result: dict[str, Any] | None = None) -> dict[str, Any]:
    """A /run response for a routed request that no agent ran."""
    return {"provider": provider, "model": "", "output": output, "input_tokens": 0, "output_tokens": 0,
            "agent": agent, "steps": 0, "result": result or {}, "pending_actions": [], "route": route}
