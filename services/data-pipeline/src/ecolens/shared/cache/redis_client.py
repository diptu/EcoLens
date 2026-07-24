"""Async Redis client factory.

Thin wrapper mirroring `ecolens.ingestion.storage.mongo`'s
`get_mongo_client()` pattern: a single cached client built from the
global `Settings.redis_dsn`. Used by `ingestion.circuit_breaker` for
breaker state that needs to be shared across concurrent ingestion
workers/cron invocations, not just within one process (see
INGESTION.md's pipeline diagram, step 3).
"""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from ecolens.config import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    return Redis.from_url(str(get_settings().redis_dsn), decode_responses=True)


__all__ = ["get_redis_client"]
