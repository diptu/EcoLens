"""Scores a trained `DemandTFT` on the held-out calibration + test splits --
a parallel module to `evaluate.py`, needed only because `DemandTFT.forward`
takes an extra `region_idx` argument `evaluate.py`'s `predict_split` doesn't
know how to supply. Everything downstream of "run the model and get MW-scale
predictions back" is architecture-agnostic and reused **unchanged**:
`fit_conformal_calibration`, `empirical_coverage` (`conformal.py`),
`evaluate_predictions` (`metrics.py`), and `log_evaluation_to_mlflow`
(`evaluate.py`) all operate on plain numpy arrays / the generic
`FullEvaluation` dataclass, with no LSTM-specific assumptions.
"""

from __future__ import annotations

import numpy as np
import torch

from ecolens.forecasting.model.tft import DemandTFT
from ecolens.forecasting.schema.features import FeatureScaler, Split, WindowedDataset

from .conformal import empirical_coverage, fit_conformal_calibration
from .evaluate import FullEvaluation
from .metrics import evaluate_predictions


@torch.no_grad()
def predict_split_tft(
    model: DemandTFT,
    split: Split,
    scaler: FeatureScaler,
    region_to_idx: dict[str, int],
) -> dict[str, np.ndarray]:
    """`evaluate.py`'s `predict_split`, plus building the `region_idx`
    tensor `DemandTFT.forward` requires from `split.region`.
    """
    model.eval()
    region_idx = torch.tensor(
        [region_to_idx[r] for r in split.region], dtype=torch.long
    )
    outputs, _ = model(split.x, region_idx)
    return {
        "p50": scaler.inverse_transform_target(outputs["p50"].numpy()),
        "p10": scaler.inverse_transform_target(outputs["p10"].numpy()),
        "p90": scaler.inverse_transform_target(outputs["p90"].numpy()),
        "y_true": scaler.inverse_transform_target(split.y.numpy()),
    }


def evaluate_tft_model(
    model: DemandTFT,
    dataset: WindowedDataset,
    region_to_idx: dict[str, int],
    *,
    alpha: float,
) -> FullEvaluation:
    """`evaluate.py`'s `evaluate_model`, calling `predict_split_tft`
    instead of `predict_split` -- otherwise identical: fit conformal
    calibration on `dataset.calibration`, score point accuracy + calibrated
    coverage on `dataset.test`.
    """
    cal_preds = predict_split_tft(
        model, dataset.calibration, dataset.scaler, region_to_idx
    )
    calibration = fit_conformal_calibration(
        cal_preds["p10"], cal_preds["p90"], cal_preds["y_true"], alpha=alpha
    )

    test_preds = predict_split_tft(model, dataset.test, dataset.scaler, region_to_idx)
    point = evaluate_predictions(
        test_preds["y_true"], test_preds["p50"], regions=dataset.test.region
    )

    p10_cal, p90_cal = calibration.calibrate(test_preds["p10"], test_preds["p90"])
    coverage = empirical_coverage(p10_cal, p90_cal, test_preds["y_true"])

    return FullEvaluation(point=point, conformal=calibration, test_coverage=coverage)


__all__ = ["predict_split_tft", "evaluate_tft_model"]
