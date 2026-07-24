"""API-triggered ingestion housekeeping: backfill into the *historical*
MongoDB cluster (`MONGO_URI_HISTORICAL`), check day-by-day document
counts against either cluster, and retry just the days that came back
missing or short. A plain `APIRouter` (same shape as `forecasting.api`'s
own router), meant to be mounted on data-pipeline's own control API
(`ecolens.api.app`).

Each `_ingest_*_historical` function mirrors its corresponding CLI
script's fetch -> validate -> upsert logic exactly (see each function's
docstring for which script) -- this module is a thin dispatch layer
over the same building blocks (fetchers, validators, `bulk_upsert`), not
a reimplementation. Each now takes a `historical: bool` flag (default
`True`, preserving `/ingestion/historical`'s original behavior) so
`/ingestion/retry-missing` can reuse the exact same functions against
either `MONGO_URI_HISTORICAL` or the live `MONGO_URI`.

Retries are always safe to re-run and never duplicate records: every
`bulk_upsert` call upserts on each source's unique key
(`MongoSettings.unique_key_for_source`), so re-ingesting a day that
already has full data just overwrites the same documents with
(presumably identical, or corrected) values -- there is no separate
"delete before reinsert" step to get right, upsert-by-unique-key already
guarantees no duplicates.

Runs in the background (a real range can take from seconds to minutes,
see each endpoint's docstring) -- trigger responses include a `job_id`;
poll the matching `GET .../{job_id}` (backed by
`ecolens.shared.job_tracker`, shared with `forecasting.api`'s equivalent
job-polling endpoint) to find out whether it's still running, finished,
or failed.

Every `_ingest_*_historical` function also mirrors its upserted batch
into the local DuckDB historical store (`ingestion/storage/duckdb_store`,
see TODO.md's ECO-158) right after the Mongo upsert -- best-effort, same
as `scripts/backfill_bom_historical.py`: a DuckDB write failure logs a
warning and doesn't fail the job, since the Mongo write already
succeeded. This runs regardless of the `historical` flag (both the
`MONGO_URI_HISTORICAL` and live-cluster paths land in the same DuckDB
table), since the fetched rows are identical in shape either way and the
whole point of the DuckDB copy is a durable, queryable record that
survives `warehouse/runner/archive.py`'s Mongo TTL deletion.
"""

from __future__ import annotations

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
from ecolens.ingestion.storage import duckdb_store
from ecolens.ingestion.storage.mongo import bulk_upsert, get_db, get_historical_db
from ecolens.ingestion.storage.settings import get_mongo_settings
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

_AEMO_FETCHERS = {"aemo_nem": AEMONEMFetcher, "aemo_wem": AEMOWEMFetcher}

# Per source: (the field docs are timestamped by, whether that field is
# stored as a real BSON datetime or a plain ISO-8601 string). Not
# uniform across sources -- bom/aemo_nem/aemo_wem's `ts` is a genuine
# datetime (built via pd.to_datetime/pd.Timestamp before upsert), but
# openelectricity's `ts` and holidays' `date` are validated as
# `Series[str]` (see validators/openelectricity.py, and
# sources/holidays/transformers.py's explicit `.isoformat()` calls) --
# comparing a string field against a Python datetime bound in a Mongo
# query does not coerce and silently matches nothing, so daily-count/
# retry queries need to know which comparison type to use.
_TIME_FIELD: dict[Source, tuple[str, Literal["datetime", "string"]]] = {
    "bom": ("ts", "datetime"),
    "aemo_nem": ("ts", "datetime"),
    "aemo_wem": ("ts", "datetime"),
    "openelectricity": ("ts", "string"),
    "holidays": ("date", "string"),
}

_jobs = JobTracker()


