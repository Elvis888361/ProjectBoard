"""The SSE endpoint.

The contract with the browser:

  * Every event carries `id: <events.id>`, a monotonic per-project cursor.
  * The browser stores the last id it saw and, on reconnect, sends it back in the
    `Last-Event-ID` header. It does this automatically -- no client code required.
  * We replay everything after that id from the events table, then stream live.

That means a client that drops off (laptop sleeps, wifi flaps, we redeploy) comes back
and catches up exactly, with no gap and no full refetch. Linear and Asana both had to
hand-build this on top of WebSockets; with SSE the browser does half of it for us.

Backpressure/liveness details that matter in practice:
  * `retry:` tells the browser how fast to reconnect.
  * A `: ping` comment every 20s. An idle SSE connection sends zero bytes, and every
    proxy in the world (nginx's `proxy_read_timeout`, most LBs) kills an idle
    connection at 60s. The comment is ignored by the EventSource parser but is real
    bytes on the wire, which resets that timer.
  * Cleanup is in `finally`. Starlette cancels the generator when the client
    disconnects, so this is where the subscription gets torn down. Without it we'd leak
    a queue per dropped connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from sse_starlette.sse import EventSourceResponse

from app.db import queries
from app.db.events import read_events_since
from app.deps import Broker, Conn, CurrentUser

log = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

PING_INTERVAL_SECONDS = 20
RECONNECT_DELAY_MS = 3000


@router.get("/projects/{project_id}/events")
async def project_events(
    project_id: uuid.UUID,
    request: Request,
    conn: Conn,
    broker: Broker,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    await queries.get_project(conn, project_id)  # 404 before we open a stream

    try:
        cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        cursor = 0

    async def stream() -> AsyncIterator[dict]:
        nonlocal cursor
        pool = request.app.state.pool

        # Subscribe BEFORE replaying. If we replayed first, an event committed in the
        # gap between the replay query and the subscribe would be lost -- delivered to
        # nobody, and not in the replay either. Subscribing first means the worst case
        # is delivering an event twice, and the cursor check below makes duplicates
        # a no-op. Duplicate-safe beats gap-free-by-luck.
        async with broker.subscribe(project_id) as queue:
            async with pool.acquire() as replay_conn:
                for row in await read_events_since(replay_conn, project_id, cursor):
                    cursor = row["id"]
                    yield _sse(row)

            # Tell the client where the replay left off. Without this, a client that
            # reconnects having missed nothing has no id to send, and would re-receive
            # the entire history of the project.
            yield {"event": "synced", "id": str(cursor), "data": json.dumps({"cursor": cursor})}

            while True:
                try:
                    event_id = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_SECONDS)
                except TimeoutError:
                    yield {"event": "ping", "comment": "keep-alive"}
                    continue

                if event_id <= cursor:
                    continue  # already sent during replay

                async with pool.acquire() as read_conn:
                    for row in await read_events_since(read_conn, project_id, cursor):
                        cursor = row["id"]
                        yield _sse(row)

    log.info(
        "sse open project=%s user=%s cursor=%s subscribers=%d",
        project_id,
        user["email"],
        cursor,
        broker.subscriber_count(project_id) + 1,
    )
    return EventSourceResponse(stream(), ping=PING_INTERVAL_SECONDS, send_timeout=10)


def _sse(row) -> dict:
    event = queries.event_to_dict(row)
    return {
        "id": str(event["id"]),
        "event": event["type"],
        "data": json.dumps(event),
        "retry": RECONNECT_DELAY_MS,
    }
