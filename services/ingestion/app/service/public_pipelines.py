"""`GET /v1/ingestion/public/pipelines`/`public/runs` logic
(`services/ingestion/TODO.md`'s "Frontend integration" section).

Query patterns mirror `services/data-pipeline`'s `app/service/
pipelines.py` (`list_pipelines`/`list_runs_public`) fairly closely --
both services write into the same shared `meta._ingest_log`/`meta.
anomalies` tables (confirmed: identical column set), so the underlying
SQL is naturally similar -- but this isn't a port. No Redis response
caching (data-pipeline's version has one): this endpoint has no real
traffic yet to justify the extra moving part, and every query here is
already a single indexed `source`/`started_at` scan, not the kind of
expensive aggregation caching earns its keep for. Add it later if a real
load profile asks for it, not preemptively.
"""

from __future__ import annotations

import base64
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.datasources import CATALOG
from app.schemas.ingest.public import (
    PublicFailedRunError,
    PublicFailedRunOut,
    PublicFailedRunsListResponse,
    PublicFailedRunsMeta,
    PublicPipelineOut,
    PublicPipelineSchedule,
    PublicPipelinesListResponse,
    PublicPipelinesMeta,
    PublicRecentRunSummary,
    PublicRetryQueueItem,
    PublicRetryQueueLastError,
    PublicRetryQueueListResponse,
    PublicRetryQueueMeta,
    PublicRunOut,
    PublicRunsListResponse,
    PublicRunsMeta,
    PublicSchedulerResponse,
    PublicSchedulerStatus,
    PublicUpcomingRun,
)

# The real cadence `app.celery_app`'s Beat schedule dispatches at for
# every source, unified since 2026-08-05 -- see `PublicPipelineOut`'s
# own docstring for why this isn't `CATALOG[].cron`.
_BEAT_CRON = "*/30 * * * *"
_BEAT_TIMEZONE = "UTC"

_STATS_WINDOW_24H = timedelta(hours=24)
_STATS_WINDOW_7D = timedelta(days=7)

_SOURCE_TO_CATALOG_ID = {entry.ingest_source: entry.id for entry in CATALOG}

# Ported from data-pipeline's `service.datasources.monitoring._classify_error`/
# `service.pipelines._NON_RETRYABLE_ERROR_CODES`/`_SECRET_LIKE_PATTERN` --
# pure, source-agnostic heuristics over `meta._ingest_log.error_message`
# free text, identical regardless of which service wrote the row (same
# shared table, same `str(exc)[:500]` truncation convention both
# services' `_common.py`-equivalent uses).
_NON_RETRYABLE_ERROR_CODES = {"missing_credentials", "schema_mismatch"}

_SECRET_LIKE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*\S+"
)


def _classify_error(message: str) -> str | None:
    """Best-effort keyword match, not an exact classification -- a
    message that matches no keyword isn't counted under any code
    (undercounting, not mis-bucketing)."""
    lowered = message.lower()
    if any(k in lowered for k in ("credential", "api key", "unauthorized", "401")):
        return "missing_credentials"
    if any(k in lowered for k in ("timeout", "timed out")):
        return "timeout"
    if any(k in lowered for k in ("rate limit", "429", "too many requests")):
        return "rate_limited"
    if any(k in lowered for k in ("schema", "keyerror", "column")):
        return "schema_mismatch"
    return None


def _redact_public_error_message(message: str) -> str:
    """Defense-in-depth for the unauthenticated public endpoints --
    `oe`'s ingestion goes through OpenElectricity's official SDK with a
    real API key; whether that SDK's exceptions ever echo it back isn't
    something this codebase can verify without auditing that dependency,
    so redact anything that looks like a credential rather than assume
    every message is safe to expose."""
    return _SECRET_LIKE_PATTERN.sub(lambda m: f"{m.group(1)}: [redacted]", message)


