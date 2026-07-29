"""ECO-110: Feature schema -- the data shapes `service/windowing.py`'s
`build_windowed_dataset` produces and every downstream consumer (training,
evaluation, serving) shares.

Split out of the original `features.py` (which also held the windowing
*logic*, now in `service/windowing.py`) as part of the forecasting
module's layered restructure: this file is pure data-shape definitions
(what a feature vector/window/dataset *is*), not the code that builds
them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

# Contemporaneous covariates + the target series itself. Excludes:
#   * demand_lag_01..48, demand_rolling_avg_7d/std_7d -- redundant with
#     the raw sequence for a model that already sees the last
#     `lookback` demand_mw values directly (rolling stats stay valid
#     inputs in principle, but the mart's rolling window is 7 days,
#     far outside the 24h lookback -- adding it back is a reasonable
#     future feature-engineering pass, not required for a working v1)
#   * is_gap_filled, data_quality_status -- audit metadata, not model
#     inputs (see ml_features_demand_v1.sql's header comment)
#   * ts_30, ts, region -- identifiers, not features
#   * rain_since_9am_mm, is_weekend -- removed by the raw-ingested-column
#     validation pass (scripts/validate_feature_columns.py): weak on all
#     three signals (missingness/variance fine, but near-zero correlation,
#     mutual info, and RF importance against the horizon target)
#   * total_generation_mw -- added by that same validation pass: the one
#     column, of everything ingested but not previously selected, that
#     scores as high as top-quartile included features (corr ~0.77 at
#     horizon). Only ~46% populated (AEMO WEM reports it; AEMO NEM
#     doesn't), but int_energy_filled_30min gap-fills it the same way it
#     already does for renewable_proportion, so it reaches the mart dense.
FEATURE_COLUMNS: tuple[str, ...] = (
    "demand_mw",
    "price_mwh",
    "renewable_generation_mw",
    "renewable_proportion",
    "total_generation_mw",
    "emissions_intensity_kgco2e_per_mwh",
    "net_import_mw",
    "temp_c",
    "apparent_temp_c",
    "dew_point_c",
    "humidity_pct",
    "wind_speed_kmh",
    "wind_direction_deg",
    "wind_gust_kmh",
    "pressure_hpa",
    "cloud_cover_pct",
    "is_holiday",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "month_sin",
    "month_cos",
)
TARGET_COLUMN = "demand_mw"
TARGET_INDEX = FEATURE_COLUMNS.index(TARGET_COLUMN)


@dataclass(frozen=True)
class FeatureScaler:
    """Mean/std per feature, fit once on the train split and reused
    everywhere else (val/calibration/test here, and at inference time
    in forecast-api) -- fitting on anything but train would leak
    future distribution info into "normalized" training data.
    """

    mean: np.ndarray
    std: np.ndarray
    columns: tuple[str, ...]

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def inverse_transform_target(self, y: np.ndarray) -> np.ndarray:
        """Undo scaling for just the target column (what a forecast needs)."""
        return y * self.std[TARGET_INDEX] + self.mean[TARGET_INDEX]

    def to_dict(self) -> dict[str, list[float] | list[str]]:
        return {
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "columns": list(self.columns),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureScaler":
        return cls(
            mean=np.asarray(d["mean"], dtype=np.float64),
            std=np.asarray(d["std"], dtype=np.float64),
            columns=tuple(d["columns"]),
        )


@dataclass(frozen=True)
class Split:
    """One chronological slice: scaled `(lookback, features)` windows and
    their `(horizon,)` demand targets, scaled by the *same* mean/std as
    the `demand_mw` feature column (`scaler.inverse_transform_target`
    undoes it) -- training the model against raw MW-scale targets
    alongside a Huber loss with `delta=1.0` would leave the loss almost
    always in its linear regime and gradients dominated by target
    magnitude rather than actual error, which is slow and unstable to
    train against.
    """

    x: torch.Tensor  # (n, lookback, n_features)
    y: torch.Tensor  # (n, horizon)
    as_of: pd.Series  # ts_30 the lookback window ends at, per sample
    region: pd.Series  # region, per sample


@dataclass(frozen=True)
class WindowedDataset:
    train: Split
    val: Split
    calibration: Split
    test: Split
    scaler: FeatureScaler
    lookback: int
    horizon: int


__all__ = [
    "FEATURE_COLUMNS",
    "TARGET_COLUMN",
    "TARGET_INDEX",
    "FeatureScaler",
    "Split",
    "WindowedDataset",
]
