"""Async Postgres session factory (SQLAlchemy 2.0 async + asyncpg).

The engine and sessionmaker are built lazily on first use, sourced from
`app.core.config.get_settings().database_url` -- importing this module
never opens a connection. Ported from `services/ingestion`'s identical
module (itself from `data-pipeline`) -- same pooler-compatibility fix
(`statement_cache_size=0`, see the comment below), this service talks to
the exact same NeonDB instance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        future=True,
        # `DATABASE_URL` in this environment goes through a transaction-mode
        # connection pooler (Neon's "-pooler" endpoint, PgBouncer under the
        # hood). asyncpg's default server-side prepared-statement cache
        # assumes a stable logical connection maps to one physical backend,
        # which a transaction pooler doesn't guarantee -- disabling it is
        # asyncpg's own documented fix for exactly this pooler combination
        # (confirmed the hard way in `services/ingestion`/`data-pipeline`).
        connect_args={"statement_cache_size": 0},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Open a session, commit on success, roll back and re-raise on error."""
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose() -> None:
    """Dispose of the engine's connection pool (call on service shutdown)."""
    await get_engine().dispose()
