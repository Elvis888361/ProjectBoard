"""Basically all the schemas used in the backend are defined here.
Schemas are used to validate and serialize data between the backend and frontend.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field, field_validator


class TaskStatus(StrEnum):
    """Defines Task Statuses:todo,inporgress,done."""

    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class RegisterRequest(BaseModel):
    """Validates User regestation details before creating a new account."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    """Validates User Login details before authentiaction process"""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """Represents a user in the system.bringing all his credentials."""

    id: uuid.UUID
    email: str
    display_name: str


class ProjectCreate(BaseModel):
    """Validates Project details before creating a new project."""

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
    """Returns complete project information."""

    id: uuid.UUID
    name: str
    description: str
    created_by: uuid.UUID
    created_at: datetime
    task_count: int = 0


class TaskCreate(BaseModel):
    """Validates task details before creating a new project task."""

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
    """Updates existing task fields while preventing conflicting simultaneous modifications."""

    version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: TaskStatus | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    clear_assignee: bool = False
    clear_due_date: bool = False


class TaskMove(BaseModel):
    """Moves a task to a new status and position."""

    version: int
    status: TaskStatus
    before_id: uuid.UUID | None = None
    after_id: uuid.UUID | None = None


class TaskOut(BaseModel):
    """Returns complete task information."""

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
    """Returns complete activity information."""

    id: int
    type: str
    task_id: uuid.UUID | None
    actor_name: str | None
    payload: dict
    created_at: datetime
