"""Provides authentication endpoints for registration, login, logout, and user sessions."""

from __future__ import annotations

import time
from collections import defaultdict, deque

import asyncpg
from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings
from app.core.errors import EmailTaken, RateLimited, Unauthorized
from app.core.security import hash_password, issue_token, verify_password
from app.db import queries
from app.deps import Conn, CurrentUser
from app.schemas import LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


_attempts: dict[str, deque[float]] = defaultdict(deque)

_DUMMY_HASH = hash_password("this-hash-is-never-a-valid-password")


def _check_rate_limit(request: Request) -> None:
    """Limits repeated login attempts to prevent brute-force authentication attacks."""

    settings = get_settings()
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _attempts[client]

    while window and now - window[0] > settings.login_rate_limit_window_seconds:
        window.popleft()

    if len(window) >= settings.login_rate_limit_attempts:
        raise RateLimited("Too many sign-in attempts. Try again in a minute.")
    window.append(now)


def _set_session_cookie(response: Response, token: str) -> None:
    """Stores secure authentication token inside user's session cookie."""

    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.access_token_ttl_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, conn: Conn) -> UserOut:
    """Registers new user, creates account, and starts authenticated session."""

    try:
        user = await queries.create_user(
            conn, body.email, hash_password(body.password), body.display_name.strip()
        )
    except asyncpg.UniqueViolationError:
        raise EmailTaken("An account with that email already exists.") from None

    _set_session_cookie(response, issue_token(user["id"]))
    return UserOut(**dict(user))


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, conn: Conn) -> UserOut:
    """Authenticates user credentials and creates secure login session."""

    _check_rate_limit(request)

    user = await queries.get_user_by_email(conn, body.email)
    password_hash = user["password_hash"] if user else _DUMMY_HASH
    password_ok = verify_password(body.password, password_hash)

    if user is None or not password_ok:
        raise Unauthorized("Email or password is incorrect.")

    _set_session_cookie(response, issue_token(user["id"]))
    return UserOut(id=user["id"], email=user["email"], display_name=user["display_name"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(**dict(user))
