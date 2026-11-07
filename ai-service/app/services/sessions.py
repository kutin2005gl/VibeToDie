"""Staff sessions (rooms), saved per user: turn after turn, a request, the AI's answer, then clarify
answers or an approval. Each finished turn leaves a digest that later turns read as room context."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from fastapi.encoders import jsonable_encoder

from app import mandates
from app.core import compaction
from app.core.context import RequestContext
from app.core.coordinator import MAX_CLARIFY_ROUNDS
from app.core.llm import Message, SystemMessage, UserMessage
from app.schemas import Clarification, RunRequest
from app.services import clients, factory, provider as provider_service
from app.services import run as run_service
from app.services.progress import PROGRESS
from app.store.sessions import DONE, FAILED, LOST, RUNNING, STOPPED, WAITING, WEB, Session, SessionStore
from app.tools import build_tools

log = logging.getLogger(__name__)
TITLE_CHARS = 48
COMPACTOR = "compactor"
# A finished turn ended on one of these may be followed by a new request
FOLLOWABLE = (DONE, FAILED)
# A failed run is continued by "làm lại" only this long after it failed; later it is run again from the start
RESUME_TTL = timedelta(minutes=30)


def _item(items: list[dict[str, Any]], kind: str, **fields: Any) -> dict[str, Any]:
    return {"id": str(len(items) + 1), "kind": kind, "at": datetime.now(timezone.utc).isoformat(), **fields}


def pending(s: Session) -> dict[str, Any] | None:
    """The clarify question, approval or agent proposal waiting for staff: always the last item of a waiting session."""
    return s.items[-1] if s.status == WAITING else None


# Both return the session still running: a run takes minutes, longer than a client or the gateway
# waits, so it goes on in the background and the client follows GET /api/sessions/{id}/events.
# PROGRESS.start comes before the response, so a client that follows at once finds the run.
async def create(store: SessionStore, ctx: RequestContext, text: str, requested: str | None,
                 background: BackgroundTasks, origin: dict[str, Any] | None = None) -> Session:
    """`origin`: where a client other than the web opened the room; its `kind` is the room's source."""
    provider = await provider_service.choose(store, requested)
    clients.check_provider(provider)  # refuse a bad provider before anything is saved
    title = text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS].rstrip() + "…"
    s = await store.create(ctx.user_id, list(ctx.departments), title, provider, [_item([], "request", body=text)],
                           source=origin["kind"] if origin else WEB, origin=origin)
    PROGRESS.start(s.id)
    background.add_task(_run, store, ctx, s)
    return s


async def answer(store: SessionStore, ctx: RequestContext, s: Session, text: str,
                 background: BackgroundTasks) -> Session:
    asked = pending(s)
    if asked is None or asked["kind"] != "clarify" or len(s.clarifications) >= MAX_CLARIFY_ROUNDS:
        raise HTTPException(status_code=409, detail="session is not waiting for an answer")
    asked["answer"] = text
    s.clarifications.append({"question": asked["question"], "answer": text})
    s.items.append(_item(s.items, "reply", body=text))
    return await _start(store, ctx, s, background)


async def follow_up(store: SessionStore, ctx: RequestContext, s: Session, text: str,
                    background: BackgroundTasks) -> Session:
    """A new request in a room whose last turn is finished: a new turn that reads the earlier ones."""
    if s.status not in FOLLOWABLE:
        raise HTTPException(status_code=409, detail="session is not ready for a new request")
    if _turn(s) >= compaction.MAX_TURNS:
        raise HTTPException(status_code=409, detail="room is full: start a new room")
    # Clarify rounds belong to one request: the new one starts with none. The old ones stay with their
    # request, in case a later "làm lại" runs it again
    _request_item(s)["clarifications"] = s.clarifications
    s.clarifications = []
    s.items.append(_item(s.items, "request", body=text))
    return await _start(store, ctx, s, background)


async def _start(store: SessionStore, ctx: RequestContext, s: Session, background: BackgroundTasks,
                 new_agent: dict[str, Any] | None = None) -> Session:
    # Each run uses the provider the admin has chosen now, not the one the room started on
    s.provider = await provider_service.choose(store, None)
    clients.check_provider(s.provider)
    s.status = RUNNING
    # Registered before the save, so the session is never running without a run a client can follow
    PROGRESS.start(s.id)
    try:
        # Saved before the run, so a second answer sent meanwhile gets 409 instead of starting another run
        s = await store.save(s)
    except BaseException:
        PROGRESS.finish(s.id)
        raise
    background.add_task(_run, store, ctx, s, new_agent)
    return s


