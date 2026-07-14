from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, projects, stream, tasks
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.db.events import EventBroker
from app.db.pool import create_pool, run_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pool = await create_pool()
    await run_migrations(app.state.pool)

    app.state.broker = EventBroker()
    await app.state.broker.start()

    yield

    await app.state.broker.stop()
    await app.state.pool.close()


app = FastAPI(
    title="ProjectBoard API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

install_error_handlers(app)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    """Reject cross-site writes.

    Cookie auth means the browser attaches the session to anything hitting this origin.
    SameSite=Lax covers the common cases but is defence-in-depth, not the control.
    """
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin:
            allowed = {str(request.base_url).rstrip("/"), *get_settings().cors_origins}
            if origin.rstrip("/") not in allowed:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "error": {
                            "code": "cross_origin_blocked",
                            "message": "Cross-origin request rejected.",
                        }
                    },
                )
    return await call_next(request)


# Empty in dev and in compose: the frontend is proxied, so it's all same-origin and
# there's no CORS at all. Here for a split-origin deploy.
if get_settings().cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(stream.router, prefix="/api/v1")


@app.get("/api/health", tags=["ops"])
async def health(request: Request) -> dict[str, object]:
    """Touches the database. A health check that doesn't only tells you the process is
    up, which you already knew."""
    try:
        async with request.app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "ok"}
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "unreachable"},
        )
