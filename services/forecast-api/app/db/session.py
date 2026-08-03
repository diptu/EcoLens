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
