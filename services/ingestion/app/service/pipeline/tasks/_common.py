"""Shared ingest-task plumbing.

Every ingester needs:
  * a run id (UUID) — written to `meta._ingest_log`
  * a circuit-breaker-wrapped fetch
  * a `stage in DuckDB → publish a RabbitMQ event → log outcome` round-trip
  * structlog fields for source, run id, row count

This module centralises the boilerplate so each task is 30-60 lines of
"how do I actually fetch from this source?" code. Ported from
data-pipeline's identical module (`services/ingestion/TODO.md` Phase 1,
"Port Resiliency & Anomaly Logic") now that its three dependencies exist
here: `pipeline.anomaly`, `pipeline.duckdb_staging`, `db.rabbitmq.
publish_landed_event`.

The actual Postgres `raw.*` load never happens here, in either service
(`overview.md` §2 Event-Driven Warehousing) — `standard_run` only takes
a run as far as "staged and the warehouse has been notified". Unlike
data-pipeline's copy, this module deliberately does **not** port
`log_run_synced`/`log_run_sync_failed` — those close out a `"staged"`
run once `pipeline.warehouse_sync`'s RabbitMQ consumer has actually
synced the staged data into Postgres, and that consumer stays in
`data-pipeline` (this service never consumes, only publishes — see
`docs/data/ingestion.md`'s service-boundary note). A `"staged"` run this
service starts is closed out to `"success"`/`"sync_failed"` by whichever
service still runs that consumer, not by this one.
"""

from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

import pandas as pd
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger, set_run_id
from app.core.metrics import (
    circuit_breaker_state as circuit_breaker_state_gauge,
)
from app.core.metrics import (
    ingest_duration_seconds,
    ingest_failures_total,
    ingest_rows_total,
    ingest_runs_total,
    latest_ingest_ts,
)
from app.db.rabbitmq import publish_landed_event
from app.db.redis import get_breaker
from app.db.session import get_session
from app.service.pipeline.anomaly import detect_anomalies, record_anomalies
from app.service.pipeline.duckdb_staging import stage_dataframe, upload_staged_file

P = ParamSpec("P")
T = TypeVar("T")

log = get_logger(__name__)

_CIRCUIT_STATE_VALUE = {"closed": 0, "half_open": 1, "open": 2}


async def _read_breaker_state(source: str, breaker: Any) -> str:
    """`breaker.state` (a `CircuitState`), also pushed to the
    `ecolens_circuit_breaker_state` gauge (`core/metrics.py`) so
    Grafana has something real to plot — same read, no extra Redis
    round-trip. Returns the plain string value `meta._ingest_log.
    circuit_breaker_state` expects.
    """
    state = await breaker.state
    circuit_breaker_state_gauge.labels(source=source).set(
        _CIRCUIT_STATE_VALUE.get(state.value, -1)
    )
    return state.value


async def _log_run_start(
    source: str,
    triggered_by: str,
    window_start: str | None,
    window_end: str | None,
) -> uuid.UUID:
    """Insert a 'running' row into meta._ingest_log. Returns the run id."""
    run_id = uuid.uuid4()
    async with get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO meta._ingest_log
                    (id, source, started_at, status, triggered_by, window_start, window_end, hostname)
                VALUES
                    (:id, :source, now(), 'running', :triggered_by, :window_start, :window_end, :hostname)
                """
            ),
            {
                "id": str(run_id),
                "source": source,
                "triggered_by": triggered_by,
                "window_start": window_start,
                "window_end": window_end,
                "hostname": get_settings().hostname,
            },
        )
    set_run_id(str(run_id))
    log.info(
        "ingest.run_started",
        source=source,
        run_id=str(run_id),
        triggered_by=triggered_by,
    )
    return run_id


async def _log_run_finish(
    run_id: uuid.UUID,
    *,
    status: str,
    rows_landed: int = 0,
    rows_loaded: int = 0,
    error_message: str | None = None,
    circuit_state: str | None = None,
) -> None:
    """Update the run row after the ingest/staging half completes.

    `status="staged"` is deliberately *not* terminal — `finished_at`
    stays NULL (same "still in flight" convention `status="running"`
    already uses) because the run isn't actually done: whichever service
    still runs `pipeline.warehouse_sync`'s consumer closes it out once
    the staged data is safely in Postgres `raw.*`. Any other status
    (`"failed"`, from the fetch or staging step itself blowing up) is
    terminal and gets a real `finished_at`.
    """
    async with get_session() as session:
        await session.execute(
            text(
                """
                UPDATE meta._ingest_log
                SET finished_at = CASE WHEN :status = 'staged' THEN finished_at ELSE now() END,
                    status = :status,
                    rows_landed = :rows_landed,
                    rows_loaded = :rows_loaded,
                    error_message = :error_message,
                    circuit_breaker_state = :circuit_state
                WHERE id = :id
                """
            ),
            {
                "id": str(run_id),
                "status": status,
                "rows_landed": rows_landed,
                "rows_loaded": rows_loaded,
                "error_message": error_message,
                "circuit_state": circuit_state,
            },
        )


def timed(
    source: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator: time the wrapped coroutine, push to the ingest_duration histogram."""

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with ingest_duration_seconds.labels(source=source).time():
                return await fn(*args, **kwargs)

        return wrapper

    return decorator


