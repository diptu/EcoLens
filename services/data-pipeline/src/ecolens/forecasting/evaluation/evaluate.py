"""ECO-114 (evaluate.py): scores a trained `DemandLSTM` on the held-out
calibration + test splits -- fits conformal calibration on
`calibration`, scores point-forecast metrics and empirical interval
coverage on `test` (a split the model never saw for anything, not even
calibration) -- and writes the results back to MLflow. This is the
"daily evaluation" job the README's schedule assumes exists, and what
`mlops/promote.py` (ECO-115) reads to decide whether a challenger beats
the current Production model.
"""

from __future__ import annotations

from dataclasses import dataclass

import mlflow
import numpy as np
import torch

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..features import FeatureScaler, Split, WindowedDataset
from ..models.lstm import DemandLSTM
from .conformal import (
    ConformalCalibration,
    empirical_coverage,
    fit_conformal_calibration,
)
from .metrics import EvaluationReport, evaluate_predictions

log = get_logger(__name__)


@dataclass(frozen=True)
class FullEvaluation:
    point: EvaluationReport
    conformal: ConformalCalibration
    test_coverage: float


@torch.no_grad()
def predict_split(
    model: DemandLSTM, split: Split, scaler: FeatureScaler
) -> dict[str, np.ndarray]:
    """Runs `model` over an entire split and inverse-transforms every
    output back to MW scale -- nothing downstream of this function
    should ever see a normalized value.
    """
    model.eval()
    outputs, _ = model(split.x)
    return {
        "p50": scaler.inverse_transform_target(outputs["p50"].numpy()),
        "p10": scaler.inverse_transform_target(outputs["p10"].numpy()),
        "p90": scaler.inverse_transform_target(outputs["p90"].numpy()),
        "y_true": scaler.inverse_transform_target(split.y.numpy()),
    }


def evaluate_model(
    model: DemandLSTM, dataset: WindowedDataset, *, alpha: float
) -> FullEvaluation:
    """Fits conformal calibration on `dataset.calibration`, then scores
    everything (point accuracy + calibrated-interval coverage) on
    `dataset.test` -- the one split that touched neither training,
    early-stopping, nor calibration.
    """
    cal_preds = predict_split(model, dataset.calibration, dataset.scaler)
    calibration = fit_conformal_calibration(
        cal_preds["p10"], cal_preds["p90"], cal_preds["y_true"], alpha=alpha
    )

    test_preds = predict_split(model, dataset.test, dataset.scaler)
    point = evaluate_predictions(
        test_preds["y_true"], test_preds["p50"], regions=dataset.test.region
    )

    p10_cal, p90_cal = calibration.calibrate(test_preds["p10"], test_preds["p90"])
    coverage = empirical_coverage(p10_cal, p90_cal, test_preds["y_true"])

    log.info(
        "evaluation.complete",
        mae=round(point.overall["mae"], 2),
        rmse=round(point.overall["rmse"], 2),
        mape=round(point.overall["mape"], 2),
        test_coverage=round(coverage, 4),
        target_coverage=round(1 - alpha, 4),
    )
    return FullEvaluation(point=point, conformal=calibration, test_coverage=coverage)


def log_evaluation_to_mlflow(
    evaluation: FullEvaluation,
    *,
    run_id: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Writes evaluation results back to MLflow: metrics onto `run_id`
    if given (the training run being scored), otherwise a fresh run --
    which needs `mlflow.set_experiment` first, same as `train_model`/
    `tune`/`fine_tune`, or it lands outside the configured experiment.
    """
    if run_id is None:
        mlflow.set_experiment((settings or get_settings()).mlflow_experiment_name)
    ctx = mlflow.start_run(run_id=run_id) if run_id else mlflow.start_run()
    with ctx:
        mlflow.log_metrics(
            {
                "test_mae": evaluation.point.overall["mae"],
                "test_rmse": evaluation.point.overall["rmse"],
                "test_mape": evaluation.point.overall["mape"],
                "test_coverage": evaluation.test_coverage,
                "conformal_alpha": evaluation.conformal.alpha,
            }
        )
        mlflow.log_dict(evaluation.conformal.to_dict(), "conformal_calibration.json")


__all__ = [
    "FullEvaluation",
    "predict_split",
    "evaluate_model",
    "log_evaluation_to_mlflow",
]
