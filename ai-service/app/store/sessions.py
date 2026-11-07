"""Staff sessions (rooms): requests to the AI one turn after another and their thread, kept per user."""

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from psycopg import OperationalError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

# waiting: a clarify question or an approval waits for the staff member
RUNNING, WAITING, DONE, FAILED = "running", "waiting", "done", "failed"
# Body of the failed item added to runs cut off by a restart
INTERRUPTED = "run interrupted: ai-service restarted"
# Body of the failed item added to a session left running by a run that ended without saving
LOST = "run ended without saving its result"
# Body of the failed item added when the staff member stopped the run
STOPPED = "run stopped by staff"
# Department of the sessions saved before departments were recorded
UNKNOWN_DEPARTMENT = "-"
# Trace events the report counts as messages
MESSAGE_EVENTS = ("llm_call", "tool_call", "tool_result", "run_failed")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cost_usd", "unpriced_calls")
# Where a room was opened: the web, or a client that sends an origin (`schemas.SessionOrigin.kind`)
WEB, SLACK = "web", "slack"


@dataclass
class Session:
    id: int
    user_id: str
    title: str
    provider: str
    status: str
    items: list[dict[str, Any]]
    clarifications: list[dict[str, str]]
    created_at: datetime
    updated_at: datetime
    # The requester's departments when the session was created: its cost is split evenly among them
    departments: list[str] = field(default_factory=list)
    # One digest per finished turn (`compaction.digest`), and the rolling summary of the oldest ones
    turns: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    # Where the last turn's Coordinator run stood when it failed, so "làm lại" can continue it; only
    # the turn right before the current one has it (services/sessions.py)
    checkpoint: dict[str, Any] | None = None
    source: str = WEB
    # Where to find the room in its source, e.g. {kind, channel, thread_ts, permalink} for Slack; {} on the web
    origin: dict[str, Any] = field(default_factory=dict)


