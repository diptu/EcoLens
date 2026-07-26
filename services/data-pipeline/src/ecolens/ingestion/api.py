"""API-triggered ingestion housekeeping: backfill historical data, check
day-by-day row counts, and retry just the days that came back missing or
short. A plain `APIRouter` (same shape as `forecasting.api`'s own
router), meant to be mounted on data-pipeline's own control API
(`ecolens.api.app`).

Each `_ingest_*_historical` function mirrors its corresponding CLI
script's fetch -> validate -> upsert logic exactly (see each function's
docstring for which script) -- this module is a thin dispatch layer over
the same building blocks (fetchers, validators,
`duckdb_store.write_historical`), not a reimplementation.

Retries are always safe to re-run and never duplicate records: every
write upserts on each source's unique key
(`IngestionSettings.unique_key_for_source`), so re-ingesting a day that
already has full data just overwrites the same rows with (presumably
identical, or corrected) values -- there is no separate "delete before
reinsert" step to get right, upsert-by-unique-key already guarantees no
duplicates.

Runs in the background (a real range can take from seconds to minutes,
see each endpoint's docstring) -- trigger responses include a `job_id`;
poll the matching `GET .../{job_id}` (backed by
`ecolens.shared.job_tracker`, shared with `forecasting.api`'s equivalent
job-polling endpoint) to find out whether it's still running, finished,
or failed.

Historically this endpoint backfilled into a *separate* "historical"
MongoDB cluster, distinct from the live one -- that whole dual-cluster
split is gone now that DuckDB is the sole raw store (see TODO.md's
ECO-150..158): there's just one store, written to by both this endpoint
and the live per-source ingestion paths.
"""

from __future__ import annotations

import asyncio
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import httpx
import pandera.errors
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ecolens.config import get_settings
from ecolens.ingestion.sources.aemo_nem import AEMONEMFetcher
from ecolens.ingestion.sources.aemo_wem import AEMOWEMFetcher
from ecolens.ingestion.sources.bom import HistoricalFetcher
from ecolens.ingestion.sources.bom.schema import HISTORICAL_TIMEOUT_SECONDS
from ecolens.ingestion.sources.holidays import HolidayFetcher
from ecolens.ingestion.sources.openelectricity import OpenElectricityFetcher
from ecolens.ingestion.sources.openelectricity.schema import MAX_5M_INTERVAL_DAYS
from ecolens.ingestion.storage import duckdb_store
from ecolens.ingestion.validators.bom import validate as validate_bom
from ecolens.ingestion.validators.holidays import validate as validate_holidays
from ecolens.ingestion.validators.openelectricity import (
    validate as validate_openelectricity,
)
from ecolens.shared.job_tracker import JobTracker
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

Source = Literal["bom", "aemo_nem", "aemo_wem", "openelectricity", "holidays"]

# Sources with a fetch_month() -- currently only aemo_nem
# (AEMONEMFetcher.fetch_month, see trigger_historical_month_ingest).
# A narrower Literal than Source so Swagger's dropdown for
# /ingestion/historical/month only ever offers what actually works,
# instead of listing all 5 sources and 400ing on 4 of them.
MonthSource = Literal["aemo_nem"]

_AEMO_FETCHERS = {"aemo_nem": AEMONEMFetcher, "aemo_wem": AEMOWEMFetcher}

# Per source: the field its rows are timestamped by. `count_by_day`
# CASTs this to DATE/TIMESTAMP in SQL, so it works whether the field
# lands as a native temporal column or an ISO-8601 string (some
# sources' fields are the latter -- see write_historical) without
# needing to track that distinction here.
_TIME_FIELD: dict[Source, str] = {
    "bom": "ts",
    "aemo_nem": "ts",
    "aemo_wem": "ts",
    "openelectricity": "ts",
    "holidays": "date",
}

_jobs = JobTracker()


