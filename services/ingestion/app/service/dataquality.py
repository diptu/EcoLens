"""`GET /v1/data-quality/summary/public` -- ported from data-pipeline's
`app/service/dataquality.py`, the summary path only (`get_summary`/
`get_public_summary`/`_generate_issues`/`_severity_from_score`) --
`list_issues`/`list_outliers`/`get_schema_report`/`trigger_recheck` back
routes nothing in this platform currently calls (`services/dashboard`'s
`lib/data-quality.ts` only ever wires up the public summary -- see that
file's own docstring), so they aren't ported here.

**What "data quality tests" means here** -- same reframing data-
pipeline's original module docstring explains: there's no dbt-test-
results tracker anywhere in this codebase, so this reframes onto two
real, already-collected signals this service owns: every ingest run
(`meta._ingest_log`) counts as one test (`failed`/`sync_failed` =
failed, a run with >=1 anomaly-flagged row = warned, else passed), and
`meta.anomalies` supplies the actual issue detail.

**Schema drift, trimmed**: data-pipeline's `_generate_issues` also folds
in `meta.schema_drifts` rows (via `pipeline.schema_drift.
get_recorded_drifts`) as a third issue category. That table is written
by schema-drift *detection* against `raw.*` tables' live Postgres
schema -- a write-side concern that belongs with whichever service owns
the `raw.*` load path (`services/waerehouse`, not this one; this
service only ever stages to DuckDB, never writes `raw.*` directly). This
module still *reads* `meta.schema_drifts` (a shared `meta.*` table, same
cross-service-readable pattern as `meta.anomalies`/`meta._ingest_log`)
so a drift recorded by whatever eventually detects it still surfaces in
this summary -- it just doesn't port the ~300-line detection/`_EXPECTED_
COLUMNS` module itself, since that's out of this service's ownership.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.datasources import CATALOG, CATALOG_BY_ID
from app.schemas.data_quality import (
    BySourceSummary,
    DataQualitySummaryResponse,
    OverallSummary,
    PublicDataQualitySummaryResponse,
)
from app.service.datasources.service import fetch_run_rows

SUMMARY_CACHE_TTL = 60
_STATS_WINDOW = timedelta(days=7)

_SOURCE_TO_ID = {entry.ingest_source: entry.id for entry in CATALOG}


def _severity_from_score(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


async def _recorded_schema_drifts(db: AsyncSession) -> list[dict[str, Any]]:
    """Trivial read of `meta.schema_drifts` -- see this module's own
    docstring for why the write/detection side isn't ported here."""
    result = await db.execute(
        text(
            "SELECT id, source, table_name, column_name, kind, severity, "
            "old_type, new_type, first_seen_at, last_checked_at, "
            "auto_adapted, action_required, downstream_impact "
            "FROM meta.schema_drifts ORDER BY first_seen_at DESC"
        )
    )
    return [dict(row) for row in result.mappings().all()]


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
    for drift in await _recorded_schema_drifts(db):
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
    own docstring for why this is a separate, unauthenticated endpoint.
    Reuses `get_summary` (and its cache) rather than re-deriving the two
    numbers from scratch, so this can never disagree with the full
    summary."""
    full = await get_summary(db, redis)
    open_risks = full.by_severity_24h.get("critical", 0) + full.by_severity_24h.get(
        "high", 0
    )
    return PublicDataQualitySummaryResponse(
        as_of=full.as_of,
        data_quality_score_pct=full.overall.pass_rate_pct_24h,
        open_risks_high_plus=open_risks,
    )