def _percentile(values: list[float], pct: float) -> int | None:
    """Linear-interpolation percentile (same method/shape as
    `datasources.service._percentile` in this same service -- not
    imported from there to keep this module's only real dependency on
    that one being `CATALOG`, not its query-layer internals too)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return round(ordered[int(rank)])
    lo_val = ordered[lo] * (hi - rank)
    hi_val = ordered[hi] * (rank - lo)
    return round(lo_val + hi_val)


def _next_run_at(now: datetime) -> datetime:
    try:
        tz = ZoneInfo(_BEAT_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return croniter(_BEAT_CRON, now.astimezone(tz)).get_next(datetime).astimezone(UTC)


async def list_pipelines_public(db: AsyncSession) -> PublicPipelinesListResponse:
    now = datetime.now(UTC)
    next_run_at = _next_run_at(now)

    sources = [entry.ingest_source for entry in CATALOG]
    result = await db.execute(
        text(
            "SELECT source, status, started_at, finished_at "
            "FROM meta._ingest_log "
            "WHERE source = ANY(:sources) AND started_at >= :since "
            "ORDER BY started_at DESC"
        ),
        {"sources": sources, "since": now - _STATS_WINDOW_24H},
    )
    rows_by_source: dict[str, list[dict[str, Any]]] = {s: [] for s in sources}
    for row in result.mappings().all():
        rows_by_source[row["source"]].append(dict(row))

    data: list[PublicPipelineOut] = []
    for entry in CATALOG:
        runs = rows_by_source.get(entry.ingest_source, [])
        # `staged` counts as a success here, not just `success` -- this
        # service's own fetch is done at `staged`; `success` only lands
        # once `pipeline.warehouse_sync`'s separate, asynchronous
        # consumer confirms the Postgres load (`backfill.already_
        # succeeded`'s own docstring treats the two identically for the
        # same reason). Only `failed`/`sync_failed` are real failures.
        successes = sum(1 for r in runs if r["status"] in ("success", "staged"))
        durations_ms = [
            (r["finished_at"] - r["started_at"]).total_seconds() * 1000
            for r in runs
            if r["finished_at"] is not None
        ]
        data.append(
            PublicPipelineOut(
                id=entry.id,
                name=entry.name,
                source_id=entry.id,
                schedule=PublicPipelineSchedule(
                    cron=_BEAT_CRON, timezone=_BEAT_TIMEZONE, enabled=True
                ),
                last_run_at=runs[0]["started_at"] if runs else None,
                next_run_at=next_run_at,
                run_count_24h=len(runs),
                success_rate_24h=(
                    round(100 * successes / len(runs), 1) if runs else None
                ),
                p95_duration_ms_24h=_percentile(durations_ms, 95),
            )
        )

    return PublicPipelinesListResponse(
        meta=PublicPipelinesMeta(total=len(data), as_of=now),
        data=data,
    )


_RUN_COLUMNS = (
    "l.id, l.source, l.status, l.triggered_by, l.started_at, l.finished_at, "
    "l.rows_landed, l.rows_loaded, COALESCE(a.cnt, 0) AS anomalies_flagged"
)
_RUN_FROM = (
    "FROM meta._ingest_log l "
    "LEFT JOIN (SELECT run_id, count(*) AS cnt FROM meta.anomalies GROUP BY run_id) a "
    "  ON a.run_id = l.id"
)


def _row_to_public_run_out(row: dict[str, Any]) -> PublicRunOut:
    duration_ms = None
    if row["finished_at"] is not None:
        duration_ms = round(
            (row["finished_at"] - row["started_at"]).total_seconds() * 1000
        )
    rows_landed = row.get("rows_landed")
    rows_loaded = row.get("rows_loaded")
    pipeline_id = _SOURCE_TO_CATALOG_ID.get(row["source"], row["source"])
    return PublicRunOut(
        id=str(row["id"]),
        pipeline_id=pipeline_id,
        source_id=pipeline_id,
        status=row["status"],
        trigger=row.get("triggered_by") or "manual",
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=duration_ms,
        records_fetched=rows_landed,
        records_inserted=rows_loaded,
        duplicates_skipped=(
            max(0, rows_landed - rows_loaded)
            if rows_landed is not None and rows_loaded is not None
            else None
        ),
        anomalies_flagged=row.get("anomalies_flagged"),
    )


async def list_runs_public(
    db: AsyncSession,
    *,
    source_id: str | None,
    status: str | None,
    trigger: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
    cursor: str | None,
) -> PublicRunsListResponse:
    """Cursor is a base64-encoded row offset, same shape data-pipeline's
    identical endpoint uses -- an opaque string as far as the API
    contract goes, a plain `OFFSET` underneath (`meta._ingest_log` at
    this service's real data volume doesn't need keyset pagination
    yet; revisit if `total` ever gets large enough for `OFFSET` to show
    up as a real cost, not preemptively)."""
    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            offset = 0

    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if source_id is not None:
        entry = next((e for e in CATALOG if e.id == source_id), None)
        source = entry.ingest_source if entry else "__no_such_source__"
        where.append("l.source = :source")
        params["source"] = source
    if status is not None:
        where.append("l.status = :status")
        params["status"] = status
    if trigger is not None:
        where.append("l.triggered_by = :trigger")
        params["trigger"] = trigger
    if from_ is not None:
        where.append("l.started_at >= :from_")
        params["from_"] = from_
    if to is not None:
        where.append("l.started_at <= :to")
        params["to"] = to
    # `where`/`where_clause` are only ever built from the fixed literal
    # clause fragments above -- actual values are always bound params,
    # never interpolated.
    where_clause = " AND ".join(where)

    total_result = await db.execute(text("SELECT count(*) FROM meta._ingest_log"))
    total = int(total_result.scalar() or 0)

    filtered_result = await db.execute(
        text(f"SELECT count(*) FROM meta._ingest_log l WHERE {where_clause}"),  # nosec B608
        params,
    )
    filtered = int(filtered_result.scalar() or 0)

    rows_result = await db.execute(
        text(
            f"SELECT {_RUN_COLUMNS} {_RUN_FROM} WHERE {where_clause} "
            "ORDER BY l.started_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = rows_result.mappings().all()

    has_more = offset + limit < filtered
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    return PublicRunsListResponse(
        meta=PublicRunsMeta(total=total, filtered=filtered),
        data=[_row_to_public_run_out(dict(row)) for row in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# `error_message` is deliberately excluded from `_RUN_COLUMNS` above (see
# `PublicRunOut`'s own docstring) -- these two endpoints exist
# specifically to surface it (redacted), so they need their own,
# wider column list.
_FAILURE_RUN_COLUMNS = "l.id, l.source, l.status, l.started_at, l.finished_at, l.error_message"
_FAILURE_RUN_FROM = "FROM meta._ingest_log l"


async def list_failed_public(
    db: AsyncSession, *, limit: int, cursor: str | None
) -> PublicFailedRunsListResponse:
    """`GET /v1/ingestion/public/failed` -- ported from data-pipeline's
    `service.pipelines.list_failed_public` (same query shape, same
    `_classify_error`/redaction), scoped to this service's own 5
    sources via `_SOURCE_TO_CATALOG_ID`."""
    now = datetime.now(UTC)

    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            offset = 0

    counts_result = await db.execute(
        text(
            "SELECT "
            "count(*) FILTER (WHERE started_at >= :since_24h) AS failed_24h, "
            "count(*) FILTER (WHERE started_at >= :since_7d) AS failed_7d "
            "FROM meta._ingest_log WHERE status = 'failed'"
        ),
        {"since_24h": now - _STATS_WINDOW_24H, "since_7d": now - _STATS_WINDOW_7D},
    )
    counts = counts_result.mappings().one()

    total_result = await db.execute(
        text("SELECT count(*) FROM meta._ingest_log WHERE status = 'failed'")
    )
    total = int(total_result.scalar() or 0)

    rows_result = await db.execute(
        text(
            f"SELECT {_FAILURE_RUN_COLUMNS} {_FAILURE_RUN_FROM} WHERE l.status = 'failed' "
            "ORDER BY l.started_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    )
    rows = rows_result.mappings().all()

    data: list[PublicFailedRunOut] = []
    for row in rows:
        message = _redact_public_error_message(
            row["error_message"] or "no error message recorded"
        )
        code = _classify_error(message)
        retryable = code not in _NON_RETRYABLE_ERROR_CODES
        duration_ms = None
        if row["finished_at"] is not None:
            duration_ms = round((row["finished_at"] - row["started_at"]).total_seconds() * 1000)
        pipeline_id = _SOURCE_TO_CATALOG_ID.get(row["source"], row["source"])
        data.append(
            PublicFailedRunOut(
                run_id=str(row["id"]),
                pipeline_id=pipeline_id,
                source_id=pipeline_id,
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                duration_ms=duration_ms,
                error=PublicFailedRunError(
                    code=code, message=message, http_status=None, retryable=retryable
                ),
                can_retry_now=retryable,
            )
        )

    has_more = offset + limit < total
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode() if has_more else None
    )

    return PublicFailedRunsListResponse(
        meta=PublicFailedRunsMeta(
            total_failed_24h=int(counts["failed_24h"]),
            total_failed_7d=int(counts["failed_7d"]),
            as_of=now,
        ),
        data=data,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def list_retry_queue_public(db: AsyncSession, *, limit: int) -> PublicRetryQueueListResponse:
    """`GET /v1/ingestion/public/retry-queue` -- `meta._ingest_log` rows
    with `status='sync_failed'` (fetched fine, warehouse-sync load
    failed). Same "no automated backoff engine" honest-null contract as
    data-pipeline's identical endpoint."""
    now = datetime.now(UTC)

    rows_result = await db.execute(
        text(
            f"SELECT {_FAILURE_RUN_COLUMNS} {_FAILURE_RUN_FROM} WHERE l.status = 'sync_failed' "
            "ORDER BY l.finished_at ASC NULLS LAST LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = rows_result.mappings().all()

    size_result = await db.execute(
        text(
            "SELECT count(*) AS cnt, min(finished_at) AS oldest "
            "FROM meta._ingest_log WHERE status = 'sync_failed'"
        )
    )
    size_row = size_result.mappings().one()

    data: list[PublicRetryQueueItem] = []
    for row in rows:
        message = _redact_public_error_message(
            row["error_message"] or "no error message recorded"
        )
        pipeline_id = _SOURCE_TO_CATALOG_ID.get(row["source"], row["source"])
        data.append(
            PublicRetryQueueItem(
                queue_id=f"rq-{row['id']}",
                run_id=str(row["id"]),
                pipeline_id=pipeline_id,
                source_id=pipeline_id,
                queued_at=row["finished_at"] or row["started_at"],
                last_error=PublicRetryQueueLastError(code=_classify_error(message), message=message),
            )
        )

    return PublicRetryQueueListResponse(
        meta=PublicRetryQueueMeta(
            queue_size=int(size_row["cnt"]),
            oldest_queued_at=size_row["oldest"],
            as_of=now,
        ),
        data=data,
    )


async def get_scheduler_status_public(db: AsyncSession) -> PublicSchedulerResponse:
    """`GET /v1/ingestion/public/scheduler` -- simplified vs. data-
    pipeline's equivalent (no `meta.pipelines` pause state, no dbt
    pipeline, no Prefect concept -- this service genuinely has none of
    those, see `PublicSchedulerStatus`'s own docstring). `queue_depth`
    reads the same shared `meta._ingest_log` data-pipeline's identical
    endpoint does -- real global queue depth regardless of which
    service's runs are actually in flight, not scoped to this service's
    own triggers only.

    No Redis cache (unlike data-pipeline's `SCHEDULER_CACHE_KEY`-cached
    version) -- same reasoning `list_pipelines_public`'s own module
    docstring gives: no real traffic yet to justify the extra moving
    part.
    """
    now = datetime.now(UTC)
    next_run_at = _next_run_at(now)

    depth_result = await db.execute(
        text("SELECT count(*) FROM meta._ingest_log WHERE status IN ('running', 'staged')")
    )
    queue_depth = int(depth_result.scalar() or 0)

    # A scheduled ("schedule"-triggered) run in roughly the last Beat
    # interval is real evidence the worker+beat pair is actually alive --
    # not a live Celery broker inspect call (real, but a slower/less
    # reliable thing to do inline in an HTTP request), a derived signal
    # from data already being queried elsewhere in this module.
    recent_schedule_result = await db.execute(
        text(
            "SELECT count(*) FROM meta._ingest_log "
            "WHERE triggered_by = 'schedule' AND started_at >= :since"
        ),
        {"since": now - timedelta(minutes=40)},
    )
    worker_alive = int(recent_schedule_result.scalar() or 0) > 0

    upcoming = [
        PublicUpcomingRun(
            pipeline_id=entry.id,
            source_id=entry.id,
            scheduled_at=next_run_at,
        )
        for entry in CATALOG
    ]

    sources = [entry.ingest_source for entry in CATALOG]
    recent_result = await db.execute(
        text(
            "SELECT id, source, status, started_at, finished_at "
            "FROM meta._ingest_log WHERE source = ANY(:sources) "
            "ORDER BY started_at DESC LIMIT 10"
        ),
        {"sources": sources},
    )
    recent_runs = [
        PublicRecentRunSummary(
            run_id=str(row["id"]),
            pipeline_id=_SOURCE_TO_CATALOG_ID.get(row["source"], row["source"]),
            status=row["status"],
            finished_at=row["finished_at"],
            duration_ms=(
                round((row["finished_at"] - row["started_at"]).total_seconds() * 1000)
                if row["finished_at"] is not None
                else None
            ),
        )
        for row in recent_result.mappings().all()
    ]

    return PublicSchedulerResponse(
        scheduler=PublicSchedulerStatus(
            as_of=now,
            active_workers=1 if worker_alive else 0,
            total_workers=1,
            queue_depth=queue_depth,
        ),
        upcoming_runs=upcoming,
        recent_runs=recent_runs,
    )
