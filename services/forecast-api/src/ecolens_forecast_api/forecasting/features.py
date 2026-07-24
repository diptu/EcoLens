"""ECO-F05/F06: feature columns, scaling, and window construction for
real-model inference.

`FEATURE_COLUMNS` and `FeatureScaler` are structural duplicates of
`data-pipeline`'s `forecasting/features.py` -- same rationale as
`model.py`'s duplicated `DemandLSTM` (see that file's docstring): the
scaler's `mean`/`std` arrays are just numbers logged as a JSON artifact
(`scaler.json`, see `data-pipeline`'s `training/train.py`), with no
class identity to preserve, so this only needs to agree on the column
*order* and the transform math, not share a Python class with the
training side.

`build_window` reconstructs the `(1, lookback, n_features)` model input
from the last `lookback` rows of `ml_features_demand_v1` -- the
sliding-window buffer `strategy.md` §6 describes, minus the
`collections.deque` (a deque would matter for a true streaming/
incremental-hidden-state serving path; this service queries Postgres
per request today, see `queries.py`'s `get_recent_feature_rows`, which
is simpler and correct for now -- ECO-F05's note in `TODO.md` flags the
deque as the next step if per-request Postgres reads become a
bottleneck).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# Order matters: must exactly match data-pipeline's forecasting/features.py.
FEATURE_COLUMNS: tuple[str, ...] = (
    "demand_mw",
    "price_mwh",
    "renewable_generation_mw",
    "renewable_proportion",
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
    "rain_since_9am_mm",
    "cloud_cover_pct",
    "is_holiday",
    "is_weekend",
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
    mean: np.ndarray
    std: np.ndarray
    columns: tuple[str, ...]

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def inverse_transform_target(self, y: np.ndarray) -> np.ndarray:
        return y * self.std[TARGET_INDEX] + self.mean[TARGET_INDEX]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FeatureScaler:
        return cls(
            mean=np.asarray(d["mean"], dtype=np.float64),
            std=np.asarray(d["std"], dtype=np.float64),
            columns=tuple(d["columns"]),
        )


@dataclass(frozen=True)
class ConformalCalibration:
    """Structural duplicate of data-pipeline's evaluation/conformal.py
    dataclass -- this service only ever *applies* an already-fit
    calibration (`calibrate`), never fits one (`fit_conformal_calibration`
    stays training-side, where the held-out calibration split lives).
    """

    q_hat: np.ndarray
    alpha: float

    def calibrate(
        self, p10_raw: np.ndarray, p90_raw: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        return p10_raw - self.q_hat, p90_raw + self.q_hat

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConformalCalibration:
        return cls(q_hat=np.asarray(d["q_hat"], dtype=np.float64), alpha=d["alpha"])


def build_window(
    rows: list[dict[str, Any]], *, lookback: int, scaler: FeatureScaler
) -> np.ndarray:
    """`rows`: the last `lookback` `ml_features_demand_v1` rows for one
    region, chronologically ascending (oldest first), each carrying
    every `FEATURE_COLUMNS` key. Returns a scaled `(1, lookback,
    n_features)` array ready for the model.
    """
    if len(rows) < lookback:
        raise ValueError(
            f"need at least {lookback} rows to build a window, got {len(rows)}"
        )
    recent = rows[-lookback:]
    values = np.array(
        [[float(row[col]) for col in FEATURE_COLUMNS] for row in recent],
        dtype=np.float64,
    )
    scaled = scaler.transform(values)
    return scaled[np.newaxis, :, :]  # (1, lookback, n_features)


__all__ = [
    "FEATURE_COLUMNS",
    "TARGET_COLUMN",
    "TARGET_INDEX",
    "FeatureScaler",
    "ConformalCalibration",
    "build_window",
]
