"""Async Postgres session factory — read-only usage (forecast-api never
writes to the warehouse, only reads `raw_marts.*`/`raw.*` that
data-pipeline's dbt project builds)."""

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
        get_settings().database_url, pool_pre_ping=True, future=True
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        await session.close()


async def dispose() -> None:
    await get_engine().dispose()
    await get_log_engine().dispose()


@lru_cache
def get_log_engine() -> AsyncEngine:
    """Second engine, bound to `Settings.log_db_url` -- the real "logger"
    tables this service touches (`meta._training_log` writes,
    `meta.anomalies`/`meta._dbt_build_log` reads) live here, separate
    from `get_engine()`'s primary (read-only) warehouse connection
    (2026-08-12). Falls back to the same database as `get_engine()` when
    `LOG_DB_URL` is unset."""
    return create_async_engine(
        get_settings().log_db_url, pool_pre_ping=True, future=True
    )


@lru_cache
def get_log_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_log_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_log_session() -> AsyncIterator[AsyncSession]:
    session = get_log_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
