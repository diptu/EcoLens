"""`GET /v1/data-sources/{id}/health` and `GET /v1/data-sources/{id}/history`
(API_SPECEFICATIONS.md §1.5-1.6) — read-only, higher-resolution views on
top of the same `meta._ingest_log`/circuit-breaker data
`app.service.datasources.service` already summarises for the list/single
endpoints.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.datasources import (
    CircuitBreakerDetail,
    HistoryRun,
    RecentRun,
    SourceHealthResponse,
    SourceHistoryResponse,
)
from app.db.redis import get_breaker
from app.core.config import Settings
from app.service.datasources.service import (
    _derive_health_status,
    _fetch_source_configs,
    _percentile,
    fetch_run_rows,
    require_catalog_entry,
)
from app.service.pipeline.circuit_breaker import CircuitState

HEALTH_CACHE_TTL_SECONDS = 10
HEALTH_CACHE_PREFIX = "datasources:health:v1"
HISTORY_CACHE_TTL_SECONDS = 60
HISTORY_CACHE_PREFIX = "datasources:history:v1"
_HEALTH_WINDOW = timedelta(days=30)

_ERROR_CODES = ("missing_credentials", "timeout", "rate_limited", "schema_mismatch")


def _classify_error(message: str) -> str | None:
    """Best-effort keyword match into `API_SPECEFICATIONS.md` §1.5's fixed
    `errors_by_code_24h` vocabulary. `error_message` is a free-text
    exception string (`str(exc)[:500]`, `_common._log_run_finish`), not a
    structured error code, so this is a heuristic, not an exact
    classification — messages that don't match any keyword aren't
    counted under any code (undercounting is the failure mode, not
    silently mis-bucketing)."""
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


async def _circuit_breaker_detail(
    source: str, redis: Redis, reset_timeout: float
) -> CircuitBreakerDetail:
    state = await get_breaker(source).state
    opened_at_raw = await redis.get(f"circuit_breaker:{source}:opened_at")
    opened_at = (
        datetime.fromtimestamp(float(opened_at_raw), tz=UTC)
        if opened_at_raw is not None
        else None
    )
    half_open_at = (
        opened_at + timedelta(seconds=reset_timeout) if opened_at is not None else None
    )
    return CircuitBreakerDetail(
        state=state.value,
        opened_at=opened_at,
        half_open_at=half_open_at,
        recovery_seconds=int(reset_timeout),
    )


async def get_source_health(
    db: AsyncSession, redis: Redis, settings: Settings, id: str
) -> SourceHealthResponse:
    entry = require_catalog_entry(id)
    source = entry.ingest_source

    cache_key = f"{HEALTH_CACHE_PREFIX}:{id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return SourceHealthResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    configs = await _fetch_source_configs(db, [id])
    enabled = bool(configs.get(id, {}).get("enabled", True))
    run_rows = (await fetch_run_rows(db, [source], now - _HEALTH_WINDOW))[source]

    def _success_rate(since: datetime) -> float | None:
        window = [r for r in run_rows if r["started_at"] >= since]
        if not window:
            return None
        successes = sum(1 for r in window if r["status"] == "success")
        return round(100 * successes / len(window), 1)

    consecutive_failures = 0
    for run in run_rows:
        if run["status"] == "failed":
            consecutive_failures += 1
        else:
            break

    durations_ms = [
        (r["finished_at"] - r["started_at"]).total_seconds() * 1000
        for r in run_rows
        if r["finished_at"] is not None
    ]

    breaker_detail = await _circuit_breaker_detail(
        source, redis, settings.circuit_breaker_reset_timeout
    )

    status = _derive_health_status(
        enabled=enabled,
        circuit_state=CircuitState(breaker_detail.state),
        consecutive_failures=consecutive_failures,
        success_rate_24h=_success_rate(now - timedelta(hours=24)),
        failure_threshold=settings.circuit_breaker_failure_threshold,
    )

    cutoff_24h = now - timedelta(hours=24)
    errors_by_code = dict.fromkeys(_ERROR_CODES, 0)
    for run in run_rows:
        if run["started_at"] < cutoff_24h or not run.get("error_message"):
            continue
        code = _classify_error(run["error_message"])
        if code:
            errors_by_code[code] += 1

    last_5 = []
    for run in run_rows[:5]:
        duration_ms = None
        if run["finished_at"] is not None:
            duration_ms = round(
                (run["finished_at"] - run["started_at"]).total_seconds() * 1000
            )
        last_5.append(
            RecentRun(
                id=str(run["id"]),
                status=run["status"],
                duration_ms=duration_ms,
                records=run["rows_loaded"],
                at=run["started_at"],
            )
        )

    response = SourceHealthResponse(
        source_id=id,
        status=status,
        as_of=now,
        success_rate_pct_1h=_success_rate(now - timedelta(hours=1)),
        success_rate_pct_24h=_success_rate(now - timedelta(hours=24)),
        success_rate_pct_7d=_success_rate(now - timedelta(days=7)),
        success_rate_pct_30d=_success_rate(now - timedelta(days=30)),
        p50_duration_ms=_percentile(durations_ms, 50),
        p95_duration_ms=_percentile(durations_ms, 95),
        p99_duration_ms=_percentile(durations_ms, 99),
        consecutive_failures=consecutive_failures,
        circuit_breaker=breaker_detail,
        last_5_runs=last_5,
        errors_by_code_24h=errors_by_code,
    )

    await redis.set(cache_key, response.model_dump_json(), ex=HEALTH_CACHE_TTL_SECONDS)
    return response


async def get_source_history(
    db: AsyncSession,
    redis: Redis,
    id: str,
    *,
    status: str | None,
    from_: datetime | None,
    to: datetime | None,
    limit: int,
    cursor: str | None,
) -> SourceHistoryResponse:
    entry = require_catalog_entry(id)
    source = entry.ingest_source

    cache_key = f"{HISTORY_CACHE_PREFIX}:{id}:{status}:{from_}:{to}:{limit}:{cursor}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return SourceHistoryResponse.model_validate_json(cached)

    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            offset = 0

    where = ["l.source = :source"]
    params: dict[str, Any] = {"source": source, "limit": limit, "offset": offset}
    if status:
        where.append("l.status = :status")
        params["status"] = status
    if from_:
        where.append("l.started_at >= :from_")
        params["from_"] = from_
    if to:
        where.append("l.started_at <= :to")
        params["to"] = to
    # `where`/`where_clause` below are only ever built from the fixed
    # literal clause fragments above (nosec B608 on both `text(...)` calls
    # that follow) -- actual values are always bound params, never
    # interpolated.
    where_clause = " AND ".join(where)

    total_result = await db.execute(
        text(f"SELECT count(*) FROM meta._ingest_log l WHERE {where_clause}"),  # nosec B608
        params,
    )
    total = int(total_result.scalar() or 0)

    rows_result = await db.execute(
        text(
            "SELECT l.id, l.status, l.started_at, l.finished_at, l.rows_landed, "
            "l.rows_loaded, l.error_message, l.triggered_by, "
            "COALESCE(a.cnt, 0) AS anomalies_flagged "
            "FROM meta._ingest_log l "
            "LEFT JOIN (SELECT run_id, count(*) AS cnt FROM meta.anomalies GROUP BY run_id) a "
            "  ON a.run_id = l.id "
            f"WHERE {where_clause} "  # nosec B608
            "ORDER BY l.started_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    rows = rows_result.mappings().all()

    data = []
    for row in rows:
        duration_ms = None
        if row["finished_at"] is not None:
            duration_ms = round(
                (row["finished_at"] - row["started_at"]).total_seconds() * 1000
            )
        rows_landed = row["rows_landed"]
        rows_loaded = row["rows_loaded"]
        duplicates_skipped = (
            max(0, rows_landed - rows_loaded)
            if rows_landed is not None and rows_loaded is not None
            else None
        )
        data.append(
            HistoryRun(
                id=str(row["id"]),
                status=row["status"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                duration_ms=duration_ms,
                records_fetched=rows_landed,
                records_inserted=rows_loaded,
                duplicates_skipped=duplicates_skipped,
                anomalies_flagged=row["anomalies_flagged"],
                trigger=row["triggered_by"] or "manual",
                error=row["error_message"],
            )
        )

    has_more = offset + limit < total
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    response = SourceHistoryResponse(
        source_id=id, total=total, data=data, next_cursor=next_cursor, has_more=has_more
    )

    await redis.set(cache_key, response.model_dump_json(), ex=HISTORY_CACHE_TTL_SECONDS)
    return response
