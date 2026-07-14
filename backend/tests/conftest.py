"""Provides shared test fixtures for integration and API endpoint testing."""

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

from app.main import app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def server() -> str:
    """Starts and manages temporary FastAPI server during integration tests."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    instance = uvicorn.Server(config)
    instance.install_signal_handlers = lambda: None

    task = asyncio.create_task(instance.serve())
    while not instance.started:
        await asyncio.sleep(0.02)

    yield f"http://127.0.0.1:{port}"

    instance.should_exit = True
    await task


@pytest_asyncio.fixture(loop_scope="session")
async def client(server: str) -> AsyncClient:
    # Creates reusable HTTP client and resets database before tests.
    pool: asyncpg.Pool = app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE events, tasks, projects, users RESTART IDENTITY CASCADE")

    async with AsyncClient(base_url=server, timeout=10) as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def alice(client: AsyncClient) -> AsyncClient:
    """Registers authenticated test user for protected endpoint testing."""
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
