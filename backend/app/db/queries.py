"""All SQL lives here. Routers do HTTP; this module does data.

Every board mutation appends to the event log in the same transaction, so there's no
path that changes a task without the change being broadcastable.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import asyncpg

from app.core.errors import NotFound, VersionConflict
from app.core.ranking import key_between
from app.db.events import append_event

TASK_COLUMNS = """
    t.id, t.project_id, t.title, t.description, t.status, t.assignee_id,
    u.display_name AS assignee_name, t.due_date, t.position, t.version,
    t.created_at, t.updated_at
"""


# --- users -------------------------------------------------------------------


async def create_user(
    conn: asyncpg.Connection, email: str, password_hash: str, display_name: str
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO users (email, password_hash, display_name)
        VALUES ($1, $2, $3)
        RETURNING id, email, display_name
        """,
        email,
        password_hash,
        display_name,
    )


async def get_user_by_email(conn: asyncpg.Connection, email: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, email, display_name, password_hash FROM users WHERE email = $1", email
    )


async def get_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT id, email, display_name FROM users WHERE id = $1", user_id)


async def list_users(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    # No roles, so everyone is assignable.
    return await conn.fetch("SELECT id, email, display_name FROM users ORDER BY display_name")


# --- projects ----------------------------------------------------------------


async def list_projects(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT p.id, p.name, p.description, p.created_by, p.created_at,
               count(t.id)::int AS task_count
        FROM projects p
        LEFT JOIN tasks t ON t.project_id = p.id
        GROUP BY p.id
        ORDER BY p.created_at DESC
        """
    )


async def create_project(
    conn: asyncpg.Connection, name: str, description: str, user_id: uuid.UUID
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO projects (name, description, created_by)
        VALUES ($1, $2, $3)
        RETURNING id, name, description, created_by, created_at, 0::int AS task_count
        """,
        name,
        description,
        user_id,
    )


async def get_project(conn: asyncpg.Connection, project_id: uuid.UUID) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        SELECT p.id, p.name, p.description, p.created_by, p.created_at,
               (SELECT count(*)::int FROM tasks WHERE project_id = p.id) AS task_count
        FROM projects p WHERE p.id = $1
        """,
        project_id,
    )
    if row is None:
        raise NotFound("Project not found.")
    return row


async def delete_project(conn: asyncpg.Connection, project_id: uuid.UUID) -> None:
    result = await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
    if result == "DELETE 0":
        raise NotFound("Project not found.")


# --- tasks -------------------------------------------------------------------


async def list_tasks(
    conn: asyncpg.Connection,
    project_id: uuid.UUID,
    *,
    search: str | None = None,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
) -> list[asyncpg.Record]:
    # Positional params, not interpolation.
    clauses = ["t.project_id = $1"]
    params: list[Any] = [project_id]

    if search:
        params.append(f"%{search}%")
        clauses.append(f"(t.title ILIKE ${len(params)} OR t.description ILIKE ${len(params)})")
    if status:
        params.append(status)
        clauses.append(f"t.status = ${len(params)}::task_status")
    if assignee_id:
        params.append(assignee_id)
        clauses.append(f"t.assignee_id = ${len(params)}")

    return await conn.fetch(
        f"""
        SELECT {TASK_COLUMNS}
        FROM tasks t
        LEFT JOIN users u ON u.id = t.assignee_id
        WHERE {" AND ".join(clauses)}
        ORDER BY t.status, t.position, t.id
        """,
        *params,
    )


async def get_task(conn: asyncpg.Connection, task_id: uuid.UUID) -> asyncpg.Record:
    row = await conn.fetchrow(
        f"""
        SELECT {TASK_COLUMNS}
        FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id
        WHERE t.id = $1
        """,
        task_id,
    )
    if row is None:
        raise NotFound("Task not found.")
    return row


async def _last_position(
    conn: asyncpg.Connection,
    project_id: uuid.UUID,
    status: str,
    exclude: uuid.UUID | None = None,
) -> str | None:
    """Bottom position in a column, or None if empty.

    `exclude` skips the task being moved, so it can't end up its own neighbour.
    """
    return await conn.fetchval(
        """
        SELECT position FROM tasks
        WHERE project_id = $1 AND status = $2::task_status
          AND ($3::uuid IS NULL OR id <> $3)
        ORDER BY position DESC, id DESC LIMIT 1
        """,
        project_id,
        status,
        exclude,
    )


async def create_task(
    conn: asyncpg.Connection,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    title: str,
    description: str,
    status: str,
    assignee_id: uuid.UUID | None,
    due_date: date | None,
) -> asyncpg.Record:
    async with conn.transaction():
        # Append to the bottom of the column.
        position = key_between(await _last_position(conn, project_id, status), None)

        row = await conn.fetchrow(
            """
            INSERT INTO tasks (project_id, title, description, status, assignee_id,
                               due_date, position, created_by)
            VALUES ($1, $2, $3, $4::task_status, $5, $6, $7, $8)
            RETURNING id
            """,
            project_id,
            title,
            description,
            status,
            assignee_id,
            due_date,
            position,
            user_id,
        )
        task = await get_task(conn, row["id"])
        await append_event(
            conn,
            project_id=project_id,
            task_id=task["id"],
            type_="task.created",
            actor_id=user_id,
            payload={"task": _task_payload(task)},
        )
        return task


async def update_task(
    conn: asyncpg.Connection,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    version: int,
    fields: dict[str, Any],
) -> asyncpg.Record:
    """Conditional on `version`, so a stale write can't clobber a fresh one."""
    if not fields:
        return await get_task(conn, task_id)

    async with conn.transaction():
        assignments = []
        params: list[Any] = []
        for column, value in fields.items():
            params.append(value)
            cast = "::task_status" if column == "status" else ""
            assignments.append(f"{column} = ${len(params)}{cast}")

        params.extend([task_id, version])
        updated = await conn.fetchrow(
            f"""
            UPDATE tasks SET {", ".join(assignments)},
                             version = version + 1,
                             updated_at = now()
            WHERE id = ${len(params) - 1} AND version = ${len(params)}
            RETURNING id
            """,
            *params,
        )

        if updated is None:
            # Zero rows is either "gone" or "someone wrote first", and the client needs
            # to tell them apart. get_task raises NotFound if it's really gone.
            current = await get_task(conn, task_id)
            raise VersionConflict(
                "This task was changed by someone else while you were editing it.",
                {"current": _task_payload(current)},
            )

        task = await get_task(conn, task_id)
        await append_event(
            conn,
            project_id=task["project_id"],
            task_id=task["id"],
            type_="task.updated",
            actor_id=user_id,
            payload={"task": _task_payload(task), "changed": sorted(fields)},
        )
        return task


async def move_task(
    conn: asyncpg.Connection,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    version: int,
    status: str,
    before_id: uuid.UUID | None,
    after_id: uuid.UUID | None,
) -> asyncpg.Record:
    """Move to `status`, between `before_id` and `after_id`.

    Neighbours are read inside the transaction, so the position is based on the order at
    write time rather than whatever the client last saw.
    """
    async with conn.transaction():
        task = await get_task(conn, task_id)

        before = (
            await conn.fetchval("SELECT position FROM tasks WHERE id = $1", before_id)
            if before_id
            else None
        )
        after = (
            await conn.fetchval("SELECT position FROM tasks WHERE id = $1", after_id)
            if after_id
            else None
        )

        # No neighbours named means rank LAST, not "empty column". Getting this wrong
        # hands every such task the first key, and they collide. Also covers a neighbour
        # that vanished mid-drag -- appending beats a 409 the user can't act on.
        if before is None and after is None:
            before = await _last_position(conn, task["project_id"], status, exclude=task_id)

        # Stale or reordered pair that doesn't bracket a gap.
        if before is not None and after is not None and before >= after:
            after = None

        position = key_between(before, after)

        updated = await conn.fetchrow(
            """
            UPDATE tasks
            SET status = $1::task_status, position = $2,
                version = version + 1, updated_at = now()
            WHERE id = $3 AND version = $4
            RETURNING id
            """,
            status,
            position,
            task_id,
            version,
        )
        if updated is None:
            current = await get_task(conn, task_id)
            raise VersionConflict(
                "This task was moved by someone else while you were dragging it.",
                {"current": _task_payload(current)},
            )

        moved = await get_task(conn, task_id)
        await append_event(
            conn,
            project_id=moved["project_id"],
            task_id=moved["id"],
            type_="task.moved",
            actor_id=user_id,
            payload={
                "task": _task_payload(moved),
                "from_status": task["status"],
                "to_status": status,
            },
        )
        return moved


async def delete_task(conn: asyncpg.Connection, task_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with conn.transaction():
        task = await get_task(conn, task_id)
        await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
        await append_event(
            conn,
            project_id=task["project_id"],
            task_id=task["id"],
            type_="task.deleted",
            actor_id=user_id,
            payload={"task_id": str(task["id"]), "title": task["title"]},
        )


def _task_payload(row: asyncpg.Record) -> dict[str, Any]:
    """Serialise a task for the event log.

    The whole task, not just an id: subscribers can apply it without a follow-up fetch,
    and `version` riding along is what lets them drop stale events.
    """
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
        "assignee_name": row["assignee_name"],
        "due_date": row["due_date"].isoformat() if row["due_date"] else None,
        "position": row["position"],
        "version": row["version"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def event_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    payload = row["payload"]
    return {
        "id": row["id"],
        "type": row["type"],
        "task_id": str(row["task_id"]) if row["task_id"] else None,
        "actor_name": row["actor_name"],
        "payload": json.loads(payload) if isinstance(payload, str) else payload,
        "created_at": row["created_at"].isoformat(),
    }
