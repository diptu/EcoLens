"""Real `meta.anomalies` listing/summary/status-mutation -- backs the
dashboard's anomaly-detection page (root TODO.md's "make every page
fully functional with real data"). See `schemas/anomalies/response.py`'s
own docstring for the real severity/method derivation this reuses
(`_severity_from_score`'s thresholds are `service/dataquality.py`'s own,
not reinvented here).

`ts`/`region`/`observed_value` come from `row_snapshot` (jsonb, real --
the exact row that tripped the check, written by `pipeline.anomaly.
record_anomalies`), not fabricated. `observed_value` uses `metric` to
pick the right key out of `row_snapshot` when possible; falls back to
the row's own `value` column (also real, though `NaN` for some check
types -- see `anomaly.py`'s own `_Winner` docstring) when the metric
name doesn't appear in the snapshot verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Same real thresholds `service/dataquality.py`'s own `_severity_from_score`
# already uses -- not reinvented, just needed as a SQL CASE expression
# here so filtering by severity can happen at the query level (correct
# pagination) instead of over-fetching and filtering in Python.
_SEVERITY_CASE = """
    case
        when anomaly_score >= 0.9 then 'high'
        when anomaly_score >= 0.5 then 'medium'
        else 'low'
    end
"""

# Real per-row derivation from which of the 3 real per-check-type score
# columns are non-null (see this module's own docstring for the real,
# live-confirmed distribution behind this rule).
_METHOD_CASE = """
    case
        when ml_score is not null and (rule_based_score is not null or statistical_score is not null) then 'hybrid'
        when ml_score is not null then 'ml'
        else 'rule'
    end
"""

_BASE_SELECT = f"""
    select
        id, run_id, source, table_name, anomaly_score, anomaly_reason,
        row_snapshot, detected_at, metric, value, z_score,
        expected_low, expected_high, status, status_updated_at,
        {_SEVERITY_CASE} as severity,
        {_METHOD_CASE} as method
    from meta.anomalies
