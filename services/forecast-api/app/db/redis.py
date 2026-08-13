"""Async Redis client — forecast hot-path cache (`README.md` § Tech stack:
"Redis 7 -- Forecast hot-path cache")."""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def close_redis() -> None:
    await get_redis().aclose()
