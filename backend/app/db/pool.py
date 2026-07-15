"""Creates database connections and automatically applies pending database schema migrations."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from app.core.config import get_settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def create_pool() -> asyncpg.Pool:
    """Creates and configures reusable PostgreSQL database connection pool for application."""

    settings = get_settings()
    return await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        statement_cache_size=100,
    )


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Applies pending SQL migrations while tracking successfully executed migration files."""

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            r["filename"] for r in await conn.fetch("SELECT filename FROM schema_migrations")
        }

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            log.info("applying migration %s", path.name)
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
                )
