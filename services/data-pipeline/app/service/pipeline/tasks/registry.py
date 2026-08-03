"""Registry of ingestion sources — one lookup both `cli.py` (ECO-D47) and
`api/routers/ingest.py` (ECO-D30) share.

Per `task.md`: `ingest_openelectricity.run` is already decorated with
`@standard_run`, so it stages+publishes+logs itself and returns rows
staged (`int`). The other 4 tasks (`ingest_aemo_nem`, `ingest_aemo_wem`,
`ingest_bom`, `ingest_holidays`) are only wrapped with `@timed` — they
return a bare `pandas.DataFrame` and don't stage, publish, or log
anything. `run_source()` applies `_common.standard_run` to those 4 at
call time (same table conventions as `docs/data/ingestion-schema.md`),
so every source has the same "trigger it, get rows staged back" contract
regardless of which task file happens to self-wrap. See `overview.md`
§2 for why "staged" — not "loaded into Postgres" — is what a successful
`run_source()` call actually means now.
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
        self_wrapped=True,
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
    """Run the named ingestion source. Returns rows staged (see module
    docstring) — not yet rows loaded into Postgres `raw.*`.

    `triggered_by` is recorded on the `meta._ingest_log` row (`GET
    /v1/data-sources/{id}/history`'s `trigger` field) — pass `"schedule"`
    for a cron-triggered call, `"manual"` (the default) for
    `POST /v1/data-sources/{id}/run`, `"backfill"` for
    `pipeline.backfill`, etc. Only takes effect for the 4 sources
    `_common.standard_run` wraps at call time — `oe` is already
    decorated with a fixed `triggered_by="manual"` at import time
    (`ingest_openelectricity.py`), so this parameter is silently ignored
    for it. That's a real, if minor, gap: fixing it means restructuring
    how `oe` self-wraps, not just this function.

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
