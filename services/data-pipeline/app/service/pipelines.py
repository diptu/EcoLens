"""`GET/POST /v1/ingestion/*` (API_SPECEFICATIONS.md §2.1-2.8).

Reframes the spec's Prefect/MongoDB/DLQ-flavoured fictional architecture
onto what this service actually runs — see `app.models.pipelines`'s
module docstring for the pipeline-count mismatch (6 real, not 8), and
each schema class's docstring in `api/schemas/pipelines.py` for which
fields are real data vs. an honestly-empty placeholder (lineage, retry
chain, Prefect metadata). Two real, useful things this module adds beyond
what `datasources/service.py`+`monitoring.py` already track:

1. `meta.pipelines` — a genuine pause/resume switch, enforced (unlike
   `PATCH .../schedule.cron`, which is cosmetic — see its own docstring)
   at the one real entrypoint GitHub Actions cron actually calls:
   `cli.py`'s `ingest` commands check `is_pipeline_paused()` before
   running when invoked with `--triggered-by schedule`.
2. `/retry-queue` and `/failed` surface real `meta._ingest_log` rows
   (`sync_failed` / `failed` respectively) instead of a fabricated retry/
   backoff/DLQ engine — there isn't one; see `RetryQueueItem`'s docstring.
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.schemas.pipelines import (
    FailedRunError,
    FailedRunOut,
    FailedRunsMeta,
    FailedRunsResponse,
    PauseResponse,
    PipelineOut,
    PipelinesListResponse,
    PipelinesMeta,
    PipelineScheduleInfo,
    PublicRunOut,
    PublicRunsListResponse,
    RecentRunSummary,
    ResumeResponse,
    RetryQueueItem,
    RetryQueueLastError,
    RetryQueueMeta,
    RetryQueueResponse,
    RunDetail,
    RunLineage,
    RunOut,
    RunsListResponse,
    RunsMeta,
    SchedulerResponse,
    SchedulerStatus,
    UpcomingRun,
)
from app.core.config import Settings
from app.models.datasources import CATALOG, CATALOG_BY_ID
from app.service.datasources.monitoring import _classify_error
from app.service.datasources.service import (
    _fetch_source_configs,
    _percentile,
    fetch_run_rows,
)
from app.service.pipeline.tasks.registry import SOURCES
from app.models.pipelines import (
    PIPELINES,
    PIPELINES_BY_ID,
    UNPAUSABLE_PIPELINE_ID,
    PipelineDef,
)

PIPELINES_CACHE_KEY = "ingestion:pipelines:v1"
PIPELINES_CACHE_TTL = 15
RUNS_CACHE_TTL = 30
SCHEDULER_CACHE_KEY = "ingestion:scheduler:v1"
SCHEDULER_CACHE_TTL = 10

_STATS_WINDOW_24H = timedelta(hours=24)
_STATS_WINDOW_7D = timedelta(days=7)

_SOURCE_TO_DS_ID = {entry.ingest_source: entry.id for entry in CATALOG}
_SOURCE_TO_PIPELINE_ID = {
    CATALOG_BY_ID[p.source_id].ingest_source: p.id for p in PIPELINES if p.source_id
}
# Not retryable: the error is about *what* was fetched/configured, not a
# transient upstream hiccup -- retrying immediately would just fail the
# same way again.
_NON_RETRYABLE_ERROR_CODES = {"missing_credentials", "schema_mismatch"}

# Defense-in-depth for the public (unauthenticated) failed/retry-queue
# endpoints: `error_message` is `str(exception)[:500]` from whatever a
# source's HTTP client/SDK raised (`pipeline/tasks/_common.py`'s
# `standard_run`). BoM/AEMO NEM/AEMO WEM/holidays hit plain unauthenticated
# URLs (nothing to leak), but OpenElectricity's ingestion goes through its
# official third-party SDK with `settings.oe_api_key` -- whether *that*
# SDK's exceptions ever echo the key back isn't something this codebase
# can verify without auditing that dependency's internals, so redact
# anything that looks like a credential rather than assume every message
# is safe to expose without a bearer token.
_SECRET_LIKE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*\S+"
)


def _redact_public_error_message(message: str) -> str:
    return _SECRET_LIKE_PATTERN.sub(lambda m: f"{m.group(1)}: [redacted]", message)


def _run_pipeline_id(source: str) -> str:
    return _SOURCE_TO_PIPELINE_ID.get(source, f"pipe-{source}")


async def _pipeline_statuses(db: AsyncSession) -> dict[str, dict[str, Any]]:
    result = await db.execute(
        text("SELECT id, status, paused_at, paused_by, reason FROM meta.pipelines")
    )
    return {row["id"]: dict(row) for row in result.mappings().all()}


async def _resolve_schedule(
    db: AsyncSession, pipeline: PipelineDef, pipeline_status: str
) -> tuple[str, str, bool]:
    """`(cron, timezone, effectively_enabled)` — for an extract pipeline,
    "effectively enabled" also requires the underlying data source's own
    `enabled` flag (`meta.data_sources`, `PATCH /v1/data-sources/{id}`);
    for the dbt pipeline it's just this pipeline's own pause state."""
    if pipeline.source_id is None:
        return pipeline.cron, pipeline.timezone, pipeline_status == "active"

    entry = CATALOG_BY_ID[pipeline.source_id]
    configs = await _fetch_source_configs(db, [pipeline.source_id])
    config = configs.get(pipeline.source_id, {})
    cron = config.get("cron") or entry.cron
    timezone = config.get("timezone") or entry.timezone
    source_enabled = bool(config.get("enabled", True))
    return cron, timezone, source_enabled and pipeline_status == "active"


def _next_run_at(cron: str, timezone: str, now: datetime) -> datetime:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return croniter(cron, now.astimezone(tz)).get_next(datetime).astimezone(UTC)


async def list_pipelines(
    db: AsyncSession, redis: Redis, settings: Settings
) -> PipelinesListResponse:
    cached = await redis.get(PIPELINES_CACHE_KEY)
    if cached is not None:
        return PipelinesListResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    statuses = await _pipeline_statuses(db)
    extract_sources = [
        CATALOG_BY_ID[p.source_id].ingest_source for p in PIPELINES if p.source_id
    ]
    run_rows = await fetch_run_rows(db, extract_sources, now - _STATS_WINDOW_24H)

    data: list[PipelineOut] = []
    for pipeline in PIPELINES:
        status_row = statuses.get(pipeline.id, {"status": "active"})
        pipeline_status = status_row["status"]
        cron, timezone, enabled = await _resolve_schedule(db, pipeline, pipeline_status)

        runs: list[dict[str, Any]] = []
        if pipeline.source_id is not None:
            runs = run_rows.get(CATALOG_BY_ID[pipeline.source_id].ingest_source, [])

        successes = sum(1 for r in runs if r["status"] == "success")
        durations_ms = [
            (r["finished_at"] - r["started_at"]).total_seconds() * 1000
            for r in runs
            if r["finished_at"] is not None
        ]
        next_run_at = _next_run_at(cron, timezone, now) if enabled else None

        data.append(
            PipelineOut(
                id=pipeline.id,
                name=pipeline.name,
                source_id=pipeline.source_id,
                stage=pipeline.stage,
                status=pipeline_status,
                schedule=PipelineScheduleInfo(
                    cron=cron, timezone=timezone, enabled=enabled
                ),
                depends_on=list(pipeline.depends_on),
                last_run_at=runs[0]["started_at"] if runs else None,
                next_run_at=next_run_at,
                run_count_24h=len(runs),
                success_rate_24h=round(100 * successes / len(runs), 1)
                if runs
                else None,
                p95_duration_ms_24h=_percentile(durations_ms, 95),
            )
        )

    response = PipelinesListResponse(
        meta=PipelinesMeta(
            total=len(data),
            active=sum(1 for p in data if p.status == "active"),
            paused=sum(1 for p in data if p.status == "paused"),
            as_of=now,
        ),
        data=data,
    )
    await redis.set(
        PIPELINES_CACHE_KEY, response.model_dump_json(), ex=PIPELINES_CACHE_TTL
    )
    return response


def _row_to_run_out(row: dict[str, Any]) -> RunOut:
    duration_ms = None
    if row["finished_at"] is not None:
        duration_ms = round(
            (row["finished_at"] - row["started_at"]).total_seconds() * 1000
        )
    rows_landed = row.get("rows_landed")
    rows_loaded = row.get("rows_loaded")
    return RunOut(
        id=str(row["id"]),
        pipeline_id=_run_pipeline_id(row["source"]),
        source_id=_SOURCE_TO_DS_ID.get(row["source"], row["source"]),
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
        error=row.get("error_message"),
        metadata={
            "hostname": row.get("hostname"),
            "circuit_breaker_state": row.get("circuit_breaker_state"),
            "window_start": row.get("window_start"),
            "window_end": row.get("window_end"),
        },
    )


_RUN_COLUMNS = (
    "l.id, l.source, l.status, l.started_at, l.finished_at, l.rows_landed, l.rows_loaded, "
    "l.error_message, l.triggered_by, l.hostname, l.circuit_breaker_state, "
    "l.window_start, l.window_end, COALESCE(a.cnt, 0) AS anomalies_flagged"
)
_RUN_FROM = (
    "FROM meta._ingest_log l "
    "LEFT JOIN (SELECT run_id, count(*) AS cnt FROM meta.anomalies GROUP BY run_id) a "
    "  ON a.run_id = l.id"
)


async def list_runs(
    db: AsyncSession,
    redis: Redis,
    *,
    pipeline_id: str | None,
    source_id: str | None,
    status: str | None,
    trigger: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
    cursor: str | None,
) -> RunsListResponse:
    cache_key = f"ingestion:runs:v1:{pipeline_id}:{source_id}:{status}:{trigger}:{from_}:{to}:{limit}:{cursor}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return RunsListResponse.model_validate_json(cached)

    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            offset = 0

    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    source = None
    if source_id is not None:
        entry = CATALOG_BY_ID.get(source_id)
        source = entry.ingest_source if entry else "__no_such_source__"
    elif pipeline_id is not None:
        pipeline = PIPELINES_BY_ID.get(pipeline_id)
        source = (
            CATALOG_BY_ID[pipeline.source_id].ingest_source
            if pipeline and pipeline.source_id
            else "__no_such_source__"
        )
    if source is not None:
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

    total_result = await db.execute(text("SELECT count(*) FROM meta._ingest_log l"))
    total = int(total_result.scalar() or 0)

    filtered_count_result = await db.execute(
        text(f"SELECT count(*) FROM meta._ingest_log l WHERE {where_clause}"),  # nosec B608
        params,
    )
    filtered = int(filtered_count_result.scalar() or 0)

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

    response = RunsListResponse(
        meta=RunsMeta(total=total, filtered=filtered),
        data=[_row_to_run_out(dict(row)) for row in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )
    await redis.set(cache_key, response.model_dump_json(), ex=RUNS_CACHE_TTL)
    return response


async def list_runs_public(
    db: AsyncSession,
    redis: Redis,
    *,
    pipeline_id: str | None,
    source_id: str | None,
    status: str | None,
    trigger: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
    cursor: str | None,
) -> PublicRunsListResponse:
    """Unauthenticated projection of `list_runs` for `GET
    /v1/ingestion/public/runs` -- drops `RunOut.error` (raw
    `str(exception)[:500]`, not needed for the dashboard's Runs tab) and
    `.metadata` (its `hostname` key is internal infra detail). See
    `PublicRunOut`'s docstring."""
    full = await list_runs(
        db,
        redis,
        pipeline_id=pipeline_id,
        source_id=source_id,
        status=status,
        trigger=trigger,
        from_=from_,
        to=to,
        limit=limit,
        cursor=cursor,
    )
    return PublicRunsListResponse(
        meta=full.meta,
        data=[
            PublicRunOut(**r.model_dump(exclude={"error", "metadata"}))
            for r in full.data
        ],
        next_cursor=full.next_cursor,
        has_more=full.has_more,
    )


async def get_run(db: AsyncSession, run_id: str) -> RunDetail:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as exc:
        raise ApiError(404, "not_found", f"No run with id '{run_id}'") from exc

    result = await db.execute(
        text(f"SELECT {_RUN_COLUMNS} {_RUN_FROM} WHERE l.id = :id"),
        {"id": str(run_uuid)},
    )
    mapping = result.mappings().first()
    if mapping is None:
        raise ApiError(404, "not_found", f"No run with id '{run_id}'")

    row = dict(mapping)
    run_out = _row_to_run_out(row)
    registry_key = _registry_key_for_source(row["source"])
    table = SOURCES[registry_key].table if registry_key else None

    return RunDetail(
        **run_out.model_dump(),
        lineage=RunLineage(
            input_datasets=[],
            output_datasets=[f"raw.{table}"] if table else [],
            downstream_runs=[],
        ),
        retry_chain=[],
        logs_url=None,
        prefect_ui_url=None,
    )


def _registry_key_for_source(source: str) -> str | None:
    for key, entry in SOURCES.items():
        if entry.source == source:
            return key
    return None


async def list_failed(
    db: AsyncSession, *, limit: int, cursor: str | None
) -> FailedRunsResponse:
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
            f"SELECT {_RUN_COLUMNS} {_RUN_FROM} WHERE l.status = 'failed' "
            "ORDER BY l.started_at DESC LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    )
    rows = [dict(r) for r in rows_result.mappings().all()]

    data = []
    for row in rows:
        message = row.get("error_message") or "no error message recorded"
        code = _classify_error(message)
        retryable = code not in _NON_RETRYABLE_ERROR_CODES
        duration_ms = None
        if row["finished_at"] is not None:
            duration_ms = round(
                (row["finished_at"] - row["started_at"]).total_seconds() * 1000
            )
        data.append(
            FailedRunOut(
                run_id=str(row["id"]),
                pipeline_id=_run_pipeline_id(row["source"]),
                source_id=_SOURCE_TO_DS_ID.get(row["source"], row["source"]),
                status="failed",
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                duration_ms=duration_ms,
                error=FailedRunError(
                    code=code, message=message, http_status=None, retryable=retryable
                ),
                retry_count=0,
                next_retry_at=None,
                in_dlq=False,
                can_retry_now=retryable,
            )
        )

    has_more = offset + limit < total
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    return FailedRunsResponse(
        meta=FailedRunsMeta(
            total_failed_24h=int(counts["failed_24h"]),
            total_failed_7d=int(counts["failed_7d"]),
            as_of=now,
        ),
        data=data,
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def list_failed_public(
    db: AsyncSession, *, limit: int, cursor: str | None
) -> FailedRunsResponse:
    """Unauthenticated projection of `list_failed` for `GET
    /v1/ingestion/public/failed` -- same shape, `error.message` redacted
    (see `_redact_public_error_message`)."""
    full = await list_failed(db, limit=limit, cursor=cursor)
    redacted = [
        item.model_copy(
            update={
                "error": item.error.model_copy(
                    update={"message": _redact_public_error_message(item.error.message)}
                )
            }
        )
        for item in full.data
    ]
    return full.model_copy(update={"data": redacted})


async def list_retry_queue(db: AsyncSession, *, limit: int) -> RetryQueueResponse:
    now = datetime.now(UTC)

    result = await db.execute(
        text(
            f"SELECT {_RUN_COLUMNS} {_RUN_FROM} WHERE l.status = 'sync_failed' "
            "ORDER BY l.finished_at ASC NULLS LAST LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = [dict(r) for r in result.mappings().all()]

    size_result = await db.execute(
        text(
            "SELECT count(*) AS cnt, min(finished_at) AS oldest "
            "FROM meta._ingest_log WHERE status = 'sync_failed'"
        )
    )
    # A bare `count(*)`/`min(...)` aggregate with no GROUP BY always
    # returns exactly one row.
    size_row = size_result.mappings().one()

    data = []
    for row in rows:
        message = row.get("error_message") or "no error message recorded"
        data.append(
            RetryQueueItem(
                queue_id=f"rq-{row['id']}",
                run_id=str(row["id"]),
                pipeline_id=_run_pipeline_id(row["source"]),
                source_id=_SOURCE_TO_DS_ID.get(row["source"], row["source"]),
                queued_at=row["finished_at"] or row["started_at"],
                next_retry_at=None,
                retry_count=0,
                max_retries=None,
                last_error=RetryQueueLastError(
                    code=_classify_error(message), message=message
                ),
                backoff_strategy="manual",
                backoff_base_seconds=None,
            )
        )

    return RetryQueueResponse(
        meta=RetryQueueMeta(
            queue_size=int(size_row["cnt"]),
            oldest_queued_at=size_row["oldest"],
            as_of=now,
        ),
        data=data,
    )


async def list_retry_queue_public(
    db: AsyncSession, *, limit: int
) -> RetryQueueResponse:
    """Unauthenticated projection of `list_retry_queue` for `GET
    /v1/ingestion/public/retry-queue` -- same shape, `last_error.message`
    redacted (see `_redact_public_error_message`)."""
    full = await list_retry_queue(db, limit=limit)
    redacted = [
        item.model_copy(
            update={
                "last_error": item.last_error.model_copy(
                    update={
                        "message": _redact_public_error_message(item.last_error.message)
                    }
                )
            }
        )
        for item in full.data
    ]
    return full.model_copy(update={"data": redacted})


async def get_scheduler_status(db: AsyncSession, redis: Redis) -> SchedulerResponse:
    cached = await redis.get(SCHEDULER_CACHE_KEY)
    if cached is not None:
        return SchedulerResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    statuses = await _pipeline_statuses(db)

    depth_result = await db.execute(
        text(
            "SELECT count(*) FROM meta._ingest_log WHERE status IN ('running', 'staged')"
        )
    )
    queue_depth = int(depth_result.scalar() or 0)

    upcoming: list[UpcomingRun] = []
    for pipeline in PIPELINES:
        pipeline_status = statuses.get(pipeline.id, {"status": "active"})["status"]
        cron, timezone, enabled = await _resolve_schedule(db, pipeline, pipeline_status)
        if not enabled:
            continue
        upcoming.append(
            UpcomingRun(
                pipeline_id=pipeline.id,
                source_id=pipeline.source_id,
                scheduled_at=_next_run_at(cron, timezone, now),
            )
        )
    upcoming.sort(key=lambda u: u.scheduled_at)

    all_sources = [entry.ingest_source for entry in CATALOG]
    run_rows = await fetch_run_rows(db, all_sources, now - _STATS_WINDOW_24H)
    recent: list[dict[str, Any]] = [r for rows in run_rows.values() for r in rows]
    recent.sort(key=lambda r: r["started_at"], reverse=True)

    recent_runs = []
    for row in recent[:10]:
        duration_ms = None
        if row["finished_at"] is not None:
            duration_ms = round(
                (row["finished_at"] - row["started_at"]).total_seconds() * 1000
            )
        recent_runs.append(
            RecentRunSummary(
                run_id=str(row["id"]),
                pipeline_id=_run_pipeline_id(row["source"]),
                status=row["status"],
                finished_at=row["finished_at"],
                duration_ms=duration_ms,
            )
        )

    response = SchedulerResponse(
        scheduler=SchedulerStatus(as_of=now, queue_depth=queue_depth),
        upcoming_runs=upcoming,
        recent_runs=recent_runs,
    )
    await redis.set(
        SCHEDULER_CACHE_KEY, response.model_dump_json(), ex=SCHEDULER_CACHE_TTL
    )
    return response


async def _invalidate_pipelines_cache(redis: Redis) -> None:
    await redis.delete(PIPELINES_CACHE_KEY)
    await redis.delete(SCHEDULER_CACHE_KEY)


async def _in_flight_runs(db: AsyncSession, pipeline: PipelineDef) -> int:
    if pipeline.source_id is None:
        return 0
    entry = CATALOG_BY_ID[pipeline.source_id]
    result = await db.execute(
        text(
            "SELECT count(*) FROM meta._ingest_log "
            "WHERE source = :source AND status IN ('running', 'staged')"
        ),
        {"source": entry.ingest_source},
    )
    return int(result.scalar() or 0)


async def pause_pipeline(
    db: AsyncSession, redis: Redis, id: str, reason: str | None, paused_by: str
) -> PauseResponse:
    pipeline = PIPELINES_BY_ID.get(id)
    if pipeline is None:
        raise ApiError(404, "not_found", f"No pipeline with id '{id}'")
    if id == UNPAUSABLE_PIPELINE_ID:
        raise ApiError(
            409,
            "cannot_pause_dbt",
            f"Cannot pause '{id}' — it's the only transform pipeline",
        )

    current = (await _pipeline_statuses(db)).get(id, {"status": "active"})
    if current["status"] == "paused":
        in_flight = await _in_flight_runs(db, pipeline)
        return PauseResponse(
            id=id,
            paused_at=current["paused_at"],
            paused_by=current["paused_by"] or paused_by,
            reason=current.get("reason"),
            in_flight_runs=in_flight,
        )

    result = await db.execute(
        text(
            "UPDATE meta.pipelines SET status = 'paused', paused_at = now(), "
            "paused_by = :paused_by, reason = :reason, updated_at = now() "
            "WHERE id = :id RETURNING paused_at, paused_by, reason"
        ),
        {"id": id, "paused_by": paused_by, "reason": reason},
    )
    row = result.mappings().first()
    if row is None:  # pragma: no cover - id is checked against PIPELINES_BY_ID first
        raise ApiError(404, "not_found", f"No pipeline with id '{id}'")
    await _invalidate_pipelines_cache(redis)

    return PauseResponse(
        id=id,
        paused_at=row["paused_at"],
        paused_by=row["paused_by"],
        reason=row["reason"],
        in_flight_runs=await _in_flight_runs(db, pipeline),
    )


async def resume_pipeline(
    db: AsyncSession, redis: Redis, id: str, resumed_by: str
) -> ResumeResponse:
    pipeline = PIPELINES_BY_ID.get(id)
    if pipeline is None:
        raise ApiError(404, "not_found", f"No pipeline with id '{id}'")

    now = datetime.now(UTC)
    current = (await _pipeline_statuses(db)).get(id, {"status": "active"})
    if current["status"] == "active":
        cron, timezone, enabled = await _resolve_schedule(db, pipeline, "active")
        next_run = _next_run_at(cron, timezone, now) if enabled else None
        return ResumeResponse(
            id=id, resumed_at=now, resumed_by=resumed_by, next_scheduled_run=next_run
        )

    await db.execute(
        text(
            "UPDATE meta.pipelines SET status = 'active', paused_at = NULL, "
            "paused_by = NULL, reason = NULL, updated_at = now() WHERE id = :id"
        ),
        {"id": id},
    )
    await _invalidate_pipelines_cache(redis)

    cron, timezone, enabled = await _resolve_schedule(db, pipeline, "active")
    next_run = _next_run_at(cron, timezone, now) if enabled else None
    return ResumeResponse(
        id=id, resumed_at=now, resumed_by=resumed_by, next_scheduled_run=next_run
    )


async def is_pipeline_paused(db: AsyncSession, registry_key: str) -> bool:
    """Used by `cli.py`'s `ingest` commands to gate `--triggered-by
    schedule` runs — the one real enforcement point for a pipeline pause,
    since that's the entrypoint GitHub Actions cron actually calls."""
    pipeline_id = f"pipe-{registry_key}"
    result = await db.execute(
        text("SELECT status FROM meta.pipelines WHERE id = :id"), {"id": pipeline_id}
    )
    row = result.first()
    return row is not None and row[0] == "paused"
