"""Handles database queries and records real-time events for application changes."""

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


async def create_user(
    conn: asyncpg.Connection, email: str, password_hash: str, display_name: str
) -> asyncpg.Record:
    """Creates a new user and returns stored user information."""

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
    """Retrieves user information using the provided email address."""

    return await conn.fetchrow(
        "SELECT id, email, display_name, password_hash FROM users WHERE email = $1", email
    )


async def get_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> asyncpg.Record | None:
    """Retrieves a user using their unique identifier."""

    return await conn.fetchrow("SELECT id, email, display_name FROM users WHERE id = $1", user_id)


async def list_users(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    # Returns all users available for task assignment.
    return await conn.fetch("SELECT id, email, display_name FROM users ORDER BY display_name")


async def list_projects(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Retrieves all projects with their associated task counts."""

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
    """Creates a new project and returns its details."""

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
    """Retrieves project details or raises not-found exception."""

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
    """Deletes specified project or raises not-found exception."""

    result = await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
    if result == "DELETE 0":
        raise NotFound("Project not found.")


async def list_tasks(
    conn: asyncpg.Connection,
    project_id: uuid.UUID,
    *,
    search: str | None = None,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
) -> list[asyncpg.Record]:
    """Retrieves project tasks with optional filtering and searching."""

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
    """Retrieves a specific task using its unique identifier."""

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
    """Finds last task position within specified project status column."""

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
        """Creates task, assigns position, and records creation event."""

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
    """Updates task fields while preventing conflicting concurrent modifications."""

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
    """Moves task between columns while maintaining correct ordering."""

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

        if before is None and after is None:
            before = await _last_position(conn, task["project_id"], status, exclude=task_id)

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
    """Deletes task and records deletion event for subscribers."""

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
    """Converts task record into event-ready dictionary payload."""

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
    """Converts database event record into JSON-serializable dictionary."""

    payload = row["payload"]
    return {
        "id": row["id"],
        "type": row["type"],
        "task_id": str(row["task_id"]) if row["task_id"] else None,
        "actor_name": row["actor_name"],
        "payload": json.loads(payload) if isinstance(payload, str) else payload,
        "created_at": row["created_at"].isoformat(),
    }
