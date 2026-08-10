"""Background cache pre-warmers (2026-08-11) -- close the real remaining
gap after `GET /v1/emissions/forecast`/`GET /v1/model/drift` gained
Redis caching: a *cached* endpoint is fast for every request except the
one that lands right after the cache entry expires, which still pays
the full real cold-compute cost (confirmed live: ~14s for the NEM
emissions forecast, ~8-10s for drift). For most of this service's newly-
cached endpoints that cold cost is small enough (1-4s) to accept as a
rare, bounded tail -- but these two are large enough that "the unlucky
request every TTL window waits 14s" is a real, user-visible problem on
its own, not just a rounding error against a 200-500ms target.

Two independent loops, not one shared interval, because the two real
costs and TTLs are different orders of magnitude: re-warming drift on
emissions-forecast's own ~45s cadence would burn real compute (~8-10s
every 45s, forever) far more often than its own 5-minute TTL actually
needs. Same "loop forever, log and keep going on a single bad pass"
shape `service/ml/forecast_reconciliation.py`'s `watch_and_reconcile`
already establishes -- one failed warm pass (e.g. a transient DB
hiccup) must never crash the whole service or stop future passes from
trying again.

Deliberately narrow scope: only `region=NEM` (not each of the 6
individual regions) for the emissions forecast, and only the default
`(model_name, regions)` combo (not every architecture) for drift --
these are what the dashboard's own default views actually request on
every page load; warming every possible parameter combination would
turn this into a much bigger, mostly-wasted background compute cost for
combinations a real user may never ask for. A request for a
non-default combination still gets the existing per-endpoint cache
(and, on a cache miss, correctly pays the real cold cost) -- this warmer
doesn't change that, it just keeps the common case fast.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.service.ml.registry import ModelRegistry

log = get_logger(__name__)


async def run_emissions_forecast_warmer(
    redis: Redis,
    db_session_factory: Callable[[], AsyncSession],
    registry: ModelRegistry,
    settings: Settings,
    interval_seconds: float,
) -> None:
    from app.api.v1.emissions.routes import (
        _compute_emissions_forecast,
        emissions_forecast_cache_key,
    )

    while True:
        try:
            bundle = registry.bundle
            if bundle is not None:
                async with db_session_factory() as db:
                    response = await _compute_emissions_forecast(db, bundle, "NEM")
                await redis.set(
                    emissions_forecast_cache_key("NEM", bundle.version),
                    response.model_dump_json(),
                    ex=settings.forecast_cache_ttl_seconds,
                )
        except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
            log.error("cache_warmer.emissions_forecast_failed", error=str(exc))

        await asyncio.sleep(interval_seconds)


async def run_model_drift_warmer(
    redis: Redis,
    settings: Settings,
    interval_seconds: float,
) -> None:
    from app.api.v1.model.routes import _compute_model_drift, model_drift_cache_key

    while True:
        try:
            model_name = settings.mlflow_registry_model_name
            regions = settings.model_default_regions
            response = await _compute_model_drift(model_name, regions)
            await redis.set(
                model_drift_cache_key(model_name, regions),
                response.model_dump_json(),
                ex=settings.model_drift_cache_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
            log.error("cache_warmer.model_drift_failed", error=str(exc))

        await asyncio.sleep(interval_seconds)
