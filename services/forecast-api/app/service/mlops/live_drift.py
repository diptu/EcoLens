"""Real concept-drift computation for the dashboard's Performance page
("Concept drift tracking" card, `performance/page.tsx`) -- `mlops/
drift.py`'s PSI/KS detector is real, tested code that has had zero
callers anywhere in this pipeline (that page's own module docstring
named this gap directly). This module is the first real caller.

Not a training-vs-live-serving comparison, `drift.py`'s own original
framing -- `/v1/forecast`'s live traffic has no real feature snapshot
logged anywhere to compare against yet, and this environment's Postgres
`raw_marts` is empty regardless (see `TODO.md`). Instead: a
chronological split of the same real feature-engineered training data
-- an older "reference" slice vs. a more recent "comparison" slice.
Real and honest, but a real, disclosed limitation too: this answers
"has the feature distribution shifted between an older and a more
recent window of real data", not "has it shifted since the model was
actually trained" (that needs a real logged serving-time snapshot,
which doesn't exist yet).
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from app.db.session import get_session
from app.service.ml import data as demand_data
from app.service.ml import features as demand_features
from app.service.ml import energy_features
from app.service.ml.energy_data_offline import (
    load_energy_training_data_from_master,
    load_holidays_from_master,
)
from app.service.ml.train_energy_forecast import DEFAULT_MODEL_NAME as ENERGY_MODEL_NAME
from app.service.mlops.drift import FeatureDriftReport, compute_feature_drift

# Minimum rows on *each* side of the chronological split for PSI/KS to
# mean anything -- below this, a "drift" reading would just be small-
# sample noise, not a real signal.
_MIN_ROWS_PER_SIDE = 200


async def _load_engineered_features(
    model_name: str, regions: Sequence[str]
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """`(engineered_df, feature_columns)` for whichever architecture
    `model_name` is -- real per-architecture feature engineering, same
    pipeline each one actually trains against."""
    if model_name == ENERGY_MODEL_NAME:
        raw_df = load_energy_training_data_from_master(regions)
        holidays_df = load_holidays_from_master()
        engineered = energy_features.build_features(raw_df, holidays=holidays_df)
        return engineered, energy_features.FEATURE_COLUMNS

    async with get_session() as db:
        raw_df = await demand_data.load_training_data(db, regions)
        holidays_df = await demand_data.load_holidays(db)
    engineered = demand_features.build_features(raw_df, holidays=holidays_df)
    return engineered, demand_features.FEATURE_COLUMNS


async def compute_drift(
    model_name: str,
    regions: Sequence[str],
    *,
    comparison_frac: float = 0.3,
    top_n: int = 10,
) -> list[FeatureDriftReport]:
    """Top `top_n` features by PSI, ranked descending -- `[]` (not an
    error) when there isn't enough real data on both sides of the split
    yet (e.g. this environment's empty Postgres marts for
    `lstm_demand`/`lstm_demand_tft` today), same "empty is a real,
    expected state" convention `GET /v1/model/versions` etc. already
    use."""
    engineered, feature_columns = await _load_engineered_features(model_name, regions)
    if "ts" in engineered.columns:
        engineered = engineered.sort_values("ts")

    split = int(len(engineered) * (1 - comparison_frac))
    reference = engineered.iloc[:split]
    comparison = engineered.iloc[split:]
    if len(reference) < _MIN_ROWS_PER_SIDE or len(comparison) < _MIN_ROWS_PER_SIDE:
        return []

    reports = compute_feature_drift(reference, comparison, feature_columns)
    reports.sort(key=lambda r: (r.psi != r.psi, -r.psi))  # NaN psi sorts last
    return reports[:top_n]