async def decide(store: SessionStore, ctx: RequestContext, s: Session, approve: bool,
                 background: BackgroundTasks) -> Session:
    """Record the decision; approved, run each queued action once, never retried (FR-19), or put the
    proposed agent to work on the request."""
    asked = pending(s)
    if asked is None or asked["kind"] not in ("approval", "agent_proposal"):
        raise HTTPException(status_code=409, detail="session is not awaiting approval")
    asked["decision"] = {"value": "yes" if approve else "no", "at": datetime.now(timezone.utc).isoformat()}
    if asked["kind"] == "agent_proposal":
        return await _decide_agent(store, ctx, s, asked, approve, background)
    if approve:
        for action in asked["actions"]:
            # Left as sending if the service stops mid-way: staff check the outcome, nothing runs it again
            action["status"] = "sending"
    if s.turns and s.turns[-1]["turn"] == _turn(s):
        # Later turns read whether the queued actions were approved
        s.turns[-1]["outcome"] = "approved" if approve else "rejected"
    s.status = DONE
    # Saved before any action runs, so a second decision gets 409 instead of running them again
    saved = await store.save(s)
    if not approve:
        return saved
    for n, action in enumerate(asked["actions"]):
        action.update(await _execute(ctx, f"{s.id}:{asked['id']}:{n}", action))
    return await store.save(s)


async def _decide_agent(store: SessionStore, ctx: RequestContext, s: Session, asked: dict[str, Any],
                        approve: bool, background: BackgroundTasks) -> Session:
    """Activate or reject the draft agent; activated, the Coordinator plans the request again with it."""
    # Only a draft changes, so a decision racing this one gets 409 instead of a second run
    if not await store.decide_agent(ctx.user_id, asked["agent_id"], approve):
        raise HTTPException(status_code=409, detail="session is not awaiting approval")
    if approve:
        return await _start(store, ctx, s, background,
                            {"name": asked["name"], "description": asked["description"]})
    s.turns.append(compaction.digest(_turn(s), _request(s), factory.FACTORY, "rejected", text=asked["summary"]))
    s.status = DONE
    return await store.save(s)


async def _execute(ctx: RequestContext, key: str, action: dict[str, Any]) -> dict[str, Any]:
    """Run one approved action with the requester's permissions; returns its status for the thread."""
    at = datetime.now(timezone.utc).isoformat()
    tools = build_tools((action["name"],), ctx)
    if not tools:
        return {"status": "failed", "error": f"no tool named {action['name']}", "at": at}
    try:
        result = await tools[0].run(json.dumps(action["arguments"]), key)
    except Exception:
        log.exception("approved action %s failed", key)
        return {"status": "failed", "error": "internal error", "at": at}
    if result.is_error:
        return {"status": "failed", "error": result.content, "at": at}
    return {"status": "done", "at": at}


