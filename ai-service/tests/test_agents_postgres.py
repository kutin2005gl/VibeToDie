"""Personal agents in the Postgres session store. Skipped without AI_TEST_DATABASE_URL.

It drops the `personal_agents` table, so point it at a throwaway database:
    docker run -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=t pgvector/pgvector:pg17
    AI_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres pytest tests/test_agents_postgres.py
"""

import asyncio
import os

import pytest
from psycopg.errors import UniqueViolation

from app.store.sessions import SCHEMA, PostgresSessionStore

URL = os.environ.get("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="AI_TEST_DATABASE_URL not set")


def design(name="warranty_lookup"):
    return {"name": name, "description": "Use when … Not for …", "tools": []}


def run(test):
    # psycopg's async mode cannot use Windows' default (Proactor) loop
    asyncio.run(with_store(test), loop_factory=asyncio.SelectorEventLoop)


async def with_store(test):
    store = PostgresSessionStore(URL)
    await store.open()
    async with store.pool.connection() as conn:
        await conn.execute("DROP TABLE IF EXISTS personal_agents")
        await conn.execute(SCHEMA)
    try:
        await test(store)
    finally:
        await store.close()


def test_a_draft_becomes_active_once_and_only_for_its_owner():
    async def test(store):
        aid = await store.create_agent("u1", 7, design())
        assert await store.agents_of("u1") == [] and await store.agent_names("u1") == {"warranty_lookup"}
        assert not await store.decide_agent("u2", aid, True)
        assert await store.decide_agent("u1", aid, True)
        assert not await store.decide_agent("u1", aid, False)
        [mine] = await store.agents_of("u1")
        assert (mine["id"], mine["name"], mine["design"]) == (aid, "warranty_lookup", design())
        assert mine["decided_at"] is not None
        assert await store.agents_of("u2") == []

    run(test)


def test_a_name_is_free_again_only_after_a_rejection():
    async def test(store):
        aid = await store.create_agent("u1", 7, design())
        with pytest.raises(UniqueViolation):
            await store.create_agent("u1", 8, design())
        await store.create_agent("u2", 9, design())  # another user's name space
        await store.decide_agent("u1", aid, False)
        await store.create_agent("u1", 8, design())
        assert await store.agent_names("u1") == {"warranty_lookup"}

    run(test)
