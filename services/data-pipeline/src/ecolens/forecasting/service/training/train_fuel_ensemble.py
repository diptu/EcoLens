"""Training loop for `model/fuel_ensemble.py`'s per-fuel LightGBM
ensemble -- structurally unlike `train.py`/`train_tft.py`/
`train_timesfm.py` in two ways: no epoch loop (`LGBMRegressor.fit` is a
single call, not a training step this module iterates), and no
`mlflow.pytorch.log_model` (a dict of 16 `LGBMRegressor`s isn't a single
torch module `mlops/registry.py`'s `ForecastingModel` protocol/loader
fits).

Persisted as one `mlflow.pyfunc.PythonModel` bundling all 16 boosters into
a single joblib artifact -- deliberately *not* 16 separate
`mlflow.lightgbm.log_model` calls under 16 artifact paths, and *not*
pickling the `FuelEnsemble` Python object directly either (that would
require whatever loads it, including `forecast-api`, to import this
package's `FuelEnsemble` class -- exactly the coupling
`mlops/registry.py`'s own docstring says the LSTM's dual-logging avoids).
The pyfunc's `predict(context, model_input) -> DataFrame` is the only
contract a loader needs; `forecast-api`'s serving-side loader (root
TODO.md's "API & Registry Serving" section) never needs to know this
ensemble is LightGBM-backed at all, only that it's a `mlflow.pyfunc`
model. This one artifact path ("model") is exactly what
`mlops/registry.py`'s existing `ModelRegistry.register()`/`get_by_alias()`/
`set_alias()` already expect (generic, MLflow-client-only, no torch
assumption) -- reused here unchanged; only *loading* the model back needs
a fuel-ensemble-specific call (`mlflow.pyfunc.load_model`, not
`ModelRegistry.load_by_alias()`'s `mlflow.pytorch.load_model`), which
lives in `forecast-api`'s own loader, not here.
"""

from __future__ import annotations

import tempfile
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
from mlflow.pyfunc import PythonModel
from sklearn.metrics import mean_absolute_error, mean_squared_error

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.model.fuel_ensemble import (
    FUEL_COLUMNS,
    FuelEnsemble,
    fit_fuel_ensemble,
)
from ecolens.forecasting.schema.features import FEATURE_COLUMNS

from .train import _git_sha

log = get_logger(__name__)

DEFAULT_TRAIN_FRACTION = 0.8


@dataclass
class FuelEnsembleTrainResult:
    run_id: str
    ensemble: FuelEnsemble
    test_mae: dict[str, float]
    test_rmse: dict[str, float]
    test_mae_mean: float


class _FuelEnsemblePyfuncModel(PythonModel):
    """Stable, version-independent pyfunc contract -- `load_context`
    reconstructs the 16 `LGBMRegressor`s from a single joblib artifact;
    `predict` is the only method any loader (this package or
    `forecast-api`'s own, dependency-free one) needs to call.
    """

    def load_context(self, context: Any) -> None:
        self._models: dict[str, Any] = joblib.load(context.artifacts["fuel_models"])

    def predict(
        self, context: Any, model_input: pd.DataFrame, params: dict | None = None
    ) -> pd.DataFrame:
        # num_threads=1: same SIGSEGV guard as FuelEnsemble.predict (see
        # that method's docstring) -- this pyfunc predict path is a
        # separate call site against the same joblib-loaded boosters, not
        # covered by fit_fuel_ensemble's n_jobs=1 alone.
        x = model_input[list(FEATURE_COLUMNS)]
        return pd.DataFrame(
            {
                fuel: model.predict(x, num_threads=1)
                for fuel, model in self._models.items()
            }
        )


