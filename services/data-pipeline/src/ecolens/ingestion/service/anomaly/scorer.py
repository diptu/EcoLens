"""Root TODO.md's "Anomaly Detection" section: combines `rules.py`
(deterministic), `baseline.py` (v1 robust statistics), and
`isolation_forest.py` (v2, periodically-retrained) into one
non-destructive `anomaly_score`/`anomaly_flags`/`anomaly_explanation`
per record.

`score_batch()` is the one function `ingestion/db/duckdb_store.py`'s
`write_historical()` calls, in the same place it already stamps
`ingest_run_id`/`fetched_at`/`source` onto every doc -- not from each of
the 5 `service/*/engine.py` fetchers individually. That module's own
docstring is explicit that *every* live fetcher *and* every historical
backfill funnel through `write_historical()`; hooking anomaly scoring in
anywhere else means five (really six, counting `HistoricalFetcher`) call
sites that could each forget it, versus one that can't.

Never removes or nulls a record for scoring high -- this only adds three
columns to what was already going to be written.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.shared.observability.logging import get_logger

from . import isolation_forest as iforest
from .baseline import BaselineResult, RollingBaseline, load_baseline
from .rules import _as_datetime, evaluate_rules

log = get_logger(__name__)

# Severity per rule flag, 0..1 -- the "how bad is this" half of the
# combined anomaly_score. Hand-assigned, not derived from data: these
# are policy calls (a price-cap breach is worse than a merely-stale
# record), not a statistical fact to infer.
_RULE_SEVERITY: dict[str, float] = {
    "rule:price_above_cap": 1.0,
    "rule:price_below_floor": 1.0,
    "rule:demand_negative": 1.0,
    "rule:demand_sudden_jump": 0.7,
    "rule:temp_out_of_range": 0.6,
    "rule:humidity_out_of_range": 0.6,
    "rule:wind_speed_out_of_range": 0.6,
    "rule:incomplete_record": 0.5,
    "rule:stale_record": 0.3,
}
# Any future rule flag not listed above -- fail toward "worth a look,"
# not toward invisible.
_DEFAULT_RULE_SEVERITY = 0.5

# Flags/explanations joined with these delimiters into plain TEXT
# columns, not a native array type -- portable across DuckDB, asyncpg/
# Postgres, and dbt SQL without needing array-handling machinery on any
# of those three hops. A comma can't appear inside a flag name (all
# `rule:`/`stat:` flags are fixed identifiers), so splitting back out is
# unambiguous if a downstream consumer ever needs to.
_FLAG_DELIMITER = ","
_EXPLANATION_DELIMITER = "; "


def _entity_key(doc: dict[str, Any], entity_cols: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(doc.get(c) for c in entity_cols)


def _sort_ts_key(value: Any) -> float:
    """Comparable epoch-seconds key for `value` (a native `datetime`, an
    ISO string, or missing) -- used only to order a batch chronologically
    per entity so the sudden-jump rule sees the right "previous" record;
    an unparseable/missing value sorts first (0.0) rather than raising,
    since a batch failing to order perfectly is far less bad than this
    scoring pass crashing the whole ingest write.
    """
    if value is None:
        return 0.0
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0


def _severity_for_zscore(zscore: float, threshold: float) -> float:
    """0.5 at exactly the threshold, ramping linearly to 1.0 by 2x the
    threshold and capped there -- a smooth ramp, not a hard 0-or-1 cliff
    right at the boundary.
    """
    if threshold <= 0:
        return 1.0
    return min(1.0, 0.5 + 0.5 * (abs(zscore) - threshold) / threshold)


def _severity_for_iforest_score(value: float, severity_floor: float) -> float:
    """0 exactly at sklearn's own inlier/outlier boundary
    (`decision_function() == 0`, the same point `IsolationForest.predict()`
    itself switches from +1 to -1) -- there's no arbitrary threshold to
    pick the way `_severity_for_zscore` needs one, sklearn already fit
    that boundary into the model at training time via `contamination`.
    Ramps to 1.0 at `severity_floor` (that model's *own* worst
    training-data decision_function value -- i.e. its single most
    anomalous training point, not a fixed global constant -- see
    `LoadedIsolationForest`'s own docstring for why a fixed scale
    doesn't work: `decision_function`'s real range varies per model with
    dataset size/dimensionality, since isolation depth has a floor a
    sufficiently extreme point hits in ~1 split regardless of exactly
    how extreme it is beyond that).
    """
    if value >= 0 or severity_floor >= 0:
        return 0.0
    return min(1.0, value / severity_floor)


def _statistical_component(
    source: str,
    doc: dict[str, Any],
    entity_key: tuple[Any, ...],
    baseline: RollingBaseline,
    settings: IngestionSettings,
) -> tuple[float, list[str], list[str], dict[str, BaselineResult]]:
    """The worst (highest-severity) statistical outlier across every
    metric this source baselines, if any exceed the threshold -- not an
    average, since one genuinely anomalous metric shouldn't get diluted
    by several ordinary ones on the same record.

    Also returns every metric's own `BaselineResult` (not just the
    fired ones) -- `_isolation_forest_component` below reuses these
    z-scores as its own input feature rather than recomputing the same
    `baseline.score()` call a second time.
    """
    best_score = 0.0
    flags: list[str] = []
    explanations: list[str] = []
    results: dict[str, BaselineResult] = {}
    for metric in settings.metric_columns_for_source(source):
        value = doc.get(metric)
        if value is None:
            continue
        result = baseline.score(entity_key, metric, float(value))
        if result.zscore is None:
            continue
        results[metric] = result
        if abs(result.zscore) <= settings.anomaly_robust_zscore_threshold:
            continue
        flags.append(f"stat:{metric}_robust_zscore_outlier")
        explanations.append(
            f"{metric}={value:g} is {result.zscore:+.1f} robust z vs. the "
            f"recent median {result.median:g} (MAD {result.mad:g}, "
            f"n={result.n_samples})"
        )
        best_score = max(
            best_score,
            _severity_for_zscore(
                result.zscore, settings.anomaly_robust_zscore_threshold
            ),
        )
    return best_score, flags, explanations, results


def _isolation_forest_component(
    source: str,
    doc: dict[str, Any],
    baseline_results: dict[str, BaselineResult],
    ts: datetime | None,
    registry: "iforest.IsolationForestRegistry",
) -> tuple[float, list[str], list[str]]:
    """v2: the worst (highest-severity) IsolationForest outlier across
    every metric this source has a *trained* model for -- silently
    skips a metric with no persisted model yet (cold start, same
    graceful-degradation contract every other signal in this module
    uses) and skips entirely if `ts` couldn't be parsed (the cyclical
    hour/day-of-week features have nothing to compute from).
    """
    if ts is None:
        return 0.0, [], []
    best_score = 0.0
    flags: list[str] = []
    explanations: list[str] = []
    for metric, result in baseline_results.items():
        loaded = registry.get(source, metric)
        if loaded is None or result.zscore is None:
            continue
        decision = iforest.score(loaded, result.zscore, ts)
        if decision >= 0:
            continue
        value = doc.get(metric)
        flags.append(f"ml:{metric}_isolation_forest_outlier")
        explanations.append(
            f"{metric}={value:g} flagged by isolation forest "
            f"(decision={decision:+.3f}, z={result.zscore:+.1f}, "
            f"model trained on {loaded.n_samples} samples at {loaded.trained_at})"
        )
        best_score = max(
            best_score, _severity_for_iforest_score(decision, loaded.severity_floor)
        )
    return best_score, flags, explanations


def score_batch(
    source: str,
    docs: list[dict[str, Any]],
    *,
    settings: IngestionSettings | None = None,
    baseline: RollingBaseline | None = None,
    isolation_forest_registry: "iforest.IsolationForestRegistry | None" = None,
    db_path: Path | None = None,
) -> None:
    """Mutates every doc in `docs` in place with `anomaly_score` (float,
    0..1 -- the max of the worst fired rule's severity, the worst v1
    statistical outlier's severity, and the worst v2 IsolationForest
    outlier's severity), `anomaly_flags` (comma-joined fired flag names,
    e.g. `"rule:price_above_cap,stat:demand_mw_robust_zscore_outlier,
    ml:demand_mw_isolation_forest_outlier"`, `""` if nothing fired), and
    `anomaly_explanation` (one human-readable line per fired check,
    `"; "`-joined, `""` if nothing fired). Record count in == record
    count out, always -- nothing is ever dropped or nulled for scoring
    high.

    `baseline`, if given, skips building a fresh one from DuckDB history
    (what tests use to inject synthetic history; production callers
    always omit it). `isolation_forest_registry`, if given, skips
    building a fresh one (same reason) -- production callers get a
    registry pointed at `isolation_forest.default_model_dir()`, or no v2
    signal at all when `settings.anomaly_isolation_forest_enabled` is
    `False`. `db_path`, if given, scopes the baseline's DuckDB read to a
    non-default store -- `write_historical`'s own `db_path` param passes
    it straight through so the baseline reads the same file it's about
    to write to.
    """
    settings = settings or get_ingestion_settings()
    if not docs:
        return

    entity_cols = settings.entity_columns_for_source(source)
    ts_col = settings.timestamp_column_for_source(source)
    resolved_baseline = baseline or load_baseline(
        source, settings=settings, db_path=db_path
    )
    resolved_iforest_registry = (
        isolation_forest_registry
        if isolation_forest_registry is not None
        else (
            iforest.IsolationForestRegistry(
                model_dir=db_path.resolve().parent / "anomaly_models"
                if db_path is not None
                else None
            )
            if settings.anomaly_isolation_forest_enabled
            else None
        )
    )

    # Sort a *copy* of the doc list by (entity, ts) so the sudden-jump
    # rule can find each doc's immediately-preceding same-entity record
    # within this batch -- the caller's own `docs` list order (and every
    # dict inside it) is otherwise untouched; only mutation is per-dict.
    ordered = sorted(
        docs, key=lambda d: (_entity_key(d, entity_cols), _sort_ts_key(d.get(ts_col)))
    )

    prev_by_entity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for doc in ordered:
        entity_key = _entity_key(doc, entity_cols)
        prev_doc = prev_by_entity.get(entity_key)

        rule_results = evaluate_rules(source, doc, prev_doc=prev_doc, settings=settings)
        rule_score = max(
            (_RULE_SEVERITY.get(r.flag, _DEFAULT_RULE_SEVERITY) for r in rule_results),
            default=0.0,
        )
        rule_flags = [r.flag for r in rule_results]
        rule_explanations = [r.detail for r in rule_results if r.detail]

        stat_score, stat_flags, stat_explanations, baseline_results = (
            _statistical_component(source, doc, entity_key, resolved_baseline, settings)
        )

        iforest_score = 0.0
        iforest_flags: list[str] = []
        iforest_explanations: list[str] = []
        if resolved_iforest_registry is not None:
            iforest_score, iforest_flags, iforest_explanations = (
                _isolation_forest_component(
                    source,
                    doc,
                    baseline_results,
                    _as_datetime(doc.get(ts_col)),
                    resolved_iforest_registry,
                )
            )

        doc["anomaly_score"] = round(max(rule_score, stat_score, iforest_score), 4)
        doc["anomaly_flags"] = _FLAG_DELIMITER.join(
            rule_flags + stat_flags + iforest_flags
        )
        doc["anomaly_explanation"] = _EXPLANATION_DELIMITER.join(
            rule_explanations + stat_explanations + iforest_explanations
        )

        prev_by_entity[entity_key] = doc

    log.info(
        "anomaly.scored_batch",
        source=source,
        docs=len(docs),
        flagged=sum(1 for d in docs if d.get("anomaly_score", 0.0) > 0.0),
    )


__all__ = ["score_batch"]
