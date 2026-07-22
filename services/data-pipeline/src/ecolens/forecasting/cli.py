"""CLI for the forecasting pipeline.

ECO-119's orchestration decision: extends this repo's existing
cron + CLI + subprocess pattern (`warehouse/runner/cli.py`, the
ingestion layer's `trigger_ingest_*.py` scripts) rather than adopting
Prefect. No `prefect` dependency exists anywhere in this repo, every
other pipeline here (ingestion, warehouse) already runs this way, and
this is a handful of jobs a day/week -- not the complex many-task DAG
Prefect earns its keep on. Introducing a second orchestration paradigm
just for the ML pipeline would mean this is the one thing operators
need a different mental model for, with no offsetting benefit at this
scale. Revisit if/when the job graph gets genuinely complex (e.g. real
parallel multi-region training with cross-job dependencies).

Usage
=====
    # Full train -> evaluate -> promote-if-better cycle (weekly cron)
    python -m ecolens.forecasting.cli train

    # Hyperparameter search (occasional, manual)
    python -m ecolens.forecasting.cli tune --n-trials 20

    # Re-evaluate the current production model against fresh data
    python -m ecolens.forecasting.cli evaluate

    # Current production model status
    python -m ecolens.forecasting.cli status

    # Online fine-tune of the current production model (lighter-weight,
    # more frequent cron -- see training/online.py's ECO-118 decision)
    python -m ecolens.forecasting.cli online-finetune
"""

from __future__ import annotations

import argparse
import asyncio

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from .features import WindowedDataset, build_windowed_dataset

log = get_logger(__name__)


async def _fetch_and_window(settings: Settings) -> WindowedDataset:
    from .data import TrainingSetLoader

    df = await TrainingSetLoader(settings=settings).fetch()
    return build_windowed_dataset(
        df, lookback=settings.model_lookback, horizon=settings.model_horizon
    )


async def cmd_train() -> int:
    from .evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
    from .mlops.promote import promote_if_better
    from .mlops.registry import ModelRegistry
    from .training.train import train_model

    settings = get_settings()
    # Constructed before train_model()/evaluate_model() run -- ModelRegistry's
    # __init__ is what actually calls mlflow.set_tracking_uri(), and
    # train_model()/log_evaluation_to_mlflow() only ever call
    # mlflow.set_experiment()/start_run(), never set_tracking_uri()
    # themselves. Built this late, mlflow had already logged the whole
    # training run against its own bare default (a local sqlite:///mlflow.db
    # relative to CWD, not settings.mlflow_tracking_uri) by the time this
    # ran -- so registry.register(result.run_id) below would look the run
    # up in the *correct* store and fail with "Run not found", since it was
    # actually written to the wrong one. See cmd_evaluate/cmd_status/
    # cmd_online_finetune, which already construct ModelRegistry first for
    # this same reason.
    registry = ModelRegistry(settings=settings)
    dataset = await _fetch_and_window(settings)
    result = train_model(dataset, settings=settings)
    evaluation = evaluate_model(result.model, dataset, alpha=settings.conformal_alpha)
    log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=settings)

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"trained version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_tune(n_trials: int | None) -> int:
    import mlflow

    from .training.tune import tune

    settings = get_settings()
    # tune() only ever calls mlflow.set_experiment()/start_run(), same gap
    # as cmd_train() -- see that function's comment. Without this, every
    # trial (and the final best-params refit) logs against mlflow's bare
    # default store instead of settings.mlflow_tracking_uri.
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    dataset = await _fetch_and_window(settings)
    result = tune(dataset, settings=settings, n_trials=n_trials)
    print(
        f"best params: {result.best_params}, "
        f"best_val_loss={result.best_val_loss:.4f}, run_id={result.best_run_id}"
    )
    return 0


async def cmd_evaluate() -> int:
    from .evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
    from .mlops.registry import ModelRegistry

    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    model = registry.load_by_alias(settings.model_registry_alias)
    dataset = await _fetch_and_window(settings)
    evaluation = evaluate_model(model, dataset, alpha=settings.conformal_alpha)

    current = registry.get_by_alias(settings.model_registry_alias)
    log_evaluation_to_mlflow(
        evaluation, run_id=current.run_id if current else None, settings=settings
    )
    print(
        f"MAPE={evaluation.point.overall['mape']:.2f} "
        f"coverage={evaluation.test_coverage:.3f}"
    )
    return 0


async def cmd_status() -> int:
    from .mlops.health import get_health_snapshot
    from .mlops.registry import ModelRegistry

    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    snapshot = get_health_snapshot(registry, alias=settings.model_registry_alias)
    print(snapshot)
    return 0


async def cmd_online_finetune() -> int:
    from .evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
    from .mlops.promote import promote_if_better
    from .mlops.registry import ModelRegistry
    from .training.online import fine_tune

    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    base_model = registry.load_by_alias(settings.model_registry_alias)
    dataset = await _fetch_and_window(settings)

    result = fine_tune(base_model, dataset, settings=settings)
    evaluation = evaluate_model(result.model, dataset, alpha=settings.conformal_alpha)
    log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=settings)

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"fine-tuned version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ecoLens forecasting pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("train", help="full train -> evaluate -> promote-if-better cycle")
    tune_parser = sub.add_parser("tune", help="Optuna hyperparameter search")
    tune_parser.add_argument("--n-trials", type=int, default=None)
    sub.add_parser(
        "evaluate", help="re-evaluate the current production model against fresh data"
    )
    sub.add_parser("status", help="current production model status")
    sub.add_parser(
        "online-finetune", help="lightweight fine-tune of the current production model"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commands = {
        "train": lambda: cmd_train(),
        "tune": lambda: cmd_tune(args.n_trials),
        "evaluate": lambda: cmd_evaluate(),
        "status": lambda: cmd_status(),
        "online-finetune": lambda: cmd_online_finetune(),
    }
    return asyncio.run(commands[args.command]())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "parse_args"]
