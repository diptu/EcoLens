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
    """
    entry = SOURCES[key]
    if entry.self_wrapped:
        return await entry.run(**kwargs)

    wrapped = _common.standard_run(
        entry.source,
        entry.table,
        triggered_by=triggered_by,
        bypass_breaker=bypass_breaker,
    )(entry.run)
    return await wrapped(**kwargs)
