"""Periodic background `dbt build` -- the fix for the raw -> raw_marts
staleness gap: continuous ingestion (`.github/workflows/ingest-*.yml`'s
5-30 minute crons) lands fresh rows in `raw.*` around the clock, but until
this existed, the only two things that ever ran `dbt build` were an
API-triggered backfill (once, after its whole range finishes) and a
manual trigger (dashboard "Run now" / `make dbt-build` / `POST
/v1/dbt/build`) -- nothing kept `raw_marts.*` in sync with regular
ingestion on an ongoing basis.

Same shape as forecast-api's `ModelRegistry.watch()`
(`services/forecast-api/app/service/ml/registry.py`) -- a long-running
loop `main.py`'s lifespan starts as an `asyncio.Task` and cancels on
shutdown, never letting one bad tick kill the loop.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.core.logging import get_logger
from app.service.pipeline.dbt_build import DbtBuildLockTimeout, run_dbt_build_locked

log = get_logger(__name__)


async def watch_and_build(redis: Redis, interval_seconds: float) -> None:
    """Every `interval_seconds`, try one `dbt build` via the same shared,
    locked path the backfill auto-trigger and dashboard manual trigger
    use (`trigger="periodic_watch"` in `meta._dbt_build_log`).

    `max_wait_seconds=0` (fail-fast, same as the dashboard's manual
    trigger) is the key choice here: a periodic watcher must never queue
    up a second multi-minute wait behind an in-flight build from another
    trigger -- by the time that other build finishes, the data is
    already fresh, so this tick's job is already done. A lock-in-progress
    is logged at `info`, not `error` -- it's an expected, benign outcome,
    not a failure.
    """
    while True:
        try:
            await run_dbt_build_locked(
                redis,
                trigger="periodic_watch",
                triggered_by="scheduler",
                max_wait_seconds=0,
            )
        except DbtBuildLockTimeout:
            log.info("dbt_build_watch.skipped_build_in_progress")
        except Exception as exc:
            log.error("dbt_build_watch.tick_failed", error=str(exc))
        await asyncio.sleep(interval_seconds)
