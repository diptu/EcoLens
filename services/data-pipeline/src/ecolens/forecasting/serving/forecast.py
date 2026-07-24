"""ECO-117: Offline/Batch Inference.

Given the latest feature window per region, runs the trained model and
produces a point + calibrated-interval forecast -- for backtesting and
batch scoring only. This is *not* the live `/v1/forecast` serving
path: that belongs to `forecast-api`'s own model loader (root
`TODO.md`'s ECO-F03/F06), a separate deployable, so this module never
becomes a second low-latency inference surface with its own,
inevitably-diverging copy of the serving contract (see README's
documented service boundary and this file's own package docstring
precedent in `strategy.md` §2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from ..evaluation.conformal import ConformalCalibration
from ..features import FEATURE_COLUMNS, FeatureScaler
from ..models.lstm import DemandLSTM


@dataclass(frozen=True)
class BatchForecast:
    region: str
    as_of: pd.Timestamp
    p50: np.ndarray  # (horizon,), MW
    p10: np.ndarray  # (horizon,), MW, conformally calibrated if `calibration` was given
    p90: np.ndarray


def build_window(
    df: pd.DataFrame, *, lookback: int, scaler: FeatureScaler
) -> tuple[torch.Tensor, pd.Timestamp]:
    """`df`: one region's rows, chronologically sorted, at least
    `lookback` long, carrying `FEATURE_COLUMNS` -- exactly the shape
    `ml_features_demand_v1` already guarantees (see that mart's own
    header comment on why every column is non-null).
    """
    if len(df) < lookback:
        raise ValueError(
            f"need at least {lookback} rows to build a window, got {len(df)}"
        )
    window_df = df.iloc[-lookback:]
    values = window_df[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    scaled = scaler.transform(values)
    x = torch.tensor(scaled, dtype=torch.float32).unsqueeze(
        0
    )  # (1, lookback, n_features)
    return x, window_df["ts_30"].iloc[-1]


@torch.no_grad()
def forecast_region(
    model: DemandLSTM,
    x: torch.Tensor,
    scaler: FeatureScaler,
    calibration: ConformalCalibration | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`x`: `(1, lookback, n_features)`, already scaled. Returns `(p50, p10, p90)`,
    each `(horizon,)`, MW scale.
    """
    model.eval()
    outputs, _ = model(x)
    p50 = scaler.inverse_transform_target(outputs["p50"].numpy())[0]
    p10 = scaler.inverse_transform_target(outputs["p10"].numpy())[0]
    p90 = scaler.inverse_transform_target(outputs["p90"].numpy())[0]
    if calibration is not None:
        p10_cal, p90_cal = calibration.calibrate(p10[None, :], p90[None, :])
        p10, p90 = p10_cal[0], p90_cal[0]
    return p50, p10, p90


def batch_forecast(
    df: pd.DataFrame,
    *,
    model: DemandLSTM,
    scaler: FeatureScaler,
    lookback: int,
    calibration: ConformalCalibration | None = None,
) -> list[BatchForecast]:
    """`df`: a multi-region snapshot (e.g. `TrainingSetLoader.fetch()`'s
    output). One forecast per region, off that region's most recent
    `lookback` rows.
    """
    results = []
    for region, region_df in df.sort_values(["region", "ts_30"]).groupby("region"):
        x, as_of = build_window(region_df, lookback=lookback, scaler=scaler)
        p50, p10, p90 = forecast_region(model, x, scaler, calibration)
        results.append(
            BatchForecast(region=region, as_of=as_of, p50=p50, p10=p10, p90=p90)
        )
    return results


__all__ = ["BatchForecast", "build_window", "forecast_region", "batch_forecast"]