def _resolve_date_range(
    date: _date | None, start_date: _date | None, end_date: _date | None
) -> tuple[_date, _date]:
    """Validates and normalizes `date` xor `start_date`+`end_date` into an
    inclusive `(start, end)` pair -- raises `HTTPException(422)` on any bad
    combination, same manual-validation convention as
    `warehouse/api/dependencies.py`'s `validate_region_dep`/etc.
    """
    has_range = start_date is not None or end_date is not None
    if date is not None:
        if has_range:
            raise HTTPException(
                status_code=422,
                detail="specify either `date` or `start_date`/`end_date`, not both",
            )
        return date, date

    if not has_range:
        raise HTTPException(
            status_code=422,
            detail="specify either `date` or both `start_date` and `end_date`",
        )
    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=422, detail="a range needs both `start_date` and `end_date`"
        )
    if end_date < start_date:
        raise HTTPException(
            status_code=422, detail="`end_date` must be on or after `start_date`"
        )
    return start_date, end_date


async def _ingest_bom_historical(start: _date, end: _date) -> int:
    """Mirrors `scripts/backfill_bom_historical.py`'s `--start-date`/
    `--end-date` path (Open-Meteo ERA5 reanalysis). Returns the number of
    rows written (0 if nothing was fetched/validated).
    """
    run_id = uuid4().hex
    fetcher = HistoricalFetcher()
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    async with httpx.AsyncClient(timeout=HISTORICAL_TIMEOUT_SECONDS) as client:
        docs = await fetcher.fetch_all_stations_for_range(client, start_dt, end_dt)

    log.info(
        "ingestion.historical.fetch_complete",
        run_id=run_id,
        source="bom",
        doc_count=len(docs),
    )
    if not docs:
        log.warning("ingestion.historical.fetch_empty", run_id=run_id, source="bom")
        return 0

    try:
        docs = validate_bom(docs)
    except pandera.errors.SchemaError as e:
        log.error(
            "ingestion.historical.validation_failed",
            run_id=run_id,
            source="bom",
            error=str(e),
        )
        return 0

    written = duckdb_store.write_historical("bom", docs, run_id=run_id)
    log.info(
        "ingestion.historical.write_complete",
        run_id=run_id,
        source="bom",
        written=written,
    )
    return written


# Concurrent day-fetches per batch for _ingest_aemo_historical. Both AEMO
# fetchers' fetch_for_date() makes several sequential HTTP requests per
# day (NEM: directory probe + zip download; WEM: current-then-previous
# fallback across 3 feeds) -- at ~4-5s/day, a fully sequential day-by-day
# loop over a multi-month range takes minutes. Bounded batches of
# concurrent days cut that roughly by this factor without firing the
# whole range at AEMO's servers at once.
_AEMO_HISTORICAL_BATCH_SIZE = 10


async def _fetch_aemo_day_safe(
    fetcher: AEMONEMFetcher | AEMOWEMFetcher,
    client: httpx.AsyncClient,
    day: _date,
) -> tuple[_date, list[dict] | None, str | None]:
    """One day's fetch, exception captured rather than raised -- so one
    bad day in a concurrent batch doesn't cancel the others via
    `asyncio.gather`.
    """
    try:
        docs = await fetcher.fetch_for_date(client, day)
    except Exception as exc:  # noqa: BLE001 - one bad day shouldn't abort the range
        return day, None, str(exc)
    return day, docs, None


