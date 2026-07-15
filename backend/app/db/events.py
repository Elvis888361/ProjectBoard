"""Manages real-time events, notifications, and
subscriber communication across application services.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from app.core.config import get_settings

log = logging.getLogger(__name__)

CHANNEL = "board_events"

SUBSCRIBER_QUEUE_SIZE = 100


async def append_event(
    conn: asyncpg.Connection,
    *,
    project_id: uuid.UUID,
    type_: str,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None,
    task_id: uuid.UUID | None = None,
) -> int:
    """Stores event and notifies subscribers after successful database transaction."""

    event_id = await conn.fetchval(
        """
        INSERT INTO events (project_id, task_id, type, actor_id, payload)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        project_id,
        task_id,
        type_,
        actor_id,
        json.dumps(payload),
    )
    await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, f"{project_id}:{event_id}")
    return event_id


async def read_events_since(
    conn: asyncpg.Connection, project_id: uuid.UUID, after_id: int, limit: int = 500
) -> list[asyncpg.Record]:
    """Retrieves events for a project that occurred after a specific event ID, up to a limit."""

    return await conn.fetch(
        """
        SELECT e.id, e.type, e.task_id, e.payload, e.created_at,
               u.display_name AS actor_name
        FROM events e
        LEFT JOIN users u ON u.id = e.actor_id
        WHERE e.project_id = $1 AND e.id > $2
        ORDER BY e.id
        LIMIT $3
        """,
        project_id,
        after_id,
        limit,
    )


class EventBroker:
    """Manages event subscriptions and broadcasts database notifications to connected clients."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[int]]] = defaultdict(set)
        self._conn: asyncpg.Connection | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._supervisor = asyncio.create_task(self._supervise(), name="event-listener")

    async def stop(self) -> None:
        self._stopping.set()
        if self._supervisor:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
        if self._conn and not self._conn.is_closed():
            await self._conn.close()

    async def _supervise(self) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            try:
                self._conn = await asyncpg.connect(get_settings().database_url)
                await self._conn.add_listener(CHANNEL, self._on_notify)
                log.info("listening on %s", CHANNEL)
                backoff = 1.0

                while not self._stopping.is_set():
                    await asyncio.sleep(20)
                    await self._conn.fetchval("SELECT 1")

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event listener died; reconnecting in %.0fs", backoff)
                if self._conn and not self._conn.is_closed():
                    with contextlib.suppress(Exception):
                        await self._conn.close()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _on_notify(self, _conn, _pid, _channel: str, payload: str) -> None:
        # Called from asyncpg's protocol loop, so it can't block or await.
        project_str, _, event_str = payload.partition(":")
        try:
            project_id = uuid.UUID(project_str)
            event_id = int(event_str)
        except ValueError:
            log.warning("unparseable notification payload: %r", payload)
            return

        for queue in self._subscribers.get(project_id, ()):
            try:
                queue.put_nowait(event_id)
            except asyncio.QueueFull:
                log.warning("subscriber queue full for project %s", project_id)

    @contextlib.asynccontextmanager
    async def subscribe(self, project_id: uuid.UUID) -> AsyncIterator[asyncio.Queue[int]]:
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers[project_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[project_id].discard(queue)
            if not self._subscribers[project_id]:
                del self._subscribers[project_id]

    def subscriber_count(self, project_id: uuid.UUID) -> int:
        return len(self._subscribers.get(project_id, ()))
