"""Connection pool and migration runner.

No ORM. The brief asked for a schema I'd actually thought about, and the fastest way
to prove that is to write the SQL. Every query in this app is a query I can explain,
and `EXPLAIN` on it is the query the database runs -- no lazy-loading surprises, no
N+1 hiding behind an attribute access.

The cost is honest and worth stating: no migration autogeneration, and I hand-map rows
to dicts. At a few dozen queries that's fine. At a few hundred I'd want SQLAlchemy Core
(still not the ORM) for composable query building.
"""

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
        # asyncpg caches prepared statements per connection. That's usually what you
        # want, but it breaks against transaction-mode poolers (PgBouncer), so if this
        # ever ends up behind one, this is the line to change.
        statement_cache_size=100,
    )


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply any *.sql in migrations/ that hasn't been applied yet, in filename order.

    Deliberately about 20 lines instead of Alembic. Alembic's value is autogenerating
    diffs from ORM models, and there are no ORM models here; what's left is a version
    table and a loop. Each file runs in a transaction, so a failed migration rolls back
    rather than leaving the schema half-applied.
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
