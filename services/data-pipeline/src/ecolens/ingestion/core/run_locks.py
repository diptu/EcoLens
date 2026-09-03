"""Redis-backed coordination for `POST /v1/data-sources/{id}/run` and
`.../backfill`: "is a run/backfill already in progress for this
source" locks, and the `Idempotency-Key` response cache both endpoints
use.

Deliberately Redis (unlike `data_source_overrides.py`'s JSON file):
this state is short-lived and self-healing by design (a lock that
outlives its TTL because a background task crashed without releasing
it should expire on its own, not require manual cleanup) -- the
opposite of an admin's `enabled=false` decision, which must survive
indefinitely and a Redis restart.

Every function degrades to "allow"/"miss" (never raises, never
permanently blocks) when Redis is unreachable -- same posture
`data_sources_cache.py` already established: a coordination/cache
system being down must never itself prevent triggering a fetch, it
just means the "already running"/idempotency checks are best-effort
for the duration of the outage. Real data-level safety still holds
regardless (every DuckDB write upserts on each source's own unique
key, so even a genuinely-duplicated concurrent run can't corrupt
anything, only waste a little work).
"""

from __future__ import annotations

import json
from typing import Any

from ecolens.shared.cache.redis_client import get_redis_client
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

# Generous vs. a realistic single-source fetch duration (seconds/low
# minutes) -- long enough that a real in-flight run is reliably still
# holding the lock, short enough that a crashed background task
# (raised before reaching the `finally`-style release) doesn't block
# that source indefinitely.
RUN_LOCK_TTL_SECONDS = 600
# A backfill can legitimately run far longer (multi-day ranges,
# multiple chunks) -- same reasoning, wider window.
BACKFILL_LOCK_TTL_SECONDS = 6 * 3600
# Per the endpoint spec's own "TTL: 1 hour."
IDEMPOTENCY_TTL_SECONDS = 3600


def _run_lock_key(source_id: str) -> str:
    return f"data_sources:run_lock:{source_id}"


def _backfill_lock_key(source_id: str) -> str:
    return f"data_sources:backfill_lock:{source_id}"


def _idempotency_key(key: str) -> str:
    return f"data_sources:idempotency:{key}"


async def _try_acquire(key: str, ttl: int) -> bool:
    try:
        redis = get_redis_client()
        acquired = await redis.set(key, "1", nx=True, ex=ttl)
        return bool(acquired)
    except Exception as exc:  # noqa: BLE001 - Redis unavailability must never block triggering a fetch
        log.warning("run_locks.acquire_failed", key=key, error=str(exc))
        return True


async def _release(key: str) -> None:
    try:
        redis = get_redis_client()
        await redis.delete(key)
    except Exception as exc:  # noqa: BLE001 - best-effort; the lock's own TTL is the real safety net
        log.warning("run_locks.release_failed", key=key, error=str(exc))


async def acquire_run_lock(source_id: str) -> bool:
    return await _try_acquire(_run_lock_key(source_id), RUN_LOCK_TTL_SECONDS)


async def release_run_lock(source_id: str) -> None:
    await _release(_run_lock_key(source_id))


async def acquire_backfill_lock(source_id: str) -> bool:
    return await _try_acquire(_backfill_lock_key(source_id), BACKFILL_LOCK_TTL_SECONDS)


async def release_backfill_lock(source_id: str) -> None:
    await _release(_backfill_lock_key(source_id))


async def get_idempotent_response(key: str) -> Any | None:
    try:
        redis = get_redis_client()
        raw = await redis.get(_idempotency_key(key))
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - a miss (re-triggering) is always safe, just not free
        log.warning("run_locks.idempotency_get_failed", key=key, error=str(exc))
        return None


async def store_idempotent_response(key: str, response: Any) -> None:
    try:
        redis = get_redis_client()
        await redis.set(
            _idempotency_key(key),
            json.dumps(response, default=str),
            ex=IDEMPOTENCY_TTL_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort; a missed store just means the next identical call re-triggers
        log.warning("run_locks.idempotency_store_failed", key=key, error=str(exc))


__all__ = [
    "RUN_LOCK_TTL_SECONDS",
    "BACKFILL_LOCK_TTL_SECONDS",
    "IDEMPOTENCY_TTL_SECONDS",
    "acquire_run_lock",
    "release_run_lock",
    "acquire_backfill_lock",
    "release_backfill_lock",
    "get_idempotent_response",
    "store_idempotent_response",
]
