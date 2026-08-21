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
import time
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
        started = time.monotonic()
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

        # Real fix (2026-08-12): sleeping the full `interval_seconds`
        # *after* this pass's own real compute (confirmed live: ~11-14s)
        # made the real refresh cadence ~(compute + interval_seconds), not
        # `interval_seconds` -- ~56-59s against this cache's 60s TTL, an
        # honest margin of only 1-4s. Any real slowdown (concurrent load,
        # DB contention) could push a cycle past the TTL, letting the
        # cache actually go cold between warms -- confirmed live to
        # actually happen, not just a theoretical race. Subtracting this
        # pass's own real elapsed time keeps the cadence anchored to wall
        # clock `interval_seconds` regardless of how long the compute
        # took, restoring the real margin against the TTL. Floored at 0 so
        # a compute pass that itself runs longer than `interval_seconds`
        # still starts the next pass immediately rather than sleeping a
        # negative duration.
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(0.0, interval_seconds - elapsed))


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


async def run_recent_backtest_warmer(
    redis: Redis,
    db_session_factory: Callable[[], AsyncSession],
    registry: ModelRegistry,
    settings: Settings,
    interval_seconds: float,
) -> None:
    """Keeps `region="NEM", days=30` -- "Emission History"'s full
    30-day real forecast confidence band (`services/dashboard`'s
    executive page) -- warm. Its own dedicated loop, not folded into
    `run_dashboard_essentials_warmer` below: confirmed live 2026-08-11
    at ~158s to compute, an order of magnitude past that warmer's
    "cheap" (1-4s) scope -- same reasoning `run_emissions_forecast_
    warmer`/`run_model_drift_warmer` above already establish for their
    own large/slow endpoints.

    No separate `_compute_*` extraction needed unlike those two,
    though: `get_recent_actual_vs_predicted` has no real request-only
    side effects (no breaker check, no served-forecast reconciliation
    logging) this warmer would need to skip, so it calls the route
    function directly -- same "delete the real cache key, then call the
    real route function" technique `run_dashboard_essentials_warmer`
    already uses for its own (cheaper) endpoints below.
    """
    from app.api.v1.forecast.routes import (
        get_recent_actual_vs_predicted,
        recent_backtest_cache_key,
    )

    while True:
        try:
            bundle = registry.bundle
            if bundle is not None:
                async with db_session_factory() as db:
                    await redis.delete(
                        recent_backtest_cache_key(
                            "NEM", 30, bundle.version, settings.mlflow_registry_model_name
                        )
                    )
                    await get_recent_actual_vs_predicted(
                        region="NEM",
                        days=30,
                        db=db,
                        redis=redis,
                        registry=registry,
                        settings=settings,
                    )
        except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
            log.error("cache_warmer.recent_backtest_failed", error=str(exc))

        await asyncio.sleep(interval_seconds)


