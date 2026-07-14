from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.db import queries
from app.deps import Conn, CurrentUser
from app.schemas import TaskMove, TaskOut, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, conn: Conn, _: CurrentUser) -> TaskOut:
    return TaskOut(**dict(await queries.get_task(conn, task_id)))


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, conn: Conn, user: CurrentUser
) -> TaskOut:
    # `exclude_unset` is what makes this a real PATCH: a field the client didn't send
    # is left alone, rather than being overwritten with None. The two `clear_*` flags
    # exist because that same rule makes it impossible to express "set this to null"
    # any other way.
    sent = body.model_dump(exclude_unset=True)
    fields: dict[str, object] = {}

    for name in ("title", "description", "assignee_id", "due_date"):
        if name in sent:
            fields[name] = sent[name]
    if "status" in sent:
        fields["status"] = body.status.value if body.status else None

    if body.clear_assignee:
        fields["assignee_id"] = None
    if body.clear_due_date:
        fields["due_date"] = None

    row = await queries.update_task(conn, task_id, user["id"], version=body.version, fields=fields)
    return TaskOut(**dict(row))


@router.post("/{task_id}/move", response_model=TaskOut)
async def move_task(task_id: uuid.UUID, body: TaskMove, conn: Conn, user: CurrentUser) -> TaskOut:
    row = await queries.move_task(
        conn,
        task_id,
        user["id"],
        version=body.version,
        status=body.status.value,
        before_id=body.before_id,
        after_id=body.after_id,
    )
    return TaskOut(**dict(row))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, conn: Conn, user: CurrentUser) -> None:
    await queries.delete_task(conn, task_id, user["id"])
