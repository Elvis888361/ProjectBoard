"""Password hashing and session tokens.

pwdlib/PyJWT rather than the passlib/python-jose pair most tutorials show -- both are
unmaintained and python-jose has CVE-2024-33663. The token rides in an httpOnly cookie
because EventSource can't set an Authorization header; see ARCHITECTURE.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHash.recommended()  # Argon2id


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
            algorithms=[settings.jwt_algorithm],  # allowlist; never trust the token's alg
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Session is invalid or has expired.") from exc

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Session is invalid or has expired.") from exc
