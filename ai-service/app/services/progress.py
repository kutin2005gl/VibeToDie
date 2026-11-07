"""Live progress of the session runs in this process, for clients that follow them over SSE.

A run's events are kept until it ends, so a client that connects late (or again after a reload)
gets them from the start. Only this process sees them: one ai-service instance is assumed.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

Event = tuple[str, dict[str, Any]]


class _Run:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.followers: set[asyncio.Queue[Event | None]] = set()
        # The task doing the run's work, so staff can stop it; `stopped` once they asked
        self.task: asyncio.Task[Any] | None = None
        self.stopped = False


class Progress:
    def __init__(self) -> None:
        self._runs: dict[int, _Run] = {}

    def start(self, session_id: int) -> None:
        """Called before the run is scheduled, so a client that follows at once does not miss it."""
        self._runs[session_id] = _Run()

    def running(self, session_id: int) -> bool:
        return session_id in self._runs

    def attach(self, session_id: int, task: asyncio.Task[Any]) -> None:
        """The task doing the run; a stop asked for before the work began cancels it at once."""
        run = self._runs.get(session_id)
        if run is None:
            return
        run.task = task
        if run.stopped:
            task.cancel()

    def stop(self, session_id: int) -> bool:
        """Cancel the run's work (a model call in flight too, so nothing more is spent); False when none runs."""
        run = self._runs.get(session_id)
        if run is None:
            return False
        run.stopped = True
        if run.task is not None:
            run.task.cancel()
        return True

    def stopped(self, session_id: int) -> bool:
        run = self._runs.get(session_id)
        return run is not None and run.stopped

    def publish(self, session_id: int, event: str, data: dict[str, Any]) -> None:
        run = self._runs.get(session_id)
        if run is None:
            return
        # When it happened, so a follower that connects late still shows how long each part took
        stamped = {**data, "at": datetime.now(timezone.utc).isoformat()}
        run.events.append((event, stamped))
        for q in run.followers:
            q.put_nowait((event, stamped))

    def finish(self, session_id: int) -> None:
        run = self._runs.pop(session_id, None)
        for q in run.followers if run else ():
            q.put_nowait(None)  # end of the run

    async def follow(self, session_id: int, heartbeat: float) -> AsyncIterator[Event | None]:
        """The run's events from its start, then live ones until it ends; None after `heartbeat` quiet seconds."""
        run = self._runs.get(session_id)
        if run is None:
            return
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        # Copy the past and subscribe with no await in between, so no event falls in the gap
        for e in run.events:
            q.put_nowait(e)
        run.followers.add(q)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), heartbeat)
                except TimeoutError:
                    yield None
                    continue
                if item is None:
                    return
                yield item
        finally:
            run.followers.discard(q)


PROGRESS = Progress()
