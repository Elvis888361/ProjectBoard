"""Connection pool and migration runner. No ORM -- see ARCHITECTURE.md."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from app.core.config import get_settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def create_pool() -> asyncpg.Pool:
    settings = get_settings()
    return await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        # Would need to be 0 behind a transaction-mode pooler.
        statement_cache_size=100,
    )


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply any unapplied *.sql in migrations/, in filename order.

    No Alembic: its value is autogenerating diffs from ORM models, and there aren't any.
    Each file runs in a transaction, so a failure rolls back rather than half-applying.
    """
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
