"""Hybrid anomaly detection (`overview.md` §1 — "every ingested record is
analysed using a hybrid anomaly detection approach that combines
rule-based checks with machine learning models... flags them with an
anomaly score and explanation... rather than removing suspicious
records").

Two signals, combined by taking the worse of the two per row:

1. Rule-based: a value outside `_BOUNDS`' physically/operationally
   plausible range for its column (negative demand, a 150°C reading), or
   a value that's missing/unparseable where the source is expected to
   report one.
2. Statistical: a per-batch z-score against that column's own mean/std
   within the current fetch. Deliberately self-contained (no historical
   baseline query, no trained model artifact) — this is a "lightweight
   local outlier check", not a claim of a production ML model; see
   `TODO.md`'s Ingestion section for the gap between this and a real
   trained detector.

`detect_anomalies` never drops or modifies the original DataFrame — it
returns a separate frame of just the flagged rows (plus `anomaly_score`/
`anomaly_reason` and the single worst-offending metric's structured
detail: `metric`/`value`/`z_score`/`expected_low`/`expected_high` —
migration `0016_anomalies_outlier_fields.sql`), which `pipeline.tasks.
_common.standard_run` persists via `record_anomalies` (`meta.anomalies`)
without blocking or failing the run. The structured fields exist
specifically for `GET /v1/data-quality/outliers`
(`API_SPECEFICATIONS.md` §3.3) to query directly instead of parsing
`anomaly_reason`'s free-text string back apart.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from app.db.session import get_session

# Which columns are worth scanning per ingest source (registry.py's
# `IngestSource.source` values), and the plausible range for each column
# that appears in more than one source's table.
_NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "openelectricity": ("demand_mw", "price_mwh", "total_generation_mw"),
    "aemo_nem": ("demand_mw", "price_mwh"),
    "aemo_wem": ("demand_mw", "price_mwh"),
    "bom": ("temp_c", "humidity_pct", "wind_speed_kmh"),
    "aemo_holidays": (),  # no numeric time-series columns worth scanning
}

# (low, high) — AEMO's market price cap/floor is the actual regulatory
# bound for price_mwh; the rest are physically-plausible-for-Australia
# sanity ranges, not exact operational limits.
_BOUNDS: dict[str, tuple[float, float]] = {
    "demand_mw": (0, 20000),
    "price_mwh": (-1000, 17500),
    "total_generation_mw": (0, 30000),
    "temp_c": (-10, 55),
    "humidity_pct": (0, 100),
    "wind_speed_kmh": (0, 300),
}

_MISSING_VALUE_SCORE = 0.5
_OUT_OF_RANGE_SCORE = 1.0
_MIN_ROWS_FOR_ZSCORE = 5
_Z_SCORE_THRESHOLD = 3.0

_RESULT_COLUMNS = (
    "anomaly_score",
    "anomaly_reason",
    "anomaly_metric",
    "anomaly_value",
    "anomaly_z_score",
    "anomaly_expected_low",
    "anomaly_expected_high",
)


@dataclass
class _Winner:
    """The single worst-offending (metric, value) pair for one row —
    "worst" meaning whichever check produced the highest score, rule-based
    or statistical. Only one winner is kept per row (matching
    `anomaly_score`/`anomaly_reason`'s existing "take the max" design),
    even if multiple columns/checks triggered."""

    score: float = 0.0
    metric: str | None = None
    value: float | None = None
    z_score: float | None = None
    expected_low: float | None = None
    expected_high: float | None = None

    def consider(self, score: float, **fields: float | str | None) -> None:
        if score > self.score:
            self.score = score
            self.metric = None
            self.value = None
            self.z_score = None
            self.expected_low = None
            self.expected_high = None
            for key, val in fields.items():
                setattr(self, key, val)


def _empty_result(df: pd.DataFrame) -> pd.DataFrame:
    empty = df.iloc[0:0].copy()
    for col in _RESULT_COLUMNS:
        empty[col] = pd.Series(dtype=object)
    return empty


def detect_anomalies(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Return just the flagged rows from `df` (unmodified, plus the
    `_RESULT_COLUMNS` above), for `source` (a `registry.IngestSource.
    source` value, e.g. `"bom"`, `"aemo_nem"`). Empty if nothing was
    flagged, or if `source` has no columns worth scanning."""
    columns = [c for c in _NUMERIC_COLUMNS.get(source, ()) if c in df.columns]
    if df.empty or not columns:
        return _empty_result(df)

    numeric = {c: pd.to_numeric(df[c], errors="coerce") for c in columns}
    stats = {
        c: (series.mean(), series.std())
        for c, series in numeric.items()
        if series.notna().sum() >= _MIN_ROWS_FOR_ZSCORE
    }

    flagged: list[tuple[object, list[str], _Winner]] = []
    for pos, idx in enumerate(df.index):
        winner = _Winner()
        reasons: list[str] = []
        for col in columns:
            value = numeric[col].iloc[pos]
            if pd.isna(value):
                reasons.append(f"missing_value:{col}")
                winner.consider(_MISSING_VALUE_SCORE, metric=col, value=None)
                continue

            bounds = _BOUNDS.get(col)
            if bounds is not None and not (bounds[0] <= value <= bounds[1]):
                reasons.append(f"out_of_range:{col}={value:g}")
                winner.consider(
                    _OUT_OF_RANGE_SCORE,
                    metric=col,
                    value=float(value),
                    expected_low=float(bounds[0]),
                    expected_high=float(bounds[1]),
                )

            if col in stats:
                mean, std = stats[col]
                if std and std > 0:
                    z = abs((value - mean) / std)
                    if z > _Z_SCORE_THRESHOLD:
                        reasons.append(f"statistical_outlier:{col}(z={z:.1f})")
                        winner.consider(
                            min(1.0, z / (_Z_SCORE_THRESHOLD * 2)),
                            metric=col,
                            value=float(value),
                            z_score=round(float(z), 2),
                            expected_low=round(mean - _Z_SCORE_THRESHOLD * std, 2),
                            expected_high=round(mean + _Z_SCORE_THRESHOLD * std, 2),
                        )

        if reasons:
            flagged.append((idx, reasons, winner))

    if not flagged:
        return _empty_result(df)

    idxs = [f[0] for f in flagged]
    result = df.loc[idxs].copy()
    result["anomaly_score"] = [f[2].score for f in flagged]
    result["anomaly_reason"] = ["; ".join(f[1]) for f in flagged]
    result["anomaly_metric"] = [f[2].metric for f in flagged]
    result["anomaly_value"] = [f[2].value for f in flagged]
    result["anomaly_z_score"] = [f[2].z_score for f in flagged]
    result["anomaly_expected_low"] = [f[2].expected_low for f in flagged]
    result["anomaly_expected_high"] = [f[2].expected_high for f in flagged]
    return result


async def record_anomalies(
    run_id: uuid.UUID, source: str, table: str, anomalies: pd.DataFrame
) -> None:
    """Persist `detect_anomalies`' output into `meta.anomalies`. A no-op
    for an empty frame (no query, no session opened)."""
    if anomalies.empty:
        return

    rows = []
    for _, row in anomalies.iterrows():
        snapshot = row.drop(labels=list(_RESULT_COLUMNS)).to_dict()
        rows.append(
            {
                "run_id": str(run_id),
                "source": source,
                "table_name": table,
                "anomaly_score": float(row["anomaly_score"]),
                "anomaly_reason": str(row["anomaly_reason"]),
                "row_snapshot": json.dumps(snapshot, default=str),
                "metric": row["anomaly_metric"],
                "value": row["anomaly_value"],
                "z_score": row["anomaly_z_score"],
                "expected_low": row["anomaly_expected_low"],
                "expected_high": row["anomaly_expected_high"],
            }
        )

    async with get_session() as session:
        await session.execute(
            # `:row_snapshot::jsonb` (no space before the `::` cast) trips
            # up SQLAlchemy's bind-param parser in a raw `text()` string --
            # it doesn't reliably tell "named param followed by a cast"
            # apart from "named param with an unusual name", and ends up
            # emitting `:row_snapshot` uncoverted to asyncpg's native `$N`
            # placeholders alongside the other params that did convert,
            # which asyncpg then rejects as a syntax error. `CAST(... AS
            # jsonb)` is unambiguous and the standard fix.
            text(
                "INSERT INTO meta.anomalies "
                "(run_id, source, table_name, anomaly_score, anomaly_reason, row_snapshot, "
                "metric, value, z_score, expected_low, expected_high) "
                "VALUES (:run_id, :source, :table_name, :anomaly_score, :anomaly_reason, "
                "CAST(:row_snapshot AS jsonb), :metric, :value, :z_score, :expected_low, :expected_high)"
            ),
            rows,
        )


async def count_anomalies(run_id: uuid.UUID) -> int:
    """How many rows were flagged for a given run — used to populate
    `LastRunInfo.anomalies_flagged` (`api/schemas/datasources.py`)."""
    async with get_session() as session:
        result = await session.execute(
            text("SELECT count(*) FROM meta.anomalies WHERE run_id = :run_id"),
            {"run_id": str(run_id)},
        )
        row = result.first()
        return int(row[0]) if row else 0
