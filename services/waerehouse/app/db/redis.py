"""Async Redis client for the warehouse service (new 2026-08-11).

Lazily built from `app.core.config.get_settings().redis_url` -- same
shared local Redis instance `services/ingestion`/`services/forecast-api`
already use, added here solely to back `app.core.response_cache`'s real
response caching (this service had no caching layer at all before this;
its own dbt-build lock lives in Postgres, not Redis -- see `app.dbt.
scheduler`'s module docstring).
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def close_redis() -> None:
    """Close the Redis client's connection pool (call on service shutdown)."""
    await get_redis().aclose()
