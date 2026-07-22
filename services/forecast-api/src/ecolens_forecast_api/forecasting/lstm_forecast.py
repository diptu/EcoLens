"""ECO-F06: real-model forecaster.

Builds the exact same `[{ts, horizon_step, p10, p50, p90}, ...]` shape
`forecasting/baseline.py`'s `forecast_from_latest_row` does, but from
actual LSTM inference plus conformal-calibrated intervals in place of
the baseline's naive std-based ones -- so `routes.py` doesn't need to
know or care which forecaster actually served a given request; the
response contract (and API consumers) never change.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import torch

from .features import build_window
from .loader import LoadedModel

MODEL_NAME_PREFIX = "demand_lstm_v"


def model_name(loaded: LoadedModel) -> str:
    return f"{MODEL_NAME_PREFIX}{loaded.version}"


@torch.no_grad()
def forecast_from_recent_rows(
    loaded: LoadedModel,
    rows: list[dict[str, Any]],
    *,
    lookback: int,
    horizon: int,
    interval_minutes: int,
) -> list[dict[str, Any]]:
    """`rows`: chronologically ascending `ml_features_demand_v1` rows for
    one region, at least `lookback` long (see `queries.get_recent_feature_rows`).
    """
    x = torch.tensor(
        build_window(rows, lookback=lookback, scaler=loaded.scaler), dtype=torch.float32
    )

    loaded.model.eval()
    outputs, _ = loaded.model(x)

    p50 = loaded.scaler.inverse_transform_target(outputs["p50"].numpy())
    p10 = loaded.scaler.inverse_transform_target(outputs["p10"].numpy())
    p90 = loaded.scaler.inverse_transform_target(outputs["p90"].numpy())

    if loaded.calibration is not None:
        p10, p90 = loaded.calibration.calibrate(p10, p90)

    base_ts = rows[-1]["ts_30"]
    available = min(horizon, p50.shape[1])
    steps = []
    for h in range(1, available + 1):
        steps.append(
            {
                "ts": base_ts + timedelta(minutes=interval_minutes * h),
                "horizon_step": h,
                "p10": float(p10[0, h - 1]),
                "p50": float(p50[0, h - 1]),
                "p90": float(p90[0, h - 1]),
            }
        )
    return steps


__all__ = ["model_name", "forecast_from_recent_rows", "MODEL_NAME_PREFIX"]