# The remaining cached endpoints below are all single, cheap queries
# (1-4s cold, not the 8-14s of the two loops above) whose real fix is
# already "cached at all" -- the occasional request that lands right
# after a TTL expiry is a small, bounded tail for these, not the
# `emissions_forecast`/`model_drift` scale of problem. Warmed anyway
# (2026-08-11, "make every real endpoint reliably fast" pass) via one
# shared loop rather than one `asyncio.create_task` per endpoint --
# same real cost either way, less background-task bookkeeping.
#
# Technique: delete the real cache key, then call the real route
# function directly (not a re-derived compute copy) with real
# dependency values passed explicitly. FastAPI route functions are
# plain async functions underneath the `@router.get` decorator --
# calling one directly outside a real request works as long as every
# `Depends(...)`-defaulted parameter is passed explicitly (an
# unresolved `Depends` object would otherwise flow in as the literal
# "value"). This reuses the exact same cache-key-construction and
# compute logic a real request hits, so it can never silently drift
# from what `emissions_forecast`/`model_drift` needed a dedicated
# `_compute_*` extraction for instead: those two are re-derived because
# their route functions carry other real request-only side effects
# (breaker checks, served-forecast reconciliation logging, tracing
# spans) this warmer shouldn't trigger; the endpoints below have none.
async def run_dashboard_essentials_warmer(
    redis: Redis,
    db_session_factory: Callable[[], AsyncSession],
    registry: ModelRegistry,
    settings: Settings,
    interval_seconds: float,
) -> None:
    from datetime import UTC, datetime

    from app.api.v1.demand.routes import get_demand_summary
    from app.api.v1.emissions.routes import (
        get_emissions_current,
        get_emissions_timeseries,
        get_emissions_ytd,
    )
    from app.api.v1.generation_mix.routes import get_generation_mix
    from app.api.v1.model.routes import get_training_runs

    while True:
        now = datetime.now(UTC)

        # Real bug, found live 2026-08-13 while restarting a hung
        # forecast-api process: `redis.delete(...)` below used to be the
        # first element of a `(redis.delete(...), fn(...))[1]` tuple --
        # building that tuple *creates* the delete's coroutine but the
        # `[1]` index discards it without ever awaiting it (confirmed
        # live: 6 real `RuntimeWarning: coroutine 'Redis.execute_command'
        # was never awaited` on every single pass). The real cache key
        # was therefore never force-invalidated -- each endpoint call
        # below just kept hitting its own still-live cached value, so
        # this warmer silently stopped actually refreshing anything the
        # moment it was written, only ever "warming" whatever the first
        # natural cache miss had already populated. `_warm` now takes
        # the real cache key and awaits the delete itself, in order,
        # before calling `fn`.
        async def _warm(label: str, cache_key: str, fn) -> None:
            try:
                await redis.delete(cache_key)
                async with db_session_factory() as db:
                    await fn(db)
            except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
                log.error("cache_warmer.dashboard_essential_failed", target=label, error=str(exc))

        await _warm(
            "emissions_current",
            "emissions:current:v1",
            lambda db: get_emissions_current(db=db, redis=redis, settings=settings),
        )
        await _warm(
            "emissions_ytd",
            f"emissions:ytd:v1:{now.year}",
            lambda db: get_emissions_ytd(db=db, redis=redis, settings=settings),
        )
        # `bucket="hour", days=7, region=None` -- the Emissions Trend
        # chart's own default real call (`RealEmissionsTrend`,
        # services/dashboard).
        await _warm(
            "emissions_timeseries",
            f"emissions:timeseries:v1:hour:7:None:{now.strftime('%Y%m%d%H')}",
            lambda db: get_emissions_timeseries(
                bucket="hour", days=7, region=None, db=db, redis=redis, settings=settings
            ),
        )
        await _warm(
            "demand_summary",
            f"demand:summary:v1:ytd:{now.year}",
            lambda db: get_demand_summary(since=None, until=None, db=db, redis=redis, settings=settings),
        )
        await _warm(
            "generation_mix",
            f"generation-mix:v1:None:ytd:{now.year}",
            lambda db: get_generation_mix(
                region=None, since=None, until=None, db=db, redis=redis, settings=settings
            ),
        )
        await _warm(
            "training_runs",
            "model:training_runs:v1:20",
            lambda db: get_training_runs(limit=20, db=db, redis=redis, settings=settings),
        )

        # `region="NEM"` -- the Demand Forecast Preview's own default
        # real call (`fetchDemandForecast("NEM")`, services/dashboard).
        # Separate from the DB-session-per-call pattern above since
        # `get_forecast` also needs the model registry, not just `db`.
        try:
            bundle = registry.bundle
            if bundle is not None:
                async with db_session_factory() as db:
                    from app.api.v1.forecast.routes import forecast_local_cache, get_forecast

                    forecast_key = (
                        f"forecast:v1:{settings.mlflow_registry_model_name}:NEM:{bundle.version}"
                    )
                    await redis.delete(forecast_key)
                    # Also invalidate the L1 process-local cache
                    # (`app.core.local_cache`) `get_forecast` checks
                    # *before* Redis -- an unexpired local entry would
                    # otherwise short-circuit this forced refresh and
                    # hand back the exact stale response this warmer
                    # exists to replace.
                    forecast_local_cache.delete(forecast_key)
                    await get_forecast(
                        region="NEM",
                        horizon=None,
                        interval=None,
                        db=db,
                        redis=redis,
                        registry=registry,
                        settings=settings,
                    )
        except Exception as exc:  # noqa: BLE001 - one bad pass must not stop future ones
            log.error("cache_warmer.dashboard_essential_failed", target="forecast_nem", error=str(exc))

        await asyncio.sleep(interval_seconds)