class SessionStore(Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def create(self, user_id: str, departments: list[str], title: str, provider: str,
                     items: list[dict[str, Any]], source: str = WEB,
                     origin: dict[str, Any] | None = None) -> Session: ...
    async def get(self, user_id: str, session_id: int) -> Session | None: ...
    async def for_user(self, user_id: str) -> list[Session]: ...
    async def save(self, session: Session) -> Session: ...
    # Staff deleting a session hides it from them; admins still see it and what it cost
    async def delete(self, user_id: str, session_id: int) -> bool: ...
    async def fail_running(self, reason: str) -> int: ...
    # One run of a session (its first request, then each clarify answer): trace and usage, for admins.
    # Saving the same run again replaces it, so a retry never counts it twice.
    async def save_run(self, session_id: int, run: int, started_at: datetime, trace: list[dict[str, Any]],
                       usage: dict[str, Any]) -> None: ...
    async def usage_by_department(self) -> list[dict[str, Any]]: ...
    async def usage_by_user(self, department: str) -> list[dict[str, Any]]: ...
    # `source` set: only the rooms opened there
    async def sessions_of(self, user_id: str, source: str | None = None) -> list[dict[str, Any]]: ...
    # Runs started since `since`, with only their message-like trace events; deleted sessions too
    async def runs_since(self, since: datetime, user_id: str | None = None) -> list[dict[str, Any]]: ...
    # System-wide settings an admin chooses (e.g. the provider), by key
    async def get_setting(self, key: str) -> str | None: ...
    async def set_setting(self, key: str, value: str) -> None: ...
    async def session_detail(self, session_id: int) -> dict[str, Any] | None: ...
    # Agents Factory designed for one user: a draft until they decide in the session that proposed it,
    # then active (theirs only) or rejected. `design` is Factory's output, compiled each time it is used.
    async def create_agent(self, user_id: str, session_id: int, design: dict[str, Any]) -> int: ...
    # Active agents only: {id, name, design, decided_at}
    async def agents_of(self, user_id: str) -> list[dict[str, Any]]: ...
    # Every name a new agent of the user may not take: drafts and active ones
    async def agent_names(self, user_id: str) -> set[str]: ...
    # False when the agent is not that user's draft (already decided): the caller answers 409
    async def decide_agent(self, user_id: str, agent_id: int, approve: bool) -> bool: ...


# Status of a personal agent
DRAFT, ACTIVE, REJECTED = "draft", "active", "rejected"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id             BIGSERIAL PRIMARY KEY,
    user_id        TEXT        NOT NULL,
    title          TEXT        NOT NULL,
    provider       TEXT        NOT NULL,
    status         TEXT        NOT NULL,
    items          JSONB       NOT NULL DEFAULT '[]',
    clarifications JSONB       NOT NULL DEFAULT '[]',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_updated ON sessions (user_id, updated_at DESC);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS departments TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS turns JSONB NOT NULL DEFAULT '[]';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS checkpoint JSONB;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'web';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS origin JSONB NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS session_runs (
    session_id     BIGINT           NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    run            INT              NOT NULL,
    started_at     TIMESTAMPTZ      NOT NULL,
    trace          JSONB            NOT NULL DEFAULT '[]',
    input_tokens   BIGINT           NOT NULL DEFAULT 0,
    output_tokens  BIGINT           NOT NULL DEFAULT 0,
    cost_usd       DOUBLE PRECISION NOT NULL DEFAULT 0,
    unpriced_calls INT              NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, run)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personal_agents (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    TEXT        NOT NULL,
    session_id BIGINT      NOT NULL,
    name       TEXT        NOT NULL,
    design     JSONB       NOT NULL,
    status     TEXT        NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS personal_agents_user_name ON personal_agents (user_id, name)
    WHERE status <> 'rejected';
"""
COLUMNS = "id, user_id, title, provider, status, items, clarifications, created_at, updated_at, departments, turns, context, checkpoint, source, origin"
# Each session once per department it is billed to, with its share of the cost
SHARES = f"""
WITH shares AS (
    SELECT id, user_id,
           unnest(CASE WHEN cardinality(departments) = 0 THEN ARRAY['{UNKNOWN_DEPARTMENT}']::text[]
                       ELSE departments END) AS department,
           1.0 / greatest(cardinality(departments), 1) AS share
    FROM sessions
)
"""
SHARED_USAGE = """
COUNT(DISTINCT sh.id) AS sessions,
COALESCE(SUM(r.input_tokens * sh.share), 0)::float AS input_tokens,
COALESCE(SUM(r.output_tokens * sh.share), 0)::float AS output_tokens,
COALESCE(SUM(r.cost_usd * sh.share), 0)::float AS cost_usd,
COALESCE(SUM(r.unpriced_calls), 0)::int AS unpriced_calls
FROM shares sh LEFT JOIN session_runs r ON r.session_id = sh.id
"""


class PostgresSessionStore:
    def __init__(self, url: str):
        # Neon's pooler (PgBouncer) does not keep server-side prepared statements between connections.
        # Neon also closes connections left idle, and a run keeps the pool idle for minutes: check each
        # connection before handing it out.
        self.pool = AsyncConnectionPool(url, open=False, check=AsyncConnectionPool.check_connection,
                                        kwargs={"prepare_threshold": None, "row_factory": dict_row})

    async def open(self) -> None:
        await self.pool.open()
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        await self.pool.close()

    async def create(self, user_id, departments, title, provider, items, source=WEB, origin=None):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"INSERT INTO sessions (user_id, departments, title, provider, status, items, source, origin) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}",
                (user_id, list(departments), title, provider, RUNNING, Jsonb(items), source, Jsonb(origin or {})))
            return Session(**await cur.fetchone())

    async def get(self, user_id, session_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {COLUMNS} FROM sessions WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                (session_id, user_id))
            row = await cur.fetchone()
            return Session(**row) if row else None

    async def for_user(self, user_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {COLUMNS} FROM sessions WHERE user_id = %s AND deleted_at IS NULL "
                f"ORDER BY updated_at DESC LIMIT 50", (user_id,))
            return [Session(**row) for row in await cur.fetchall()]

    async def save(self, s):
        # The result of a run that took minutes: one more try on a connection the server dropped in
        # between, rather than lose it. The update sets whole values, so running it twice is harmless.
        for attempt in (1, 2):
            try:
                async with self.pool.connection() as conn:
                    cur = await conn.execute(
                        f"UPDATE sessions SET provider = %s, status = %s, items = %s, clarifications = %s, turns = %s, context = %s, "
                        f"checkpoint = %s, updated_at = now() WHERE id = %s RETURNING {COLUMNS}",
                        (s.provider, s.status, Jsonb(s.items), Jsonb(s.clarifications), Jsonb(s.turns), Jsonb(s.context),
                         None if s.checkpoint is None else Jsonb(s.checkpoint), s.id))
                    return Session(**await cur.fetchone())
            except OperationalError:
                if attempt == 2:
                    raise

    async def delete(self, user_id, session_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE sessions SET deleted_at = now() WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                (session_id, user_id))
            return cur.rowcount == 1

    async def fail_running(self, reason):
        # Runs live in this process only: at startup any session still running was cut off.
        # Assumes a single ai-service instance; with several, each would fail the others' runs.
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """UPDATE sessions SET status = %s, updated_at = now(),
                       items = items || jsonb_build_array(jsonb_build_object(
                           'id', (jsonb_array_length(items) + 1)::text, 'kind', 'failed', 'body', %s::text,
                           'at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')))
                   WHERE status = %s""",
                (FAILED, reason, RUNNING))
            return cur.rowcount

    async def save_run(self, session_id, run, started_at, trace, usage):
        # Saved after a run of minutes, like save: one more try on a dropped connection
        for attempt in (1, 2):
            try:
                async with self.pool.connection() as conn:
                    await conn.execute(
                        """INSERT INTO session_runs (session_id, run, started_at, trace, input_tokens, output_tokens,
                                                     cost_usd, unpriced_calls)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (session_id, run) DO UPDATE SET
                               started_at = EXCLUDED.started_at, trace = EXCLUDED.trace,
                               input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens,
                               cost_usd = EXCLUDED.cost_usd, unpriced_calls = EXCLUDED.unpriced_calls""",
                        (session_id, run, started_at, Jsonb(trace), *(usage[k] for k in USAGE_FIELDS)))
                    return
            except OperationalError:
                if attempt == 2:
                    raise

    async def usage_by_department(self):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"{SHARES} SELECT sh.department, {SHARED_USAGE} GROUP BY sh.department ORDER BY cost_usd DESC")
            return await cur.fetchall()

    async def usage_by_user(self, department):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                f"{SHARES} SELECT sh.user_id, {SHARED_USAGE} WHERE sh.department = %s "
                f"GROUP BY sh.user_id ORDER BY cost_usd DESC", (department,))
            return await cur.fetchall()

    async def sessions_of(self, user_id, source=None):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """SELECT s.id, s.title, s.provider, s.status, s.departments, s.source, s.origin, s.created_at,
                          s.updated_at, s.deleted_at, COUNT(r.run)::int AS runs,
                          COALESCE(SUM(r.input_tokens), 0)::bigint AS input_tokens,
                          COALESCE(SUM(r.output_tokens), 0)::bigint AS output_tokens,
                          COALESCE(SUM(r.cost_usd), 0)::float AS cost_usd,
                          COALESCE(SUM(r.unpriced_calls), 0)::int AS unpriced_calls
                   FROM sessions s LEFT JOIN session_runs r ON r.session_id = s.id
                   WHERE s.user_id = %s AND (%s::text IS NULL OR s.source = %s)
                   GROUP BY s.id ORDER BY s.updated_at DESC""", (user_id, source, source))
            return await cur.fetchall()

    async def get_setting(self, key):
        async with self.pool.connection() as conn:
            cur = await conn.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_setting(self, key, value):
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))

    async def runs_since(self, since, user_id=None):
        # Pick the few fields the report reads, so the long text of the trace stays in the database
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                """SELECT r.session_id, s.title, r.run, r.started_at, r.input_tokens, r.output_tokens, r.cost_usd,
                          r.unpriced_calls,
                          COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                        'event', e->'event', 'at', e->'at', 'agent', e->'agent', 'model', e->'model',
                                        'name', e->'name', 'is_error', e->'is_error',
                                        'prompt_tokens', e->'prompt_tokens', 'completion_tokens', e->'completion_tokens',
                                        'cost_usd', e->'cost_usd'))
                                    FROM jsonb_array_elements(r.trace) e
                                    WHERE e->>'event' = ANY(%s)), '[]'::jsonb) AS events
                   FROM session_runs r JOIN sessions s ON s.id = r.session_id
                   WHERE r.started_at >= %s AND (%s::text IS NULL OR s.user_id = %s)
                   ORDER BY r.started_at""", (list(MESSAGE_EVENTS), since, user_id, user_id))
            return await cur.fetchall()

    async def session_detail(self, session_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(f"SELECT {COLUMNS}, deleted_at FROM sessions WHERE id = %s", (session_id,))
            row = await cur.fetchone()
            if row is None:
                return None
            cur = await conn.execute(
                "SELECT run, started_at, trace, input_tokens, output_tokens, cost_usd, unpriced_calls "
                "FROM session_runs WHERE session_id = %s ORDER BY run", (session_id,))
            return {**row, "runs": await cur.fetchall()}

    async def create_agent(self, user_id, session_id, design):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO personal_agents (user_id, session_id, name, design) VALUES (%s, %s, %s, %s) RETURNING id",
                (user_id, session_id, design["name"], Jsonb(design)))
            return (await cur.fetchone())["id"]

    async def agents_of(self, user_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, name, design, decided_at FROM personal_agents WHERE user_id = %s AND status = %s ORDER BY id",
                (user_id, ACTIVE))
            return await cur.fetchall()

    async def agent_names(self, user_id):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name FROM personal_agents WHERE user_id = %s AND status <> %s", (user_id, REJECTED))
            return {row["name"] for row in await cur.fetchall()}

    async def decide_agent(self, user_id, agent_id, approve):
        # Only a draft changes, so a second decision (or one racing it) finds nothing to update
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE personal_agents SET status = %s, decided_at = now() "
                "WHERE id = %s AND user_id = %s AND status = %s",
                (ACTIVE if approve else REJECTED, agent_id, user_id, DRAFT))
            return cur.rowcount == 1


class InMemorySessionStore:
    """Tests and offline dev (no AI_DATABASE_URL): gone on restart."""

    def __init__(self):
        self._rows: dict[int, Session] = {}
        self._deleted: dict[int, datetime] = {}
        self._runs: dict[tuple[int, int], dict[str, Any]] = {}
        self._settings: dict[str, str] = {}
        self._agents: dict[int, dict[str, Any]] = {}
        # Ids are never reused, also after a delete, as BIGSERIAL does
        self._last_id = 0

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def create(self, user_id, departments, title, provider, items, source=WEB, origin=None):
        now = datetime.now(timezone.utc)
        self._last_id += 1
        s = Session(self._last_id, user_id, title, provider, RUNNING, list(items), [], now, now, list(departments),
                    source=source, origin=copy.deepcopy(origin or {}))
        self._rows[s.id] = s
        return copy.deepcopy(s)

    async def get(self, user_id, session_id):
        s = self._rows.get(session_id)
        return copy.deepcopy(s) if s and s.user_id == user_id and session_id not in self._deleted else None

    async def for_user(self, user_id):
        mine = [s for s in self._rows.values() if s.user_id == user_id and s.id not in self._deleted]
        return [copy.deepcopy(s) for s in sorted(mine, key=lambda s: s.updated_at, reverse=True)]

    async def save(self, s):
        s.updated_at = datetime.now(timezone.utc)
        self._rows[s.id] = copy.deepcopy(s)
        return copy.deepcopy(s)

    async def delete(self, user_id, session_id):
        s = self._rows.get(session_id)
        if s is None or s.user_id != user_id or session_id in self._deleted:
            return False
        self._deleted[session_id] = datetime.now(timezone.utc)
        return True

    async def fail_running(self, reason):
        cut = [s for s in self._rows.values() if s.status == RUNNING]
        for s in cut:
            now = datetime.now(timezone.utc)
            s.items.append({"id": str(len(s.items) + 1), "kind": "failed", "body": reason, "at": now.isoformat()})
            s.status, s.updated_at = FAILED, now
        return len(cut)

    async def save_run(self, session_id, run, started_at, trace, usage):
        self._runs[(session_id, run)] = copy.deepcopy(
            {"run": run, "started_at": started_at, "trace": trace, **{k: usage[k] for k in USAGE_FIELDS}})

    def _runs_of(self, session_id: int) -> list[dict[str, Any]]:
        return [r for (sid, _), r in sorted(self._runs.items()) if sid == session_id]

    def _shared(self, key: str, department: str | None) -> list[dict[str, Any]]:
        # Same sums as SHARES / SHARED_USAGE: each session split evenly among its departments
        totals: dict[str, dict[str, Any]] = {}
        for s in self._rows.values():
            departments = s.departments or [UNKNOWN_DEPARTMENT]
            for d in departments:
                if department is not None and d != department:
                    continue
                name = d if key == "department" else s.user_id
                t = totals.setdefault(name, {key: name, "sessions": 0, **{k: 0 for k in USAGE_FIELDS}})
                t["sessions"] += 1
                for r in self._runs_of(s.id):
                    for k in ("input_tokens", "output_tokens", "cost_usd"):
                        t[k] += r[k] / len(departments)
                    t["unpriced_calls"] += r["unpriced_calls"]
        return sorted(totals.values(), key=lambda t: t["cost_usd"], reverse=True)

    async def usage_by_department(self):
        return self._shared("department", None)

    async def usage_by_user(self, department):
        return self._shared("user_id", department)

    async def sessions_of(self, user_id, source=None):
        mine = sorted((s for s in self._rows.values()
                       if s.user_id == user_id and (source is None or s.source == source)),
                      key=lambda s: s.updated_at, reverse=True)
        out = []
        for s in mine:
            runs = self._runs_of(s.id)
            out.append({"id": s.id, "title": s.title, "provider": s.provider, "status": s.status,
                        "departments": list(s.departments), "source": s.source,
                        "origin": copy.deepcopy(s.origin), "created_at": s.created_at, "updated_at": s.updated_at,
                        "deleted_at": self._deleted.get(s.id), "runs": len(runs),
                        **{k: sum(r[k] for r in runs) for k in USAGE_FIELDS}})
        return out

    async def get_setting(self, key):
        return self._settings.get(key)

    async def set_setting(self, key, value):
        self._settings[key] = value

    async def runs_since(self, since, user_id=None):
        return copy.deepcopy([
            {"session_id": sid, "title": self._rows[sid].title, **r,
             "events": [e for e in r["trace"] if e["event"] in MESSAGE_EVENTS]}
            for (sid, _), r in sorted(self._runs.items()) if r["started_at"] >= since
            and (user_id is None or self._rows[sid].user_id == user_id)])

    async def session_detail(self, session_id):
        s = self._rows.get(session_id)
        if s is None:
            return None
        return copy.deepcopy({**asdict(s), "deleted_at": self._deleted.get(session_id),
                              "runs": self._runs_of(session_id)})

    async def create_agent(self, user_id, session_id, design):
        # The unique index of the table: one live agent per name and user
        if design["name"] in await self.agent_names(user_id):
            raise ValueError(f"agent {design['name']!r} already exists")
        agent_id = len(self._agents) + 1
        self._agents[agent_id] = {"id": agent_id, "user_id": user_id, "session_id": session_id,
                                  "name": design["name"], "design": copy.deepcopy(design), "status": DRAFT,
                                  "decided_at": None}
        return agent_id

    async def agents_of(self, user_id):
        return [copy.deepcopy({k: a[k] for k in ("id", "name", "design", "decided_at")})
                for a in self._agents.values() if a["user_id"] == user_id and a["status"] == ACTIVE]

    async def agent_names(self, user_id):
        return {a["name"] for a in self._agents.values() if a["user_id"] == user_id and a["status"] != REJECTED}

    async def decide_agent(self, user_id, agent_id, approve):
        a = self._agents.get(agent_id)
        if a is None or a["user_id"] != user_id or a["status"] != DRAFT:
            return False
        a["status"] = ACTIVE if approve else REJECTED
        a["decided_at"] = datetime.now(timezone.utc)
        return True
