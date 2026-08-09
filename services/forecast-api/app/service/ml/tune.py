"""Hyperparameter tuning (`make tune`, `TODO.md`'s Forecasting section
item 6).

Two approaches, both real:

- `tune` — a plain grid search over the two most consequential
  hyperparameters (`hidden_size`, `lr`). Cheap (6 trials, each a full
  `config.epochs` run) and exhaustive over its small grid.
- `tune_optuna` (`todo-model-training.md`-adjacent real request: an
  actual Optuna search, not a grid) — TPE-sampled search over 6
  hyperparameters (`hidden_size`/`num_layers`/`dropout`/`weight_decay`/
  `lr`/`batch_size`) with median pruning of bad trials mid-training via
  `ml/train.py`'s generic `epoch_callback` hook. Each trial trains for a
  *reduced* epoch
  budget (`tune_epochs`, default well under `Settings.model_train_epochs`)
  as a fast proxy for full-budget quality — standard successive-halving
  practice, not a shortcut unique to this codebase. The caller is
  responsible for re-training the winning config at full epoch budget on
  the real split afterward (`cli.py`'s `tune-optuna` command does exactly
  that); `tune_optuna` itself only searches, it does not register a final
  model.

Each trial trains via `ml/train.py`'s `train_model` and gets logged to
MLflow as its own run (tagged `tuning=true`), so every trial shows up
side by side with regular training runs in the MLflow UI/`GET
/v1/model`'s history, not hidden inside a single opaque "tuning job" run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from itertools import product
from typing import Literal

import mlflow
import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.service.ml.data import (
    load_holidays,
    load_ml_features_v1_imputed_fraction,
    load_ml_features_v1_training_data,
    load_training_data,
)
from app.service.ml.train import TrainConfig, TrainResult, train_model
from app.service.mlops.tracking import configure_mlflow, git_sha
from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_HIDDEN_SIZES: tuple[int, ...] = (64, 128, 256)
DEFAULT_LEARNING_RATES: tuple[float, ...] = (1e-3, 5e-4)

DataSource = Literal["fct_energy_demand", "ml_features_v1"]

# Optuna search space for `tune_optuna` -- the same architecture/
# optimization hyperparameters `tune`'s grid covers (`hidden_size`, `lr`),
# plus `num_layers`/`dropout`/`batch_size`. `lookback`/`horizon` are
# deliberately not searched -- both are load-bearing for `forecast-api`'s
# serving contract (fixed input window / output horizon), not free
# architecture choices a tuning run should be allowed to change.
OPTUNA_HIDDEN_SIZES: tuple[int, ...] = (64, 128, 256)
OPTUNA_NUM_LAYERS: tuple[int, int] = (1, 3)
OPTUNA_DROPOUT: tuple[float, float] = (0.1, 0.5)
OPTUNA_LR: tuple[float, float] = (1e-4, 5e-3)
OPTUNA_BATCH_SIZES: tuple[int, ...] = (32, 64, 128, 256)
# Added alongside `Settings.model_weight_decay` (previously absent from
# the optimizer entirely) -- log-uniform, matching `OPTUNA_LR`'s own
# `log=True` search, since a good weight_decay is a real order-of-
# magnitude question, not a linear one.
OPTUNA_WEIGHT_DECAY: tuple[float, float] = (1e-6, 1e-3)


@dataclass
class TuneTrial:
    hidden_size: int
    lr: float
    val_mape: float
    run_id: str


@dataclass
class TuneResult:
    best_config: TrainConfig
    best_val_mape: float
    best_run_id: str
    trials: list[TuneTrial]


async def tune(
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    base_config: TrainConfig | None = None,
    hidden_sizes: Sequence[int] = DEFAULT_HIDDEN_SIZES,
    learning_rates: Sequence[float] = DEFAULT_LEARNING_RATES,
) -> TuneResult:
    settings = settings or get_settings()
    base_config = base_config or TrainConfig.from_settings(settings)
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in the warehouse for regions={list(regions)}"
        )

    trials: list[TuneTrial] = []
    best_val_mape = float("inf")
    best_config = base_config
    best_run_id = ""

    for hidden_size, lr in product(hidden_sizes, learning_rates):
        trial_config = replace(base_config, hidden_size=hidden_size, lr=lr)
        log.info("tune.trial_start", hidden_size=hidden_size, lr=lr)
        result = train_model(raw_df, trial_config, holidays=holidays_df)
        final_val_mape = (
            result.history[-1]["val_mape"] if result.history else float("inf")
        )

        with mlflow.start_run() as run:
            mlflow.log_params(trial_config.as_mlflow_params())
            mlflow.log_param("regions", ",".join(regions))
            mlflow.set_tags({"git_sha": git_sha() or "unknown", "tuning": "true"})
            mlflow.log_metric("val_mape", final_val_mape)
            if result.test_metrics:
                mlflow.log_metrics(result.test_metrics)
            run_id = run.info.run_id

        trials.append(
            TuneTrial(
                hidden_size=hidden_size, lr=lr, val_mape=final_val_mape, run_id=run_id
            )
        )
        log.info(
            "tune.trial_done", hidden_size=hidden_size, lr=lr, val_mape=final_val_mape
        )

        if final_val_mape < best_val_mape:
            best_val_mape = final_val_mape
            best_config = trial_config
            best_run_id = run_id

    return TuneResult(
        best_config=best_config,
        best_val_mape=best_val_mape,
        best_run_id=best_run_id,
        trials=trials,
    )


@dataclass
class OptunaTrialResult:
    number: int
    params: dict[str, object]
    val_mape: float
    run_id: str | None
    pruned: bool


@dataclass
class OptunaTuneResult:
    best_config: TrainConfig
    best_val_mape: float
    best_run_id: str
    best_test_metrics: dict[str, float]
    trials: list[OptunaTrialResult] = field(default_factory=list)
    n_raw_rows: int = 0
    data_source: DataSource = "fct_energy_demand"
    imputed_fraction: float | None = None

    @property
    def n_completed_trials(self) -> int:
        return sum(1 for t in self.trials if not t.pruned)

    @property
    def n_pruned_trials(self) -> int:
        return sum(1 for t in self.trials if t.pruned)


def _make_pruning_callback(
    trial: optuna.Trial,
) -> Callable[[int, dict[str, float]], None]:
    """`train_model`'s `epoch_callback`, wired to `trial.report`/
    `trial.should_prune` -- pulled out of `tune_optuna`'s `objective`
    closure so it's directly unit-testable against a fake `trial` object,
    not just observable through a full (slow) real training run."""

    def epoch_callback(epoch: int, epoch_history: dict[str, float]) -> None:
        trial.report(epoch_history["val_mape"], epoch)
        if trial.should_prune():
            raise optuna.TrialPruned()

    return epoch_callback


async def tune_optuna(
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    base_config: TrainConfig | None = None,
    n_trials: int = 20,
    tune_epochs: int = 15,
    tune_patience: int = 3,
    data_source: DataSource = "fct_energy_demand",
    train_frac: float | None = None,
    val_frac: float | None = None,
    seed: int = 42,
) -> OptunaTuneResult:
    """Real Optuna TPE search (`optuna.samplers.TPESampler`) over
    `hidden_size`/`num_layers`/`dropout`/`lr`/`batch_size`, `n_trials`
    trials, each trained for a reduced `tune_epochs` budget with
    `optuna.pruners.MedianPruner` stopping any trial whose per-epoch
    `val_mape` is trending worse than the median of trials so far
    (`ml/train.py`'s `epoch_callback` hook -- real mid-training pruning,
    not just a post-hoc best-of comparison). `train_frac`/`val_frac`
    override `base_config`'s split fractions for every trial (and the
    caller's own subsequent full-budget retrain, if it reuses
    `best_config`) — e.g. a real 60/20/20 split instead of the default
    70/15/15.

    `data_source="ml_features_v1"` sources from the (orphaned, partly
    synthetic — see `ml/data.py`'s `load_ml_features_v1_training_data`
    module comment) `ml.ml_features_demand_v1` table instead of the
    dbt-tracked `fct_energy_demand`; the real imputed-row fraction is
    logged as an MLflow param on every trial run and returned on the
    result so it's never silently absorbed into the numbers.

    Returns the winning trial's config/metrics — does **not** itself
    retrain at full epoch budget or register anything; `cli.py`'s
    `tune-optuna` command does that as a separate, explicit final step.
    """
    settings = settings or get_settings()
    base_config = base_config or TrainConfig.from_settings(settings)
    if train_frac is not None or val_frac is not None:
        base_config = replace(
            base_config,
            train_frac=train_frac if train_frac is not None else base_config.train_frac,
            val_frac=val_frac if val_frac is not None else base_config.val_frac,
        )
    configure_mlflow(settings)

    imputed_fraction: float | None = None
    async with get_session() as db:
        if data_source == "ml_features_v1":
            raw_df = await load_ml_features_v1_training_data(db, regions)
            imputed_fraction = await load_ml_features_v1_imputed_fraction(db, regions)
        else:
            raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in {data_source!r} for regions={list(regions)}"
        )

    # `study.optimize`'s `objective` closure stashes each completed trial's
    # `(config, TrainResult, run_id)` here, keyed by Optuna's own trial
    # number -- `study.best_trial.number` is how the winning one is
    # retrieved back out after `optimize` returns, without re-training it.
    trial_artifacts: dict[int, tuple[TrainConfig, TrainResult, str]] = {}

    def objective(trial: optuna.Trial) -> float:
        hidden_size = trial.suggest_categorical(
            "hidden_size", list(OPTUNA_HIDDEN_SIZES)
        )
        num_layers = trial.suggest_int("num_layers", *OPTUNA_NUM_LAYERS)
        dropout = trial.suggest_float("dropout", *OPTUNA_DROPOUT)
        weight_decay = trial.suggest_float("weight_decay", *OPTUNA_WEIGHT_DECAY, log=True)
        lr = trial.suggest_float("lr", *OPTUNA_LR, log=True)
        batch_size = trial.suggest_categorical("batch_size", list(OPTUNA_BATCH_SIZES))

        trial_config = replace(
            base_config,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            weight_decay=weight_decay,
            lr=lr,
            batch_size=batch_size,
            epochs=tune_epochs,
            early_stopping_patience=tune_patience,
        )

        epoch_callback = _make_pruning_callback(trial)

        log.info(
            "tune_optuna.trial_start",
            trial=trial.number,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            weight_decay=weight_decay,
            lr=lr,
            batch_size=batch_size,
        )
        result = train_model(
            raw_df, trial_config, holidays=holidays_df, epoch_callback=epoch_callback
        )
        final_val_mape = (
            result.history[-1]["val_mape"] if result.history else float("inf")
        )

        with mlflow.start_run() as run:
            mlflow.log_params(trial_config.as_mlflow_params())
            mlflow.log_param("regions", ",".join(regions))
            mlflow.log_param("data_source", data_source)
            mlflow.log_param("optuna_trial_number", trial.number)
            if imputed_fraction is not None:
                mlflow.log_param("imputed_fraction", imputed_fraction)
            mlflow.set_tags(
                {
                    "git_sha": git_sha() or "unknown",
                    "tuning": "true",
                    "tuning_method": "optuna",
                }
            )
            mlflow.log_metric("val_mape", final_val_mape)
            if result.test_metrics:
                mlflow.log_metrics(result.test_metrics)
            run_id = run.info.run_id

        trial_artifacts[trial.number] = (trial_config, result, run_id)
        log.info("tune_optuna.trial_done", trial=trial.number, val_mape=final_val_mape)
        return final_val_mape

    study = optuna.create_study(
        direction="minimize",
        sampler=TPESampler(seed=seed),
        pruner=MedianPruner(n_warmup_steps=3),
    )
    study.optimize(objective, n_trials=n_trials)

    trials = [
        OptunaTrialResult(
            number=t.number,
            params=t.params,
            val_mape=t.value if t.value is not None else float("inf"),
            run_id=trial_artifacts[t.number][2]
            if t.number in trial_artifacts
            else None,
            pruned=t.state == optuna.trial.TrialState.PRUNED,
        )
        for t in study.trials
    ]

    if study.best_trial.number not in trial_artifacts:
        # Every completed (non-pruned) trial is captured in
        # `trial_artifacts` -- Optuna only ever picks a completed trial as
        # `best_trial` (pruned/failed trials have no `value` to compare),
        # so this would indicate an Optuna internal-state bug, not a
        # reachable real-world condition.
        raise RuntimeError("optuna selected a best trial with no captured artifacts")
    best_config, best_result, best_run_id = trial_artifacts[study.best_trial.number]

    return OptunaTuneResult(
        best_config=best_config,
        best_val_mape=study.best_value,
        best_run_id=best_run_id,
        best_test_metrics=best_result.test_metrics,
        trials=trials,
        n_raw_rows=len(raw_df),
        data_source=data_source,
        imputed_fraction=imputed_fraction,
    )