def standard_run(
    source: str,
    table: str,
    triggered_by: str = "manual",
    window_start: str | None = None,
    window_end: str | None = None,
    bypass_breaker: bool = False,
) -> Callable[[Callable[P, Awaitable[pd.DataFrame]]], Callable[P, Awaitable[int]]]:
    """Decorator factory: standardise the run-start / fetch / anomaly-scan /
    stage+publish / finish lifecycle.

    Usage:
        @standard_run("openelectricity", "openelectricity_mix")
        async def fetch_openelectricity(lookback_minutes: int) -> pd.DataFrame: ...

    The wrapped function returns a `pandas.DataFrame`; the decorator
    handles anomaly scoring (flag, don't drop — `pipeline.anomaly`),
    staging it in DuckDB, publishing a RabbitMQ event, logging, and
    metrics. The row count returned here is *staged*, not yet loaded
    into Postgres `raw.*` — that happens asynchronously once whichever
    service still runs `pipeline.warehouse_sync`'s consumer picks up the
    event (`overview.md` §2). An empty fetch is the one case that's
    immediately terminal (`status="success"`, nothing to stage or sync).

    `bypass_breaker=True` calls `fetch_fn` directly instead of through
    `breaker.call(...)` — `POST /v1/data-sources/{id}/run`'s `force: true`
    needs this to actually mean something: a call still routed through a
    tripped-open breaker would just raise `CircuitOpenError` immediately
    regardless of `force`. A bypassed fetch's outcome still isn't
    recorded as a breaker success/failure either way — matches `breaker.
    call`'s existing "only successes and failures through the breaker
    affect its state" contract.
    """

    def decorator(
        fetch_fn: Callable[P, Awaitable[pd.DataFrame]],
    ) -> Callable[P, Awaitable[int]]:
        @functools.wraps(fetch_fn)
        @timed(source)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> int:
            run_id = await _log_run_start(
                source, triggered_by, window_start, window_end
            )
            breaker = get_breaker(source)
            try:
                if bypass_breaker:
                    df = await fetch_fn(*args, **kwargs)
                else:
                    df = await breaker.call(fetch_fn, *args, **kwargs)

                anomalies = detect_anomalies(df, source)
                if not anomalies.empty:
                    await record_anomalies(run_id, source, table, anomalies)
                    log.warning(
                        "ingest.anomalies_flagged",
                        source=source,
                        run_id=str(run_id),
                        count=len(anomalies),
                    )

                duckdb_path, rows_staged = stage_dataframe(df, table, str(run_id))

                if rows_staged == 0:
                    # Nothing fetched -> nothing to stage or sync. This is
                    # the one case that's immediately terminal, same as
                    # data-pipeline's own no-op-empty-fetch handling.
                    await _log_run_finish(
                        run_id,
                        status="success",
                        rows_landed=0,
                        rows_loaded=0,
                        circuit_state=await _read_breaker_state(source, breaker),
                    )
                    ingest_runs_total.labels(source=source, outcome="success").inc()
                    log.info(
                        "ingest.run_succeeded",
                        source=source,
                        run_id=str(run_id),
                        rows=0,
                    )
                    return 0

                # Uploads the same local file `stage_dataframe` just wrote
                # to object storage (`services/ingestion/TODO.md` Phase 2,
                # "Integrate Cloudflare R2 Staging") -- `duckdb_path` stays
                # in the payload too (Phase 2's "Bridge Legacy Handoffs":
                # whichever service still runs `pipeline.warehouse_sync`'s
                # consumer reads the shared-volume local path unmodified
                # during the transition), `object_storage_key`/`_bucket`
                # are the forward path for once that consumer is updated
                # to read object storage instead.
                object_storage_key = await upload_staged_file(
                    duckdb_path, table, str(run_id)
                )
                # Phase 4's "Execute Shadow Runs": `triggered_by="shadow"`
                # publishes to the shadow queue instead of the real one,
                # so a shadow run does everything else for real (fetch,
                # anomaly-scan, stage, `meta._ingest_log` row) but never
                # reaches the real consumer -- no double-load of `raw.*`
                # from two independent fetches of the same window.
                landing_queue = (
                    get_settings().rabbitmq_landing_queue_shadow
                    if triggered_by == "shadow"
                    else None
                )
                await publish_landed_event(
                    {
                        "run_id": str(run_id),
                        "source": source,
                        "table": table,
                        "schema": "raw",
                        "duckdb_path": duckdb_path,
                        "object_storage_key": object_storage_key,
                        "object_storage_bucket": get_settings().object_storage_bucket,
                        "rows": rows_staged,
                    },
                    queue_name=landing_queue,
                )
                await _log_run_finish(
                    run_id,
                    status="staged",
                    rows_landed=rows_staged,
                    circuit_state=await _read_breaker_state(source, breaker),
                )
                ingest_rows_total.labels(source=source).inc(rows_staged)
                ingest_runs_total.labels(source=source, outcome="success").inc()
                latest_ingest_ts.labels(source=source).set(time.time())
                log.info(
                    "ingest.run_staged",
                    source=source,
                    run_id=str(run_id),
                    rows=rows_staged,
                    duckdb_path=duckdb_path,
                )
                return rows_staged
            except Exception as e:
                ingest_failures_total.labels(source=source).inc()
                ingest_runs_total.labels(source=source, outcome="failure").inc()
                await _log_run_finish(
                    run_id,
                    status="failed",
                    error_message=str(e)[:500],
                    circuit_state=await _read_breaker_state(source, breaker),
                )
                log.error(
                    "ingest.run_failed",
                    source=source,
                    run_id=str(run_id),
                    error=str(e),
                )
                raise

        return wrapper

    return decorator


# ── Sync helper for sources that don't speak async ─────────────────────
def run_sync(loop: Any, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a sync function in the current event loop.

    Use sparingly — prefer async fetch clients. Provided for SDKs that
    only have a blocking variant.
    """
    return loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
