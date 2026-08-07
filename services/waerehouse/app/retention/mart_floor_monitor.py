"""Mart-history regression monitor (`TODO.md` Phase 1's deferred
follow-up: "a dbt/CLI check that asserts mart min(ts) never moves
forward between scheduled runs in production").

Phase 1 fixed the actual bug (marts converted from `table` to
`incremental` so a `dbt run` after a `raw.*` prune no longer rebuilds
them down to the pruned window) and live-verified the mechanism against
a disposable Postgres container. This module is the production-facing
half: something that actually watches the real NeonDB over time and
would catch a *regression* of that fix (e.g. someone reverting a mart
back to `+materialized: table` later) instead of relying on nobody ever
doing that.

**Design note — why this doesn't lean on Prometheus for the "previous
value" comparison** (a Gauge + `delta(...) > 0` alert rule was the
original plan): a Prometheus gauge only reflects reality in whichever
process actually sets it *and* gets scraped. `check_mart_floors` is
meant to run from `.github/workflows/warehouse-monitor.yml`'s scheduled
job — a fresh, short-lived GitHub Actions runner every time, never the
actual deployed (and Prometheus-scraped) `warehouse` service — so a
gauge set there would vanish with the process and never reach
Prometheus at all. `meta.mart_floor_checks` (migration `0003`) is the
fix: the one thing a CI job and the real deployed service always share
is the same production database, so the "previous value" lives there
instead. `core.metrics.mart_min_ts_seconds` is still set as a side
effect purely for `/metrics` visibility on whichever process happens to
run this (e.g. an operator running it against a live deployment) — it
is not what drives alerting; `check_mart_floors`' own `regressed` flag
(surfaced as a nonzero CLI exit code, same shape `check-size` already
uses) is.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.metrics import mart_min_ts_seconds
from app.db.session import get_session

log = get_logger(__name__)

# mart name -> the column holding its earliest-row timestamp. The 2
# row-grain marts key on `ts`, the 2 hour-grain marts on `hour` (fct_
# carbon_intensity.sql/fct_generation_mix.sql's own `date_trunc('hour',
# ts)` column) -- same 4 marts Phase 1 converted to incremental, since
# those are the only ones whose history a `table` rebuild could ever
# have silently dropped (dim_energy_mix/dim_facility are small reference
# sets, not time series, deliberately excluded here too).
_MART_TS_COLUMNS = {
    "fct_energy_demand": "ts",
    "fct_emissions_5min": "ts",
    "fct_carbon_intensity": "hour",
    "fct_generation_mix": "hour",
}


@dataclass(frozen=True)
class MartFloor:
    mart: str
    min_ts: str | None  # ISO-formatted, None when the mart is empty
    regressed: bool  # True iff min_ts moved forward since the last check


async def check_mart_floors() -> list[MartFloor]:
    """For each of the 4 time-series marts: queries the current
    `min(<ts column>)`, compares it against `meta.mart_floor_checks`'
    row for that mart (the last time this was checked, from *any*
    invocation — CLI or otherwise), flags `regressed=True` if the floor
    moved forward, then upserts the new value as this run's baseline for
    next time. Also pushes the raw value to `mart_min_ts_seconds` (see
    module docstring for why that's visibility-only, not the alert
    mechanism).

    An empty mart (no rows yet, e.g. right after a fresh deploy before
    the first `dbt run` has any `raw.*` data to build from) reports
    `min_ts=None`, `regressed=False` (nothing to compare), and neither
    sets the gauge nor writes a baseline row for that mart — an honest
    "nothing to measure yet", not a false regression against a
    since-populated table on the next real check.

    A mart with no prior `meta.mart_floor_checks` row (first-ever check)
    always reports `regressed=False` — there is nothing yet to have
    regressed *from*.
    """
    reports = []
    async with get_session() as session:
        for mart, column in _MART_TS_COLUMNS.items():
            result = await session.execute(
                # nosec B608 -- `_MART_TS_COLUMNS` is a fixed module-level
                # mapping, not user input
                text(f"SELECT min({column}) FROM raw_marts.{mart}")  # nosec B608
            )
            row = result.first()
            min_ts = row[0] if row else None

            if min_ts is None:
                reports.append(MartFloor(mart=mart, min_ts=None, regressed=False))
                continue

            previous = await session.execute(
                text("SELECT min_ts FROM meta.mart_floor_checks WHERE mart = :mart"),
                {"mart": mart},
            )
            previous_row = previous.first()
            previous_min_ts = previous_row[0] if previous_row else None
            regressed = previous_min_ts is not None and min_ts > previous_min_ts

            await session.execute(
                text(
                    "INSERT INTO meta.mart_floor_checks (mart, min_ts, checked_at) "
                    "VALUES (:mart, :min_ts, now()) "
                    "ON CONFLICT (mart) DO UPDATE "
                    "SET min_ts = EXCLUDED.min_ts, checked_at = EXCLUDED.checked_at"
                ),
                {"mart": mart, "min_ts": min_ts},
            )
            mart_min_ts_seconds.labels(mart=mart).set(min_ts.timestamp())
            reports.append(
                MartFloor(mart=mart, min_ts=min_ts.isoformat(), regressed=regressed)
            )
        # `get_session()` commits on clean exit from this block -- no
        # explicit commit needed here.

    for r in reports:
        if r.regressed:
            log.error("retention.mart_floor_regressed", mart=r.mart, min_ts=r.min_ts)
    log.info(
        "retention.mart_floors_checked",
        floors={r.mart: r.min_ts for r in reports},
    )
    return reports