def _chronological_split(
    df: pd.DataFrame, *, train_fraction: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-region chronological split -- same never-shuffle-a-time-series
    rationale `windowing.py`'s `build_windowed_dataset` documents (a
    random split would leak future rows into "past" training data).
    LightGBM has no lookback window, so unlike `build_windowed_dataset`
    this is a plain two-way split, not four.
    """
    train_parts, test_parts = [], []
    for _, region_df in df.sort_values("ts_30").groupby("region", sort=True):
        cut = int(round(len(region_df) * train_fraction))
        train_parts.append(region_df.iloc[:cut])
        test_parts.append(region_df.iloc[cut:])
    return (
        pd.concat(train_parts, ignore_index=True),
        pd.concat(test_parts, ignore_index=True),
    )


def train_fuel_ensemble_model(
    df: pd.DataFrame,
    settings: Settings | None = None,
    *,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    log_to_mlflow: bool = True,
) -> FuelEnsembleTrainResult:
    """`df` must carry every `FEATURE_COLUMNS` + `FUEL_COLUMNS` column,
    plus `region`/`ts_30` (see `repository/fuel_training_data.py`'s
    `FuelTrainingSetLoader`). Rows missing any of those are dropped, same
    as `windowing.py`'s handling of missing `FEATURE_COLUMNS` values --
    training against a fabricated fill-in would be worse than training
    on fewer, complete rows.
    """
    settings = settings or get_settings()
    required = list(FEATURE_COLUMNS) + list(FUEL_COLUMNS)
    df = df.dropna(subset=required).sort_values(["region", "ts_30"])
    if df.empty:
        raise ValueError(
            "no rows with every FEATURE_COLUMNS + FUEL_COLUMNS value populated -- "
            "nothing to train the fuel ensemble on"
        )

    train_df, test_df = _chronological_split(df, train_fraction=train_fraction)

    ensemble = fit_fuel_ensemble(
        train_df,
        train_df,
        num_leaves=settings.model_fuel_num_leaves,
        n_estimators=settings.model_fuel_n_estimators,
        learning_rate=settings.model_fuel_learning_rate,
        max_depth=settings.model_fuel_max_depth,
    )

    test_preds = ensemble.predict(test_df)
    test_mae = {
        fuel: float(mean_absolute_error(test_df[fuel], test_preds[fuel]))
        for fuel in FUEL_COLUMNS
    }
    test_rmse = {
        fuel: float(mean_squared_error(test_df[fuel], test_preds[fuel]) ** 0.5)
        for fuel in FUEL_COLUMNS
    }
    test_mae_mean = float(np.mean(list(test_mae.values())))

    if log_to_mlflow:
        mlflow.set_experiment(settings.mlflow_experiment_name_fuel_ensemble)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            params: dict[str, int | float | str] = {
                "num_leaves": settings.model_fuel_num_leaves,
                "n_estimators": settings.model_fuel_n_estimators,
                "learning_rate": settings.model_fuel_learning_rate,
                "max_depth": settings.model_fuel_max_depth,
                "train_samples": len(train_df),
                "test_samples": len(test_df),
            }
            sha = _git_sha()
            if sha:
                params["git_sha"] = sha
            mlflow.log_params(params)
            for fuel in FUEL_COLUMNS:
                mlflow.log_metric(f"test_mae_{fuel}", test_mae[fuel])
                mlflow.log_metric(f"test_rmse_{fuel}", test_rmse[fuel])
            mlflow.log_metric("test_mae_mean", test_mae_mean)
            mlflow.log_dict(
                {
                    "fuel_columns": list(FUEL_COLUMNS),
                    "feature_columns": list(FEATURE_COLUMNS),
                },
                "fuel_ensemble_schema.json",
            )

            with tempfile.TemporaryDirectory() as tmp_dir:
                models_path = Path(tmp_dir) / "fuel_models.joblib"
                joblib.dump(ensemble.models, models_path)
                mlflow.pyfunc.log_model(
                    name="model",
                    python_model=_FuelEnsemblePyfuncModel(),
                    artifacts={"fuel_models": str(models_path)},
                    pip_requirements=[],
                )

        run_id = run.info.run_id if run is not None else ""

    log.info(
        "training_fuel_ensemble.complete",
        run_id=run_id,
        test_mae_mean=round(test_mae_mean, 4),
        train_samples=len(train_df),
        test_samples=len(test_df),
    )
    return FuelEnsembleTrainResult(
        run_id=run_id,
        ensemble=ensemble,
        test_mae=test_mae,
        test_rmse=test_rmse,
        test_mae_mean=test_mae_mean,
    )


__all__ = ["FuelEnsembleTrainResult", "train_fuel_ensemble_model"]
