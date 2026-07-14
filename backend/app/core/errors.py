"""One error shape for the whole API.

    {"error": {"code": "task_conflict", "message": "...", "details": {...}}}

`code` is a stable machine-readable string; the frontend switches on it. `message`
is for humans. `details` is free-form and is where a 409 puts the current server
state so the client can reconcile without a second round trip.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(APIError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Unauthorized(APIError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class EmailTaken(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = "email_taken"


class RateLimited(APIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class VersionConflict(APIError):
    """Optimistic concurrency check failed -- someone else wrote first.

    The version travels in the request BODY, not an `If-Match` header, so per RFC 9110
    this is a 409 (a conflict with current resource state) and not a 412 (a conditional
    request header evaluated false). Documented in ARCHITECTURE.md; the practical reason
    for body-over-header is that the board's move endpoint already carries a small
    intent object, and splitting half of it into headers buys nothing.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "version_conflict"


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's raw output has a `ctx` key that can hold non-serialisable objects,
        # so pick out just the fields the client can act on.
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body("validation_error", "Request body failed validation.", fields),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body("http_error", str(exc.detail)),
        )
