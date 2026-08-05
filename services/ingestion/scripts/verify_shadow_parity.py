#!/usr/bin/env python3
"""Compare a `triggered_by="shadow"` run's outcome against a real one for
the same `(source, day)` — `services/ingestion/TODO.md` Phase 4's
"Validate Data Integrity"/"Verify Backfill Consistency" items.

Reads `meta._ingest_log` (row counts, circuit breaker state, status) and
`meta.anomalies` (flagged-row counts) for both trigger groups within the
given window and reports the deltas. Exits non-zero if any delta exceeds
`--tolerance-pct` — meant for a human (or a CI step) to run after a
shadow-run window, not something this service calls itself.

**Real, honest limitation, not a hypothetical one**: this compares two
rows already in the same `meta._ingest_log` table, both written by
whichever service ran them — it does *not* prove services/ingestion's
own fetch is correct in isolation, only that its `meta._ingest_log`/
`meta.anomalies` outcome for a given window matches whatever the
`--against` trigger type already produced. It also depends on `meta.
_ingest_log`/`meta.anomalies` existing and being populated in the target
database, which they may not be — this script does not create schema or
recover from that; see `services/ingestion/TODO.md`'s own note on the
2026-08-05 Neon reset finding.

Run from `services/ingestion/`:

    uv run python scripts/verify_shadow_parity.py --source bom \\
        --from 2026-08-01 --to 2026-08-01

    uv run python scripts/verify_shadow_parity.py --source aemo-nem \\
        --from 2026-08-01 --to 2026-08-03 --against schedule --tolerance-pct 5
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import click
from sqlalchemy import text

from app.core.logging import configure_logging
from app.db.session import get_session
from app.service.pipeline.tasks.registry import SOURCES


@dataclass
class _GroupStats:
    trigger: str
    runs: int
    rows_landed: int
    anomalies_flagged: int
    statuses: dict[str, int]
    circuit_states: dict[str, int]


async def _collect(source: str, day: date, trigger: str) -> _GroupStats:
    window_start = datetime(day.year, day.month, day.day)
    window_end = window_start + timedelta(days=1)

    async with get_session() as session:
        log_result = await session.execute(
            text(
                "SELECT id, status, rows_landed, circuit_breaker_state "
                "FROM meta._ingest_log "
                "WHERE source = :source AND triggered_by = :trigger "
                "AND started_at >= :window_start AND started_at < :window_end"
            ),
            {
                "source": source,
                "trigger": trigger,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        rows = log_result.mappings().all()

        run_ids = [str(row["id"]) for row in rows]
        anomalies_flagged = 0
        if run_ids:
            anomaly_result = await session.execute(
                text(
                    "SELECT count(*) FROM meta.anomalies WHERE run_id = ANY(:run_ids)"
                ),
                {"run_ids": run_ids},
            )
            anomalies_flagged = int(anomaly_result.scalar() or 0)

    statuses: dict[str, int] = {}
    circuit_states: dict[str, int] = {}
    rows_landed = 0
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        state = row["circuit_breaker_state"] or "unknown"
        circuit_states[state] = circuit_states.get(state, 0) + 1
        rows_landed += row["rows_landed"] or 0

    return _GroupStats(
        trigger=trigger,
        runs=len(rows),
        rows_landed=rows_landed,
        anomalies_flagged=anomalies_flagged,
        statuses=statuses,
        circuit_states=circuit_states,
    )


def _pct_delta(shadow: int, real: int) -> float:
    if real == 0:
        return 0.0 if shadow == 0 else 100.0
    return abs(shadow - real) / real * 100.0


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


async def _verify(
    source: str, start: date, end: date, against: str, tolerance_pct: float
) -> bool:
    if source not in SOURCES:
        raise click.UsageError(
            f"unknown source '{source}' — expected one of {sorted(SOURCES)}"
        )

    all_within_tolerance = True
    for day in _daterange(start, end):
        shadow = await _collect(source, day, "shadow")
        real = await _collect(source, day, against)

        rows_delta_pct = _pct_delta(shadow.rows_landed, real.rows_landed)
        anomalies_delta_pct = _pct_delta(
            shadow.anomalies_flagged, real.anomalies_flagged
        )
        within_tolerance = (
            rows_delta_pct <= tolerance_pct and anomalies_delta_pct <= tolerance_pct
        )
        all_within_tolerance = all_within_tolerance and within_tolerance

        click.echo(f"{day} {source}:")
        click.echo(
            f"  rows_landed      shadow={shadow.rows_landed:<8} {against}={real.rows_landed:<8} "
            f"delta={rows_delta_pct:.1f}%"
        )
        click.echo(
            f"  anomalies_flagged shadow={shadow.anomalies_flagged:<7} {against}={real.anomalies_flagged:<7} "
            f"delta={anomalies_delta_pct:.1f}%"
        )
        click.echo(
            f"  statuses         shadow={shadow.statuses} {against}={real.statuses}"
        )
        click.echo(
            f"  circuit_breaker  shadow={shadow.circuit_states} {against}={real.circuit_states}"
        )
        click.echo(f"  within {tolerance_pct}% tolerance: {within_tolerance}")

    return all_within_tolerance


@click.command()
@click.option("--source", required=True, type=click.Choice(sorted(SOURCES)))
@click.option(
    "--from", "from_", required=True, type=click.DateTime(formats=["%Y-%m-%d"])
)
@click.option("--to", "to_", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option(
    "--against",
    type=click.Choice(["manual", "schedule", "backfill"]),
    default="schedule",
    show_default=True,
    help="Which real trigger type to compare the shadow runs against.",
)
@click.option(
    "--tolerance-pct",
    type=float,
    default=1.0,
    show_default=True,
    help="Max acceptable relative delta in rows_landed/anomalies_flagged.",
)
def main(
    source: str, from_: datetime, to_: datetime, against: str, tolerance_pct: float
) -> None:
    """Compare shadow-run outcomes against real ones for one source over a date range."""
    configure_logging()
    start, end = from_.date(), to_.date()
    if start > end:
        raise click.UsageError(f"--from ({start}) must not be after --to ({end})")

    passed = asyncio.run(_verify(source, start, end, against, tolerance_pct))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
