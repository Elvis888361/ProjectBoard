from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field, field_validator


class TaskStatus(StrEnum):
    """Mirrors the task_status enum in Postgres; change both together."""

    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class RegisterRequest(BaseModel):
    email: EmailStr
    # Length only. Character-class rules just produce "Password1!".
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank.")
        return v


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    created_by: uuid.UUID
    created_at: datetime
    task_count: int = 0


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: TaskStatus = TaskStatus.todo
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be blank.")
        return v


class TaskUpdate(BaseModel):
    """PATCH: only what's sent gets written.

    `version` is required, so the lost-update check can't be forgotten.
    """

    version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: TaskStatus | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None

    # "not sent" vs "explicitly cleared". Without these, PATCH {"version": 3} would
    # unassign the task.
    clear_assignee: bool = False
    clear_due_date: bool = False


class TaskMove(BaseModel):
    """Relational, not absolute: name the neighbours, the server computes the position.

    Two clients can't fight over a number neither of them picked.
    """

    version: int
    status: TaskStatus
    before_id: uuid.UUID | None = None  # sit immediately after this task
    after_id: uuid.UUID | None = None  # sit immediately before this task


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str
    status: TaskStatus
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    due_date: date | None
    position: str
    version: int
    created_at: datetime
    updated_at: datetime


class ActivityOut(BaseModel):
    id: int
    type: str
    task_id: uuid.UUID | None
    actor_name: str | None
    payload: dict
    created_at: datetime
