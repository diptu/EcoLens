"""Backfill missing days for one or more ingestion sources.

Idempotent: for each `(source, day)` in the requested range, checks
`meta._ingest_log` for an existing `status='success'` row before
re-running that source's ingest task with a lookback covering the day
(24h by default — `task.md`'s own examples use `--lookback-minutes
1440`). Days that already succeeded are skipped.

The actual CLI entrypoint is `services/data-pipeline/scripts/backfill.py`
(a thin wrapper, matching `task.md`'s documented `python
scripts/backfill.py --from ... --to ...` usage) — this module holds the
logic so it's unit-testable without a subprocess.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

from sqlalchemy import text

from app.db.session import get_session
from app.core.logging import get_logger
from app.service.pipeline.tasks.registry import SOURCES, run_source

log = get_logger(__name__)

DEFAULT_LOOKBACK_MINUTES = 1440  # 24h, per task.md's own examples

# holidays is an annual snapshot, not a per-day time series -- backfilling
# it by date range doesn't make sense the way it does for the other 4.
BACKFILLABLE_SOURCES: tuple[str, ...] = tuple(
    key for key in SOURCES if key != "holidays"
)


def daterange(start: date, end: date) -> Iterator[date]:
    """Inclusive date range, one `date` per day."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


async def already_succeeded(source: str, day: date) -> bool:
    """True if `meta._ingest_log` already has a `status='success'` (fully
    synced) OR `status='staged'` (fetched, staged, warehouse notified —
    just hasn't been synced by `pipeline.warehouse_sync`'s consumer yet)
    row for `source` on `day`. Treating `'staged'` as "don't re-fetch"
    avoids redundant work piling up while the consumer catches up;
    `load_to_postgres`'s `ON CONFLICT DO NOTHING` would make a genuine
    double-fetch harmless anyway, this just skips the wasted work."""
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM meta._ingest_log "
                "WHERE source = :source AND status IN ('success', 'staged') "
                "AND started_at::date = :day LIMIT 1"
            ),
            {"source": source, "day": day},
        )
        return result.first() is not None


async def backfill_day(
    key: str, day: date, lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
) -> str:
    """Backfill one `(source, day)` pair if it hasn't already succeeded.

    Returns `"skipped"`, `"success"`, or `"failed: <message>"` — never
    raises, so one bad day/source doesn't abort the rest of the range.
    """
    entry = SOURCES[key]
    if await already_succeeded(entry.source, day):
        return "skipped"

    try:
        rows = await run_source(
            key, triggered_by="backfill", lookback_minutes=lookback_minutes
        )
    except Exception as exc:
        log.error("backfill.day_failed", source=key, day=str(day), error=str(exc))
        return f"failed: {exc}"

    log.info("backfill.day_succeeded", source=key, day=str(day), rows=rows)
    return "success"


async def backfill(
    sources: tuple[str, ...],
    start: date,
    end: date,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> dict[tuple[str, date], str]:
    """Backfill every `(source, day)` pair in the range.

    Returns one result per pair, in `(source, day) -> outcome` order —
    see `backfill_day`'s docstring for the possible outcome strings.
    """
    results: dict[tuple[str, date], str] = {}
    for day in daterange(start, end):
        for key in sources:
            results[(key, day)] = await backfill_day(key, day, lookback_minutes)
    return results
