"""Real, measured problem (2026-08-11): several `GET` endpoints in this
service had no caching at all and were confirmed live at 2-4s per call,
*every* call, against this service's remote Postgres (Neon) -- not a
per-endpoint compute cost, just the real network round-trip cost this
service already pays on every fresh query, paid again on every request
with nothing amortizing it. `forecast-api` already had this exact
Redis-cache-then-compute shape duplicated inline at three call sites
(`GET /v1/forecast`, `GET /v1/emissions/forecast`, `GET /v1/emissions/
current`) -- this module is that same shape, extracted once, for this
service's own several new call sites rather than re-duplicating it
each time.

Callers own their own cache-key construction (including every query
param that affects the result) and their own TTL choice -- this module
only owns the real get-or-compute-and-set mechanics, not policy.
"""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis

ModelT = TypeVar("ModelT", bound=BaseModel)


async def cached_response(
    redis: Redis,
    cache_key: str,
    ttl_seconds: int,
    model_cls: type[ModelT],
    compute: Callable[[], Awaitable[ModelT]],
) -> ModelT:
    """Real cache-or-compute: a Redis hit returns the real previously-
    computed response (deserialized via `model_cls.model_validate_json`,
    same real data, not a placeholder); a miss calls `compute()` for the
    real value, stores it, and returns it. Never masks a real compute
    failure -- an exception from `compute()` propagates normally, same
    as an uncached call would."""
    cached = await redis.get(cache_key)
    if cached is not None:
        return model_cls.model_validate_json(cached)
    result = await compute()
    await redis.set(cache_key, result.model_dump_json(), ex=ttl_seconds)
    return result
