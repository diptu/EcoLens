"""Isolation-forest anomaly scoring — the ML half of the "hybrid"
detection approach (`overview.md` §1) `pipeline.anomaly`'s rule-based/
z-score checks are the other half of; see that module's own docstring
for the split and the `_Winner` "take the worse of the signals" pattern
this plugs into as a third signal, not a separate/parallel flagging
system.

Trained per source (`pipeline.tasks.registry.SOURCES`' `IngestSource.
source` value, e.g. `"bom"`, `"aemo_nem"`) against that source's
accumulated history in the single shared DuckDB staging file
(`pipeline.duckdb_staging.read_table_history`) — genuinely queryable for
this specifically *because* staging moved off one-file-per-run (a
trained model needs more than one run's worth of rows to mean anything).
An `IsolationForest` per source over whatever numeric columns `anomaly.
_NUMERIC_COLUMNS` already scans for it — same column set both signals
look at, not a separate feature list to keep in sync.

Model artifacts persist through `app.service.object_storage` (R2, local
MinIO fallback) under `models/anomaly/{source}.joblib` — the same
upload/idempotency-check shape `duckdb_staging.upload_staged_file`
already uses for staged-run snapshots; this is what "all artefacts
(including model weights) end up in Cloudflare R2" (`overview.md`
Storage) means in practice, no new storage mechanism.

**Retraining is manual/CLI-triggered** (`ecolens-ingestion train-
anomaly-model <source>`), not on a Celery Beat schedule. `TODO.md`'s own
"periodic vs. manual/CLI-triggered; not decided here" note on cadence
still holds — this starts conservative (an operator/cron outside this
service decides when to retrain) rather than silently retraining
on an unreviewed automatic schedule the first time this ships. Wiring a
periodic Beat entry later (once real retraining cadence needs are
known) is a small, additive follow-up on top of this, not a redesign.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.core.config import get_settings
from app.core.logging import get_logger
from app.service import object_storage
from app.service.pipeline.anomaly import _NUMERIC_COLUMNS
from app.service.pipeline.duckdb_staging import read_table_history

log = get_logger(__name__)

# Below this many real (non-NaN, across all scanned columns) historical
# rows, a fitted forest is more noise than signal -- skip training
# rather than persist something that isn't meaningfully better than
# "no model yet". Deliberately generous for a first cut; revisit once
# real per-source history volumes are known.
MIN_TRAINING_ROWS = 50

_CONTAMINATION = "auto"
_RANDOM_STATE = 0  # fixed -- deterministic training output, not tuned

_MODEL_KEY_PREFIX = "models/anomaly"

# **Important calibration note, found live 2026-08-05 while first
# training against real AEMO-NEM history**: `IsolationForest.
# score_samples`' natural baseline is *not* a fixed, dataset-independent
# ~-0.5..0.5 range -- on real `aemo_nem_dispatch` history it sat tightly
# around -0.49 (std 0.046), so an earlier version of this module's
# `0.5 - score_samples` heuristic scored almost *every* row (normal and
# genuinely anomalous alike) at ~0.98-0.99, clearing any fixed threshold
# and making the ML signal useless (flags nearly everything). Confirmed
# by directly inspecting `score_samples`'/`decision_function`'s real
# output against real trained-on data before shipping this version.
#
# Fix: calibrate per model, against its own training distribution, not a
# universal constant. `train` computes `decision_function` (sklearn's
# own already-offset "higher = more normal, ~0 is the boundary" measure)
# over the training set itself, and stores two per-model numbers:
#   - `decision_threshold`: the `_THRESHOLD_PERCENTILE`-th percentile of
#     training `decision_function` values -- "a new point this far into
#     the tail, or further, is rarer than `_THRESHOLD_PERCENTILE`% of
#     this source's own real history".
#   - `decision_floor`: the single most-anomalous `decision_function`
#     value seen in training -- just used to scale `score`'s output onto
#     a 0..1 range relative to *this model's own* observed spread, not
#     an arbitrary global unit.
_THRESHOLD_PERCENTILE = 1.0

# A row must clear this fraction of the "threshold -> floor" gap (not
# just barely cross `decision_threshold`) to actually get flagged --
# `_THRESHOLD_PERCENTILE` alone would mean ~1% of every future batch
# gets flagged by construction, forever, purely from the model's own
# calibration -- same "small nonzero long-run detection rate is
# inherent, keep the bar high enough to still mean something" tradeoff
# the z-score signal's own `_Z_SCORE_THRESHOLD` already accepts. A
# heuristic starting point, not a calibrated false-positive-rate
# guarantee.
ANOMALY_SCORE_THRESHOLD = 0.3


@dataclass(frozen=True)
class AnomalyModel:
    source: str
    columns: tuple[str, ...]
    forest: IsolationForest
    decision_threshold: float = 0.0
    decision_floor: float = 0.0
    rows_trained: int = 0


def _model_dir() -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir) / "models" / "anomaly"


def _model_path(source: str) -> Path:
    return _model_dir() / f"{source}.joblib"


def _model_key(source: str) -> str:
    return f"{_MODEL_KEY_PREFIX}/{source}.joblib"


def train(source: str, table: str) -> AnomalyModel | None:
    """Fit a fresh `IsolationForest` for `source` against `table`'s full
    accumulated history in the shared staging file. Returns `None`
    (trains nothing, persists nothing) if `source` has no numeric
    columns configured (`anomaly._NUMERIC_COLUMNS`) or there isn't
    `MIN_TRAINING_ROWS` worth of real history yet — both are expected,
    non-error states (a brand new source, or `holidays`, which scans no
    numeric columns at all), same "nothing to do" shape `duckdb_
    staging.stage_dataframe`'s empty-df case already uses.
    """
    columns = list(_NUMERIC_COLUMNS.get(source, ()))
    if not columns:
        return None

    history = read_table_history(table)
    if history.empty:
        return None

    present = [c for c in columns if c in history.columns]
    if not present:
        return None

    numeric = history[present].apply(pd.to_numeric, errors="coerce").dropna()
    if len(numeric) < MIN_TRAINING_ROWS:
        return None

    forest = IsolationForest(contamination=_CONTAMINATION, random_state=_RANDOM_STATE)
    array = numeric.to_numpy()
    forest.fit(array)

    training_decision = forest.decision_function(array)
    decision_threshold = float(np.percentile(training_decision, _THRESHOLD_PERCENTILE))
    decision_floor = float(training_decision.min())

    return AnomalyModel(
        source=source,
        columns=tuple(numeric.columns),
        forest=forest,
        decision_threshold=decision_threshold,
        decision_floor=decision_floor,
        rows_trained=len(numeric),
    )


def save_local(model: AnomalyModel) -> Path:
    path = _model_path(model.source)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "source": model.source,
            "columns": list(model.columns),
            "forest": model.forest,
            "decision_threshold": model.decision_threshold,
            "decision_floor": model.decision_floor,
            "rows_trained": model.rows_trained,
        },
        path,
    )
    return path


def load_local(source: str) -> AnomalyModel | None:
    """Load straight from disk, bypassing the in-process cache
    (`invalidate_cache`/`score` use the cache; `train_and_publish` and
    tests want the uncached read)."""
    path = _model_path(source)
    if not path.exists():
        return None
    payload: dict[str, Any] = joblib.load(path)
    return AnomalyModel(
        source=payload["source"],
        columns=tuple(payload["columns"]),
        forest=payload["forest"],
        decision_threshold=payload.get("decision_threshold", 0.0),
        decision_floor=payload.get("decision_floor", 0.0),
        rows_trained=payload.get("rows_trained", 0),
    )


async def upload_model(path: Path, source: str) -> str:
    """Same "check existence first, skip if already there" idiom
    `duckdb_staging.upload_staged_file` uses -- unlike a run snapshot's
    unique-per-run key, a model's key is fixed per source (`{source}.
    joblib`, always overwritten by design on retrain), so this mostly
    exists for parity/consistency with that module's pattern rather than
    expecting to actually skip in practice."""
    key = _model_key(source)
    uri = await object_storage.upload_file(path, key)
    log.info("ml_anomaly.model_uploaded", source=source, key=key, uri=uri)
    return key


async def train_and_publish(source: str, table: str) -> dict[str, Any] | None:
    """`ecolens-ingestion train-anomaly-model`'s command body: train,
    save locally, upload, invalidate the in-process score cache so the
    very next ingest run for `source` picks up the freshly retrained
    model instead of a stale cached one (or a stale cached `None`, for a
    source's very first successful training run). Returns a small
    summary dict, or `None` if training itself was skipped (see
    `train`'s own docstring for why).
    """
    model = train(source, table)
    if model is None:
        return None
    path = save_local(model)
    key = await upload_model(path, source)
    invalidate_cache(source)
    return {
        "source": source,
        "rows_trained": model.rows_trained,
        "columns": list(model.columns),
        "object_storage_key": key,
    }


_CACHE: dict[str, AnomalyModel | None] = {}


def _load_cached(source: str) -> AnomalyModel | None:
    """Lazy in-process cache — loads the local joblib file (if any) once
    per source per worker process, not once per ingest batch. A missing
    model is cached too (`None`), so a source with no trained model yet
    doesn't re-stat the filesystem on every single ingest run."""
    if source not in _CACHE:
        _CACHE[source] = load_local(source)
    return _CACHE[source]


def invalidate_cache(source: str | None = None) -> None:
    """Drop the in-process model cache — called after a fresh `train_
    and_publish` so the next scoring call picks up the just-retrained
    model rather than a stale in-memory one (or a stale cached `None`).
    Also used by tests to reset state between cases."""
    if source is None:
        _CACHE.clear()
    else:
        _CACHE.pop(source, None)


def score(df: pd.DataFrame, source: str) -> pd.Series | None:
    """Per-row ML anomaly score in `[0, 1]` (higher = more anomalous),
    aligned to `df`'s index. `None` if no trained model exists yet for
    `source` — a real, expected state before the first `train_and_
    publish` run for it, not an error; `anomaly.detect_anomalies`
    treats `None` as "this signal has nothing to contribute this batch",
    same as it already does for the z-score signal on too-small batches.

    Uses `IsolationForest.decision_function` (sklearn's own already-
    offset "higher = more normal, ~0 is roughly the boundary" measure),
    not raw `score_samples` — see this module's own top-of-file
    calibration note for why the naive `score_samples`-based version
    this replaced was badly miscalibrated on real data. A row's raw
    `decision_function` value is rescaled onto `[0, 1]` relative to
    *this model's own* training distribution: `model.decision_
    threshold` (0) and `model.decision_floor` (1, clipped beyond) —
    every source gets its own calibration, not one universal scale.

    Rows with a missing/unparseable value in any of the model's trained
    columns are scored `0.0` (not dropped, not NaN) — `anomaly.py`'s own
    `missing_value:` rule-based check already flags those independently;
    this signal simply doesn't also have an opinion about them.
    """
    model = _load_cached(source)
    if model is None:
        return None

    columns = [c for c in model.columns if c in df.columns]
    if not columns:
        return None

    numeric = df[columns].apply(pd.to_numeric, errors="coerce")
    mask = numeric.notna().all(axis=1)

    scores = pd.Series(0.0, index=df.index)
    if not mask.any():
        return scores

    decision = model.forest.decision_function(numeric.loc[mask].to_numpy())
    spread = max(model.decision_threshold - model.decision_floor, 1e-9)
    scaled = np.clip((model.decision_threshold - decision) / spread, 0, 1)
    scores.loc[mask[mask].index] = scaled
    return scores
