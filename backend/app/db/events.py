"""The realtime spine: an append-only event log plus a Postgres-backed broker.

How a change reaches another user's browser:

    PATCH /tasks/{id}
      |
      +-- BEGIN
      |     UPDATE tasks ... WHERE id = $1 AND version = $2     <- optimistic lock
      |     INSERT INTO events (...) RETURNING id               <- same transaction
      |     SELECT pg_notify('board_events', '<project>:<id>')  <- fires on COMMIT
      +-- COMMIT
                |
                v
    listener connection (one per worker, LISTEN board_events)
                |
                v
    in-process fan-out to the asyncio.Queue of every SSE subscriber on that project
                |
                v
    GET /projects/{id}/events  ->  `id: 42\\ndata: {...}`  ->  EventSource.onmessage

Three things about this are load-bearing, and each is a decision I'd defend:

1. The event row is written in the SAME transaction as the state change. The log
   therefore cannot disagree with the table -- if the update rolls back, so does the
   event. This is why the log is trustworthy enough to replay from.

2. NOTIFY carries an ID, never the row. The payload cap is 8000 bytes and an oversized
   payload does not drop the notification -- it ABORTS the writing transaction. Sending
   an ID also means identical notifications dedupe within a transaction for free. The
   subscriber re-reads the event by id, so it always renders current state rather than
   a snapshot that may already be stale by the time it's delivered.

3. NOTIFY is a latency optimisation, NOT the correctness mechanism. It is at-most-once
   with no persistence: if the listener is reconnecting when a NOTIFY fires, that
   notification is gone and there is no way to detect the loss. Correctness comes from
   the client's cursor -- on every (re)connect it sends `Last-Event-ID` and we replay
   the gap out of the events table. The system is still correct with NOTIFY entirely
   disabled; it just gets slower. Every team that has succeeded with LISTEN/NOTIFY
   built it this way, and the ones that treated it as a delivery guarantee got burned.

Known ceiling, so I can say it out loud rather than be caught by it: on PG <= 18 a
NOTIFY signals every listening backend in the database regardless of channel, so cost
is O(listeners). Our listener count equals our worker count (single digits), not our
user count -- the pathological case is one listener per connected client, which this
design specifically avoids. And every NOTIFY-bearing transaction takes an exclusive
lock on a global object, so those commits serialise instance-wide; that bites at tens
of thousands of concurrent writers, roughly four orders of magnitude above this app.
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

# Bounded, so a slow browser can't grow a queue without limit. If a subscriber falls
# this far behind, dropping it is correct: it reconnects with Last-Event-ID and replays
# from the log, which is exactly the path we already have to support.
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
    """Append to the log and schedule the notification. MUST be called inside the
    same transaction as the state change it describes."""
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
    # pg_notify inside the transaction: Postgres holds the notification until COMMIT
    # and drops it on ROLLBACK, so subscribers can never see an event for a change
    # that didn't happen.
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
        """Keep a listener connection alive, forever.

        This loop is not defensive boilerplate -- it's the single most likely way this
        design fails in production. asyncpg does NOT auto-reconnect a standalone
        connection (only pooled ones), and it has no client-side TCP keepalive, so a
        connection to a server that died can sit there looking healthy and silently
        deliver nothing. Hence the explicit `SELECT 1` heartbeat: it's how we find out.

        The listener also cannot come from the pool. asyncpg's pool runs `UNLISTEN *`
        when a connection is released, which would silently unsubscribe us.
        """
        backoff = 1.0
        while not self._stopping.is_set():
            try:
                settings = get_settings()
                self._conn = await asyncpg.connect(settings.database_url)
                await self._conn.add_listener(CHANNEL, self._on_notify)
                log.info("listening on %s", CHANNEL)
                backoff = 1.0

                while not self._stopping.is_set():
                    await asyncio.sleep(20)
                    await self._conn.fetchval("SELECT 1")  # liveness probe

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
        # asyncpg calls this synchronously from the protocol loop, so it must not block
        # and must not await. Parse, route, return.
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
                # See SUBSCRIBER_QUEUE_SIZE. Drop it; the client will resync on reconnect.
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
