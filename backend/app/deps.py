from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
from fastapi import Cookie, Depends, Request

from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.db import queries
from app.db.events import EventBroker


async def get_conn(request: Request) -> AsyncIterator[asyncpg.Connection]:
    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as conn:
        yield conn


def get_broker(request: Request) -> EventBroker:
    return request.app.state.broker


Conn = Annotated[asyncpg.Connection, Depends(get_conn)]
Broker = Annotated[EventBroker, Depends(get_broker)]


async def current_user(
    conn: Conn,
    session: Annotated[str | None, Cookie(alias=get_settings().cookie_name)] = None,
) -> asyncpg.Record:
    if not session:
        raise Unauthorized("Not signed in.")

    from app.core.security import read_token  # avoids a config import cycle

    user_id: uuid.UUID = read_token(session)
    user = await queries.get_user(conn, user_id)
    if user is None:
        # Validly signed, but the user is gone. Signed out, not a 500.
        raise Unauthorized("Not signed in.")
    return user


CurrentUser = Annotated[asyncpg.Record, Depends(current_user)]
