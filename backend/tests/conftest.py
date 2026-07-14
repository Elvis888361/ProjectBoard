"""Test fixtures.

Real Postgres (the app leans on citext, a native enum, BIGSERIAL and LISTEN/NOTIFY), and
a real uvicorn server rather than httpx's ASGITransport -- that transport awaits the ASGI
app to completion, and an SSE stream never completes, so it deadlocks on the events
endpoint. Fifteen lines to boot a real socket, and the streaming path gets tested.
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
    # RESTART IDENTITY resets the events sequence, so the replay test can assert on a
    # concrete Last-Event-ID.
    pool: asyncpg.Pool = app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE events, tasks, projects, users RESTART IDENTITY CASCADE")

    async with AsyncClient(base_url=server, timeout=10) as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def alice(client: AsyncClient) -> AsyncClient:
    """Signed in. httpx's cookie jar carries the session, same as a browser."""
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
