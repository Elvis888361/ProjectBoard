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


# In-process sliding window, keyed by client IP.
#
# This is a deliberate 20-line answer to the brief's "basic rate limiting" rather than
# a real one, and the limitation is worth naming because it's the same limitation the
# realtime layer would have had if I'd used an in-memory pub/sub: it is PER PROCESS.
# Run two uvicorn workers and an attacker gets 2x the budget. The fix is a shared
# counter -- Redis, or a Postgres table with a window bucket -- and it's about an
# hour's work. I spent that hour on the SSE replay path instead, which is the thing
# the brief actually weights.
_attempts: dict[str, deque[float]] = defaultdict(deque)

# Hashed once at import so the "no such user" branch of login does the same amount of
# work as the "wrong password" branch. See the comment in login().
_DUMMY_HASH = hash_password("this-hash-is-never-a-valid-password")


def _check_rate_limit(request: Request) -> None:
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
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,  # unreadable from JS, so XSS can't exfiltrate it
        secure=settings.cookie_secure,
        samesite="lax",  # blocks cross-site POSTs; see the Origin check in main.py
        path="/",
        max_age=settings.access_token_ttl_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, conn: Conn) -> UserOut:
    try:
        user = await queries.create_user(
            conn, body.email, hash_password(body.password), body.display_name.strip()
        )
    except asyncpg.UniqueViolationError:
        # Let the database be the arbiter. A check-then-insert has a race window; the
        # unique index doesn't.
        raise EmailTaken("An account with that email already exists.") from None

    _set_session_cookie(response, issue_token(user["id"]))
    return UserOut(**dict(user))


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, conn: Conn) -> UserOut:
    _check_rate_limit(request)

    user = await queries.get_user_by_email(conn, body.email)

    # Same error, same shape, whether the email exists or the password is wrong --
    # otherwise this endpoint is an account-enumeration oracle. Short-circuiting on
    # `user is None` would leak the same fact through timing (a real Argon2 verify is
    # ~50ms; skipping it is ~0), so hash against a dummy to keep the two paths even.
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
