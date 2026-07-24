"""ECO-113: Hyperparameter Search.

Wraps `train_model` in an Optuna study of `Settings.optuna_n_trials`
trials (architecture: hidden size, layer count, dropout, learning
rate), each trial logged as its own nested MLflow run under one parent
"hyperparameter_search" run. Per-trial runs log only params + final val
loss, not the model itself -- logging a full model artifact per trial
would multiply storage by `n_trials` for no benefit, since only the
winner ever gets registered. Once the study finishes, the winning
hyperparameters are refit once more (also nested) *with* full model
logging, and that run's id is what a caller hands to
`mlops/registry.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import mlflow
import optuna

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..features import WindowedDataset
from ..mlops.registry import log_model_artifacts
from .search_space import load_search_space
from .train import train_model

log = get_logger(__name__)


@dataclass
class TuneResult:
    best_params: dict[str, float | int]
    best_val_loss: float
    best_run_id: str
    study: optuna.Study


def tune(
    dataset: WindowedDataset,
    settings: Settings | None = None,
    *,
    n_trials: int | None = None,
) -> TuneResult:
    settings = settings or get_settings()
    n_trials = n_trials or settings.optuna_n_trials
    search_space = load_search_space(settings.hyperparameter_search_config_path)

    def objective(trial: optuna.Trial) -> float:
        trial_settings = search_space.suggest_settings(trial, settings)
        with mlflow.start_run(nested=True, run_name=f"trial_{trial.number}"):
            # trial.params: whatever suggest_settings() just sampled, keyed
            # by each ParamSpec's generic name (e.g. "hidden_size") -- same
            # keys study.best_params ends up with, so this stays correct
            # however the YAML search space is edited (params added/renamed),
            # not just for today's fixed hidden_size/num_layers/dropout/lr.
            mlflow.log_params(trial.params)
            result = train_model(dataset, settings=trial_settings, log_to_mlflow=False)
            mlflow.log_metric("val_loss", result.best_val_loss)
        log.info(
            "tune.trial_complete",
            trial=trial.number,
            val_loss=round(result.best_val_loss, 4),
        )
        return result.best_val_loss

    # See train.py's identical guard: without this, both the parent run
    # and every nested trial land outside the configured experiment.
    mlflow.set_experiment(settings.mlflow_experiment_name)
    with mlflow.start_run(run_name="hyperparameter_search"):
        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=n_trials)

        best_settings = search_space.apply_best_params(settings, study.best_params)
        mlflow.log_params({f"best_{k}": v for k, v in study.best_params.items()})
        mlflow.log_metric("best_trial_val_loss", study.best_value)

        with mlflow.start_run(nested=True, run_name="best_trial_final_fit") as best_run:
            final = train_model(dataset, settings=best_settings, log_to_mlflow=False)
            mlflow.log_params(
                {
                    **study.best_params,
                    "lookback": dataset.lookback,
                    "horizon": dataset.horizon,
                }
            )
            mlflow.log_metric("val_loss", final.best_val_loss)
            mlflow.log_dict(final.dataset.scaler.to_dict(), "scaler.json")
            log_model_artifacts(final.model)
            best_run_id = best_run.info.run_id

    log.info(
        "tune.complete",
        n_trials=n_trials,
        best_val_loss=round(study.best_value, 4),
        best_run_id=best_run_id,
    )
    return TuneResult(
        best_params=study.best_params,
        best_val_loss=study.best_value,
        best_run_id=best_run_id,
        study=study,
    )


__all__ = ["TuneResult", "tune"]
