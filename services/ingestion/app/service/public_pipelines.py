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
from datetime import UTC, datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.datasources import CATALOG
from app.schemas.ingest.public import (
    PublicPipelineOut,
    PublicPipelineSchedule,
    PublicPipelinesListResponse,
    PublicPipelinesMeta,
    PublicRunOut,
    PublicRunsListResponse,
    PublicRunsMeta,
)

# The real cadence `app.celery_app`'s Beat schedule dispatches at for
# every source, unified since 2026-08-05 -- see `PublicPipelineOut`'s
# own docstring for why this isn't `CATALOG[].cron`.
_BEAT_CRON = "*/30 * * * *"
_BEAT_TIMEZONE = "UTC"

_STATS_WINDOW_24H = timedelta(hours=24)

_SOURCE_TO_CATALOG_ID = {entry.ingest_source: entry.id for entry in CATALOG}


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
