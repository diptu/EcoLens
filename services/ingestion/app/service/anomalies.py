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

`method`'s `'rule'` bucket is legacy-only since `pipeline.anomaly`'s
rule-based signal was retired 2026-08-12 (that module's own docstring
has the real, live-observed reason) -- `rule_based_score` is never set
on a row detected after that date, so `_METHOD_CASE` below only ever
lands a *new* row on `'rule'` if the ML signal also didn't fire and it
somehow still has a `rule_based_score` (can't happen going forward, but
the branch is there for correctness, not dead code removed prematurely).
Rows that only cleared the statistical (z-score) signal, old or new,
land on `'statistical'` -- previously mislabeled `'rule'` by a `_METHOD_
CASE` that only ever checked `ml_score is null`, not which of `rule_
based_score`/`statistical_score` was actually set; harmless while rule-
based was still real (every non-ML row had *a* rule/statistical score),
misleading now that `'rule'` is meant to mean something specific.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.service.dataquality import _severity_from_score
from app.service.pipeline.anomaly import _MIN_ROWS_FOR_ZSCORE, _Z_SCORE_THRESHOLD

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
# live-confirmed distribution behind this rule, and for why the final
# two branches split 'rule' (legacy) from 'statistical' now).
_METHOD_CASE = """
    case
        when ml_score is not null and (rule_based_score is not null or statistical_score is not null) then 'hybrid'
        when ml_score is not null then 'ml'
        when rule_based_score is not null then 'rule'
        else 'statistical'
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

    latest_detected_at = (
        await db.execute(text("select max(detected_at) from meta.anomalies"))
    ).scalar_one()

    return {
        "total": total,
        "avg_score": float(avg_score) if avg_score is not None else 0.0,
        "by_severity": await _counts(_SEVERITY_CASE),
        "by_status": await _counts("status"),
        "by_source": await _counts("source"),
        "by_method": await _counts(_METHOD_CASE),
        "by_reason_kind": await _counts("split_part(anomaly_reason, ':', 1)"),
        "daily_counts": daily_counts,
        "latest_detected_at": latest_detected_at,
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


# Columns `raw_marts.fct_energy_demand` actually has that are meaningful
# to chart per-timestamp -- not every numeric column on that mart (e.g.
# weather/lag/rolling features), just the two `pipeline.anomaly`'s own
# `_NUMERIC_COLUMNS` scans for `aemo_nem`/`aemo_wem`.
_TIMESERIES_METRICS = ("demand_mw", "price_mwh")

# Rolling-window size for the real expected-range band below -- point
# count, not a time span (native grain varies: 5-min for NEM, mixed for
# WEM). Comfortably above `_MIN_ROWS_FOR_ZSCORE` so the window itself is
# never the reason a stretch of points gets no band.
_TIMESERIES_ROLLING_WINDOW = 48


async def get_demand_timeseries(
    db: AsyncSession,
    *,
    region: str,
    metric: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Real per-timestamp series from `raw_marts.fct_energy_demand` for
    the anomaly-detection page's overview chart. `is_anomalous`/
    `anomaly_score` are already real columns on that mart -- joined once
    by dbt (`int_anomaly_by_demand.sql`, "worst signal per (ts, region)",
    same "take the worst" rule `pipeline.anomaly.detect_anomalies`'s own
    `_Winner` already applies) -- so this needs no separate join to
    `meta.anomalies` itself.

    `expected_low`/`expected_high` per point are a REAL rolling-window
    mean +/- `_Z_SCORE_THRESHOLD` * std over `metric`, computed here for
    visualization -- the exact same statistical-signal arithmetic
    `pipeline.anomaly.detect_anomalies` uses (constant imported, not
    duplicated), just applied over a rolling window instead of one fetch
    batch, since an "expected range" isn't itself persisted per row
    anywhere (only `meta.anomalies.expected_low/high`, and only for rows
    that were actually flagged). A real, derived statistic, not a
    fabricated band -- `None` at the series' own edges and any stretch
    with fewer than `_MIN_ROWS_FOR_ZSCORE` real values in its window,
    same honesty convention the detector itself already follows rather
    than than pretending a band exists where too little data backs one.

    Raises `ValueError` for an unsupported `metric` -- the route turns
    that into a 400.
    """
    if metric not in _TIMESERIES_METRICS:
        raise ValueError(
            f"unsupported metric {metric!r}; expected one of {_TIMESERIES_METRICS}"
        )

    result = await db.execute(
        text(
            f"select ts, {metric} as value, is_anomalous, anomaly_score "
            "from raw_marts.fct_energy_demand "
            "where region = :region and ts >= :start and ts <= :end "
            "order by ts"
        ),
        {"region": region, "start": start, "end": end},
    )
    rows = [dict(r) for r in result.mappings().all()]

    if not rows:
        return {
            "region": region,
            "metric": metric,
            "start": start,
            "end": end,
            "total_points": 0,
            "anomalous_points": 0,
            "points": [],
        }

    values = pd.to_numeric(pd.Series([r["value"] for r in rows]), errors="coerce")
    rolling = values.rolling(
        window=_TIMESERIES_ROLLING_WINDOW,
        min_periods=_MIN_ROWS_FOR_ZSCORE,
        center=True,
    )
    mean = rolling.mean()
    std = rolling.std()
    expected_low = (mean - _Z_SCORE_THRESHOLD * std).to_numpy()
    expected_high = (mean + _Z_SCORE_THRESHOLD * std).to_numpy()
    values_arr = values.to_numpy()

    points = []
    anomalous_points = 0
    for idx, row in enumerate(rows):
        is_anom = bool(row["is_anomalous"])
        score = (
            float(row["anomaly_score"]) if row["anomaly_score"] is not None else None
        )
        if is_anom:
            anomalous_points += 1
        val = values_arr[idx]
        el = expected_low[idx]
        eh = expected_high[idx]
        points.append(
            {
                "ts": row["ts"],
                "value": None if pd.isna(val) else float(val),
                "is_anomalous": is_anom,
                "anomaly_score": score,
                "severity": (
                    _severity_from_score(score) if is_anom and score is not None else None
                ),
                "expected_low": None if pd.isna(el) else float(el),
                "expected_high": None if pd.isna(eh) else float(eh),
            }
        )

    return {
        "region": region,
        "metric": metric,
        "start": start,
        "end": end,
        "total_points": len(points),
        "anomalous_points": anomalous_points,
        "points": points,
    }
