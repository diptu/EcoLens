"""Anomaly detection (`overview.md` §1 — "every ingested record is
analysed using a hybrid anomaly detection approach... flags them with an
anomaly score and explanation... rather than removing suspicious
records").

Two signals, combined by taking the worse of the two per row:

1. Statistical: a per-batch z-score against that column's own mean/std
   within the current fetch. Deliberately self-contained (no historical
   baseline query, no trained model artifact) — a "lightweight local
   outlier check", complementary to signal 2's actual trained model.
2. **ML**: `pipeline.ml_anomaly.score` — a per-source `IsolationForest`
   trained against this source's accumulated staging history, scored
   per batch. `None` (no contribution) until a model has actually been
   trained for a given source (`ecolens-ingestion train-anomaly-model`)
   — a real, expected state for a source that hasn't been trained yet,
   not an error; the detector simply runs on 1 signal until then.

**Rule-based checks retired 2026-08-12** (out-of-range physical bounds
and missing/unparseable-value flagging, `_BOUNDS`/`_MISSING_VALUE_SCORE`/
`_OUT_OF_RANGE_SCORE`, formerly signal 1). Real, live-observed cost: the
missing-value check alone accounted for 121K/150K+ real `meta.anomalies`
rows, the overwhelming majority structurally expected rather than
anomalous (e.g. `aemo_wem`'s `price_mwh` is genuinely `NaN` on 5/6 of
every WEM batch — AEMO only publishes price at the :00/:30 marks, see
`ingest_aemo_wem._fetch_wem_day`'s own docstring — so nearly every WEM
row was flagged on a column that was never going to have a value, not a
real data-quality problem). The out-of-range bounds themselves were also
never derived from real anomaly-labeled data, just generous physically-
plausible-for-Australia sanity ceilings (module history, `git blame`).
`meta.anomalies.rule_based_score` and the historical rows it's already
set on are left alone (real, disclosed schema-migration boundary, same
shape the `method` derivation already handles for pre-signal-columns
rows — see `service/anomalies.py`'s own docstring) — `detect_anomalies`
just never sets it on any new row going forward.

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

A row can clear both signals at once (e.g. a statistical outlier that's
also flagged by the ML model) — `anomaly_score`/`metric`/`value`/
`z_score`/... above only ever record the single *worst* signal, same as
`anomaly_reason`'s design always has. `statistical_score`/`ml_score`
(migration `0025_anomalies_signal_scores.sql`) record each signal's own
score independently — NULL meaning that signal didn't fire — so "which
signal(s) triggered" is a queryable structured field instead of only
recoverable by parsing `anomaly_reason`'s free-text string.

**High-confidence-only gate, 2026-08-12, tightened further 2026-08-13**
(`_MIN_ANOMALY_SCORE_TO_FLAG`): clearing a signal's own trigger
(z > `_Z_SCORE_THRESHOLD`, or a trained ML model's own
`ANOMALY_SCORE_THRESHOLD`) is necessary but no longer sufficient to
actually get flagged/persisted — the *winning* signal's own combined
score must also exceed `0.98`. A row that only barely clears a signal's
own lower bar (e.g. z just over 4.0) is now silently not flagged at all,
same as if neither signal had fired; this trades real detection recall
for a much lower false-positive rate on borderline cases. See that constant's
own comment for the exact real thresholds this implies per signal.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from app.db.session import get_session

# Which columns are worth scanning per ingest source (registry.py's
# `IngestSource.source` values).
#
# `openelectricity` excludes `demand_mw`/`price_mwh` -- `ingest_
# openelectricity.py`'s `_pivot_long_to_wide` sources them by filtering
# `long_df["fuel_type"] == "demand"/"price"`, but `long_df` only ever
# contains `DataMetric.POWER` (fueltech) rows from `fetch_network_data`;
# demand/price live on the OE SDK's separate `MarketMetric` enum, only
# reachable via `client.get_market()`, which this codebase doesn't call
# yet. That filter has therefore never matched a single row -- both
# columns are unconditionally `None` on every OE row, every run -- so
# scanning them here would still be pointless even now that the (now-
# retired) rule-based missing-value check isn't around to flood
# `meta.anomalies` over it (confirmed live 2026-08-05: 63 runs in ~2h
# each re-inserted the same ~1728-row batch, 108,864 duplicate rows/
# ~110MB, enough on its own to push a 512MB Neon project over its limit
# and wedge every subsequent run in `status='running'` forever) -- a
# column that's always `None` has no mean/std for the z-score signal to
# work with either. Drop these two until `get_market()`/`MarketMetric.
# PRICE`/`MarketMetric.DEMAND` are actually wired up to populate real
# values.
_NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "openelectricity": ("total_generation_mw",),
    "aemo_nem": ("demand_mw", "price_mwh"),
    "aemo_wem": ("demand_mw", "price_mwh"),
    "bom": ("temp_c", "humidity_pct", "wind_speed_kmh"),
    "aemo_holidays": (),  # no numeric time-series columns worth scanning
}

_MIN_ROWS_FOR_ZSCORE = 5
# Raised 3.0 -> 4.0, 2026-08-13 (operator-requested tightening) -- a
# stricter individual-trigger bar on top of `_MIN_ANOMALY_SCORE_TO_FLAG`
# below, not a replacement for it; the two now compound (fewer rows even
# become "candidates", and candidates need a higher combined score too).
_Z_SCORE_THRESHOLD = 4.0

# Real gate, 2026-08-12: a row clearing *either* signal's own trigger
# (z > _Z_SCORE_THRESHOLD, or ml_score >= ml_anomaly.ANOMALY_SCORE_
# THRESHOLD) used to be enough to get flagged/persisted to `meta.
# anomalies`, even right at that signal's own threshold -- e.g. a z just
# above `_Z_SCORE_THRESHOLD` scores z_signal_score=min(1.0, z/(2·
# _Z_SCORE_THRESHOLD))≈0.5, barely above the statistical signal's own
# bar. This raises the bar for what actually counts as "an anomaly"
# (gets recorded) to a real high-confidence score: the WINNING signal's
# own combined score (`_Winner.score`, 0-1) must exceed this, not just
# clear its own signal's individual trigger.
# Raised 0.95 -> 0.98, 2026-08-13 (operator-requested tightening, same
# change as `_Z_SCORE_THRESHOLD` above). In practice: the statistical
# signal alone now needs z > 7.84 (0.98 * 2 * 4.0) to flag on its own,
# and the ML signal needs ml_score >= 0.98 -- both signals' own lower
# triggers above still gate whether a row is even a *candidate* worth
# scoring at all (a real, deliberately cheap pre-filter), but a row that
# only clears a signal's own lower trigger without reaching this bar is
# now dropped entirely, same as if neither signal had fired -- not
# persisted to `meta.anomalies` in any form.
_MIN_ANOMALY_SCORE_TO_FLAG = 0.98

_RESULT_COLUMNS = (
    "anomaly_score",
    "anomaly_reason",
    "anomaly_metric",
    "anomaly_value",
    "anomaly_z_score",
    "anomaly_expected_low",
    "anomaly_expected_high",
    "anomaly_rule_based_score",
    "anomaly_statistical_score",
    "anomaly_ml_score",
)


@dataclass
class _Winner:
    """The single worst-offending (metric, value) pair for one row —
    "worst" meaning whichever check produced the highest score,
    statistical or ML. Only one winner is kept per row (matching
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

    # Lazy import -- `ml_anomaly` imports `_NUMERIC_COLUMNS` from this
    # module at its own top level, so importing it back at this module's
    # top level would be circular. `None` (no model trained yet for
    # `source`) is the common/expected case, not an error -- see this
    # module's own docstring for signal 2.
    from app.service.pipeline import ml_anomaly

    ml_scores = ml_anomaly.score(df, source)

    flagged: list[
        tuple[object, list[str], _Winner, float | None, float | None]
    ] = []
    for pos, idx in enumerate(df.index):
        winner = _Winner()
        reasons: list[str] = []
        # Independent of `winner` -- a row can clear both signal
        # categories at once (e.g. statistical_outlier *and* ml_outlier);
        # each category's own best score is tracked here regardless of
        # which one ends up "winning" `winner`/`anomaly_score`.
        statistical_score: float | None = None
        ml_score_value: float | None = None

        for col in columns:
            value = numeric[col].iloc[pos]
            if pd.isna(value):
                continue

            if col in stats:
                mean, std = stats[col]
                if std and std > 0:
                    z = abs((value - mean) / std)
                    if z > _Z_SCORE_THRESHOLD:
                        reasons.append(f"statistical_outlier:{col}(z={z:.1f})")
                        z_signal_score = min(1.0, z / (_Z_SCORE_THRESHOLD * 2))
                        winner.consider(
                            z_signal_score,
                            metric=col,
                            value=float(value),
                            z_score=round(float(z), 2),
                            expected_low=round(mean - _Z_SCORE_THRESHOLD * std, 2),
                            expected_high=round(mean + _Z_SCORE_THRESHOLD * std, 2),
                        )
                        statistical_score = max(
                            statistical_score or 0.0, z_signal_score
                        )

        if ml_scores is not None:
            ml_score = ml_scores.iloc[pos]
            if pd.notna(ml_score) and ml_score >= ml_anomaly.ANOMALY_SCORE_THRESHOLD:
                reasons.append(f"ml_outlier:isolation_forest(score={ml_score:.2f})")
                winner.consider(
                    float(ml_score), metric="ml_isolation_forest", value=None
                )
                ml_score_value = float(ml_score)

        if reasons and winner.score > _MIN_ANOMALY_SCORE_TO_FLAG:
            flagged.append((idx, reasons, winner, statistical_score, ml_score_value))

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
    # Rule-based checks are retired (this module's own docstring) --
    # never set on a newly-detected row. `meta.anomalies.rule_based_score`
    # itself isn't dropped (historical rows still have it); this just
    # never populates it going forward.
    result["anomaly_rule_based_score"] = [None for _ in flagged]
    result["anomaly_statistical_score"] = [f[3] for f in flagged]
    result["anomaly_ml_score"] = [f[4] for f in flagged]
    return result


def _json_safe_snapshot(row: pd.Series) -> dict:
    """`row`'s non-`_RESULT_COLUMNS` fields as a dict, with NaN/NaT
    (a real, honest missing value -- e.g. `aemo_wem`'s `price_mwh` on
    5-min-only rows) mapped to `None`. Plain `json.dumps` happily
    serializes a float NaN as the bare `NaN` token -- valid Python, not
    valid JSON -- which Postgres's `jsonb` input parser then rejects
    outright (`invalid input syntax for type json`). Since this insert
    runs inside `standard_run`'s try block, that failure previously took
    the *entire* ingest attempt down with it, not just this one anomaly
    row -- confirmed the hard way: every `aemo_wem` backfill day failed
    on exactly this, because WEM's demand-only rows (5/6 of them) always
    have a NaN `price_mwh` and (back when the now-retired rule-based
    `missing_value:` check existed) therefore always got flagged. Still
    needed even with that check gone: `row_snapshot` includes every
    column of a flagged row, not just the one that tripped the winning
    signal, so a NaN in some *other* column of a statistical/ML-flagged
    row hits this same serialization path."""
    snapshot = row.drop(labels=list(_RESULT_COLUMNS)).to_dict()
    return {key: (None if pd.isna(value) else value) for key, value in snapshot.items()}


async def record_anomalies(
    run_id: uuid.UUID, source: str, table: str, anomalies: pd.DataFrame
) -> None:
    """Persist `detect_anomalies`' output into `meta.anomalies`. A no-op
    for an empty frame (no query, no session opened)."""
    if anomalies.empty:
        return

    rows = []
    for _, row in anomalies.iterrows():
        snapshot = _json_safe_snapshot(row)
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
                "rule_based_score": row["anomaly_rule_based_score"],
                "statistical_score": row["anomaly_statistical_score"],
                "ml_score": row["anomaly_ml_score"],
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
                "metric, value, z_score, expected_low, expected_high, "
                "rule_based_score, statistical_score, ml_score) "
                "VALUES (:run_id, :source, :table_name, :anomaly_score, :anomaly_reason, "
                "CAST(:row_snapshot AS jsonb), :metric, :value, :z_score, :expected_low, :expected_high, "
                ":rule_based_score, :statistical_score, :ml_score)"
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