"""


def _row_to_out(row: dict[str, Any]) -> dict[str, Any]:
    snapshot = row["row_snapshot"] or {}
    metric = row["metric"]
    observed = None
    if metric and metric in snapshot:
        observed = snapshot.get(metric)
    elif row["value"] is not None:
        try:
            v = float(row["value"])
            observed = v if v == v else None  # NaN != NaN
        except (TypeError, ValueError):
            observed = None

    def _clean_float(x: Any) -> float | None:
        if x is None:
            return None
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        return f if f == f else None  # drop NaN -- not valid JSON

    return {
        "id": str(row["id"]),
        "detected_at": row["detected_at"],
        "ts": snapshot.get("ts"),
        "region": snapshot.get("region"),
        "source": row["source"],
        "table_name": row["table_name"],
        "reason": row["anomaly_reason"],
        "severity": row["severity"],
        "method": row["method"],
        "score": float(row["anomaly_score"]),
        "metric": metric,
        "observed_value": observed,
        "z_score": _clean_float(row["z_score"]),
        "expected_low": _clean_float(row["expected_low"]),
        "expected_high": _clean_float(row["expected_high"]),
        "status": row["status"],
        "status_updated_at": row["status_updated_at"],
    }


async def list_anomalies(
    db: AsyncSession,
    *,
    severity: str | None = None,
    method: str | None = None,
    status: str | None = None,
    source: str | None = None,
    reason_kind: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Real, filtered, paginated `meta.anomalies` rows, newest first.
    Returns `(rows, total_matching)` -- `total_matching` is the real
    count *after* filters (for real pagination UI), not the whole
    table's count.

    `reason_kind` filters on the real prefix of `anomaly_reason` (e.g.
    `"missing_value"`, `"out_of_range"`, `"statistical_outlier"`,
    `"ml_outlier"` -- `pipeline.anomaly.detect_anomalies`'s own real,
    fixed set of reason strings, confirmed live: no other prefixes exist
    in this table) -- the real substitute for a fictional "anomaly type"
    taxonomy the old mock invented (demand_spike/negative_price/etc.,
    none of which this detector actually produces)."""
    where = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if severity:
        where.append(f"({_SEVERITY_CASE}) = :severity")
        params["severity"] = severity
    if method:
        where.append(f"({_METHOD_CASE}) = :method")
        params["method"] = method
    if status:
        where.append("status = :status")
        params["status"] = status
    if source:
        where.append("source = :source")
        params["source"] = source
    if reason_kind:
        where.append("split_part(anomaly_reason, ':', 1) = :reason_kind")
        params["reason_kind"] = reason_kind
    if search:
        where.append(
            "(anomaly_reason ILIKE :search OR row_snapshot::text ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where_sql = f"where {' and '.join(where)}" if where else ""

    count_result = await db.execute(
        text(f"select count(*) from meta.anomalies {where_sql}"), params
    )
    total = count_result.scalar_one()

    result = await db.execute(
        text(
            f"{_BASE_SELECT} {where_sql} "
            "order by detected_at desc limit :limit offset :offset"
        ),
        params,
    )
    rows = [_row_to_out(dict(r)) for r in result.mappings().all()]
    return rows, total


async def get_anomaly_summary(db: AsyncSession) -> dict[str, Any]:
    """Real aggregate counts -- backs the KPI cards on the dashboard's
    anomaly-detection page. One query per breakdown rather than one
    giant pivot -- each is cheap (indexed/sequential over the same
    table) and this stays readable."""
    total = (await db.execute(text("select count(*) from meta.anomalies"))).scalar_one()
    avg_score = (
        await db.execute(text("select avg(anomaly_score) from meta.anomalies"))
    ).scalar_one()

    async def _counts(expr: str) -> dict[str, int]:
        rows = (
            await db.execute(text(f"select {expr} as k, count(*) c from meta.anomalies group by 1"))
        ).mappings().all()
        return {r["k"]: r["c"] for r in rows}

    # Last 7 real calendar days (by `detected_at`, when the detector
    # actually flagged it -- not `row_snapshot`'s own `ts`, which can be
    # a much older historical timestamp for a backfilled row) --
    # 0-filled for any day with real zero detections, not just omitted.
    daily_rows = (
        await db.execute(
            text(
                "select date(detected_at) d, count(*) c from meta.anomalies "
                "where detected_at >= now() - interval '7 days' "
                "group by 1 order by 1"
            )
        )
    ).mappings().all()
    daily_by_date = {str(r["d"]): r["c"] for r in daily_rows}
    daily_counts = []
    for i in range(6, -1, -1):
        d = (datetime.now(UTC) - timedelta(days=i)).date()
        daily_counts.append({"date": str(d), "count": daily_by_date.get(str(d), 0)})

    return {
        "total": total,
        "avg_score": float(avg_score) if avg_score is not None else 0.0,
        "by_severity": await _counts(_SEVERITY_CASE),
        "by_status": await _counts("status"),
        "by_source": await _counts("source"),
        "by_method": await _counts(_METHOD_CASE),
        "by_reason_kind": await _counts("split_part(anomaly_reason, ':', 1)"),
        "daily_counts": daily_counts,
    }


async def update_anomaly_status(db: AsyncSession, anomaly_id: str, status: str) -> dict[str, Any] | None:
    """Real status mutation -- returns the updated row, or `None` if
    `anomaly_id` doesn't exist (caller turns that into a 404)."""
    await db.execute(
        text(
            "update meta.anomalies set status = :status, status_updated_at = :now "
            "where id = :id"
        ),
        {"status": status, "now": datetime.now(UTC), "id": anomaly_id},
    )
    await db.commit()

    result = await db.execute(text(f"{_BASE_SELECT} where id = :id"), {"id": anomaly_id})
    row = result.mappings().first()
    return _row_to_out(dict(row)) if row else None
