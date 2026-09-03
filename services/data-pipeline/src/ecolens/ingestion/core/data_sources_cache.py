"""Redis cache for `GET /v1/data-sources[/{id}]` -- 30s TTL, matching
the endpoint spec's own key convention (`datasources:list:v1:
{query_hash}`, `datasources:one:v1:{id}`).

No-ops (cache miss / silent no-op) whenever Redis can't be reached --
same degrade-don't-500 posture `data_sources_routes.py`'s own
`_circuit_breaker_state()` already uses, applied here rather than
reinvented: a health/listing endpoint must never fail *because its
cache* is unavailable.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ecolens.shared.cache.redis_client import get_redis_client
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

CACHE_TTL_SECONDS = 30
LIST_KEY_PREFIX = "datasources:list:v1"
ONE_KEY_PREFIX = "datasources:one:v1"


def list_cache_key(query: dict[str, Any]) -> str:
    """`{query_hash}` -- a stable hash of the normalized (sorted-key)
    query params, so two equivalent requests (same filters, different
    param order) share one cache entry, and two different filter sets
    never collide.
    """
    normalized = json.dumps(query, sort_keys=True, default=str)
    query_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"{LIST_KEY_PREFIX}:{query_hash}"


def one_cache_key(source_id: str) -> str:
    return f"{ONE_KEY_PREFIX}:{source_id}"


async def get_cached(key: str) -> Any | None:
    try:
        redis = get_redis_client()
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - cache unavailability must never fail the request
        log.debug("data_sources_cache.get_failed", key=key, error=str(exc))
        return None


async def set_cached(key: str, value: Any, *, ttl: int = CACHE_TTL_SECONDS) -> None:
    try:
        redis = get_redis_client()
        await redis.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:  # noqa: BLE001 - cache unavailability must never fail the request
        log.debug("data_sources_cache.set_failed", key=key, error=str(exc))


async def invalidate_list_cache() -> None:
    """Clears every `datasources:list:v1:*` entry -- called after a
    successful `PATCH`, per the endpoint spec's own cache-invalidation
    contract (a stale list must never keep serving a since-changed
    source for up to 30s after an explicit admin edit).
    """
    try:
        redis = get_redis_client()
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor, match=f"{LIST_KEY_PREFIX}:*", count=100
            )
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:  # noqa: BLE001 - cache unavailability must never fail the request
        log.debug("data_sources_cache.invalidate_list_failed", error=str(exc))


async def invalidate_one_cache(source_id: str) -> None:
    try:
        redis = get_redis_client()
        await redis.delete(one_cache_key(source_id))
    except Exception as exc:  # noqa: BLE001 - cache unavailability must never fail the request
        log.debug(
            "data_sources_cache.invalidate_one_failed",
            source=source_id,
            error=str(exc),
        )


__all__ = [
    "CACHE_TTL_SECONDS",
    "list_cache_key",
    "one_cache_key",
    "get_cached",
    "set_cached",
    "invalidate_list_cache",
    "invalidate_one_cache",
]
