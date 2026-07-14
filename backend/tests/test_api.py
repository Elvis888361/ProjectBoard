"""API integration tests.

Covers the places where being wrong is both likely and silent: optimistic concurrency
(the only path where two correct clients produce a wrong result), and the realtime path
end to end. Not covered: every CRUD permutation, and the rate limiter -- see
ARCHITECTURE.md for why.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

# Real server over a real socket -- see conftest.
pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _create_task(client: AsyncClient, project: str, title: str) -> dict:
    res = await client.post(f"/api/v1/projects/{project}/tasks", json={"title": title})
    assert res.status_code == 201, res.text
    return res.json()


async def test_requires_authentication(client: AsyncClient):
    res = await client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


async def test_login_does_not_reveal_whether_an_account_exists(client: AsyncClient):
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

    # Identical, or the login form is an account-enumeration oracle.
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


async def test_create_task_appends_to_the_bottom_of_the_column(alice: AsyncClient, project: str):
    first = await _create_task(alice, project, "First")
    second = await _create_task(alice, project, "Second")

    assert first["position"] < second["position"]

    res = await alice.get(f"/api/v1/projects/{project}/tasks")
    assert [t["title"] for t in res.json()] == ["First", "Second"]


async def test_move_places_a_task_between_its_new_neighbours(alice: AsyncClient, project: str):
    top = await _create_task(alice, project, "Top")
    bottom = await _create_task(alice, project, "Bottom")
    dragged = await _create_task(alice, project, "Dragged")

    # Move Top and Bottom over first, so there's a real ordering to slot into.
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
    """The lost-update problem -- the whole reason `version` exists."""
    task = await _create_task(alice, project, "Contested")
    stale_version = task["version"]

    first = await alice.patch(
        f"/api/v1/tasks/{task['id']}", json={"version": stale_version, "title": "Alice's title"}
    )
    assert first.status_code == 200
    assert first.json()["version"] == stale_version + 1

    # Bob still holds the version he loaded, from before Alice's write.
    second = await alice.patch(
        f"/api/v1/tasks/{task['id']}", json={"version": stale_version, "title": "Bob's title"}
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "version_conflict"
    assert body["error"]["details"]["current"]["title"] == "Alice's title"

    # Alice's write survived. This is the assertion that matters.
    current = await alice.get(f"/api/v1/tasks/{task['id']}")
    assert current.json()["title"] == "Alice's title"


async def _read_events(
    server: str, cookies, project: str, *, last_event_id: str | None = None, until: str
) -> list[dict]:
    """Read a second user's stream until `until` arrives.

    Hard timeout, because a stream stays open by design: without one a broken test hangs
    rather than fails, and CI just sits there.
    """
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
    """The core requirement: A writes, B sees it without refreshing.

    A real SSE connection through a real LISTEN/NOTIFY round trip.
    """
    watcher = asyncio.create_task(
        _read_events(server, alice.cookies, project, until="task.created")
    )
    await asyncio.sleep(0.4)  # subscribe before we write

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
    """Reconnect with no gap and no full refetch -- the payoff of the cursor."""
    await _create_task(alice, project, "Before you left")
    missed = await _create_task(alice, project, "While you were gone")

    # The browser reconnecting, last having seen event 1.
    replayed = await _read_events(server, alice.cookies, project, last_event_id="1", until="synced")

    assert len(replayed) == 1, f"expected exactly the one missed event, got {len(replayed)}"
    assert replayed[0]["payload"]["task"]["id"] == missed["id"]
    assert replayed[0]["payload"]["task"]["title"] == "While you were gone"


async def test_a_caught_up_client_replays_nothing(alice: AsyncClient, project: str, server: str):
    """The other half of the contract: miss nothing, get nothing.

    Without the `synced` marker, a client with no id to send would replay the project's
    whole history on every reconnect.
    """
    await _create_task(alice, project, "Only event")

    replayed = await _read_events(server, alice.cookies, project, last_event_id="1", until="synced")
    assert replayed == []


async def test_the_event_log_doubles_as_an_activity_feed(alice: AsyncClient, project: str):
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
