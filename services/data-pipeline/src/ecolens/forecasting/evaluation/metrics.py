"""ECO-114 (point-forecast metrics): MAPE/RMSE/MAE per region and per
horizon step, plus the aggregate across all of them.

All functions take *already MW-scale* (inverse-transformed) arrays --
see `features.FeatureScaler.inverse_transform_target` -- callers are
responsible for undoing normalization before scoring, since an error
metric computed in scaled-feature space isn't interpretable by anyone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, *, eps: float = 1e-3) -> float:
    """Mean absolute percentage error. `eps` guards against near-zero
    demand denominators blowing this up to a meaningless huge number --
    grid demand is never actually ~0 MW, so this only bites on
    synthetic/test data with unrealistic values.
    """
    denom = np.clip(np.abs(y_true), eps, None)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100.0)


@dataclass(frozen=True)
class EvaluationReport:
    overall: dict[str, float]
    per_horizon_step: pd.DataFrame  # columns: horizon_step, mae, rmse, mape
    per_region: pd.DataFrame  # columns: region, mae, rmse, mape


def evaluate_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    regions: pd.Series | None = None,
) -> EvaluationReport:
    """`y_true`/`y_pred`: `(n_samples, horizon)`, MW scale.

    `regions`: optional length-`n_samples` label per sample, for the
    per-region breakdown (omit for a horizon-only report, e.g. when
    scoring a single region).
    """
    if y_true.shape != y_pred.shape:
        raise ValueError(
            f"shape mismatch: y_true {y_true.shape} vs y_pred {y_pred.shape}"
        )

    overall = {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "mape": mape(y_true, y_pred),
    }

    horizon_rows = []
    for step in range(y_true.shape[1]):
        yt, yp = y_true[:, step], y_pred[:, step]
        horizon_rows.append(
            {
                "horizon_step": step + 1,
                "mae": mae(yt, yp),
                "rmse": rmse(yt, yp),
                "mape": mape(yt, yp),
            }
        )
    per_horizon_step = pd.DataFrame(horizon_rows)

    if regions is not None:
        region_rows = []
        for region in sorted(regions.unique()):
            mask = (regions == region).to_numpy()
            yt, yp = y_true[mask], y_pred[mask]
            region_rows.append(
                {
                    "region": region,
                    "mae": mae(yt, yp),
                    "rmse": rmse(yt, yp),
                    "mape": mape(yt, yp),
                }
            )
        per_region = pd.DataFrame(region_rows)
    else:
        per_region = pd.DataFrame(columns=["region", "mae", "rmse", "mape"])

    return EvaluationReport(
        overall=overall, per_horizon_step=per_horizon_step, per_region=per_region
    )


__all__ = ["mae", "rmse", "mape", "EvaluationReport", "evaluate_predictions"]
