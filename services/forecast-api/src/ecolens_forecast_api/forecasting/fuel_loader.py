"""Loader for the per-fuel LightGBM ensemble (root TODO.md's
"Normalization Constraint Layer" -> "API & Registry Serving"), structurally
parallel to `loader.py`'s `ModelLoader` for the LSTM but much thinner:
data-pipeline's `training/train_fuel_ensemble.py` persists the whole
ensemble as one generic `mlflow.pyfunc` model (see that module's
docstring for why), so loading it back is a single
`mlflow.pyfunc.load_model` call -- no architecture dict, no state_dict,
no `FeatureScaler` to reconstruct alongside it, and no dependency on
data-pipeline's own `FuelEnsemble` class.

Deliberately loaded **once at startup**, not on `reload.py`'s
poll-loop cadence -- a real simplification versus the LSTM's hot-reload
path (ECO-F04), scoped out for this pass rather than silently skipped:
the fuel mix's *shares* (what this ensemble actually predicts, see
`fuel_forecast.py`) drift far slower than demand itself, and standing up
a second background poll loop/sanity-check/rollback path structurally
identical to `reload.py` for a lower-priority signal was judged not worth
it in this pass. `app.py`'s lifespan calls `load_once()` the same
resilient way it already calls `reloader.start()` -- an unreachable
MLflow server or no version registered yet degrades `source_breakdown_mw`/
`carbon_metrics` to `None` in the response, never blocks startup or
breaks `/v1/forecast`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import mlflow
import mlflow.pyfunc
from mlflow.pyfunc import PyFuncModel
from mlflow.tracking import MlflowClient

from ..logging import get_logger
from ..settings import ForecastApiSettings

log = get_logger(__name__)


class FuelEnsembleLoadError(Exception):
    """The aliased version exists but couldn't be loaded."""


@dataclass(frozen=True)
class LoadedFuelEnsemble:
    model: PyFuncModel
    version: str
    run_id: str


class FuelEnsembleLoader:
    def __init__(self, settings: ForecastApiSettings) -> None:
        self.settings = settings
        # Same fail-fast rationale as loader.py's ModelLoader.__init__ --
        # must happen before any MLflow HTTP call.
        os.environ.setdefault(
            "MLFLOW_HTTP_REQUEST_TIMEOUT", str(settings.mlflow_http_timeout_seconds)
        )
        os.environ.setdefault(
            "MLFLOW_HTTP_REQUEST_MAX_RETRIES", str(settings.mlflow_http_max_retries)
        )
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        self.client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    def load_current(self) -> LoadedFuelEnsemble | None:
        """The version currently behind `settings.model_alias`, or `None`
        if nothing holds that alias yet -- same "not an error" contract
        as `loader.py`'s `ModelLoader.load_current`.
        """
        try:
            mv = self.client.get_model_version_by_alias(
                self.settings.mlflow_registered_model_name_fuel_ensemble,
                self.settings.model_alias,
            )
        except mlflow.exceptions.MlflowException:
            return None

        run_id = mv.run_id or ""
        version = str(mv.version)
        try:
            model = mlflow.pyfunc.load_model(f"runs:/{run_id}/model")
        except Exception as exc:  # noqa: BLE001 - any artifact/network failure is a load failure, wrapped uniformly
            raise FuelEnsembleLoadError(
                f"failed to load fuel ensemble version {version} (run {run_id}): {exc}"
            ) from exc

        log.info("fuel_loader.loaded", version=version, run_id=run_id)
        return LoadedFuelEnsemble(model=model, version=version, run_id=run_id)


__all__ = ["FuelEnsembleLoader", "FuelEnsembleLoadError", "LoadedFuelEnsemble"]
