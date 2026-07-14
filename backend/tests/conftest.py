"""Test fixtures.

Two decisions here that are worth the paragraph:

1. THE TESTS RUN AGAINST A REAL POSTGRES, not SQLite and not a mock. This app leans on
   `citext`, a native enum, a `BIGSERIAL` cursor and `LISTEN/NOTIFY`. A stand-in
   database would be a stand-in for precisely the parts I most need to be right about.

2. THE TESTS RUN AGAINST A REAL HTTP SERVER, not httpx's in-process ASGITransport.
   This is not a style preference -- ASGITransport *cannot* test this app. It awaits
   the ASGI application to completion before returning a response, and an SSE stream
   never completes, so `client.stream(...)` against the events endpoint deadlocks
   forever. (I found this the hard way; see AI_USAGE.md.) Booting uvicorn on a real
   socket costs about fifteen lines and buys real coverage of the streaming path,
   which is the single most important thing in this codebase.
"""

from __future__ import annotations

import asyncio
import os
import socket

import asyncpg
import pytest_asyncio
import uvicorn
from httpx import AsyncClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql://taskboard:taskboard@localhost:5432/taskboard_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-for-hs256")

from app.main import app  # noqa: E402  (must import after the env vars above)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def server() -> str:
    """A real uvicorn server for the whole test session."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    instance = uvicorn.Server(config)
    # Don't let uvicorn grab SIGINT/SIGTERM -- pytest needs them.
    instance.install_signal_handlers = lambda: None

    task = asyncio.create_task(instance.serve())
    while not instance.started:
        await asyncio.sleep(0.02)

    yield f"http://127.0.0.1:{port}"

    instance.should_exit = True
    await task


@pytest_asyncio.fixture(loop_scope="session")
async def client(server: str) -> AsyncClient:
    # Truncating is faster than dropping and re-migrating, and RESTART IDENTITY resets
    # the events sequence so each test's event ids start from 1 -- which is what lets
    # the replay test assert on a concrete Last-Event-ID.
    pool: asyncpg.Pool = app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE events, tasks, projects, users RESTART IDENTITY CASCADE")

    async with AsyncClient(base_url=server, timeout=10) as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def alice(client: AsyncClient) -> AsyncClient:
    """A signed-in client. The server sets an httpOnly session cookie and httpx's cookie
    jar carries it from here on -- exactly what a browser does."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "correct-horse",
            "display_name": "Alice",
        },
    )
    assert res.status_code == 201, res.text
    return client


@pytest_asyncio.fixture(loop_scope="session")
async def project(alice: AsyncClient) -> str:
    res = await alice.post("/api/v1/projects", json={"name": "Q3 Launch"})
    assert res.status_code == 201, res.text
    return res.json()["id"]
