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

The data shapes this builds (`FeatureScaler`/`Split`/`WindowedDataset`/
`FEATURE_COLUMNS`) live in `ecolens.forecasting.schema.features` --
split out from this module as part of the forecasting layer restructure,
since those are shared data-shape definitions, not windowing logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from ecolens.forecasting.schema.features import (
    FEATURE_COLUMNS,
    TARGET_INDEX,
    FeatureScaler,
    Split,
    WindowedDataset,
)


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
    scaler: FeatureScaler | None = None,
    split_fractions: tuple[float, float, float, float] = (0.7, 0.1, 0.1, 0.1),
) -> WindowedDataset:
    """The main entry point: raw snapshot -> ready-to-train tensors.

    Splits chronologically *within each region* first (so every split
    has data from every region), then concatenates -- never splits by
    shuffling rows, which would leak future information into "past"
    training windows.

    `scaler`, if given, is used as-is (no fitting) instead of fitting a
    fresh one from this call's own train split -- required for
    `training/incremental.py`'s chunked training loop: fitting a new
    scaler per chunk (2023's mean/std, then 2024's, then 2025's, ...)
    would shift the LSTM's input distribution at every chunk boundary,
    confusing a model whose weights were trained against a *different*
    normalization. Fit once (omit `scaler` on the first chunk) and reuse
    it for every later chunk in the same sequence.
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

    if scaler is None:
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


__all__ = ["build_windowed_dataset"]
