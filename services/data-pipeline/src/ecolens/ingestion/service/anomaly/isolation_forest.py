"""Root TODO.md's "Anomaly Detection" section, v2: "periodically-retrained
IsolationForest, once v1's real false-positive rate is known." Unsupervised
(no anomaly labels exist anywhere in this pipeline) -- fit per `(source,
metric)` on a rolling window of recent DuckDB history by its own daily
cron job (`scripts/train_anomaly_isolation_forest.py` +
`scripts/cron_train_anomaly_models.sh`), persisted as a plain joblib
artifact under a local model directory next to `historical_duckdb_path`.
Deliberately **not** registered through MLflow -- see this module's own
training-script docstring for why.

Granularity note, a real decision made while implementing (not exactly
the literal training-script sketch): "(source, metric)" pools every
entity (region/station) of that source into *one* model per metric, which
would be meaningless on raw values alone -- 6,000 MW is normal for NSW1
and wildly high for TAS1. Rather than train a separate model per
`(source, entity, metric)` (defeating the "far lighter than the demand
models" framing this whole v2 item opens with), each row is first
converted to `baseline.py`'s own entity-relative robust z-score (the
exact same v1 statistic, reused rather than recomputed) before being fed
to the pooled model -- restoring cross-entity comparability without a
per-entity model. This also directly closes the gap `baseline.py`'s own
module docstring opens with and v1's flat threshold can't: "this value is
fine in the abstract but wildly out of character for 3pm on a Tuesday in
this region" needs a *contextual* model, not a single flat threshold --
so `hour_sin/cos` and `dow_sin/cos` are included as features alongside
the z-score, letting the model learn a different "normal" region for
peak-vs-off-peak and weekday-vs-weekend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ecolens.config import Settings, get_settings
from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.ingestion.db import duckdb_store
from ecolens.shared.observability.logging import get_logger

from .baseline import RollingBaseline

log = get_logger(__name__)

_ALL_SOURCES: tuple[str, ...] = (
    "openelectricity",
    "aemo_nem",
    "aemo_wem",
    "bom",
    "aemo_holidays",
)

_N_FEATURES = 5  # zscore, hour_sin, hour_cos, dow_sin, dow_cos


def default_model_dir(settings: Settings | None = None) -> Path:
    """`historical_duckdb_path`'s own directory, `anomaly_models/`
    alongside it -- "a local model directory next to
    `historical_duckdb_path`," per the TODO item's own wording, not an
    independently-configurable path most callers would need to remember
    to keep in sync with wherever the DuckDB file itself lives.
    """
    settings = settings or get_settings()
    return settings.historical_duckdb_path.resolve().parent / "anomaly_models"


def _model_path(model_dir: Path, source: str, metric: str) -> Path:
    return model_dir / f"{source}__{metric}.joblib"


def _cyclical_features(ts: datetime) -> tuple[float, float, float, float]:
    """`(hour_sin, hour_cos, dow_sin, dow_cos)` -- same cyclical-encoding
    convention `ml_features_demand_v1`'s own `hour_sin`/`hour_cos`/
    `dow_sin`/`dow_cos` columns already use, reused here rather than
    inventing a second one: a plain integer hour/day-of-week would tell
    an `IsolationForest` that hour 23 and hour 0 are far apart, when
    they're adjacent.
    """
    hour_frac = ts.hour + ts.minute / 60.0
    dow = ts.weekday()
    return (
        math.sin(2 * math.pi * hour_frac / 24.0),
        math.cos(2 * math.pi * hour_frac / 24.0),
        math.sin(2 * math.pi * dow / 7.0),
        math.cos(2 * math.pi * dow / 7.0),
    )


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class LoadedIsolationForest:
    """`severity_floor`: the *minimum* `decision_function()` value over
    this model's own training data -- i.e. the single most anomalous
    point this model saw at training time (computed once, in `train_one`
    below) -- what `scorer.py`'s severity mapping normalizes a
    scoring-time `decision_function()` value against, instead of a fixed
    guessed constant. Necessary, not just nicer: empirically,
    `decision_function()`'s actual range varies with dataset size/
    dimensionality per model (isolation depth has a floor -- a
    sufficiently extreme point isolates in ~1 split and further
    extremity doesn't push the score any more negative), so one global
    scale either saturates at severity far below 1.0 for a small/tight
    model or over-reacts for a model with a wider natural spread. Each
    model calibrating against its own training distribution avoids both.
    A low percentile (e.g. the 1st) was tried first and rejected: with
    `contamination=0.01`, only a handful of training points fall below
    the fitted boundary at all, so a percentile computed over that thin
    a tail lands noisily close to 0 rather than deep in it, making
    scoring-time severity saturate at 1.0 almost immediately. `min()` has
    no such small-sample noise -- see `train_one`'s own comment.
    """

    model: IsolationForest
    source: str
    metric: str
    trained_at: str
    n_samples: int
    severity_floor: float


def _build_training_matrix(
    history: pd.DataFrame,
    source: str,
    metric: str,
    ts_col: str,
    ingestion_settings: IngestionSettings,
) -> np.ndarray:
    """Every historical `(entity, ts)` row with a non-null `metric` value
    and a baseline thick enough to trust, turned into a `(zscore,
    hour_sin, hour_cos, dow_sin, dow_cos)` feature row. Reuses
    `RollingBaseline` (v1) fit on this *same* window to compute each
    row's z-score -- standard for an unsupervised model (there's no
    train/test leakage concern the way there would be for a supervised
    metric like MAPE).
    """
    entity_cols = ingestion_settings.entity_columns_for_source(source)
    baseline = RollingBaseline(source, settings=ingestion_settings, history=history)

    rows: list[list[float]] = []
    for _, record in history.iterrows():
        value = record.get(metric)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        ts = _as_datetime(record.get(ts_col))
        if ts is None:
            continue
        entity_key = tuple(record.get(c) for c in entity_cols)
        result = baseline.score(entity_key, metric, float(value))
        if result.zscore is None:
            continue
        rows.append([result.zscore, *_cyclical_features(ts)])

    return np.asarray(rows, dtype=np.float64) if rows else np.empty((0, _N_FEATURES))


def train_one(
    source: str,
    metric: str,
    *,
    settings: Settings | None = None,
    ingestion_settings: IngestionSettings | None = None,
    db_path: Path | None = None,
    model_dir: Path | None = None,
) -> bool:
    """Trains and persists one `(source, metric)` model. Returns whether
    it actually trained -- `False` (not an error) if there weren't
    `anomaly_isolation_forest_min_samples` valid rows to learn from yet,
    same cold-start reasoning `baseline.py`'s own min-samples guard uses.
    """
    settings = settings or get_settings()
    ingestion_settings = ingestion_settings or get_ingestion_settings()
    model_dir = model_dir or default_model_dir(settings)
    ts_col = ingestion_settings.timestamp_column_for_source(source)

    since = datetime.now(timezone.utc) - timedelta(
        days=ingestion_settings.anomaly_isolation_forest_lookback_days
    )
    rows = duckdb_store.read_historical_since(source, since=since, db_path=db_path)
    history = pd.DataFrame(rows)

    if history.empty or metric not in history.columns:
        log.info("isolation_forest.no_history", source=source, metric=metric)
        return False

    X = _build_training_matrix(history, source, metric, ts_col, ingestion_settings)
    if len(X) < ingestion_settings.anomaly_isolation_forest_min_samples:
        log.info(
            "isolation_forest.insufficient_samples",
            source=source,
            metric=metric,
            n_samples=len(X),
            required=ingestion_settings.anomaly_isolation_forest_min_samples,
        )
        return False

    model = IsolationForest(
        n_estimators=ingestion_settings.anomaly_isolation_forest_n_estimators,
        contamination=ingestion_settings.anomaly_isolation_forest_contamination,
        n_jobs=1,
        random_state=42,
    )
    model.fit(X)

    # The single most anomalous point in this model's own training
    # window -- see LoadedIsolationForest's own docstring for why this
    # (not a fixed global constant) is what scoring-time severity gets
    # normalized against: severity 1.0 means "at least as anomalous as
    # the worst thing this model has ever actually seen." A low
    # percentile (e.g. the 1st) was tried first and rejected -- with
    # `contamination=0.01`, only a handful of training points fall below
    # the fitted boundary at all, so a percentile computed over that
    # thin a tail lands noisily close to 0 rather than deep in it,
    # making scoring-time severity saturate at 1.0 almost immediately.
    # `min()` has no such small-sample noise (it's just the worst single
    # point, well-defined regardless of how many points are near it).
    # Clamped away from 0 for the degenerate case where even the worst
    # training point is (barely) non-negative.
    train_scores = model.decision_function(X)
    severity_floor = min(-1e-6, float(train_scores.min()))

    model_dir.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(timezone.utc).isoformat()
    joblib.dump(
        {
            "model": model,
            "source": source,
            "metric": metric,
            "trained_at": trained_at,
            "n_samples": len(X),
            "severity_floor": severity_floor,
        },
        _model_path(model_dir, source, metric),
    )
    log.info(
        "isolation_forest.trained",
        source=source,
        metric=metric,
        n_samples=len(X),
        path=str(_model_path(model_dir, source, metric)),
    )
    return True


def train_all(
    *,
    settings: Settings | None = None,
    ingestion_settings: IngestionSettings | None = None,
    db_path: Path | None = None,
    model_dir: Path | None = None,
) -> dict[str, bool]:
    """Trains every `(source, metric)` model. Returns `{"source:metric":
    trained}` -- the training script's own summary output; a `False`
    entry is a normal cold-start skip, not a failure.
    """
    ingestion_settings = ingestion_settings or get_ingestion_settings()
    results: dict[str, bool] = {}
    for source in _ALL_SOURCES:
        for metric in ingestion_settings.metric_columns_for_source(source):
            trained = train_one(
                source,
                metric,
                settings=settings,
                ingestion_settings=ingestion_settings,
                db_path=db_path,
                model_dir=model_dir,
            )
            results[f"{source}:{metric}"] = trained
    return results


class IsolationForestRegistry:
    """Loads persisted `(source, metric)` models from `model_dir`,
    caching each in memory after first load -- ingestion is a
    short-lived, one-shot-per-cron-invocation process (see
    `scorer.py`'s own docstring on `write_historical` being called once
    per batch), so a simple load-once-per-process cache is enough; there
    is no long-running server here that would need cache invalidation
    when a newer model gets trained.
    """

    def __init__(
        self, model_dir: Path | None = None, *, settings: Settings | None = None
    ) -> None:
        self.model_dir = model_dir or default_model_dir(settings)
        self._cache: dict[tuple[str, str], LoadedIsolationForest | None] = {}

    def get(self, source: str, metric: str) -> LoadedIsolationForest | None:
        key = (source, metric)
        if key not in self._cache:
            self._cache[key] = self._load(source, metric)
        return self._cache[key]

    def _load(self, source: str, metric: str) -> LoadedIsolationForest | None:
        path = _model_path(self.model_dir, source, metric)
        if not path.exists():
            return None
        try:
            payload = joblib.load(path)
            return LoadedIsolationForest(
                model=payload["model"],
                source=payload["source"],
                metric=payload["metric"],
                trained_at=payload["trained_at"],
                n_samples=payload["n_samples"],
                severity_floor=payload["severity_floor"],
            )
        except Exception as exc:  # noqa: BLE001 - a corrupt/stale model file must degrade to "no ML signal," never crash ingestion
            log.warning(
                "isolation_forest.load_failed",
                source=source,
                metric=metric,
                error=str(exc),
            )
            return None


def score(loaded: LoadedIsolationForest, zscore: float, ts: datetime) -> float:
    """The raw sklearn `decision_function` value for one `(zscore, ts)`
    observation -- negative means "more anomalous than the training
    contamination threshold," per sklearn's own convention (the same
    boundary `IsolationForest.predict()` uses to emit -1 vs. +1).
    `scorer.py` converts this into the same 0..1 severity scale every
    other signal uses.
    """
    features = np.array([[zscore, *_cyclical_features(ts)]], dtype=np.float64)
    return float(loaded.model.decision_function(features)[0])


__all__ = [
    "LoadedIsolationForest",
    "IsolationForestRegistry",
    "default_model_dir",
    "train_one",
    "train_all",
    "score",
]
