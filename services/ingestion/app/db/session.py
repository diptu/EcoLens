"""Async Postgres session factory (SQLAlchemy 2.0 async + asyncpg).

The engine and sessionmaker are built lazily on first use, sourced from
`app.core.config.get_settings().database_url` -- importing this module
never opens a connection. Ported verbatim from data-pipeline's identical
module (`services/ingestion/TODO.md` Phase 0) -- this service only ever
writes `meta._ingest_log` through it (never `raw.*`), but the connection
plumbing itself is the same regardless of which tables get touched.
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
        # Same Neon transaction-pooler fix as data-pipeline's identical
        # engine factory -- see that module's docstring for the full
        # `DuplicatePreparedStatementError` failure mode this avoids.
        connect_args={"statement_cache_size": 0},
        # **2026-08-07 — explicit, conservative pool sizing, added after
        # a real (if not reliably reproducible) 500 chased live while
        # verifying `POST /{id}/run`: unconfigured meant SQLAlchemy's
        # defaults (`pool_size=5`, `max_overflow=10` -- up to 15
        # connections *per engine instance*). `get_engine` is `@lru_
        # cache`'d per *process*, and this service now runs as several
        # independent processes against the same Neon database at once
        # (the FastAPI server, an 8-child-prefork Celery worker each
        # with its own engine post the persistent-event-loop fix above)
        # -- worst case, `9 processes * 15 = 135` possible connections
        # from this service alone, well past what Neon's pooler
        # comfortably serves alongside `data-pipeline`'s own connections
        # to the same database. Small per-process pool + a short
        # `pool_timeout` (fail fast with a real error in seconds, not
        # hang for the default 30s and surface an empty, undebuggable
        # exception the way the live-observed 500 did) + `pool_recycle`
        # (Neon can terminate idle connections server-side; recycling
        # avoids handing out one that looks fine to `pool_pre_ping` but
        # was already dropped moments before).
        pool_size=2,
        max_overflow=3,
        pool_timeout=10,
        pool_recycle=300,
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
    await get_log_engine().dispose()


@lru_cache
def get_log_engine() -> AsyncEngine:
    """Second engine, bound to `Settings.log_db_url` -- the real "logger"
    tables (`meta._ingest_log`, `meta.anomalies`, `meta._feature_
    selection_log`) live here, separate from `get_engine()`'s primary
    database (2026-08-12). Falls back to the same database as `get_
    engine()` when `LOG_DB_URL` is unset (`Settings.log_db_url`'s own
    docstring), so this is always safe to call. Same Neon transaction-
    pooler fix as the primary engine."""
    return create_async_engine(
        get_settings().log_db_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"statement_cache_size": 0},
        pool_size=2,
        max_overflow=3,
        pool_timeout=10,
        pool_recycle=300,
    )


@lru_cache
def get_log_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_log_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_log_session() -> AsyncIterator[AsyncSession]:
    """Same commit/rollback contract as `get_session()`, bound to the
    separate logging database instead."""
    session = get_log_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
