"""Real, measured problem (2026-08-11): `GET /v1/dbt/build/last`/
`/build/runs` had no caching at all and were confirmed live at
~2.3-2.7s per call, *every* call, against this service's remote Postgres
(Neon) -- not per-endpoint compute, just the real network round-trip
cost this service already pays on every fresh query, paid again on every
request with nothing amortizing it. `services/forecast-api` already had
this exact Redis-cache-then-compute shape duplicated inline at several
call sites; `services/ingestion` extracted it once into its own `app.
core.response_cache` -- this is that same module, ported here (this
service had no Redis/caching layer at all before this).

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
