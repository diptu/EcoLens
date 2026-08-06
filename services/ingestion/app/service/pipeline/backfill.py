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
from datetime import UTC, date, datetime, timedelta

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
    double-fetch harmless anyway, this just skips the wasted work.

    Checks `window_start` (the actual historical date a run *fetched*,
    now populated by `registry.run_source` from `start`/`end` -- see its
    own docstring) -- **not** `started_at` (when the run itself executed
    in real wall-clock time), which this used to check instead. That was
    a real bug: `started_at::date` only ever coincidentally equals a
    historical `day`, so this returned `False` for every genuinely
    historical day on every call, silently defeating backfill's own
    idempotency/resumability for the entire range every single run.
    """
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM meta._ingest_log "
                "WHERE source = :source AND status IN ('success', 'staged') "
                "AND window_start::date = :day LIMIT 1"
            ),
            {"source": source, "day": day},
        )
        return result.first() is not None


#  aemo-nem/aemo-wem/bom/oe have a real historical fetch keyed on an
# actual date range (see ingest_aemo_nem/wem/bom/openelectricity's
# `_fetch_historical_range`) -- route those through `start`/`end`
# instead of `lookback_minutes`, which is always "last N minutes from
# *now*" and structurally can't target a specific past day no matter how
# many days this loops over. `bom` joined this list 2026-08-05 --
# previously BoM's own API had no date-range query at all (only a
# rolling ~72h window), so its backfill would have silently re-fetched
# today's data once per day in the range instead of the actual requested
# days; `ingest_bom.py`'s `_fetch_historical_range` now sources real
# historical weather from Open-Meteo's ERA5 archive instead, closing
# that gap for real. `oe` joined the same day for the same reason --
# `ingest_openelectricity.py`'s `_fetch_historical_range` now targets a
# real day via `network_region`/`date_start`/`date_end` (the OE
# region-join blocker fix, `todo-model-training.md`) instead of always
# meaning "last N minutes from now".
_DATE_RANGE_SOURCES: tuple[str, ...] = ("aemo-nem", "aemo-wem", "bom", "oe")


async def backfill_day(
    key: str, day: date, lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES
) -> str:
    """Backfill one `(source, day)` pair if it hasn't already succeeded.

    Returns `"skipped"`, `"success"`, or `"failed: <message>"` — never
    raises, so one bad day/source doesn't abort the rest of the range.
    `already_succeeded`'s own DB check is inside this same `try` for that
    reason -- it used to sit before it, so a transient Postgres
    connection drop there (real, observed: `asyncpg.exceptions.
    ConnectionDoesNotExistError` mid-way through a 370-day `oe` backfill,
    ~3h/91 days in) went unhandled and killed the entire multi-hour
    `backfill()` loop instead of just failing that one day -- silently
    contradicting this docstring's own "never raises" promise.
    """
    entry = SOURCES[key]
    try:
        if await already_succeeded(entry.source, day):
            return "skipped"

        if key in _DATE_RANGE_SOURCES:
            # `ingest_aemo_{nem,wem}.py`'s `_fetch_historical_range` treats
            # `[start.date(), end.date()]` as an INCLUSIVE calendar-day
            # range (its own docstring/tests) -- passing `end=day_start +
            # 1 day` here (a half-open-range instinct) made every single
            # day of backfill fetch *two* real calendar days (this day
            # plus the next), silently doubling AEMO archive requests and
            # inflating the `rows_landed` this function returns, e.g.
            # ~576 instead of the real 288/day for `aemo-wem`. `start` and
            # `end` both resolving to the same calendar date is what
            # actually asks for exactly one day.
            day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            rows = await run_source(
                key,
                triggered_by="backfill",
                start=day_start,
                end=day_start,
            )
        else:
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