def _write_duckdb_best_effort(source: str, docs: list[dict], run_id: str) -> None:
    """Mirror `docs` into the local DuckDB historical store, best-effort.

    Called right after each `_ingest_*_historical` function's own Mongo
    `bulk_upsert`, with the same `source` string passed to that call
    (note: holidays upserts under Mongo collection key `"aemo_holidays"`,
    not `"holidays"` -- callers must pass the same key here). A DuckDB
    failure logs a warning rather than raising, since the Mongo write --
    the job's actual success criterion -- already succeeded.
    """
    try:
        written = duckdb_store.write_historical(source, docs)
        log.info(
            "ingestion.historical.duckdb_write_complete",
            run_id=run_id,
            source=source,
            written=written,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort, Mongo write already succeeded
        log.warning(
            "ingestion.historical.duckdb_write_failed",
            run_id=run_id,
            source=source,
            error=str(exc),
        )


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


async def _ingest_bom_historical(
    start: _date, end: _date, *, historical: bool = True
) -> int:
    """Mirrors `scripts/backfill_bom_historical.py`'s `--start-date`/
    `--end-date` path (Open-Meteo ERA5 reanalysis), against the
    historical Mongo cluster by default (`historical=False` targets the
    live cluster instead -- used by `/ingestion/retry-missing`). Returns
    the number of documents upserted (0 if nothing was fetched/validated).
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

    db = get_historical_db() if historical else get_db()
    upserted = await bulk_upsert(db, "bom", docs, run_id)
    log.info(
        "ingestion.historical.upsert_complete",
        run_id=run_id,
        source="bom",
        upserted=upserted,
    )
    _write_duckdb_best_effort("bom", docs, run_id)
    return upserted


async def _ingest_aemo_historical(
    source: str, start: _date, end: _date, *, historical: bool = True
) -> int:
    """Mirrors `services/scripts/backfill_aemo.py`'s day-by-day loop
    (neither AEMO fetcher supports a native range, unlike bom/
    openelectricity) -- one bad day is logged and skipped rather than
    aborting the rest of the range, against the historical Mongo
    cluster by default (`historical=False` targets the live cluster
    instead). Returns the total number of documents upserted across the
    whole range.
    """
    fetcher = _AEMO_FETCHERS[source]()
    db = get_historical_db() if historical else get_db()
    upserted_total = 0
    day = start
    async with httpx.AsyncClient(timeout=60) as client:
        while day <= end:
            run_id = uuid4().hex
            try:
                docs = await fetcher.fetch_for_date(client, day)
            except Exception as exc:  # noqa: BLE001 - one bad day shouldn't abort the range
                log.error(
                    "ingestion.historical.fetch_failed",
                    run_id=run_id,
                    source=source,
                    day=day.isoformat(),
                    error=str(exc),
                )
                day += timedelta(days=1)
                continue

            if docs:
                upserted = await bulk_upsert(db, source, docs, run_id)
                upserted_total += upserted
                log.info(
                    "ingestion.historical.day_complete",
                    run_id=run_id,
                    source=source,
                    day=day.isoformat(),
                    upserted=upserted,
                )
                _write_duckdb_best_effort(source, docs, run_id)
            else:
                log.warning(
                    "ingestion.historical.no_data",
                    run_id=run_id,
                    source=source,
                    day=day.isoformat(),
                )
            day += timedelta(days=1)

    log.info(
        "ingestion.historical.range_complete",
        source=source,
        days=(end - start).days + 1,
        upserted_total=upserted_total,
    )
    return upserted_total


async def _ingest_openelectricity_historical(
    start: _date, end: _date, *, historical: bool = True
) -> int:
    """`OpenElectricityFetcher.fetch()` supports `since`/`until` natively
    (see `sources/openelectricity/engine.py`), but no backfill script
    ever used it -- this is that range path, wired against the
    historical Mongo cluster by default (`historical=False` targets the
    live cluster instead). Returns the number of documents upserted (0
    if nothing was fetched/validated, or if OE_API_KEY isn't configured).
    """
    settings = get_settings()
    if not settings.oe_api_key:
        log.error(
            "ingestion.historical.oe_api_key_missing", hint="set OE_API_KEY in .env"
        )
        return 0

    run_id = uuid4().hex
    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    since = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    until = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(
        days=1
    )
    async with httpx.AsyncClient(timeout=settings.oe_request_timeout_seconds) as client:
        docs = await fetcher.fetch(client, since=since, until=until)

    log.info(
        "ingestion.historical.fetch_complete",
        run_id=run_id,
        source="openelectricity",
        doc_count=len(docs),
    )
    if not docs:
        log.warning(
            "ingestion.historical.fetch_empty", run_id=run_id, source="openelectricity"
        )
        return 0

    try:
        docs = validate_openelectricity(docs)
    except pandera.errors.SchemaError as e:
        log.error(
            "ingestion.historical.validation_failed",
            run_id=run_id,
            source="openelectricity",
            error=str(e),
        )
        return 0

    db = get_historical_db() if historical else get_db()
    upserted = await bulk_upsert(db, "openelectricity", docs, run_id)
    log.info(
        "ingestion.historical.upsert_complete",
        run_id=run_id,
        source="openelectricity",
        upserted=upserted,
    )
    _write_duckdb_best_effort("openelectricity", docs, run_id)
    return upserted


async def _ingest_holidays_historical(
    start: _date, end: _date, *, historical: bool = True
) -> int:
    """Holidays are fetched per calendar *year*
    (`HolidayFetcher.fetch(year=...)`), so a date range is normalized to
    the distinct years it spans -- mirrors
    `scripts/trigger_ingest_holidays.py`'s `--start-year`/`--end-year`
    loop, against the historical Mongo cluster by default
    (`historical=False` targets the live cluster instead). Returns the
    total number of documents upserted across every year spanned by the
    range.
    """
    fetcher = HolidayFetcher()
    upserted_total = 0
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

        db = get_historical_db() if historical else get_db()
        upserted = await bulk_upsert(db, "aemo_holidays", docs, run_id)
        upserted_total += upserted
        log.info(
            "ingestion.historical.upsert_complete",
            run_id=run_id,
            source="holidays",
            year=year,
            upserted=upserted,
        )
        _write_duckdb_best_effort("aemo_holidays", docs, run_id)

    return upserted_total


async def _daily_counts(
    source: Source, start: _date, end: _date, *, historical: bool
) -> dict[_date, int]:
    """Document count per calendar day in `[start, end]` (inclusive) for
    one source's collection -- the shared logic behind both
    `/ingestion/daily-counts` and `/ingestion/retry-missing` (the latter
    just filters this down to the days that came back short).

    Fetches only the timestamp field (`{field: 1, "_id": 0}` projection)
    and buckets by day in Python rather than a server-side `$group`
    aggregation -- deliberately, since the timestamp field's *storage
    type* differs by source (see `_TIME_FIELD`'s comment), and getting
    that wrong in a `$dateFromString`/`$dateTrunc` pipeline expression
    fails silently (matches nothing) rather than raising. Python-side
    parsing handles both cases with one code path, at the cost of
    pulling one field per matching document over the wire instead of
    letting Mongo do the bucketing -- fine at this endpoint's actual
    scale (a review/ops tool, not a hot path), worth revisiting only if
    someone points this at a many-year range on a very high-frequency
    source.
    """
    db = get_historical_db() if historical else get_db()
    collection_name = get_mongo_settings().collection_for_source(
        "aemo_holidays" if source == "holidays" else source
    )
    field, field_kind = _TIME_FIELD[source]

    if field_kind == "datetime":
        gte: object = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        lt: object = datetime(
            end.year, end.month, end.day, tzinfo=timezone.utc
        ) + timedelta(days=1)
    else:
        # ISO-8601 strings sort lexicographically in chronological order,
        # so plain string bounds work correctly even when the field's
        # actual values carry more precision than a bare date (e.g.
        # openelectricity's full datetime strings vs. these date-only
        # bounds) -- a date-only string is a *prefix* of any same-day
        # datetime string, and prefixes always sort first.
        gte = start.isoformat()
        lt = (end + timedelta(days=1)).isoformat()

    counts: dict[_date, int] = {}
    cursor = db[collection_name].find({field: {"$gte": gte, "$lt": lt}}, {field: 1})
    async for doc in cursor:
        raw = doc[field]
        day = (
            raw.date()
            if isinstance(raw, datetime)
            else datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        )
        counts[day] = counts.get(day, 0) + 1

    # Reindexed over the full requested range so days with zero
    # documents show up as an explicit 0 instead of silently missing
    # from the result (same "show gaps, don't hide them" convention as
    # scripts/plot_data_frequency.py).
    full_range: dict[_date, int] = {}
    day = start
    while day <= end:
        full_range[day] = counts.get(day, 0)
        day += timedelta(days=1)
    return full_range


async def _retry_missing_dates(
    source: Source, missing_dates: list[_date], *, historical: bool
) -> int:
    """Re-ingests just the given (already-known-to-be-missing-or-short)
    dates. holidays is fetched per *year*, not per day, so a missing day
    there triggers a full re-fetch of that whole year (deduped -- one
    call per distinct year among `missing_dates`, not one per day).
    Returns the total documents upserted across every retried
    date/year.
    """
    upserted_total = 0
    if source == "bom":
        for day in missing_dates:
            upserted_total += await _ingest_bom_historical(
                day, day, historical=historical
            )
    elif source in _AEMO_FETCHERS:
        for day in missing_dates:
            upserted_total += await _ingest_aemo_historical(
                source, day, day, historical=historical
            )
    elif source == "openelectricity":
        for day in missing_dates:
            upserted_total += await _ingest_openelectricity_historical(
                day, day, historical=historical
            )
    elif source == "holidays":
        for year in sorted({day.year for day in missing_dates}):
            upserted_total += await _ingest_holidays_historical(
                _date(year, 1, 1), _date(year, 12, 31), historical=historical
            )
    return upserted_total


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
    historical: bool = Query(
        False,
        description="Check the historical Mongo cluster instead of the live one.",
    ),
) -> dict[str, object]:
    """Document count per day for one source, over a single `date` or an
    inclusive `start_date`/`end_date` range -- runs synchronously (not a
    background job; even a full year is a light read), returning 0 for
    any day with no documents at all.
    """
    if historical and not get_mongo_settings().mongo_uri_historical:
        raise HTTPException(
            status_code=503,
            detail="MONGO_URI_HISTORICAL is not configured; historical ingestion is disabled.",
        )

    start, end = _resolve_date_range(date, start_date, end_date)
    counts = await _daily_counts(source, start, end, historical=historical)
    return {
        "source": source,
        "historical": historical,
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
    historical: bool = Query(
        False,
        description="Check/retry against the historical Mongo cluster instead of the live one.",
    ),
    min_expected_count: int | None = Query(
        None,
        description=(
            "Also retry days with fewer than this many documents, not just "
            "fully-missing (zero) days. Omit to only retry zero-document days."
        ),
    ),
) -> dict[str, object]:
    """Finds days in `[date]`/`[start_date, end_date]` with zero
    documents (or, if `min_expected_count` is given, fewer than that
    many) and re-ingests just those -- never the whole range, and never
    at risk of duplicating anything: every upsert is keyed on each
    source's unique key (`MongoSettings.unique_key_for_source`), so
    retrying an already-complete day just overwrites it with the same
    values.

    Returns immediately with the day count actually checked and the
    list of gaps found; if any were found, also a `job_id` -- poll
    `GET /ingestion/retry-missing/{job_id}` for the retry's outcome.
    Returns with no `job_id` (nothing scheduled) if no gaps were found.
    """
    if historical and not get_mongo_settings().mongo_uri_historical:
        raise HTTPException(
            status_code=503,
            detail="MONGO_URI_HISTORICAL is not configured; historical ingestion is disabled.",
        )

    start, end = _resolve_date_range(date, start_date, end_date)
    counts = await _daily_counts(source, start, end, historical=historical)
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
            "historical": historical,
            "days_checked": len(counts),
            "missing_dates": [],
        }

    job_id = _jobs.start(
        source=source,
        historical=historical,
        missing_dates=[d.isoformat() for d in missing_dates],
    )
    background_tasks.add_task(
        _jobs.run,
        job_id,
        _retry_missing_dates,
        source,
        missing_dates,
        historical=historical,
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
        "historical": historical,
        "days_checked": len(counts),
        "missing_dates": [d.isoformat() for d in missing_dates],
    }


@router.get("/retry-missing/{job_id}")
async def get_retry_missing_status(job_id: str) -> dict[str, object]:
    """Poll a `/ingestion/retry-missing` trigger's outcome by its `job_id`.

    `status` is `"running"`, `"completed"`, or `"failed"`; `upserted`
    (only set once `completed`) is the total documents upserted across
    every retried date, `error` (only set once `failed`) is the
    exception message.
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
        "upserted": job.result,
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
    """Backfills one source into the *historical* MongoDB cluster
    (`MONGO_URI_HISTORICAL`), for a single `date` or an inclusive
    `start_date`/`end_date` range.

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
    find out when it finishes and how many documents were upserted.
    """
    if not get_mongo_settings().mongo_uri_historical:
        raise HTTPException(
            status_code=503,
            detail="MONGO_URI_HISTORICAL is not configured; historical ingestion is disabled.",
        )

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

    `status` is `"running"`, `"completed"`, or `"failed"`; `upserted`
    (only set once `completed`) is the total documents upserted, `error`
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
        "upserted": job.result,
        "error": job.error,
    }


__all__ = ["router"]
