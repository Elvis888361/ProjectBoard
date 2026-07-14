"""Append-only event log + a Postgres-backed broker.

Writes append an event in the same transaction as the state change, then NOTIFY. Each
SSE subscriber gets a queue; the listener fans notifications out to them.

NOTIFY is a latency optimisation, not a delivery guarantee -- it's at-most-once with no
replay. Correctness comes from the client's Last-Event-ID cursor. See ARCHITECTURE.md.
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

# A subscriber that falls this far behind gets dropped. It reconnects and replays.
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
    """Must be called inside the transaction that made the change."""
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
    # Payload is an id, never the row: the cap is 8000 bytes and overflowing it aborts
    # the transaction. Fires on COMMIT, dropped on ROLLBACK.
    await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, f"{project_id}:{event_id}")
    return event_id


async def read_events_since(
    conn: asyncpg.Connection, project_id: uuid.UUID, after_id: int, limit: int = 500
) -> list[asyncpg.Record]:
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
    """Owns the LISTEN connection and fans notifications out to local subscribers."""

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
        # A dedicated connection, not a pooled one: asyncpg runs `UNLISTEN *` on release.
        # asyncpg also won't auto-reconnect a standalone connection and has no TCP
        # keepalive, so a dead listener sits there looking healthy. Hence the heartbeat.
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
