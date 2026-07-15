"""Tests API behaviour, concurrency, auth, and real-time event streaming."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_task(client: AsyncClient, project: str, title: str) -> dict:
    # Creates test task and returns created task information.
    res = await client.post(f"/api/v1/projects/{project}/tasks", json={"title": title})
    assert res.status_code == 201, res.text
    return res.json()


async def test_requires_authentication(client: AsyncClient):
    # Verifies protected endpoints require authenticated user access.
    res = await client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


async def test_same_origin_write_is_allowed(client: AsyncClient):
    # A browser always sends Origin on a POST. When it matches the Host, it's our own
    # page and must go through -- this is the case a header-less curl test misses.
    host = client.base_url.host
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "same@x.com", "password": "correct-horse", "display_name": "S"},
        headers={"Origin": f"http://{host}", "Host": host},
    )
    assert res.status_code == 201, res.text


async def test_cross_origin_write_is_blocked(client: AsyncClient):
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "evil@x.com", "password": "correct-horse", "display_name": "E"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "cross_origin_blocked"


async def test_login_does_not_reveal_whether_an_account_exists(client: AsyncClient):
    # Ensures login never reveals whether user account exists.
    await client.post(
        "/api/v1/auth/register",
        json={"email": "real@example.com", "password": "correct-horse", "display_name": "R"},
    )

    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "nope-nope-nope"}
    )
    no_such_user = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


async def test_create_task_appends_to_the_bottom_of_the_column(alice: AsyncClient, project: str):
    # Verifies new tasks are appended to column bottom correctly.
    first = await _create_task(alice, project, "First")
    second = await _create_task(alice, project, "Second")

    assert first["position"] < second["position"]

    res = await alice.get(f"/api/v1/projects/{project}/tasks")
    assert [t["title"] for t in res.json()] == ["First", "Second"]


async def test_move_places_a_task_between_its_new_neighbours(alice: AsyncClient, project: str):
    # Verifies task moves correctly between neighboring task positions.
    top = await _create_task(alice, project, "Top")
    bottom = await _create_task(alice, project, "Bottom")
    dragged = await _create_task(alice, project, "Dragged")

    for task in (top, bottom):
        res = await alice.post(
            f"/api/v1/tasks/{task['id']}/move",
            json={"version": task["version"], "status": "in_progress", "after_id": None},
        )
        assert res.status_code == 200, res.text

    ordered = [
        t
        for t in (await alice.get(f"/api/v1/projects/{project}/tasks")).json()
        if t["status"] == "in_progress"
    ]
    assert [t["title"] for t in ordered] == ["Top", "Bottom"]

    res = await alice.post(
        f"/api/v1/tasks/{dragged['id']}/move",
        json={
            "version": dragged["version"],
            "status": "in_progress",
            "before_id": ordered[0]["id"],  # after Top
            "after_id": ordered[1]["id"],  # before Bottom
        },
    )
    assert res.status_code == 200, res.text

    final = [
        t
        for t in (await alice.get(f"/api/v1/projects/{project}/tasks")).json()
        if t["status"] == "in_progress"
    ]
    assert [t["title"] for t in final] == ["Top", "Dragged", "Bottom"]


async def test_a_stale_write_is_rejected_and_nothing_is_lost(alice: AsyncClient, project: str):
    """Verifies optimistic locking prevents conflicting task updates safely."""
    task = await _create_task(alice, project, "Contested")
    stale_version = task["version"]

    first = await alice.patch(
        f"/api/v1/tasks/{task['id']}", json={"version": stale_version, "title": "Alice's title"}
    )
    assert first.status_code == 200
    assert first.json()["version"] == stale_version + 1

    second = await alice.patch(
        f"/api/v1/tasks/{task['id']}", json={"version": stale_version, "title": "Bob's title"}
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "version_conflict"
    assert body["error"]["details"]["current"]["title"] == "Alice's title"

    current = await alice.get(f"/api/v1/tasks/{task['id']}")
    assert current.json()["title"] == "Alice's title"


async def _read_events(
    server: str, cookies, project: str, *, last_event_id: str | None = None, until: str
) -> list[dict]:
    """Reads Server-Sent Events until specified event is received."""
    events: list[dict] = []

    async def read() -> None:
        headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
        async with (
            AsyncClient(base_url=server, cookies=cookies, timeout=10) as bob,
            bob.stream("GET", f"/api/v1/projects/{project}/events", headers=headers) as stream,
        ):
            async for line in stream.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:])
                if payload.get("type") == until:
                    events.append(payload)
                    return
                if until == "synced" and "cursor" in payload:
                    return
                if "cursor" not in payload:
                    events.append(payload)

    await asyncio.wait_for(read(), timeout=8)
    return events


async def test_a_change_is_pushed_to_a_client_watching_the_stream(
    alice: AsyncClient, project: str, server: str
):
    """Verifies realtime task updates reach connected clients immediately."""
    watcher = asyncio.create_task(
        _read_events(server, alice.cookies, project, until="task.created")
    )
    await asyncio.sleep(0.4)

    await _create_task(alice, project, "Look at me")

    try:
        received = await asyncio.wait_for(watcher, timeout=8)
    except TimeoutError:
        watcher.cancel()
        pytest.fail("the SSE stream never delivered the task.created event")

    assert received[0]["payload"]["task"]["title"] == "Look at me"
    assert received[0]["actor_name"] == "Alice"


async def test_a_reconnecting_client_replays_exactly_what_it_missed(
    alice: AsyncClient, project: str, server: str
):
    """Verifies reconnecting clients receive only missed events."""
    await _create_task(alice, project, "Before you left")
    missed = await _create_task(alice, project, "While you were gone")

    replayed = await _read_events(server, alice.cookies, project, last_event_id="1", until="synced")

    assert len(replayed) == 1, f"expected exactly the one missed event, got {len(replayed)}"
    assert replayed[0]["payload"]["task"]["id"] == missed["id"]
    assert replayed[0]["payload"]["task"]["title"] == "While you were gone"


async def test_a_caught_up_client_replays_nothing(alice: AsyncClient, project: str, server: str):
    """Verifies synchronized clients receive no duplicate replayed events."""
    await _create_task(alice, project, "Only event")

    replayed = await _read_events(server, alice.cookies, project, last_event_id="1", until="synced")
    assert replayed == []


async def test_the_event_log_doubles_as_an_activity_feed(alice: AsyncClient, project: str):
    """Verifies event log correctly powers project activity feed."""
    task = await _create_task(alice, project, "Ship it")
    await alice.post(
        f"/api/v1/tasks/{task['id']}/move",
        json={"version": task["version"], "status": "done"},
    )

    res = await alice.get(f"/api/v1/projects/{project}/activity")
    entries = res.json()

    assert [e["type"] for e in entries] == ["task.moved", "task.created"]
    assert entries[0]["actor_name"] == "Alice"
    assert entries[0]["payload"]["to_status"] == "done"