async def _ingest_aemo_historical(source: str, start: _date, end: _date) -> int:
    """Mirrors `services/scripts/backfill_aemo.py`'s day-by-day loop,
    fetching `_AEMO_HISTORICAL_BATCH_SIZE` days concurrently at a time
    (both AEMO fetchers' own `fetch()` already fetches a whole range
    concurrently internally -- this just bounds that concurrency rather
    than either going fully sequential or firing every day in the range
    at once) -- one bad day (fetch OR write) is logged and skipped
    rather than aborting the rest of the range. Returns the total
    number of rows written across the whole range.
    """
    fetcher = _AEMO_FETCHERS[source]()
    written_total = 0
    all_days: list[_date] = []
    day = start
    while day <= end:
        all_days.append(day)
        day += timedelta(days=1)

    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(all_days), _AEMO_HISTORICAL_BATCH_SIZE):
            batch = all_days[i : i + _AEMO_HISTORICAL_BATCH_SIZE]
            results = await asyncio.gather(
                *(_fetch_aemo_day_safe(fetcher, client, d) for d in batch)
            )
            for fetched_day, docs, fetch_error in results:
                run_id = uuid4().hex
                if fetch_error is not None:
                    log.error(
                        "ingestion.historical.fetch_failed",
                        run_id=run_id,
                        source=source,
                        day=fetched_day.isoformat(),
                        error=fetch_error,
                    )
                    continue

                if not docs:
                    log.warning(
                        "ingestion.historical.no_data",
                        run_id=run_id,
                        source=source,
                        day=fetched_day.isoformat(),
                    )
                    continue

                try:
                    written = duckdb_store.write_historical(source, docs, run_id=run_id)
                except Exception as exc:  # noqa: BLE001 - one bad day shouldn't abort the range
                    # A single day's write failing (e.g. a lock conflict
                    # that outlasted write_historical's own internal
                    # retries) used to be able to propagate straight out
                    # of this function, aborting every remaining day in
                    # the range and losing the job's `written_total`
                    # progress entirely. Skip it instead;
                    # /ingestion/retry-missing already finds and
                    # re-ingests exactly the days that ended up with zero
                    # rows.
                    log.error(
                        "ingestion.historical.write_failed",
                        run_id=run_id,
                        source=source,
                        day=fetched_day.isoformat(),
                        error=str(exc),
                    )
                    continue
                written_total += written
                log.info(
                    "ingestion.historical.day_complete",
                    run_id=run_id,
                    source=source,
                    day=fetched_day.isoformat(),
                    written=written,
                )

    log.info(
        "ingestion.historical.range_complete",
        source=source,
        days=(end - start).days + 1,
        written_total=written_total,
    )
    return written_total


async def _ingest_aemo_nem_month(year: int, month: int) -> int:
    """Mirrors `scripts/trigger_ingest_aemo_nem.py`'s `--month` path:
    one NEMWeb Archive zip-of-zips download -> whole month's docs ->
    a single DuckDB write, instead of looping `_ingest_aemo_historical`
    day-by-day. Returns the number of rows written (0 if the month
    hasn't been archived yet, or nothing was fetched).
    """
    run_id = uuid4().hex
    fetcher = AEMONEMFetcher()
    async with httpx.AsyncClient(timeout=300) as client:
        docs = await fetcher.fetch_month(client, year, month)

    log.info(
        "ingestion.historical_month.fetch_complete",
        run_id=run_id,
        source="aemo_nem",
        year=year,
        month=month,
        doc_count=len(docs),
    )
    if not docs:
        log.warning(
            "ingestion.historical_month.fetch_empty",
            run_id=run_id,
            source="aemo_nem",
            year=year,
            month=month,
        )
        return 0

    written = duckdb_store.write_historical("aemo_nem", docs, run_id=run_id)
    log.info(
        "ingestion.historical_month.write_complete",
        run_id=run_id,
        source="aemo_nem",
        written=written,
    )
    return written


