from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field, field_validator


class TaskStatus(StrEnum):
    """Mirrors the `task_status` enum in Postgres. The two must be changed together --
    the DB is the one that actually enforces it."""

    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class RegisterRequest(BaseModel):
    email: EmailStr
    # 8 is the floor OWASP asks for. I'm not enforcing character classes: they push
    # users toward "Password1!" and NIST dropped the recommendation years ago.
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
    """PATCH semantics: every field is optional, and only what's sent gets written.

    `version` is required. There is no way to update a task without saying which
    version you believed you were editing -- that's what makes the lost-update check
    non-optional rather than a thing callers can forget.
    """

    version: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: TaskStatus | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None

    # Distinguishes "not sent" from "explicitly cleared" for the nullable fields --
    # without this, PATCH {"version": 3} would unassign the task.
    clear_assignee: bool = False
    clear_due_date: bool = False


class TaskMove(BaseModel):
    """Move is relational, not absolute: the client names the neighbours it wants to
    land between and the SERVER computes the position string.

    This is what Jira's and Asana's rank APIs do, and it's the thing that makes
    concurrent drags safe -- two clients cannot fight over a number they both chose,
    because neither of them chooses it.
    """

    version: int
    status: TaskStatus
    before_id: uuid.UUID | None = None  # task this one should sit immediately after
    after_id: uuid.UUID | None = None  # task this one should sit immediately before


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
