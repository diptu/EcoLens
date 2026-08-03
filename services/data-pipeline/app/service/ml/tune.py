"""Hyperparameter tuning (`make tune`, `TODO.md`'s Forecasting section
item 6) — a plain grid search over the two most consequential
hyperparameters (`hidden_size`, `lr`), not Optuna (`ml/train.py`'s module
docstring explains why: this training loop doesn't need a heavier search
framework's abstraction to justify the new dependency).

Each trial trains via `ml/train.py`'s `train_model` and gets logged to
MLflow as its own run (tagged `tuning=true`), so every trial shows up
side by side with regular training runs in the MLflow UI/`GET
/v1/model`'s history, not hidden inside a single opaque "tuning job" run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import product

import mlflow

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.service.ml.data import load_holidays, load_training_data
from app.service.ml.train import TrainConfig, train_model
from app.service.mlops.tracking import configure_mlflow, git_sha
from app.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_HIDDEN_SIZES: tuple[int, ...] = (64, 128, 256)
DEFAULT_LEARNING_RATES: tuple[float, ...] = (1e-3, 5e-4)


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