async def _run(store: SessionStore, ctx: RequestContext, s: Session, new_agent: dict[str, Any] | None = None) -> Session:
    """Run `s` in the background: progress goes to its followers, the tools it called are kept as trace.

    Every progress event, with tool arguments, tool results and model calls, is also kept with
    the run's usage and cost for admins (`store.save_run`). An admin's own room streams them live too.
    `new_agent` ({name, description}) is the agent just approved: the Coordinator plans the request
    again with it, without Jev.
    """
    detailed = run_service.is_admin(ctx)
    trace: list[dict[str, Any]] = []
    # The latest call by (step, agent, call id): steps running at the same time interleave their events
    calls: dict[tuple[Any, ...], dict[str, Any]] = {}
    # Runs are numbered across the room: every request, clarify answer and approved agent starts one
    run_no = sum(1 for i in s.items if _starts_run(i)) - 1
    started_at = datetime.now(timezone.utc)
    full: list[dict[str, Any]] = []
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0}

    def emit(event: str, data: dict[str, Any]) -> None:
        full.append({"event": event, "at": datetime.now(timezone.utc).isoformat(), **data})
        if event == "llm_call":
            usage["input_tokens"] += data["prompt_tokens"]
            usage["output_tokens"] += data["completion_tokens"]
            if data["cost_usd"] is None:
                usage["unpriced_calls"] += 1
            else:
                usage["cost_usd"] += data["cost_usd"]
        shown = data if detailed else run_service.public(event, data)
        if shown is not None:
            PROGRESS.publish(s.id, event, shown)
        key = (data.get("step_id"), data.get("agent"), data.get("id"))
        if event == "tool_call":
            calls[key] = {"agent": data["agent"], "name": data["name"], "id": data["id"], "ok": True}
            trace.append(calls[key])
        elif event == "tool_result" and data["is_error"] and key in calls:
            # Call ids repeat across agents and steps: the latest call with this key is the one that answered
            calls[key]["ok"] = False

    request = _request(s)
    # A turn that redoes an earlier request asks for that request, with the clarify answers it had
    req = RunRequest(task_id=s.id, text=request, provider=s.provider,
                     clarifications=[Clarification(**c) for c in _clarifications(s)])

    async def turn() -> dict[str, Any]:
        own = await factory.own_agents(store, ctx)
        room = None if _turn(s) == 1 else await _room(s, ctx, emit)
        if new_agent is not None:
            # No second Factory for this request: the agent the staff member approved is the one asked for
            return await run_service.coordinate(req, ctx, None, emit, "agent_added", room=room, own=own,
                                                notes={"new_agent": new_agent}, ask_factory=False)

        async def on_redo(route: dict[str, Any]) -> dict[str, Any]:
            """The request only asks to do the last one again: continue it if it failed in the Coordinator
            a moment ago, otherwise run it again from the start."""
            target = _redo_target(s)
            item = _request_item(s)
            item["redo_of"], item["redo_clarifications"] = target["text"], target["clarifications"]
            saved = s.checkpoint
            if saved is not None and datetime.now(timezone.utc) - datetime.fromisoformat(saved["at"]) <= RESUME_TTL:
                emit("redo", {"mode": "resume"})
                return {**await run_service.resume(_redo_request(req, saved["text"], saved["clarifications"]), ctx,
                                                   saved, emit, room, own), "route": route}
            emit("redo", {"mode": "full"})
            # The last turn is what is run again: leave it out, so the agents do not copy its answer
            earlier = compaction.fit(compaction.room_view(s.context, s.turns[:-1])) if len(s.turns) > 1 else None
            return {**await run_service.run(_redo_request(req, target["text"], target["clarifications"]), ctx, emit,
                                             room=earlier, own=own), "route": route}

        return await run_service.run(req, ctx, emit, room=room, own=own, on_redo=on_redo)

    # Set only when this turn failed in the Coordinator; every other ending leaves none
    checkpoint: dict[str, Any] | None = None
    try:
        # The work runs as its own task so staff can stop it (PROGRESS.stop) and the session is still saved
        work = asyncio.create_task(turn())
        PROGRESS.attach(s.id, work)
        try:
            result = await work
            agent_id = None
            if result["agent"] == factory.FACTORY and result["result"]["decision"] == "create":
                # A draft until the staff member decides: the thread points at it, nothing runs it before
                agent_id = await store.create_agent(ctx.user_id, s.id, result["result"]["agent"])
            s.status = _record(s, result, trace, agent_id)
        except asyncio.CancelledError:
            if not PROGRESS.stopped(s.id):
                raise  # the service itself is shutting down: fail_running takes it at the next start
            s.items.append(_item(s.items, "failed", body=STOPPED, trace=trace))
            s.status = FAILED
        except HTTPException as e:
            s.items.append(_item(s.items, "failed", body=str(e.detail), trace=trace))
            s.status = FAILED
            if isinstance(e, run_service.ResumableFailure):
                # What this turn really ran: a "làm lại" turn ran the request it redoes
                checkpoint = {**e.checkpoint, "at": datetime.now(timezone.utc).isoformat(),
                              "text": _request(s), "clarifications": _clarifications(s)}
        except Exception:
            # Saved as failed rather than left running forever
            log.exception("session %s run failed", s.id)
            s.items.append(_item(s.items, "failed", body="internal error", trace=trace))
            s.status = FAILED
        s.checkpoint = checkpoint
        if s.status == FAILED:
            s.turns.append(compaction.digest(_turn(s), _request(s), "", "failed", text=s.items[-1]["body"]))
            full.append({"event": "run_failed", "at": datetime.now(timezone.utc).isoformat(),
                         "body": s.items[-1]["body"]})
        saved = await store.save(s)
        try:
            await store.save_run(s.id, run_no, started_at, full, usage)
        except Exception:
            # The staff member's answer is saved; only the admin trace of this run is lost
            log.exception("session %s: saving run %d failed", s.id, run_no)
        return saved
    finally:
        # After the save: a follower re-reads the session once the run ends
        PROGRESS.finish(s.id)


def _record(s: Session, result: dict[str, Any], trace: list[dict[str, Any]], agent_id: int | None = None) -> str:
    """Add the run's route, answer and whatever waits for staff to the thread; returns the new status.

    `agent_id` is the draft agent saved for a Factory `create`, which waits for the staff member.
    """
    if result["route"] is not None:
        s.items.append(_item(s.items, "route", agent=result["agent"], branch=result["route"]["branch"]))
    if result["result"].get("decision") == "clarify":
        s.items.append(_item(s.items, "clarify", question=result["result"]["clarify_question"]))
        return WAITING
    if agent_id is not None:
        design = result["result"]["agent"]
        s.items.append(_item(s.items, "agent_proposal", agent_id=agent_id, name=design["name"],
                             description=design["description"], tools=design["tools"], summary=result["output"]))
        return WAITING
    s.items.append(_item(s.items, "result", agent=result["agent"], output=result["output"],
                         result=result["result"], trace=trace))
    waits = bool(result["pending_actions"])
    s.turns.append(compaction.digest(_turn(s), _request(s), result["agent"],
                                     "awaiting_approval" if waits else "done", result["result"], result["output"]))
    if waits:
        s.items.append(_item(s.items, "approval", actions=result["pending_actions"]))
        return WAITING
    return DONE


