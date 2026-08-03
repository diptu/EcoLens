"""`GET /v1/data-quality/{summary,issues,outliers,schema}` and
`POST /v1/data-quality/recheck/{source}` (API_SPECEFICATIONS.md §3).

**What "data quality tests" actually means here.** There is no dbt-test-
results tracker in this codebase — `dbt test`'s pass/fail output isn't
parsed or persisted anywhere (`dbt_runner.runner.run_dbt` just returns an
exit code). Rather than fabricate one, this module reframes the spec's
"tests passed/failed" vocabulary onto two real, already-collected
signals:

- Every ingest run (`meta._ingest_log`) counts as one test: `failed`/
  `sync_failed` = failed, a `success`/`staged` run that had >=1 row
  flagged by `pipeline.anomaly` = warned, everything else = passed.
- `meta.anomalies` (rule-based + statistical flags) and
  `meta.schema_drifts` (`pipeline.schema_drift`) supply the actual
  *issues* (§3.2), *outliers* (§3.3), and *schema drift* (§3.4) detail.

`_generate_issues` is the one place that turns those two tables into the
`DataQualityIssue` shape — `list_issues` (§3.2) and `get_summary`'s
(§3.1) `by_severity_24h`/`by_source_24h`/`by_category_24h` both read from
it, so a source's issue count always means the same thing in both
responses. Issues are synthesized fresh on every call (not persisted) —
there's no acknowledge/resolve workflow behind `status`, since the spec
only documents a GET for issues, no endpoint to change one's status;
every synthesized issue reports `status="open"`.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.schemas.data_quality import (
    BySourceSummary,
    DataQualityIssue,
    DataQualityIssuesMeta,
    DataQualityIssuesResponse,
    DataQualityOutlier,
    DataQualityOutliersMeta,
    DataQualityOutliersResponse,
    DataQualitySchemaResponse,
    DataQualitySummaryResponse,
    ExpectedRange,
    OverallSummary,
    PublicDataQualitySummaryResponse,
    RecheckResponse,
    SchemaDriftOut,
    SchemaDriftSummary,
)
from app.models.datasources import CATALOG, CATALOG_BY_ID
from app.service.datasources.service import fetch_run_rows, require_catalog_entry
from app.db.session import get_session
from app.core.logging import get_logger
from app.service.pipeline import schema_drift
from app.service.pipeline.tasks.registry import run_source

log = get_logger(__name__)

SUMMARY_CACHE_TTL = 60
ISSUES_CACHE_TTL = 30
OUTLIERS_CACHE_TTL = 300
SCHEMA_CACHE_TTL = 300
IDEMPOTENCY_TTL_SECONDS = 3600
_STATS_WINDOW = timedelta(days=7)

_SOURCE_TO_ID = {entry.ingest_source: entry.id for entry in CATALOG}
_ID_TO_REGISTRY_KEY = {entry.id: entry.registry_key for entry in CATALOG}


def _severity_from_score(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


async def _generate_issues(db: AsyncSession) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    sources = [entry.ingest_source for entry in CATALOG]
    run_rows = await fetch_run_rows(db, sources, now - _STATS_WINDOW)

    issues: list[dict[str, Any]] = []

    # 1. Consecutive-failure clusters, one issue per source.
    for entry in CATALOG:
        runs = run_rows.get(entry.ingest_source, [])
        streak = []
        for run in runs:
            if run["status"] in ("failed", "sync_failed"):
                streak.append(run)
            else:
                break
        if streak:
            last_error = streak[0].get("error_message") or "no error message recorded"
            issues.append(
                {
                    "id": f"dq-failures-{entry.id}",
                    "source_id": entry.id,
                    "pipeline_id": f"pipe-{entry.registry_key}",
                    "severity": "critical" if len(streak) >= 5 else "high",
                    "category": "completeness",
                    "title": f"{entry.name}: {len(streak)} consecutive failed runs",
                    "description": f"Most recent failure: {last_error}",
                    "first_seen_at": streak[-1]["started_at"],
                    "last_seen_at": streak[0]["started_at"],
                    "occurrences": len(streak),
                    "status": "open",
                    "suggested_action": (
                        f"Check GET /v1/data-sources/{entry.id}/health and "
                        "meta._ingest_log.error_message for the failure reason."
                    ),
                    "auto_resolvable": False,
                }
            )

    # 2. Anomaly clusters, one issue per (source, metric) with >=1 flagged
    # row in the stats window.
    anomaly_result = await db.execute(
        text(
            "SELECT source, metric, count(*) AS occurrences, "
            "min(detected_at) AS first_seen_at, max(detected_at) AS last_seen_at, "
            "avg(anomaly_score) AS avg_score, "
            "bool_or(anomaly_reason LIKE 'missing_value%') AS any_missing "
            "FROM meta.anomalies "
            "WHERE detected_at >= :since AND metric IS NOT NULL "
            "GROUP BY source, metric"
        ),
        {"since": now - _STATS_WINDOW},
    )
    for row in anomaly_result.mappings().all():
        source_id = _SOURCE_TO_ID.get(row["source"])
        if source_id is None:
            continue
        entry = CATALOG_BY_ID[source_id]
        category = "completeness" if row["any_missing"] else "validity"
        issues.append(
            {
                "id": f"dq-anomaly-{source_id}-{row['metric']}",
                "source_id": source_id,
                "pipeline_id": f"pipe-{entry.registry_key}",
                "severity": _severity_from_score(float(row["avg_score"])),
                "category": category,
                "title": f"{row['metric']}: {row['occurrences']} flagged reading(s)",
                "description": (
                    f"{row['occurrences']} record(s) flagged for {row['metric']} "
                    f"in the last {_STATS_WINDOW.days} days (avg score "
                    f"{float(row['avg_score']):.2f})."
                ),
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "occurrences": row["occurrences"],
                "status": "open",
                "suggested_action": (
                    "Review GET /v1/data-quality/outliers?source_id="
                    f"{source_id}&metric={row['metric']} for the flagged records."
                ),
                "auto_resolvable": True,
            }
        )

    # 3. Schema drift, one issue per actionable drift.
    for drift in await schema_drift.get_recorded_drifts(db):
        if not drift["action_required"]:
            continue
        source_id = _SOURCE_TO_ID.get(drift["source"])
        if source_id is None:
            continue
        entry = CATALOG_BY_ID[source_id]
        issues.append(
            {
                "id": f"dq-schema-{drift['id']}",
                "source_id": source_id,
                "pipeline_id": f"pipe-{entry.registry_key}",
                "severity": drift["severity"],
                "category": "consistency",
                "title": f"Schema drift: {drift['kind']} on {drift['table_name']}.{drift['column_name']}",
                "description": (
                    drift["downstream_impact"]
                    or f"{drift['kind']} detected on {drift['table_name']}.{drift['column_name']} "
                    f"({drift['old_type']} -> {drift['new_type']})."
                ),
                "first_seen_at": drift["first_seen_at"],
                "last_seen_at": drift["last_checked_at"],
                "occurrences": 1,
                "status": "open",
                "suggested_action": "Update pipeline.schema_drift._EXPECTED_COLUMNS and the dbt staging model for this table.",
                "auto_resolvable": False,
            }
        )

    return issues


async def get_summary(db: AsyncSession, redis: Redis) -> DataQualitySummaryResponse:
    cache_key = "dataquality:summary:v1"
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataQualitySummaryResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    sources = [entry.ingest_source for entry in CATALOG]
    run_rows = await fetch_run_rows(db, sources, now - _STATS_WINDOW)
    issues = await _generate_issues(db)

    cutoff_24h = now - timedelta(hours=24)

    def _test_counts(runs: list[dict[str, Any]]) -> tuple[int, int, int, int]:
        total = len(runs)
        failed = sum(1 for r in runs if r["status"] in ("failed", "sync_failed"))
        warned = sum(
            1
            for r in runs
            if r["status"] not in ("failed", "sync_failed")
            and (r.get("anomalies_flagged") or 0) > 0
        )
        passed = total - failed - warned
        return total, passed, failed, warned

    total_24h = passed_24h = failed_24h = warned_24h = 0
    total_7d = passed_7d = 0
    by_source: list[BySourceSummary] = []
    issues_by_source: dict[str, int] = {}
    for issue in issues:
        issues_by_source[issue["source_id"]] = (
            issues_by_source.get(issue["source_id"], 0) + 1
        )

    for entry in CATALOG:
        runs = run_rows.get(entry.ingest_source, [])
        runs_24h = [r for r in runs if r["started_at"] >= cutoff_24h]
        t24, p24, f24, w24 = _test_counts(runs_24h)
        t7, p7, _, _ = _test_counts(runs)
        total_24h += t24
        passed_24h += p24
        failed_24h += f24
        warned_24h += w24
        total_7d += t7
        passed_7d += p7
        by_source.append(
            BySourceSummary(
                source_id=entry.id,
                pass_rate_pct=round(100 * p24 / t24, 1) if t24 else None,
                issues=issues_by_source.get(entry.id, 0),
            )
        )

    by_severity_24h = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_category_24h = {
        "completeness": 0,
        "validity": 0,
        "uniqueness": 0,
        "consistency": 0,
        "timeliness": 0,
    }
    for issue in issues:
        if issue["first_seen_at"] >= cutoff_24h or issue["last_seen_at"] >= cutoff_24h:
            by_severity_24h[issue["severity"]] = (
                by_severity_24h.get(issue["severity"], 0) + 1
            )
            by_category_24h[issue["category"]] = (
                by_category_24h.get(issue["category"], 0) + 1
            )

    response = DataQualitySummaryResponse(
        as_of=now,
        overall=OverallSummary(
            pass_rate_pct_24h=round(100 * passed_24h / total_24h, 1)
            if total_24h
            else None,
            pass_rate_pct_7d=round(100 * passed_7d / total_7d, 1) if total_7d else None,
            total_tests_24h=total_24h,
            tests_passed_24h=passed_24h,
            tests_failed_24h=failed_24h,
            tests_warned_24h=warned_24h,
        ),
        by_severity_24h=by_severity_24h,
        by_source_24h=by_source,
        by_category_24h=by_category_24h,
    )

    await redis.set(cache_key, response.model_dump_json(), ex=SUMMARY_CACHE_TTL)
    return response


async def get_public_summary(
    db: AsyncSession, redis: Redis
) -> PublicDataQualitySummaryResponse:
    """Backs `GET /v1/data-quality/summary/public` -- see that schema's
    own docstring for why this is a separate, unauthenticated endpoint
    rather than just relaxing `/summary`'s auth gate. Reuses `get_summary`
    (and its cache) rather than re-deriving the two numbers from scratch,
    so this can never disagree with the authenticated summary."""
    full = await get_summary(db, redis)
    open_risks = full.by_severity_24h.get("critical", 0) + full.by_severity_24h.get(
        "high", 0
    )
    return PublicDataQualitySummaryResponse(
        as_of=full.as_of,
        data_quality_score_pct=full.overall.pass_rate_pct_24h,
        open_risks_high_plus=open_risks,
    )


def _issue_cache_key(**params: Any) -> str:
    return "dataquality:issues:v1:" + ":".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )


async def list_issues(
    db: AsyncSession,
    redis: Redis,
    *,
    source_id: str | None,
    severity: str | None,
    category: str | None,
    status: str,
    limit: int,
    cursor: str | None,
) -> DataQualityIssuesResponse:
    cache_key = _issue_cache_key(
        source_id=source_id,
        severity=severity,
        category=category,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataQualityIssuesResponse.model_validate_json(cached)

    issues = await _generate_issues(db)
    total = len(issues)

    filtered = issues
    if source_id is not None:
        filtered = [i for i in filtered if i["source_id"] == source_id]
    if severity is not None:
        filtered = [i for i in filtered if i["severity"] == severity]
    if category is not None:
        filtered = [i for i in filtered if i["category"] == category]
    filtered = [i for i in filtered if i["status"] == status]
    filtered.sort(key=lambda i: i["last_seen_at"], reverse=True)

    offset = 0
    if cursor:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:
            offset = 0
    page = filtered[offset : offset + limit]
    has_more = offset + limit < len(filtered)
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    response = DataQualityIssuesResponse(
        meta=DataQualityIssuesMeta(total=total, filtered=len(filtered)),
        data=[DataQualityIssue(**i) for i in page],
        next_cursor=next_cursor,
        has_more=has_more,
    )
    await redis.set(cache_key, response.model_dump_json(), ex=ISSUES_CACHE_TTL)
    return response


async def list_outliers(
    db: AsyncSession,
    redis: Redis,
    *,
    source_id: str | None,
    metric: str | None,
    z_score_min: float,
    from_: datetime,
    to: datetime,
    limit: int,
) -> DataQualityOutliersResponse:
    cache_key = f"dataquality:outliers:v1:{source_id}:{metric}:{z_score_min}:{from_}:{to}:{limit}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataQualityOutliersResponse.model_validate_json(cached)

    where = [
        "z_score IS NOT NULL",
        "z_score >= :z_score_min",
        "detected_at BETWEEN :from_ AND :to",
    ]
    params: dict[str, Any] = {
        "z_score_min": z_score_min,
        "from_": from_,
        "to": to,
        "limit": limit,
    }
    if source_id is not None:
        entry = CATALOG_BY_ID.get(source_id)
        where.append("source = :source")
        params["source"] = entry.ingest_source if entry else "__no_such_source__"
    if metric is not None:
        where.append("metric = :metric")
        params["metric"] = metric

    result = await db.execute(
        text(
            "SELECT id, run_id, source, metric, value, z_score, expected_low, expected_high, "
            "detected_at, row_snapshot "
            f"FROM meta.anomalies WHERE {' AND '.join(where)} "  # nosec B608 -- `where` is only ever built from fixed literal clause fragments above; values are bound params
            "ORDER BY z_score DESC LIMIT :limit"
        ),
        params,
    )
    rows = result.mappings().all()

    now = datetime.now(UTC)
    data = []
    for row in rows:
        snapshot = row["row_snapshot"] or {}
        source_id_out = _SOURCE_TO_ID.get(row["source"], row["source"])
        data.append(
            DataQualityOutlier(
                id=f"out-{row['id']}",
                source_id=source_id_out,
                metric=row["metric"],
                value=float(row["value"]) if row["value"] is not None else 0.0,
                expected_range=ExpectedRange(
                    low=float(row["expected_low"])
                    if row["expected_low"] is not None
                    else None,
                    high=float(row["expected_high"])
                    if row["expected_high"] is not None
                    else None,
                ),
                z_score=float(row["z_score"]),
                observed_at=snapshot.get("ts") or row["detected_at"],
                region=snapshot.get("region"),
                station_id=snapshot.get("station_id"),
                context=None,
                linked_issue_id=f"dq-anomaly-{source_id_out}-{row['metric']}",
            )
        )

    response = DataQualityOutliersResponse(
        meta=DataQualityOutliersMeta(total=len(data), as_of=now), data=data
    )
    await redis.set(cache_key, response.model_dump_json(), ex=OUTLIERS_CACHE_TTL)
    return response


async def get_schema_report(
    db: AsyncSession, redis: Redis
) -> DataQualitySchemaResponse:
    cache_key = "dataquality:schema:v1"
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataQualitySchemaResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    drifts = await schema_drift.get_recorded_drifts(db)
    counts = await schema_drift.count_recent_drifts(db, now - timedelta(hours=24))

    response = DataQualitySchemaResponse(
        as_of=now,
        drifts=[
            SchemaDriftOut(
                source_id=_SOURCE_TO_ID.get(d["source"], d["source"]),
                table=d["table_name"],
                severity=d["severity"],
                kind=d["kind"],
                column=d["column_name"],
                old_type=d["old_type"],
                new_type=d["new_type"],
                first_seen_at=d["first_seen_at"],
                auto_adapted=d["auto_adapted"],
                action_required=d["action_required"],
                downstream_impact=d["downstream_impact"],
            )
            for d in drifts
        ],
        summary=SchemaDriftSummary(**counts),
    )
    await redis.set(cache_key, response.model_dump_json(), ex=SCHEMA_CACHE_TTL)
    return response


def _parse_window_to_minutes(window: str) -> int:
    """`P1D`-`P30D` only (API_SPECEFICATIONS.md §3.5's documented range,
    "1d-30d") — not a general ISO-8601 duration parser."""
    if not (window.startswith("P") and window.endswith("D")):
        raise ApiError(
            400, "invalid_body", f"Unsupported window '{window}' — expected P1D-P30D"
        )
    try:
        days = int(window[1:-1])
    except ValueError as exc:
        raise ApiError(400, "invalid_body", f"Unsupported window '{window}'") from exc
    if not (1 <= days <= 30):
        raise ApiError(400, "invalid_body", "window must be between P1D and P30D")
    return days * 1440


async def trigger_recheck(
    redis: Redis,
    source_id: str,
    tests: list[str],
    window: str,
    *,
    idempotency_key: str | None,
    triggered_by: str,
) -> RecheckResponse:
    require_catalog_entry(source_id)
    _parse_window_to_minutes(
        window
    )  # validates `window`; 400s before the 202 if malformed

    idem_cache_key = None
    if idempotency_key:
        idem_cache_key = (
            f"idempotency:dataquality:{source_id}:recheck:{idempotency_key}"
        )
        cached = await redis.get(idem_cache_key)
        if cached is not None:
            return RecheckResponse.model_validate_json(cached)

    lock_key = f"dataquality:recheck-lock:{source_id}"
    if await redis.get(lock_key) is not None:
        raise ApiError(
            409,
            "recheck_in_progress",
            f"A recheck for '{source_id}' is already running",
        )
    await redis.set(lock_key, "1", ex=120)

    now = datetime.now(UTC)
    recheck_id = f"rc-{int(now.timestamp())}-{uuid.uuid4().hex[:5]}"
    response = RecheckResponse(
        recheck_id=recheck_id,
        source_id=source_id,
        tests=tests,
        window=window,
        estimated_completion_at=now + timedelta(seconds=60),
        result_url=f"/v1/data-quality/issues?source_id={source_id}&status=open",
    )

    if idem_cache_key:
        await redis.set(
            idem_cache_key, response.model_dump_json(), ex=IDEMPOTENCY_TTL_SECONDS
        )

    return response


async def run_recheck_in_background(
    redis: Redis,
    source_id: str,
    registry_key: str,
    lookback_minutes: int,
    triggered_by: str,
) -> None:
    """Re-fetches `source_id` (so `pipeline.anomaly` re-scores fresh data)
    and re-runs schema-drift detection — see `RecheckResponse`'s
    docstring for why this is a real re-check, not a no-op."""
    try:
        await run_source(
            registry_key, triggered_by=triggered_by, lookback_minutes=lookback_minutes
        )
        async with get_session() as db:
            await schema_drift.detect_drift(db)
    except Exception as exc:
        log.error(
            "dataquality.recheck_background_failed", source_id=source_id, error=str(exc)
        )
    finally:
        await redis.delete(f"dataquality:recheck-lock:{source_id}")
