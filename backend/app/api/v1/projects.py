"""Provides project, user, task, and activity API endpoint implementations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.db import queries
from app.deps import Conn, CurrentUser
from app.schemas import (
    ActivityOut,
    ProjectCreate,
    ProjectOut,
    TaskCreate,
    TaskOut,
    UserOut,
)

router = APIRouter(tags=["projects"])


@router.get("/users", response_model=list[UserOut])
async def list_users(conn: Conn, _: CurrentUser) -> list[UserOut]:
    # Retrieves all users available for project task assignments.
    return [UserOut(**dict(r)) for r in await queries.list_users(conn)]


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(conn: Conn, _: CurrentUser) -> list[ProjectOut]:
    # Returns all projects with their associated task counts.
    return [ProjectOut(**dict(r)) for r in await queries.list_projects(conn)]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, conn: Conn, user: CurrentUser) -> ProjectOut:
    # Creates a new project using validated user-provided information.
    row = await queries.create_project(conn, body.name, body.description, user["id"])
    return ProjectOut(**dict(row))


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, conn: Conn, _: CurrentUser) -> ProjectOut:
    # Retrieves project details using its unique project identifier.
    return ProjectOut(**dict(await queries.get_project(conn, project_id)))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, conn: Conn, _: CurrentUser) -> None:
    # Deletes specified project from the database permanently.
    await queries.delete_project(conn, project_id)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: uuid.UUID,
    conn: Conn,
    _: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status"),
    assignee_id: uuid.UUID | None = None,
) -> list[TaskOut]:
    # Retrieves project tasks with optional search and filtering capabilities.
    await queries.get_project(conn, project_id)
    rows = await queries.list_tasks(
        conn, project_id, search=search, status=status_filter, assignee_id=assignee_id
    )
    return [TaskOut(**dict(r)) for r in rows]


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: uuid.UUID, body: TaskCreate, conn: Conn, user: CurrentUser
) -> TaskOut:
    # Creates new task within selected project and returns details.
    await queries.get_project(conn, project_id)
    row = await queries.create_task(
        conn,
        project_id,
        user["id"],
        title=body.title,
        description=body.description,
        status=body.status.value,
        assignee_id=body.assignee_id,
        due_date=body.due_date,
    )
    return TaskOut(**dict(row))


@router.get("/projects/{project_id}/activity", response_model=list[ActivityOut])
async def project_activity(
    project_id: uuid.UUID,
    conn: Conn,
    _: CurrentUser,
    limit: int = Query(default=50, le=200),
) -> list[ActivityOut]:
    """Returns recent project activity events from the application event log."""
    rows = await conn.fetch(
        """
        SELECT e.id, e.type, e.task_id, e.payload, e.created_at,
               u.display_name AS actor_name
        FROM events e LEFT JOIN users u ON u.id = e.actor_id
        WHERE e.project_id = $1
        ORDER BY e.id DESC
        LIMIT $2
        """,
        project_id,
        limit,
    )
    return [ActivityOut(**queries.event_to_dict(r)) for r in rows]