async def _ingest_openelectricity_historical(start: _date, end: _date) -> int:
    """`OpenElectricityFetcher.fetch()` deliberately raises `ValueError`
    rather than auto-chunking any request wider than
    `MAX_5M_INTERVAL_DAYS` (the OE API's own hard limit for
    `interval=5m`, confirmed live: 8 days works, 9 doesn't) -- a bare
    `fetch()` call hides how many requests it's making if it silently
    splits a wide range under the hood. This is the one place that
    chunking happens instead: the requested range is split into
    `MAX_5M_INTERVAL_DAYS`-sized windows here, each fetched + validated
    + written independently, mirroring `_ingest_aemo_historical`'s
    day-by-day loop -- one bad chunk (fetch, validation, OR write) is
    logged and skipped rather than aborting the rest of the range.
    Returns the total rows written (0 if OE_API_KEY isn't configured).
    """
    settings = get_settings()
    if not settings.oe_api_key:
        log.error(
            "ingestion.historical.oe_api_key_missing", hint="set OE_API_KEY in .env"
        )
        return 0

    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    range_start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    range_end = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(
        days=1
    )

    written_total = 0
    async with httpx.AsyncClient(timeout=settings.oe_request_timeout_seconds) as client:
        chunk_start = range_start
        step = timedelta(days=MAX_5M_INTERVAL_DAYS)
        while chunk_start < range_end:
            chunk_end = min(chunk_start + step, range_end)
            run_id = uuid4().hex
            label = f"{chunk_start.date().isoformat()}..{chunk_end.date().isoformat()}"

            try:
                docs = await fetcher.fetch(client, since=chunk_start, until=chunk_end)
            except Exception as exc:  # noqa: BLE001 - one bad chunk shouldn't abort the range
                log.error(
                    "ingestion.historical.fetch_failed",
                    run_id=run_id,
                    source="openelectricity",
                    chunk=label,
                    error=str(exc),
                )
                chunk_start = chunk_end
                continue

            if not docs:
                log.warning(
                    "ingestion.historical.no_data",
                    run_id=run_id,
                    source="openelectricity",
                    chunk=label,
                )
                chunk_start = chunk_end
                continue

            try:
                docs = validate_openelectricity(docs)
            except pandera.errors.SchemaError as e:
                log.error(
                    "ingestion.historical.validation_failed",
                    run_id=run_id,
                    source="openelectricity",
                    chunk=label,
                    error=str(e),
                )
                chunk_start = chunk_end
                continue

            try:
                written = duckdb_store.write_historical(
                    "openelectricity", docs, run_id=run_id
                )
            except Exception as exc:  # noqa: BLE001 - one bad chunk shouldn't abort the range
                log.error(
                    "ingestion.historical.write_failed",
                    run_id=run_id,
                    source="openelectricity",
                    chunk=label,
                    error=str(exc),
                )
                chunk_start = chunk_end
                continue

            written_total += written
            log.info(
                "ingestion.historical.chunk_complete",
                run_id=run_id,
                source="openelectricity",
                chunk=label,
                written=written,
            )
            chunk_start = chunk_end

    return written_total


async def _ingest_holidays_historical(start: _date, end: _date) -> int:
    """Holidays are fetched per calendar *year*
    (`HolidayFetcher.fetch(year=...)`), so a date range is normalized to
    the distinct years it spans -- mirrors
    `scripts/trigger_ingest_holidays.py`'s `--start-year`/`--end-year`
    loop. Returns the total number of rows written across every year
    spanned by the range.
    """
    fetcher = HolidayFetcher()
    written_total = 0
    for year in range(start.year, end.year + 1):
        run_id = uuid4().hex
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                docs = await fetcher.fetch(client, year=year)
        except Exception as exc:  # noqa: BLE001 - one bad year shouldn't abort the range
            log.error(
                "ingestion.historical.fetch_failed",
                run_id=run_id,
                source="holidays",
                year=year,
                error=str(exc),
            )
            continue

        if not docs:
            log.warning(
                "ingestion.historical.fetch_empty",
                run_id=run_id,
                source="holidays",
                year=year,
            )
            continue

        try:
            docs = validate_holidays(docs)
        except pandera.errors.SchemaError as e:
            log.error(
                "ingestion.historical.validation_failed",
                run_id=run_id,
                source="holidays",
                year=year,
                error=str(e),
            )
            continue

        try:
            written = duckdb_store.write_historical(
                "aemo_holidays", docs, run_id=run_id
            )
        except Exception as exc:  # noqa: BLE001 - one bad year shouldn't abort the range
            # Same protection as the fetch step above -- see
            # _ingest_aemo_historical's identical fix for why this can't
            # be allowed to propagate and abort every remaining year.
            log.error(
                "ingestion.historical.write_failed",
                run_id=run_id,
                source="holidays",
                year=year,
                error=str(exc),
            )
            continue
        written_total += written
        log.info(
            "ingestion.historical.write_complete",
            run_id=run_id,
            source="holidays",
            year=year,
            written=written,
        )

    return written_total


