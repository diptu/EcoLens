"""ECO-F03: Model Loader.

Resolves the MLflow Registry alias to a run, then loads the artifacts
that run wrote (see `data-pipeline`'s `mlops/registry.py`'s
`log_model_artifacts`, `training/train.py`'s `scaler.json`, and
`evaluation/evaluate.py`'s `conformal_calibration.json`): architecture,
`state_dict`, feature scaler, and conformal calibration -- everything
one self-contained forecast needs, no other service call.

Uses `mlflow.pytorch.load_state_dict`/`mlflow.artifacts.load_dict`, not
`mlflow.pytorch.load_model` -- the latter would try to unpickle a
`DemandLSTM` instance, which requires the *exact* class importable at
the *exact* module path it was pickled from (`data-pipeline`'s
`ecolens.forecasting.models.lstm`). This service has its own structural
duplicate (`forecasting/model.py`) instead, precisely so it doesn't
need to depend on `data-pipeline`'s package -- see that file's
docstring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import mlflow
import mlflow.artifacts
import mlflow.pytorch
import torch
from mlflow.tracking import MlflowClient

from ..logging import get_logger
from ..settings import ForecastApiSettings
from .features import ConformalCalibration, FeatureScaler
from .model import DemandLSTM
from .optimize import apply_inference_optimization

log = get_logger(__name__)


class ModelLoadError(Exception):
    """The aliased version exists but couldn't be loaded (missing/
    corrupt artifact, architecture mismatch, ...). Distinct from "no
    version holds the alias yet," which isn't an error -- see
    `load_current`'s `None` return.
    """


@dataclass(frozen=True)
class LoadedModel:
    model: DemandLSTM
    scaler: FeatureScaler
    calibration: ConformalCalibration | None
    version: str
    run_id: str


class ModelLoader:
    def __init__(self, settings: ForecastApiSettings) -> None:
        self.settings = settings
        # Must happen before any MLflow HTTP call -- these env vars are
        # what mlflow's internal REST client reads for timeout/retry
        # config, and its defaults (120s x 7 retries) turn "MLflow is
        # briefly unreachable" into a multi-minute stall (see
        # settings.py's mlflow_http_timeout_seconds docstring).
        os.environ.setdefault(
            "MLFLOW_HTTP_REQUEST_TIMEOUT", str(settings.mlflow_http_timeout_seconds)
        )
        os.environ.setdefault(
            "MLFLOW_HTTP_REQUEST_MAX_RETRIES", str(settings.mlflow_http_max_retries)
        )
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        self.client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    def load_current(self) -> LoadedModel | None:
        """The version currently behind `settings.model_alias`, or `None`
        if nothing holds that alias yet (e.g. `data-pipeline` hasn't
        trained/promoted a model at all) -- the baseline forecaster
        keeps serving in that case (see `routes.py`, ECO-F06).
        """
        try:
            mv = self.client.get_model_version_by_alias(
                self.settings.mlflow_registered_model_name, self.settings.model_alias
            )
        except mlflow.exceptions.MlflowException:
            return None
        return self._load_version(run_id=mv.run_id or "", version=str(mv.version))

    def _load_version(self, *, run_id: str, version: str) -> LoadedModel:
        try:
            architecture = mlflow.artifacts.load_dict(
                f"runs:/{run_id}/model_architecture.json"
            )
            state_dict = mlflow.pytorch.load_state_dict(
                f"runs:/{run_id}/model_state_dict",
                map_location=torch.device(self.settings.inference_device),
            )
            scaler_dict = mlflow.artifacts.load_dict(f"runs:/{run_id}/scaler.json")
        except Exception as exc:  # noqa: BLE001 - any artifact/network failure is a load failure, wrapped uniformly below
            raise ModelLoadError(
                f"failed to load model version {version} (run {run_id}): {exc}"
            ) from exc

        model = DemandLSTM(**architecture)
        try:
            model.load_state_dict(state_dict)
        except Exception as exc:  # noqa: BLE001 - architecture/state_dict mismatch (e.g. this file drifted from data-pipeline's DemandLSTM)
            raise ModelLoadError(
                f"model version {version} (run {run_id}) state_dict does not match "
                f"this service's DemandLSTM architecture -- has forecasting/model.py "
                f"drifted from data-pipeline's? ({exc})"
            ) from exc
        model.eval()
        model = apply_inference_optimization(model, self.settings)

        calibration = None
        try:
            calibration_dict = mlflow.artifacts.load_dict(
                f"runs:/{run_id}/conformal_calibration.json"
            )
            calibration = ConformalCalibration.from_dict(calibration_dict)
        except Exception as exc:  # noqa: BLE001 - calibration is optional; degrade to raw quantile heads rather than fail the whole load
            log.warning(
                "loader.no_calibration", run_id=run_id, version=version, error=str(exc)
            )

        log.info(
            "loader.loaded",
            version=version,
            run_id=run_id,
            has_calibration=calibration is not None,
        )
        return LoadedModel(
            model=model,
            scaler=FeatureScaler.from_dict(scaler_dict),
            calibration=calibration,
            version=version,
            run_id=run_id,
        )


__all__ = ["ModelLoader", "ModelLoadError", "LoadedModel"]
