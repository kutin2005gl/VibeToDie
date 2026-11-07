"""Who is asking, and which dev hooks the deployment allows."""

import os

from app.core.context import RequestContext
from fastapi import Depends, Header, HTTPException, Request
from app.services.run import is_admin
from app.store.sessions import SessionStore

# No gateway yet, so no authentication: requests run as this demo CSKH user
DEMO_USER = RequestContext(user_id="demo-cskh", departments=("cskh",))


def agent_override_allowed() -> bool:
    return os.environ.get("AI_ALLOW_AGENT_OVERRIDE") == "1"


def request_context(user_id: str | None, departments: str | None) -> RequestContext:
    """Identity forwarded by the gateway; trusted only when AI_TRUST_IDENTITY_HEADERS=1.

    Plain headers can be forged by anyone who reaches this service directly, so they are ignored
    unless the deployment puts ai-service behind the gateway.
    """
    if os.environ.get("AI_TRUST_IDENTITY_HEADERS") != "1" or not user_id:
        return DEMO_USER
    names = tuple(d.strip() for d in (departments or "").split(",") if d.strip())
    return RequestContext(user_id=user_id, departments=names)


def requester(x_user_id: str | None = Header(default=None),
              x_user_departments: str | None = Header(default=None)) -> RequestContext:
    return request_context(x_user_id, x_user_departments)


def admin(ctx: RequestContext = Depends(requester)) -> RequestContext:
    """The requester, if they are in the admin department (ADMIN_DEPARTMENT, as in user-service)."""
    if not is_admin(ctx):
        raise HTTPException(status_code=403, detail="admins only")
    return ctx


def session_store(request: Request) -> SessionStore:
    return request.app.state.sessions