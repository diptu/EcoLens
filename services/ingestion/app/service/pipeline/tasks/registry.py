"""Registry of ingestion sources — one lookup both the CLI and API will
share, once they exist (`services/ingestion/TODO.md` Phase 1's "Expose
CLI & API Routers" item).

`SOURCES`/`IngestSource` are ported (Phase 1, "Migrate Ingest Tasks") --
the 5 tasks are catalogued and directly callable (`SOURCES[key].
run(**kwargs)`), matching data-pipeline's identical catalog verbatim.

`run_source()` is ported now too ("Port Resiliency & Anomaly Logic") --
`_common.standard_run`'s three dependencies (`pipeline.anomaly`,
`pipeline.duckdb_staging`, `db.rabbitmq.publish_landed_event`) all exist
in this service now. Same shape as data-pipeline's, `triggered_by`/
`bypass_breaker` passthrough included, not a redesign.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.service.pipeline.tasks import (
    _common,
    ingest_aemo_nem,
    ingest_aemo_wem,
    ingest_bom,
    ingest_holidays,
    ingest_openelectricity,
)


@dataclass(frozen=True)
class IngestSource:
    source: str
    table: str
    run: Callable[..., Awaitable[Any]]
    self_wrapped: bool  # True if `run` already applies @standard_run itself


SOURCES: dict[str, IngestSource] = {
    "oe": IngestSource(
        source="openelectricity",
        table="openelectricity_mix",
        run=ingest_openelectricity.run,
        self_wrapped=False,
    ),
    "aemo-nem": IngestSource(
        source="aemo_nem",
        table="aemo_nem_dispatch",
        run=ingest_aemo_nem.run,
        self_wrapped=False,
    ),
    "aemo-wem": IngestSource(
        source="aemo_wem",
        table="aemo_wem_dispatch",
        run=ingest_aemo_wem.run,
        self_wrapped=False,
    ),
    "bom": IngestSource(
        source="bom",
        table="bom_observations",
        run=ingest_bom.run,
        self_wrapped=False,
    ),
    "holidays": IngestSource(
        source="aemo_holidays",
        table="aemo_holidays",
        run=ingest_holidays.run,
        self_wrapped=False,
    ),
}


async def run_source(
    key: str,
    *,
    triggered_by: str = "manual",
    bypass_breaker: bool = False,
    duckdb_only: bool = False,
    **kwargs: Any,
) -> int:
    """Run the named ingestion source. Returns rows staged (see
    `_common.standard_run`'s docstring) — not yet rows loaded into
    Postgres `raw.*`.

    `triggered_by` is recorded on the `meta._ingest_log` row -- pass
    `"schedule"` for a cron-triggered call, `"manual"` (the default) for
    an API-triggered run, `"backfill"` for `pipeline.backfill`, etc.

    Raises `KeyError` for an unknown `key` — callers (CLI, API router)
    turn that into their own "invalid source" response.

    `kwargs["start"]`/`["end"]` (present for `pipeline.backfill`'s
    date-range sources) get forwarded to `standard_run` as `window_start`/
    `window_end` too, not just on to `entry.run` -- these used to only
    reach `entry.run`, leaving `meta._ingest_log.window_start`/`_end`
    permanently `NULL` for every run ever, backfill included. Real,
    observed consequence: `pipeline.backfill.already_succeeded` checks
    `started_at::date = day` as its only fallback, which only ever
    coincidentally matches when a historical `day` happens to equal the
    real wall-clock date the backfill itself ran on -- for a true
    historical day it never matches, so every backfill re-fetched and
    re-staged its *entire* range from day 1 on every single run,
    silently, "success"/"skipped" output notwithstanding. Confirmed live
    2026-08-06: resuming a crashed 370-day `oe` backfill re-fetched day 1
    instead of picking up from day 92.
    """
    entry = SOURCES[key]
    if entry.self_wrapped:
        return await entry.run(**kwargs)

    start = kwargs.get("start")
    end = kwargs.get("end")
    window_start = start.isoformat() if isinstance(start, datetime) else None
    window_end = end.isoformat() if isinstance(end, datetime) else None

    wrapped = _common.standard_run(
        entry.source,
        entry.table,
        triggered_by=triggered_by,
        bypass_breaker=bypass_breaker,
        window_start=window_start,
        window_end=window_end,
        duckdb_only=duckdb_only,
    )(entry.run)
    return await wrapped(**kwargs)
