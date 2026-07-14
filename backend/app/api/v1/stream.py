"""Streams real-time project events to connected clients using Server-Sent Events."""

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
    """Streams project events while replaying missed updates after reconnection."""

    await queries.get_project(conn, project_id)

    try:
        cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        cursor = 0

    async def stream() -> AsyncIterator[dict]:
        nonlocal cursor
        pool = request.app.state.pool

        async with broker.subscribe(project_id) as queue:
            async with pool.acquire() as replay_conn:
                for row in await read_events_since(replay_conn, project_id, cursor):
                    cursor = row["id"]
                    yield _sse(row)

            yield {
                "event": "synced",
                "id": str(cursor),
                "data": json.dumps({"cursor": cursor}),
            }

            while True:
                try:
                    event_id = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_SECONDS)
                except TimeoutError:
                    yield {"event": "ping", "comment": "keep-alive"}
                    continue

                if event_id <= cursor:
                    continue

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
    """Formats database events into Server-Sent Events response structure."""

    event = queries.event_to_dict(row)
    return {
        "id": str(event["id"]),
        "event": event["type"],
        "data": json.dumps(event),
        "retry": RECONNECT_DELAY_MS,
    }
