"""Scores a trained `TimesFMCalibrationHead` on the held-out calibration +
test splits -- a parallel module to `evaluate.py`/`evaluate_tft.py`.
Unlike those two, this never calls the frozen TimesFM backbone itself: it
takes the `RawForecast`s `training/train_timesfm.py`'s one-time precompute
pass already produced for every split (`TimesFMTrainResult.raw_forecasts`)
rather than recomputing them, since the backbone's output for a fixed
input never changes and a second real-model pass would be pure waste.
Everything downstream of "run the head and get MW-scale predictions back"
is architecture-agnostic and reused **unchanged**: `fit_conformal_calibration`,
`empirical_coverage` (`conformal.py`), `evaluate_predictions` (`metrics.py`),
and `log_evaluation_to_mlflow` (`evaluate.py`).
"""

from __future__ import annotations

import numpy as np
import torch

from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead
from ecolens.forecasting.schema.features import FeatureScaler, Split, WindowedDataset

from ..training.train_timesfm import RawForecast
from .conformal import empirical_coverage, fit_conformal_calibration
from .evaluate import FullEvaluation
from .metrics import evaluate_predictions


@torch.no_grad()
def predict_split_timesfm(
    model: TimesFMCalibrationHead,
    split: Split,
    scaler: FeatureScaler,
    region_to_idx: dict[str, int],
    raw: RawForecast,
) -> dict[str, np.ndarray]:
    """`evaluate.py`'s `predict_split`, running the head against a
    precomputed `RawForecast` instead of the model taking `split.x`
    directly.
    """
    model.eval()
    region_idx = torch.tensor(
        [region_to_idx[r] for r in split.region], dtype=torch.long
    )
    outputs = model(raw.p10, raw.p50, raw.p90, region_idx)
    return {
        "p50": scaler.inverse_transform_target(outputs["p50"].numpy()),
        "p10": scaler.inverse_transform_target(outputs["p10"].numpy()),
        "p90": scaler.inverse_transform_target(outputs["p90"].numpy()),
        "y_true": scaler.inverse_transform_target(split.y.numpy()),
    }


def evaluate_timesfm_model(
    model: TimesFMCalibrationHead,
    dataset: WindowedDataset,
    region_to_idx: dict[str, int],
    raw_forecasts: dict[str, RawForecast],
    *,
    alpha: float,
) -> FullEvaluation:
    """`evaluate.py`'s `evaluate_model`, calling `predict_split_timesfm`
    against the already-precomputed `raw_forecasts["calibration"]`/
    `raw_forecasts["test"]` instead of re-running TimesFM -- otherwise
    identical: fit conformal calibration on `dataset.calibration`, score
    point accuracy + calibrated coverage on `dataset.test`.
    """
    cal_preds = predict_split_timesfm(
        model,
        dataset.calibration,
        dataset.scaler,
        region_to_idx,
        raw_forecasts["calibration"],
    )
    calibration = fit_conformal_calibration(
        cal_preds["p10"], cal_preds["p90"], cal_preds["y_true"], alpha=alpha
    )

    test_preds = predict_split_timesfm(
        model, dataset.test, dataset.scaler, region_to_idx, raw_forecasts["test"]
    )
    point = evaluate_predictions(
        test_preds["y_true"], test_preds["p50"], regions=dataset.test.region
    )

    p10_cal, p90_cal = calibration.calibrate(test_preds["p10"], test_preds["p90"])
    coverage = empirical_coverage(p10_cal, p90_cal, test_preds["y_true"])

    return FullEvaluation(point=point, conformal=calibration, test_coverage=coverage)


__all__ = ["predict_split_timesfm", "evaluate_timesfm_model"]
