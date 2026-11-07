"""HTTP endpoints: read the request and the identity headers, hand the work to the services."""

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import admin, agent_override_allowed, request_context, requester, session_store
from app.core.context import RequestContext
from app.schemas import (AnswerRequest, DecisionRequest, MessageRequest, ProviderRequest, RouteRequest, RunRequest,
                         RunResult, SessionRequest)
from app.services import agents as agents_service, analytics, clients, provider as provider_service, run as run_service
from app.services import sessions as session_service, factory
from app.services.progress import PROGRESS
from app.store.sessions import RUNNING, Session, SessionStore

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    providers = clients.CATALOG.configured() + ([clients.FAKE] if clients.fake_allowed() else [])
    return {"status": "ok", "providers": providers}


@router.post("/route")
async def route_only(
    req: RouteRequest,
    x_user_id: str | None = Header(default=None),
    x_user_departments: str | None = Header(default=None),
) -> dict:
    """Where Jev would send `text`, without running any agent: for checking the router."""
    return await run_service.jev_route(req.text, request_context(x_user_id, x_user_departments))


@router.post("/run", response_model=RunResult)
async def run(
    req: RunRequest,
    x_user_id: str | None = Header(default=None),
    x_user_departments: str | None = Header(default=None),
    accept: str | None = Header(default=None),
    store: SessionStore = Depends(session_store),
) -> Any:
    if req.agent is not None and not agent_override_allowed():
        raise HTTPException(status_code=422, detail="choosing the agent is disabled (set AI_ALLOW_AGENT_OVERRIDE=1)")
    ctx = request_context(x_user_id, x_user_departments)
    req = req.model_copy(update={"provider": await provider_service.choose(store, req.provider)})
    if accept is not None and "text/event-stream" in accept:
        # Opt-in: progress as server-sent events; other clients keep the single JSON response
        return StreamingResponse(run_service.stream(req, ctx), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await run_service.run(req, ctx)


async def _owned(store: SessionStore, ctx: RequestContext, session_id: int) -> Session:
    # Another user's session answers 404 like a missing one, so ids reveal nothing
    s = await store.get(ctx.user_id, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


# A session's `checkpoint` (a failed run's state) is for the service only, so no response carries it.
# Sessions keep the gateway's path (keep_prefix), like /api/tasks before them: they get their own
# route there because clients follow a run over SSE while it goes on.
@router.get("/api/sessions", response_model_exclude={"__all__": {"checkpoint"}})
async def list_sessions(ctx: RequestContext = Depends(requester),
                        store: SessionStore = Depends(session_store)) -> list[Session]:
    return await store.for_user(ctx.user_id)


# Before /{session_id}, which would take "agents" for an id
@router.get("/api/sessions/agents")
async def my_agents(ctx: RequestContext = Depends(requester),
                    store: SessionStore = Depends(session_store)) -> list[dict]:
    """The requester's own agents (approved from Factory's proposals), oldest first."""
    return [{"id": a["id"], "name": a["name"], "description": a["design"]["description"],
             "role": a["design"]["role"], "tools": a["design"]["tools"], "approved_at": a["decided_at"]}
            for a in await store.agents_of(ctx.user_id)]


@router.get("/api/sessions/agents/{agent_id}")
async def my_agent_detail(agent_id: int, ctx: RequestContext = Depends(requester),
                          store: SessionStore = Depends(session_store)) -> dict:
    """Configuration and seven-day usage of an approved agent owned by the requester."""
    row = next((a for a in await store.agents_of(ctx.user_id) if a["id"] == agent_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    # Compile only for display, including tools originally approved; this never executes the agent
    # or grants tools the requester can no longer use. Runtime still checks allowed_tools.
    m = factory.compile(row["design"], set(), set(row["design"]["tools"]))
    report = analytics.build(await store.runs_since(analytics.window_start(7), user_id=ctx.user_id), 7)
    stats = next((a for a in report["per_agent"] if a["agent"] == m.name), {
        "agent": m.name, "sessions": 0, "llm_calls": 0, "tool_calls": 0, "errors": 0, "last": "",
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0,
    })
    return {"agent": {"name": m.name, "description": m.description, "tools": list(m.tools),
                      "includes": list(m.includes), "departments": list(m.departments),
                      "model_tier": m.model_tier, "effort": m.effort,
                      "models": {p: tiers[m.model_tier] for p, tiers in clients.CATALOG.profiles.items()},
                      "prompt": m.system_prompt}, "stats": stats}


@router.get("/api/sessions/{session_id}", response_model_exclude={"checkpoint"})
async def get_session(session_id: int, ctx: RequestContext = Depends(requester),
                      store: SessionStore = Depends(session_store)) -> Session:
    return await _owned(store, ctx, session_id)


@router.post("/api/sessions", status_code=201, response_model_exclude={"checkpoint"})
async def create_session(req: SessionRequest, background: BackgroundTasks, ctx: RequestContext = Depends(requester),
                         store: SessionStore = Depends(session_store)) -> Session:
    origin = req.origin.model_dump(exclude_none=True) if req.origin else None
    return await session_service.create(store, ctx, req.text, req.provider, background, origin)


@router.post("/api/sessions/{session_id}/answer", response_model_exclude={"checkpoint"})
async def answer_session(session_id: int, req: AnswerRequest, background: BackgroundTasks,
                         ctx: RequestContext = Depends(requester),
                         store: SessionStore = Depends(session_store)) -> Session:
    return await session_service.answer(store, ctx, await _owned(store, ctx, session_id), req.answer, background)


@router.post("/api/sessions/{session_id}/messages", response_model_exclude={"checkpoint"})
async def message_session(session_id: int, req: MessageRequest, background: BackgroundTasks,
                          ctx: RequestContext = Depends(requester),
                          store: SessionStore = Depends(session_store)) -> Session:
    return await session_service.follow_up(store, ctx, await _owned(store, ctx, session_id), req.text, background)


@router.post("/api/sessions/{session_id}/decision", response_model_exclude={"checkpoint"})
async def decide_session(session_id: int, req: DecisionRequest, background: BackgroundTasks,
                         ctx: RequestContext = Depends(requester),
                         store: SessionStore = Depends(session_store)) -> Session:
    return await session_service.decide(store, ctx, await _owned(store, ctx, session_id), req.approve, background)


@router.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int, ctx: RequestContext = Depends(requester),
                         store: SessionStore = Depends(session_store)) -> None:
    s = await _owned(store, ctx, session_id)
    # A running session still has a run that will save into it; it can go once the run ends
    if s.status == RUNNING:
        raise HTTPException(status_code=409, detail="session is still running")
    await store.delete(ctx.user_id, session_id)


@router.post("/api/sessions/{session_id}/stop", status_code=202)
async def stop_session(session_id: int, ctx: RequestContext = Depends(requester),
                       store: SessionStore = Depends(session_store)) -> None:
    # 202: the run stops at once but saves itself a moment later; followers get it as `session`
    await _owned(store, ctx, session_id)
    if not PROGRESS.stop(session_id):
        raise HTTPException(status_code=409, detail="session is not running")


@router.get("/api/sessions/{session_id}/events")
async def follow_session(session_id: int, ctx: RequestContext = Depends(requester),
                         store: SessionStore = Depends(session_store)) -> StreamingResponse:
    s = await _owned(store, ctx, session_id)
    return StreamingResponse(session_service.follow(store, ctx, s), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Admins: what sessions cost per department and user, and each session's full trace. They keep the
# gateway's path (keep_prefix) on a route of their own, so browsing them is not held to /api/ai's limit.
@router.get("/api/admin/usage", dependencies=[Depends(admin)])
async def usage_by_department(store: SessionStore = Depends(session_store)) -> list[dict]:
    return await store.usage_by_department()


@router.get("/api/admin/usage/{department}", dependencies=[Depends(admin)])
async def usage_by_user(department: str, store: SessionStore = Depends(session_store)) -> list[dict]:
    return await store.usage_by_user(department)


@router.get("/api/admin/provider", dependencies=[Depends(admin)])
async def get_provider(store: SessionStore = Depends(session_store)) -> dict:
    return {"provider": await provider_service.current(store), "available": provider_service.available()}


@router.put("/api/admin/provider", dependencies=[Depends(admin)])
async def put_provider(req: ProviderRequest, store: SessionStore = Depends(session_store)) -> dict:
    await provider_service.save(store, req.provider)
    return await get_provider(store)


@router.get("/api/admin/agents", dependencies=[Depends(admin)])
async def admin_agents() -> list[dict]:
    return agents_service.listing()


@router.get("/api/admin/analytics", dependencies=[Depends(admin)])
async def admin_analytics(days: int = Query(7, ge=1, le=analytics.MAX_DAYS),
                          store: SessionStore = Depends(session_store)) -> dict:
    return analytics.build(await store.runs_since(analytics.window_start(days)), days)


@router.get("/api/admin/users/{user_id}/sessions", dependencies=[Depends(admin)])
async def sessions_of(user_id: str, source: Literal["web", "slack"] | None = None,
                      store: SessionStore = Depends(session_store)) -> list[dict]:
    return await store.sessions_of(user_id, source)


@router.get("/api/admin/sessions/{session_id}", dependencies=[Depends(admin)])
async def session_detail(session_id: int, store: SessionStore = Depends(session_store)) -> dict:
    detail = await store.session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="session not found")
    return detail