def _starts_run(item: dict[str, Any]) -> bool:
    if item["kind"] == "agent_proposal":
        return (item.get("decision") or {}).get("value") == "yes"
    return item["kind"] in ("request", "reply")


def _turn(s: Session) -> int:
    """The number of the room's current turn: each request starts one."""
    return sum(1 for i in s.items if i["kind"] == "request")


def _request_item(s: Session) -> dict[str, Any]:
    return next(i for i in reversed(s.items) if i["kind"] == "request")


def _request(s: Session) -> str:
    """The current turn's request; for a "làm lại" the request it redoes."""
    item = _request_item(s)
    return item.get("redo_of", item["body"])


def _clarifications(s: Session) -> list[dict[str, str]]:
    """The clarify answers the current turn's request runs with: a redo's own, after those of what it redoes."""
    return _request_item(s).get("redo_clarifications", []) + s.clarifications


def _redo_target(s: Session) -> dict[str, Any]:
    """What a "làm lại" turn redoes: the request before it, or the one that request redid."""
    requests = [i for i in s.items if i["kind"] == "request"]
    before = requests[-2]
    return {"text": before.get("redo_of", before["body"]),
            "clarifications": before.get("redo_clarifications", []) + before.get("clarifications", [])}


def _redo_request(req: RunRequest, text: str, clarifications: list[dict[str, str]]) -> RunRequest:
    return req.model_copy(update={"text": text, "clarifications": [Clarification(**c) for c in clarifications]})


async def _room(s: Session, ctx: RequestContext, emit: run_service.Emit) -> dict[str, Any]:
    """The room context the current turn reads; folds older turns into the summary first when the room is too big.

    Folding is best effort: when it fails or does not make the room smaller, the oldest digests are
    left out instead, so the turn still runs.
    """
    fold = compaction.to_fold(s.context, s.turns)
    if fold:
        try:
            context = await _fold(s, ctx, fold, emit)
            before = compaction.estimate_tokens(compaction.room_view(s.context, s.turns))
            if compaction.estimate_tokens(compaction.room_view(context, s.turns)) < before:
                s.context = context  # saved with the session: the next turn folds only what is new
            else:
                log.warning("session %s: folding did not shrink the room; truncating instead", s.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("session %s: folding the room failed; truncating instead", s.id)
    return compaction.fit(compaction.room_view(s.context, s.turns))


async def _fold(s: Session, ctx: RequestContext, fold: list[dict[str, Any]], emit: run_service.Emit) -> dict[str, Any]:
    """Run the compactor on `fold`; its model calls go to the run's trace and cost like any agent's."""
    mandate = mandates.load(COMPACTOR)
    llm, _ = clients.model_for(s.provider, mandate)
    messages: list[Message] = [SystemMessage(content=mandate.system_prompt),
                               UserMessage(content=compaction.fold_input(s.context, fold))]
    finished = await run_service.run_agent(llm, ctx, mandate, messages, compaction.facts_verifier(s.context, fold),
                                           emit, clients.config_for(s.provider, mandate))
    if finished.status != "done" or finished.final is None:
        raise RuntimeError(f"compactor {finished.status}: {finished.reason}")
    return compaction.folded(s.context, fold, finished.final)


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def follow(store: SessionStore, ctx: RequestContext, s: Session) -> AsyncIterator[str]:
    """SSE for `s`: every progress event of its current run (from the start, so a reload misses
    nothing), then `session` with what was saved. Closing it does not stop the run."""
    if s.status == RUNNING and not PROGRESS.running(s.id):
        # Running in the database with no run in this process: the run ended without saving (one
        # ai-service instance is assumed, as for fail_running). Failed, so clients stop waiting for it.
        s.items.append(_item(s.items, "failed", body=LOST))
        s.status = FAILED
        s = await store.save(s)
    if s.status == RUNNING:
        async for item in PROGRESS.follow(s.id, run_service.HEARTBEAT_SECONDS):
            yield ": ping\n\n" if item is None else _sse(*item)
    yield _sse("session", jsonable_encoder(await store.get(ctx.user_id, s.id), exclude={"checkpoint"}))
