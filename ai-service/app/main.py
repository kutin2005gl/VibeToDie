"""ai-service HTTP API: runs the agents and their models.

The Go backend calls `/run` today and will become the API gateway that authenticates users and
forwards their identity. Until then `/run` stays backward compatible: the five original response
fields are kept, the rest are additions.
"""

from fastapi import FastAPI

from app.api.routes import router

import os
from contextlib import asynccontextmanager

from app.store.sessions import INTERRUPTED, InMemorySessionStore, PostgresSessionStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = os.environ.get("AI_DATABASE_URL")
    # Without a database (tests, offline dev) sessions stay in memory until restart
    app.state.sessions = PostgresSessionStore(url) if url else InMemorySessionStore()
    await app.state.sessions.open()
    # Session runs are background tasks of this process: whatever was running died with the last one
    await app.state.sessions.fail_running(INTERRUPTED)
    yield
    await app.state.sessions.close()

app = FastAPI(title="boa", lifespan=lifespan)
app.include_router(router)
