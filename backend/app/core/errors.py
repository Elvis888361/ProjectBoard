"""Provides consistent API error handling and standardized error response formatting."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Base exception class for all custom API application errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(APIError):
    # Raised when requested resource cannot be found in database.
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Unauthorized(APIError):
    # Raised when user authentication fails or session becomes invalid.
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class EmailTaken(APIError):
    # Raised when registration email already exists in system database.
    status_code = status.HTTP_409_CONFLICT
    code = "email_taken"


class RateLimited(APIError):
    # Raised when client exceeds allowed request rate limits.
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class VersionConflict(APIError):
    """Raised when concurrent updates create conflicting task modifications."""

    status_code = status.HTTP_409_CONFLICT
    code = "version_conflict"


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Creates standardized JSON error response with optional additional details."""

    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    """Registers global exception handlers for consistent API error responses."""

    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
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