async def _daily_counts(source: Source, start: _date, end: _date) -> dict[_date, int]:
    """Row count per calendar day in `[start, end]` (inclusive) for one
    source -- the shared logic behind both `/ingestion/daily-counts` and
    `/ingestion/retry-missing` (the latter just filters this down to the
    days that came back short). A single SQL GROUP BY (`duckdb_store.
    count_by_day`), not a Python-side bucketing workaround.
    """
    field = _TIME_FIELD[source]
    return duckdb_store.count_by_day(
        "aemo_holidays" if source == "holidays" else source, field, start, end
    )


async def _retry_missing_dates(source: Source, missing_dates: list[_date]) -> int:
    """Re-ingests just the given (already-known-to-be-missing-or-short)
    dates. holidays is fetched per *year*, not per day, so a missing day
    there triggers a full re-fetch of that whole year (deduped -- one
    call per distinct year among `missing_dates`, not one per day).
    Returns the total rows written across every retried date/year.
    """
    written_total = 0
    if source == "bom":
        for day in missing_dates:
            written_total += await _ingest_bom_historical(day, day)
    elif source in _AEMO_FETCHERS:
        for day in missing_dates:
            written_total += await _ingest_aemo_historical(source, day, day)
    elif source == "openelectricity":
        for day in missing_dates:
            written_total += await _ingest_openelectricity_historical(day, day)
    elif source == "holidays":
        for year in sorted({day.year for day in missing_dates}):
            written_total += await _ingest_holidays_historical(
                _date(year, 1, 1), _date(year, 12, 31)
            )
    return written_total


@router.get("/daily-counts")
async def get_daily_counts(
    source: Source = Query(..., description="Which source to check."),
    date: _date | None = Query(None, description="Single day to check (YYYY-MM-DD)."),
    start_date: _date | None = Query(
        None, description="First day of an inclusive range (YYYY-MM-DD)."
    ),
    end_date: _date | None = Query(
        None, description="Last day of an inclusive range (YYYY-MM-DD)."
    ),
) -> dict[str, object]:
    """Row count per day for one source, over a single `date` or an
    inclusive `start_date`/`end_date` range -- runs synchronously (not a
    background job; even a full year is a light read), returning 0 for
    any day with no rows at all.
    """
    start, end = _resolve_date_range(date, start_date, end_date)
    counts = await _daily_counts(source, start, end)
    return {
        "source": source,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "counts": [
            {"date": day.isoformat(), "count": count}
            for day, count in sorted(counts.items())
        ],
    }


