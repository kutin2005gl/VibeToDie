"""The provider profile every request runs on: one choice for the whole system, made by an admin."""

import os

from fastapi import HTTPException

from app.services import clients
from app.store.sessions import SessionStore

KEY = "provider"
# Until an admin chooses one (overridable per deployment)
DEFAULT = "deepseek"


def override_allowed() -> bool:
    """Dev/test hook: let a request name its own provider (staff clients never do)."""
    return os.environ.get("AI_ALLOW_PROVIDER_OVERRIDE") == "1"


def available() -> list[str]:
    """Providers an admin can choose: profiles in models.json that have their keys, plus `fake` when enabled."""
    return clients.CATALOG.configured() + ([clients.FAKE] if clients.fake_allowed() else [])


async def current(store: SessionStore) -> str:
    return await store.get_setting(KEY) or os.environ.get("AI_DEFAULT_PROVIDER", DEFAULT)


async def choose(store: SessionStore, requested: str | None) -> str:
    """The provider a request runs on: the system's, unless the dev hook lets it name one."""
    return requested if requested and override_allowed() else await current(store)


async def save(store: SessionStore, provider: str) -> None:
    if provider not in available():
        raise HTTPException(status_code=422, detail=f"provider {provider!r} is not available")
    await store.set_setting(KEY, provider)
