"""Registry of ingestion sources — one lookup both `cli.py` (ECO-D47) and
`api/routers/ingest.py` (ECO-D30) share.

All 5 tasks (`ingest_openelectricity`, `ingest_aemo_nem`,
`ingest_aemo_wem`, `ingest_bom`, `ingest_holidays`) are only wrapped with
`@timed` — none self-wrap with `@standard_run` (as of 2026-08-05; `oe`
used to, see below) — they return a bare `pandas.DataFrame` and don't
stage, publish, or log anything on their own. `run_source()` applies
`_common.standard_run` to all 5 at call time (same table conventions as
`docs/data/ingestion-schema.md`), so every source has the same "trigger
it, get rows staged back" contract, and `triggered_by` (`"manual"`/
`"schedule"`/`"backfill"`) genuinely reaches `meta._ingest_log` for all
of them. See `overview.md` §2 for why "staged" — not "loaded into
Postgres" — is what a successful `run_source()` call actually means now.

`self_wrapped` still exists below for `oe` to flip back to `True` if a
future source genuinely needs its own bespoke lifecycle (a real reason
this flag exists, not a soon-to-be-dead one) -- but `oe` itself no
longer needs it: it used to self-wrap with `@standard_run` applied *at
import time*, which baked in a fixed `triggered_by="manual"` no caller
could override -- `run_source`'s own `triggered_by` argument was
silently ignored for `oe` specifically, mislabeling every real OE
backfill's `meta._ingest_log` rows as `trigger='manual'` instead of
`'backfill'` (confirmed live: the dashboard's `pollBackfillSummary`
filters on `trigger === "backfill"`, so a real, successfully-running OE
backfill showed zero progress there). Un-self-wrapping it — `oe`'s own
`run()` is now a plain fetch function, same shape as the other 4 — closes
that gap for good.
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
        # Was True -- un-self-wrapped 2026-08-05 (see this module's own
        # docstring for why: the fixed-at-import-time triggered_by="manual"
        # it used to bake in silently broke backfill labeling for `oe`).
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
    """Run the named ingestion source. Returns rows staged (see module
    docstring) — not yet rows loaded into Postgres `raw.*`.

    `triggered_by` is recorded on the `meta._ingest_log` row (`GET
    /v1/data-sources/{id}/history`'s `trigger` field) — pass `"schedule"`
    for a cron-triggered call, `"manual"` (the default) for
    `POST /v1/data-sources/{id}/run`, `"backfill"` for
    `pipeline.backfill`, etc. Takes effect for all 5 sources — `oe`
    used to be self-wrapped with a fixed `triggered_by="manual"` baked
    in at import time, silently ignoring whatever this function was
    passed, but was un-self-wrapped 2026-08-05 (see `SOURCES["oe"]`'s
    own comment) specifically to close that gap: OE backfills were
    landing real `meta._ingest_log` rows the whole time, just mislabeled
    `trigger='manual'` instead of `'backfill'`, so the dashboard's
    trigger-filtered backfill-progress view showed nothing for a backfill
    that was genuinely running.

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