@router.post("/retry-missing")
async def trigger_retry_missing(
    background_tasks: BackgroundTasks,
    source: Source = Query(..., description="Which source to check and retry."),
    date: _date | None = Query(None, description="Single day to check (YYYY-MM-DD)."),
    start_date: _date | None = Query(
        None, description="First day of an inclusive range (YYYY-MM-DD)."
    ),
    end_date: _date | None = Query(
        None, description="Last day of an inclusive range (YYYY-MM-DD)."
    ),
    min_expected_count: int | None = Query(
        None,
        description=(
            "Also retry days with fewer than this many rows, not just "
            "fully-missing (zero) days. Omit to only retry zero-row days."
        ),
    ),
) -> dict[str, object]:
    """Finds days in `[date]`/`[start_date, end_date]` with zero rows
    (or, if `min_expected_count` is given, fewer than that many) and
    re-ingests just those -- never the whole range, and never at risk of
    duplicating anything: every write is keyed on each source's unique
    key (`IngestionSettings.unique_key_for_source`), so retrying an
    already-complete day just overwrites it with the same values.

    Returns immediately with the day count actually checked and the
    list of gaps found; if any were found, also a `job_id` -- poll
    `GET /ingestion/retry-missing/{job_id}` for the retry's outcome.
    Returns with no `job_id` (nothing scheduled) if no gaps were found.
    """
    start, end = _resolve_date_range(date, start_date, end_date)
    counts = await _daily_counts(source, start, end)
    missing_dates = sorted(
        day
        for day, count in counts.items()
        if count == 0 or (min_expected_count is not None and count < min_expected_count)
    )

    if not missing_dates:
        log.info(
            "api.retry_missing.no_gaps",
            source=source,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        return {
            "status": "no_gaps_found",
            "source": source,
            "days_checked": len(counts),
            "missing_dates": [],
        }

    job_id = _jobs.start(
        source=source, missing_dates=[d.isoformat() for d in missing_dates]
    )
    background_tasks.add_task(
        _jobs.run, job_id, _retry_missing_dates, source, missing_dates
    )
    log.info(
        "api.retry_missing_triggered",
        job_id=job_id,
        source=source,
        missing_dates=[d.isoformat() for d in missing_dates],
    )
    return {
        "status": "started",
        "job_id": job_id,
        "source": source,
        "days_checked": len(counts),
        "missing_dates": [d.isoformat() for d in missing_dates],
    }


@router.get("/retry-missing/{job_id}")
async def get_retry_missing_status(job_id: str) -> dict[str, object]:
    """Poll a `/ingestion/retry-missing` trigger's outcome by its `job_id`.

    `status` is `"running"`, `"completed"`, or `"failed"`; `written`
    (only set once `completed`) is the total rows written across every
    retried date, `error` (only set once `failed`) is the exception
    message.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No such job: {job_id!r} (unknown, or the server restarted since it ran)",
        )
    return {
        **job.meta,
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "written": job.result,
        "error": job.error,
    }


@router.post("/historical")
async def trigger_historical_ingest(
    background_tasks: BackgroundTasks,
    source: Source = Query(..., description="Which source to backfill."),
    date: _date | None = Query(
        None, description="Single day to backfill (YYYY-MM-DD)."
    ),
    start_date: _date | None = Query(
        None, description="First day of an inclusive range (YYYY-MM-DD)."
    ),
    end_date: _date | None = Query(
        None, description="Last day of an inclusive range (YYYY-MM-DD)."
    ),
) -> dict[str, str]:
    """Backfills one source into the local DuckDB store, for a single
    `date` or an inclusive `start_date`/`end_date` range.

    Query parameters, not a JSON body -- `source` being an `enum`-typed
    query param (rather than a body field) is what makes Swagger UI
    render it as an actual dropdown in "Try it out" instead of a raw
    JSON textarea, which doesn't render per-field widgets even when the
    schema documents an enum.

    Runs in the background -- a real range can take anywhere from
    seconds (openelectricity, bom) to minutes (aemo_nem/aemo_wem's
    day-by-day loop, holidays' year-by-year loop) -- so this returns
    immediately rather than holding the request open. Poll
    `GET /ingestion/historical/{job_id}` with the returned `job_id` to
    find out when it finishes and how many rows were written.

    `source='openelectricity'` rejects (422) a range wider than
    `MAX_5M_INTERVAL_DAYS` up front, before any job starts -- the OE
    API itself rejects `interval=5m` requests over 8 days
    (`OpenElectricityFetcher.fetch()` raises `ValueError` for exactly
    this reason), and this endpoint doesn't chunk a too-wide
    openelectricity range into multiple requests on your behalf.
    Split it into several `start_date`/`end_date` calls yourself
    instead. (bom/aemo_nem/aemo_wem/holidays have no such limit --
    their own historical helpers already chunk day-by-day/year-by-year
    internally; `_ingest_openelectricity_historical` now does the same
    thing in `MAX_5M_INTERVAL_DAYS`-sized chunks, so `openelectricity`
    accepts any range too.)
    """
    start, end = _resolve_date_range(date, start_date, end_date)

    job_id = _jobs.start(
        source=source, start_date=start.isoformat(), end_date=end.isoformat()
    )

    if source == "bom":
        background_tasks.add_task(_jobs.run, job_id, _ingest_bom_historical, start, end)
    elif source in _AEMO_FETCHERS:
        background_tasks.add_task(
            _jobs.run, job_id, _ingest_aemo_historical, source, start, end
        )
    elif source == "openelectricity":
        background_tasks.add_task(
            _jobs.run, job_id, _ingest_openelectricity_historical, start, end
        )
    elif source == "holidays":
        background_tasks.add_task(
            _jobs.run, job_id, _ingest_holidays_historical, start, end
        )

    log.info(
        "api.historical_ingest_triggered",
        job_id=job_id,
        source=source,
        start=start.isoformat(),
        end=end.isoformat(),
    )
    return {
        "status": "started",
        "job_id": job_id,
        "source": source,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


@router.get("/historical/{job_id}")
async def get_historical_ingest_status(job_id: str) -> dict[str, object]:
    """Poll a `/ingestion/historical` trigger's outcome by its `job_id`.

    `status` is `"running"`, `"completed"`, or `"failed"`; `written`
    (only set once `completed`) is the total rows written, `error`
    (only set once `failed`) is the exception message.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No such job: {job_id!r} (unknown, or the server restarted since it ran)",
        )
    return {
        **job.meta,
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "written": job.result,
        "error": job.error,
    }


@router.post("/historical/month")
async def trigger_historical_month_ingest(
    background_tasks: BackgroundTasks,
    source: MonthSource = Query(
        ..., description="Which source to backfill (only `aemo_nem` has a month-fetch)."
    ),
    year: int = Query(..., ge=2000, le=2100, description="Calendar year, e.g. 2026."),
    month: int = Query(..., ge=1, le=12, description="Calendar month, 1-12."),
) -> dict[str, str]:
    """Backfills one whole calendar month directly from the source's
    archive endpoint in a single request, instead of looping
    `/ingestion/historical` day-by-day over `start_date`/`end_date`.

    Only `aemo_nem` supports this (`AEMONEMFetcher.fetch_month`,
    pulling NEMWeb's Archive zip-of-zips --
    https://www.nemweb.com.au/Reports/ARCHIVE/Daily_Reports/ -- in one
    ~150-200MB download instead of up to 31 Current-listing probes) --
    `source` is typed as `MonthSource` (not the full `Source` enum),
    so Swagger's dropdown only ever offers `aemo_nem`; any other value
    fails FastAPI's own request validation (422) before this function
    body even runs. Returns 0 rows written if the month hasn't been
    archived yet (archive publishing lags live data by roughly a month).

    Runs in the background like `/ingestion/historical` -- poll
    `GET /ingestion/historical/{job_id}` (same job store) with the
    returned `job_id`.
    """
    job_id = _jobs.start(source=source, year=year, month=month)
    background_tasks.add_task(_jobs.run, job_id, _ingest_aemo_nem_month, year, month)

    log.info(
        "api.historical_month_ingest_triggered",
        job_id=job_id,
        source=source,
        year=year,
        month=month,
    )
    return {
        "status": "started",
        "job_id": job_id,
        "source": source,
        "year": str(year),
        "month": str(month),
    }


__all__ = ["router"]
