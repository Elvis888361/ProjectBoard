"""Password hashing and session tokens.

Two deliberate deviations from what most FastAPI tutorials still show:

* `pwdlib[argon2]`, not `passlib`. passlib's last release was 2020 and it breaks
  outright against bcrypt 5.x; FastAPI's own docs moved to pwdlib. Argon2id also
  sidesteps bcrypt's 72-byte silent input truncation.
* `PyJWT`, not `python-jose`. python-jose is unmaintained and carries CVE-2024-33663
  (algorithm confusion -> signature forgery). FastAPI's docs moved to PyJWT too.

The token lives in an httpOnly cookie rather than localStorage. That is not a
security-theatre preference -- it's forced by the realtime design. The browser's
EventSource API cannot set an `Authorization` header (whatwg/html#2177, open since
2016), so a bearer token would have to travel in the SSE query string, where it lands
in every access log and proxy trace. A cookie is sent automatically, is unreadable
from JS, and works for both the REST calls and the stream. The cost is CSRF surface,
handled by SameSite=Lax + an Origin check on mutations (see main.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHash.recommended()  # Argon2id at OWASP's current parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


def issue_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            # An explicit allowlist. Without it, PyJWT would honour the `alg` in the
            # token header, which is the whole algorithm-confusion attack class.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Session is invalid or has expired.") from exc

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Session is invalid or has expired.") from exc
