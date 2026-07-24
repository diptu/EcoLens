"""ECO-110: Feature Windowing Layer.

Turns a ml_features_demand_v1 snapshot (ECO-109) into
`(lookback -> horizon)` tensor pairs sized to `Settings.model_lookback`/
`model_horizon`, with a time-based (never random) train/validation/
calibration/test split and a scaler fit only on the train split.

Deliberately reads the *raw sequence* of covariates per 30-min slot as
the LSTM's input at each timestep -- not the mart's precomputed
`demand_lag_01..48` columns, which exist for the non-sequential
seasonal-naive baseline (`forecast-api`'s `forecasting/baseline.py`).
An LSTM wants "here's what the grid looked like at each of the last 48
half-hours," not "here's the same 48 numbers flattened into one row";
reusing the lag columns for both would just be duplicating the same
information in two incompatible shapes for no benefit. This is also
exactly the sequence shape `strategy.md`'s sliding-window `deque`
(ECO-F05) has to reconstruct at inference time, so the two stay
consistent by construction.
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


def _windows_for_region(
    df: pd.DataFrame, lookback: int, horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every valid `(lookback -> horizon)` window for one region's
    chronologically-sorted feature matrix. Returns `(X, y, end_idx)`
    where `end_idx` is the row index each window's lookback ends at
    (for attaching `ts_30`/`region` back afterward).
    """
    values = df[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    target = values[:, TARGET_INDEX]
    n = len(df)
    last_start = n - lookback - horizon
    if last_start < 0:
        return (
            np.empty((0, lookback, len(FEATURE_COLUMNS))),
            np.empty((0, horizon)),
            np.empty((0,), dtype=np.int64),
        )

    starts = np.arange(0, last_start + 1)
    x_idx = starts[:, None] + np.arange(lookback)[None, :]
    x = values[x_idx]
    y_idx = starts[:, None] + lookback + np.arange(horizon)[None, :]
    y = target[y_idx]
    end_idx = starts + lookback - 1
    return x, y, end_idx


def _time_split_indices(
    n: int, fractions: tuple[float, float, float, float]
) -> list[slice]:
    """Chronological (non-shuffled) cut points for n samples into 4 slices."""
    if abs(sum(fractions) - 1.0) > 1e-6:
        raise ValueError(f"split fractions must sum to 1.0, got {fractions}")
    cuts = np.cumsum([int(round(n * f)) for f in fractions[:-1]])
    bounds = [0, *cuts.tolist(), n]
    return [slice(bounds[i], bounds[i + 1]) for i in range(4)]


def build_windowed_dataset(
    df: pd.DataFrame,
    *,
    lookback: int,
    horizon: int,
    split_fractions: tuple[float, float, float, float] = (0.7, 0.1, 0.1, 0.1),
) -> WindowedDataset:
    """The main entry point: raw snapshot -> ready-to-train tensors.

    Splits chronologically *within each region* first (so every split
    has data from every region), then concatenates -- never splits by
    shuffling rows, which would leak future information into "past"
    training windows.
    """
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"snapshot is missing expected columns: {missing}")

    df = df.dropna(subset=list(FEATURE_COLUMNS)).sort_values(["region", "ts_30"])

    per_split_x: list[list[np.ndarray]] = [[], [], [], []]
    per_split_y: list[list[np.ndarray]] = [[], [], [], []]
    per_split_ts: list[list[pd.Series]] = [[], [], [], []]
    per_split_region: list[list[pd.Series]] = [[], [], [], []]

    for region, region_df in df.groupby("region", sort=True):
        region_df = region_df.reset_index(drop=True)
        x, y, end_idx = _windows_for_region(region_df, lookback, horizon)
        if len(end_idx) == 0:
            continue
        ts_at_end = region_df["ts_30"].to_numpy()[end_idx]

        for i, sl in enumerate(_time_split_indices(len(end_idx), split_fractions)):
            per_split_x[i].append(x[sl])
            per_split_y[i].append(y[sl])
            per_split_ts[i].append(pd.Series(ts_at_end[sl]))
            per_split_region[i].append(pd.Series([region] * (sl.stop - sl.start)))

    empty_splits = [len(chunks) == 0 for chunks in per_split_x]
    if any(empty_splits):
        raise ValueError(
            "not enough history to build even one window per split -- need "
            f"at least {lookback + horizon} rows per region, ideally many "
            "multiples of that so every split gets samples"
        )

    train_x = np.concatenate(per_split_x[0], axis=0)
    flat = train_x.reshape(-1, train_x.shape[-1])
    std = flat.std(axis=0)
    scaler = FeatureScaler(
        mean=flat.mean(axis=0),
        std=np.where(std > 1e-8, std, 1.0),
        columns=FEATURE_COLUMNS,
    )

    splits = []
    for i in range(4):
        x_cat = np.concatenate(per_split_x[i], axis=0)
        y_cat = np.concatenate(per_split_y[i], axis=0)
        x_scaled = scaler.transform(x_cat)
        y_scaled = (y_cat - scaler.mean[TARGET_INDEX]) / scaler.std[TARGET_INDEX]
        splits.append(
            Split(
                x=torch.tensor(x_scaled, dtype=torch.float32),
                y=torch.tensor(y_scaled, dtype=torch.float32),
                as_of=pd.concat(per_split_ts[i], ignore_index=True),
                region=pd.concat(per_split_region[i], ignore_index=True),
            )
        )

    return WindowedDataset(
        train=splits[0],
        val=splits[1],
        calibration=splits[2],
        test=splits[3],
        scaler=scaler,
        lookback=lookback,
        horizon=horizon,
    )


__all__ = [
    "FEATURE_COLUMNS",
    "TARGET_COLUMN",
    "TARGET_INDEX",
    "FeatureScaler",
    "Split",
    "WindowedDataset",
    "build_windowed_dataset",
]
