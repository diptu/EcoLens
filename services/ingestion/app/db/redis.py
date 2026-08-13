"""Async Redis client for the ingestion service.

Lazily built from `app.core.config.get_settings().redis_url`. Used for
circuit-breaker state (`get_breaker`, ported `services/ingestion/TODO.md`
Phase 1, "Migrate Ingest Tasks" -- every one of the 5 ingest tasks calls
this directly).
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings
from app.service.pipeline.circuit_breaker import CircuitBreaker


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def close_redis() -> None:
    """Close the Redis client's connection pool (call on service shutdown)."""
    await get_redis().aclose()


@lru_cache
def get_breaker(name: str) -> CircuitBreaker:
    """One `CircuitBreaker` per `name`, shared for the process's lifetime.

    `failure_threshold`/`reset_timeout` come from `Settings`
    (`CIRCUIT_BREAKER_FAILURE_THRESHOLD`/`CIRCUIT_BREAKER_RESET_TIMEOUT`)
    -- applied the same way to every source, not tuned per-source.
    """
    settings = get_settings()
    return CircuitBreaker(
        name,
        get_redis(),
        failure_threshold=settings.circuit_breaker_failure_threshold,
        reset_timeout=settings.circuit_breaker_reset_timeout,
    )
