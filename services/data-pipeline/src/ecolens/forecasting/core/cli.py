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
    # Full train -> evaluate -> promote-if-better cycle (weekly cron).
    # Trains on a live Colab T4 GPU bridge if NTFY_TOPIC is set and one is
    # published (see training/colab_dispatch.py), else falls back to local
    # CPU/CUDA. Pass --no-colab to always train locally.
    python -m ecolens.forecasting.cli train [--no-colab]

    # Full TFT train -> evaluate -> promote-if-better cycle. Registers
    # under its own MLflow experiment/registered-model name, independent
    # of the LSTM's -- see config.py's mlflow_*_tft settings. Always local
    # CPU/CUDA for now, no Colab bridge (training/colab_dispatch.py is
    # LSTM-only as of this writing).
    python -m ecolens.forecasting.cli train-tft

    # Train TimesFM's calibration head -> evaluate -> promote-if-better.
    # TimesFM itself (Google's pretrained checkpoint) is frozen and never
    # trained -- only a small head on top of its output is. First run
    # downloads the ~2GB checkpoint from Hugging Face Hub (cached after
    # that). Registers under its own MLflow experiment/registered-model
    # name, independent of the LSTM's and TFT's.
    python -m ecolens.forecasting.cli train-timesfm

    # Hyperparameter search (occasional, manual)
    python -m ecolens.forecasting.cli tune --n-trials 20

    # Re-evaluate the current production model against fresh data
    python -m ecolens.forecasting.cli evaluate

    # Current production model status
    python -m ecolens.forecasting.cli status

    # Online fine-tune of the current production model (lighter-weight,
    # more frequent cron -- see training/online.py's ECO-118 decision).
    # All three *-finetune variants below scope their data fetch to the
    # buffer accumulated since the current production version's own
    # last_trained_at (root TODO.md's "Fine tuning" section, "feed each
    # run from the new 30-min data buffer... not the full historical
    # set"), and reuse that production run's own FeatureScaler rather
    # than fitting a fresh one on just that narrow buffer.
    python -m ecolens.forecasting.cli online-finetune

    # Same, for the current production TFT -- static covariate encoder
    # frozen, only VSN/attention/decoder adapt (see training/online_tft.py)
    python -m ecolens.forecasting.cli online-finetune-tft

    # Same, for the current production TimesFM calibration head -- the
    # frozen pretrained backbone never trains in this repo to begin with,
    # so this is just a few more low-LR epochs on the head (see
    # training/online_timesfm.py)
    python -m ecolens.forecasting.cli online-finetune-timesfm

    # Feature selection Steps 1/2/3/4 against the live ml_features_demand_v1
    # mart (root TODO.md "Feature selection" section) -- occasional,
    # manual, re-run whenever the candidate feature set changes. Step 5
    # (TFT VSN gating) needs a trained DemandTFT's own test split and
    # region mapping, so it's a separate call
    # (service/feature_selection.py's step5_tft_vsn_gating), not wired
    # into this summary.
    python -m ecolens.forecasting.cli feature-selection
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
from typing import TYPE_CHECKING

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.schema.features import FeatureScaler, WindowedDataset
from ecolens.forecasting.service.windowing import build_windowed_dataset

if TYPE_CHECKING:
    from ecolens.forecasting.service.mlops.registry import ModelRegistry

log = get_logger(__name__)


async def _fetch_and_window(
    settings: Settings,
    *,
    since: date | datetime | None = None,
    scaler: FeatureScaler | None = None,
) -> WindowedDataset:
    """`since`, if given, scopes the fetch to `ts_30 >= since` -- root
    TODO.md's "Fine tuning" section, "feed each run from the new 30-min
    data buffer accumulated since the previous fine-tune, not the full
    historical set." `cmd_train*()` never pass this (a full retrain
    always wants the whole history); the `*-finetune` commands derive it
    from the current production model's own `last_trained_at` via
    `_last_trained_at()` below.

    `scaler`, if given, is reused as-is instead of fitting a fresh one
    from this call's own (buffer-scoped) train split -- same
    feature-scale-drift reasoning `training/incremental.py`'s module
    docstring documents for its chunked training loop. The
    `*-finetune` commands pass the current production run's own scaler
    (`ModelRegistry.load_checkpoint(...).scaler`) so a model fine-tuned
    on a few weeks' buffer keeps seeing inputs normalized the same way
    it was originally trained on, rather than a fresh mean/std fit on
    just that narrow, likely-unrepresentative window.
    """
    from ecolens.forecasting.repository.training_data import TrainingSetLoader

    df = await TrainingSetLoader(settings=settings).fetch(since=since)
    return build_windowed_dataset(
        df,
        lookback=settings.model_lookback,
        horizon=settings.model_horizon,
        scaler=scaler,
    )


async def _last_trained_at(registry: "ModelRegistry", *, alias: str) -> datetime | None:  # noqa: F821 - imported lazily below, only for the type checker
    from ecolens.forecasting.service.mlops.health import get_health_snapshot

    return get_health_snapshot(registry, alias=alias).last_trained_at


def _load_region_to_idx(run_id: str) -> dict[str, int]:
    """Reads back a TFT/TimesFM run's own `region_index.json` artifact
    (see `train_tft.py`/`train_timesfm.py`'s `mlflow.log_dict(region_to_idx,
    ...)` calls) -- the `*-finetune-tft`/`*-finetune-timesfm` commands need
    the *original* training run's region->index mapping, not one freshly
    derived from the (possibly smaller/different) fine-tune buffer, since
    the frozen/warm-started region embedding's rows are indexed by that
    original mapping (see `online_tft.py`/`online_timesfm.py`'s own
    docstrings on why).
    """
    import mlflow

    return mlflow.artifacts.load_dict(f"runs:/{run_id}/region_index.json")


async def cmd_train(no_colab: bool = False) -> int:
    from ecolens.forecasting.service.evaluation.evaluate import (
        evaluate_model,
        log_evaluation_to_mlflow,
    )
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training import colab_dispatch
    from ecolens.forecasting.service.training.train import DEVICE, train_model

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

    # Colab GPU bridge (see training/colab_dispatch.py): tries a live Colab
    # kernel first if NTFY_TOPIC is set and --no-colab wasn't passed, falls
    # back to local train_model() on any bridge-unavailable condition (or
    # if the bridge simply isn't configured, which is the common case).
    remote_result = (
        None if no_colab else colab_dispatch.try_remote_train(dataset, settings)
    )
    if remote_result is not None:
        print("Training on: Colab GPU (remote)")
        result = colab_dispatch.log_remote_result_to_mlflow(
            remote_result, dataset, settings
        )
    else:
        print(f"Training on: {DEVICE} (local)")
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


async def cmd_train_tft() -> int:
    from ecolens.forecasting.service.evaluation.evaluate import log_evaluation_to_mlflow
    from ecolens.forecasting.service.evaluation.evaluate_tft import evaluate_tft_model
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.train_tft import train_tft_model

    settings = get_settings()
    # TFT is registered under its own MLflow experiment/registered-model
    # name (see config.py's mlflow_*_tft fields) so it holds its own
    # "production" alias independent of the LSTM's -- ModelRegistry reads
    # settings.mlflow_registered_model_name directly, so this builds a
    # derived Settings with that field swapped rather than changing
    # ModelRegistry's constructor. Built before train_tft_model() runs,
    # same reason cmd_train() constructs its registry early -- see that
    # function's comment.
    tft_settings = settings.model_copy(
        update={
            "mlflow_registered_model_name": settings.mlflow_registered_model_name_tft,
            "mlflow_experiment_name": settings.mlflow_experiment_name_tft,
        }
    )
    registry = ModelRegistry(settings=tft_settings)
    dataset = await _fetch_and_window(settings)

    print("Training on: local (no Colab GPU bridge for TFT yet)")
    result = train_tft_model(dataset, settings=settings)
    evaluation = evaluate_tft_model(
        result.model, dataset, result.region_to_idx, alpha=settings.conformal_alpha
    )
    log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=tft_settings)

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"trained TFT version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_train_timesfm() -> int:
    from ecolens.forecasting.service.evaluation.evaluate import log_evaluation_to_mlflow
    from ecolens.forecasting.service.evaluation.evaluate_timesfm import (
        evaluate_timesfm_model,
    )
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.train_timesfm import train_timesfm_model

    settings = get_settings()
    # TimesFM's calibration head is registered under its own MLflow
    # experiment/registered-model name (config.py's mlflow_*_timesfm
    # fields), independent of the LSTM's and TFT's -- same derived-Settings
    # approach cmd_train_tft() uses, see that function's comment.
    timesfm_settings = settings.model_copy(
        update={
            "mlflow_registered_model_name": settings.mlflow_registered_model_name_timesfm,
            "mlflow_experiment_name": settings.mlflow_experiment_name_timesfm,
        }
    )
    registry = ModelRegistry(settings=timesfm_settings)
    dataset = await _fetch_and_window(settings)

    print(
        "Training on: local (frozen TimesFM backbone, no Colab bridge -- "
        "only the small calibration head trains)"
    )
    result = train_timesfm_model(dataset, settings=settings)
    evaluation = evaluate_timesfm_model(
        result.model,
        dataset,
        result.region_to_idx,
        result.raw_forecasts,
        alpha=settings.conformal_alpha,
    )
    log_evaluation_to_mlflow(
        evaluation, run_id=result.run_id, settings=timesfm_settings
    )

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"trained TimesFM version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_train_fuel_ensemble() -> int:
    from ecolens.forecasting.repository.fuel_training_data import (
        FuelTrainingSetLoader,
    )
    from ecolens.forecasting.service.mlops.promote_fuel_ensemble import (
        promote_if_better as promote_fuel_ensemble_if_better,
    )
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.train_fuel_ensemble import (
        train_fuel_ensemble_model,
    )

    settings = get_settings()
    # Own MLflow experiment/registered-model name, same reasoning as
    # cmd_train_tft()/cmd_train_timesfm() -- see cmd_train_tft()'s comment.
    fuel_settings = settings.model_copy(
        update={
            "mlflow_registered_model_name": settings.mlflow_registered_model_name_fuel_ensemble,
            "mlflow_experiment_name": settings.mlflow_experiment_name_fuel_ensemble,
        }
    )
    registry = ModelRegistry(settings=fuel_settings)
    df = await FuelTrainingSetLoader(settings=settings).fetch()

    result = train_fuel_ensemble_model(df, settings=settings)

    registered = registry.register(result.run_id)
    decision = promote_fuel_ensemble_if_better(
        registry, registered, result.test_mae_mean, alias=settings.model_registry_alias
    )
    print(
        f"trained fuel ensemble version {registered.version}, "
        f"mean test MAE={result.test_mae_mean:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_tune(n_trials: int | None) -> int:
    import mlflow

    from ecolens.forecasting.service.training.tune import tune

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
    from ecolens.forecasting.service.evaluation.evaluate import (
        evaluate_model,
        log_evaluation_to_mlflow,
    )
    from ecolens.forecasting.service.mlops.registry import ModelRegistry

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
    from ecolens.forecasting.service.mlops.health import get_health_snapshot
    from ecolens.forecasting.service.mlops.registry import ModelRegistry

    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    snapshot = get_health_snapshot(registry, alias=settings.model_registry_alias)
    print(snapshot)
    return 0


async def cmd_online_finetune() -> int:
    from ecolens.forecasting.service.evaluation.evaluate import (
        evaluate_model,
        log_evaluation_to_mlflow,
    )
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.online import fine_tune

    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    current = registry.get_by_alias(settings.model_registry_alias)
    if current is None:
        raise RuntimeError(
            f"no '{settings.model_registry_alias}' version registered yet -- "
            "run `make model-train` first, online fine-tuning has nothing to "
            "fine-tune"
        )
    base_model = registry.load_by_alias(settings.model_registry_alias)
    checkpoint = registry.load_checkpoint(current.run_id)
    since = await _last_trained_at(registry, alias=settings.model_registry_alias)
    dataset = await _fetch_and_window(settings, since=since, scaler=checkpoint.scaler)

    # Not yet Colab-bridge-aware (see training/colab_dispatch.py, wired into
    # cmd_train() first) -- online fine-tuning is a short, frequent job
    # that doesn't benefit from GPU dispatch's fixed overhead as much as a
    # full train_model() run does.
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


async def cmd_online_finetune_tft() -> int:
    from ecolens.forecasting.model.tft import DemandTFT
    from ecolens.forecasting.service.evaluation.evaluate import log_evaluation_to_mlflow
    from ecolens.forecasting.service.evaluation.evaluate_tft import evaluate_tft_model
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.online_tft import fine_tune_tft

    settings = get_settings()
    # Same TFT-scoped derived Settings cmd_train_tft()/cmd_train_timesfm()
    # use, for the same reason -- see cmd_train_tft()'s comment.
    tft_settings = settings.model_copy(
        update={
            "mlflow_registered_model_name": settings.mlflow_registered_model_name_tft,
            "mlflow_experiment_name": settings.mlflow_experiment_name_tft,
        }
    )
    registry = ModelRegistry(settings=tft_settings)
    current = registry.get_by_alias(settings.model_registry_alias)
    if current is None:
        raise RuntimeError(
            f"no TFT '{settings.model_registry_alias}' version registered yet -- "
            "run `make model-train-tft` first, online fine-tuning has nothing "
            "to fine-tune"
        )
    base_model = registry.load_by_alias(
        settings.model_registry_alias, model_type=DemandTFT
    )
    checkpoint = registry.load_checkpoint(current.run_id)
    region_to_idx = _load_region_to_idx(current.run_id)
    since = await _last_trained_at(registry, alias=settings.model_registry_alias)
    dataset = await _fetch_and_window(settings, since=since, scaler=checkpoint.scaler)

    result = fine_tune_tft(base_model, dataset, region_to_idx, settings=settings)
    evaluation = evaluate_tft_model(
        result.model, dataset, region_to_idx, alpha=settings.conformal_alpha
    )
    log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=tft_settings)

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"fine-tuned TFT version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_online_finetune_timesfm() -> int:
    from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead
    from ecolens.forecasting.service.evaluation.evaluate import log_evaluation_to_mlflow
    from ecolens.forecasting.service.evaluation.evaluate_timesfm import (
        evaluate_timesfm_model,
    )
    from ecolens.forecasting.service.mlops.promote import promote_if_better
    from ecolens.forecasting.service.mlops.registry import ModelRegistry
    from ecolens.forecasting.service.training.online_timesfm import fine_tune_timesfm

    settings = get_settings()
    # Same TimesFM-scoped derived Settings cmd_train_timesfm() uses, for
    # the same reason -- see cmd_train_tft()'s comment.
    timesfm_settings = settings.model_copy(
        update={
            "mlflow_registered_model_name": settings.mlflow_registered_model_name_timesfm,
            "mlflow_experiment_name": settings.mlflow_experiment_name_timesfm,
        }
    )
    registry = ModelRegistry(settings=timesfm_settings)
    current = registry.get_by_alias(settings.model_registry_alias)
    if current is None:
        raise RuntimeError(
            f"no TimesFM '{settings.model_registry_alias}' version registered "
            "yet -- run `make model-train-timesfm` first, online fine-tuning "
            "has nothing to fine-tune"
        )
    base_model = registry.load_by_alias(
        settings.model_registry_alias, model_type=TimesFMCalibrationHead
    )
    checkpoint = registry.load_checkpoint(current.run_id)
    region_to_idx = _load_region_to_idx(current.run_id)
    since = await _last_trained_at(registry, alias=settings.model_registry_alias)
    dataset = await _fetch_and_window(settings, since=since, scaler=checkpoint.scaler)

    result = fine_tune_timesfm(base_model, dataset, region_to_idx, settings=settings)
    evaluation = evaluate_timesfm_model(
        result.model,
        dataset,
        region_to_idx,
        result.raw_forecasts,
        alpha=settings.conformal_alpha,
    )
    log_evaluation_to_mlflow(
        evaluation, run_id=result.run_id, settings=timesfm_settings
    )

    registered = registry.register(result.run_id)
    decision = promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )
    print(
        f"fine-tuned TimesFM version {registered.version}, "
        f"MAPE={evaluation.point.overall['mape']:.2f}, "
        f"promoted={decision.promote} ({decision.reason})"
    )
    return 0


async def cmd_feature_selection() -> int:
    from ecolens.forecasting.repository.training_data import TrainingSetLoader
    from ecolens.forecasting.service.feature_selection import (
        run_steps_1_2_4,
        step3_pacf_lag_selection,
    )

    settings = get_settings()
    df = await TrainingSetLoader(settings=settings).fetch()

    # Excluded from candidates, not from the mart: these are Feature
    # Engineering's *output* (lags/rolling stats/cyclical encodings), not
    # inputs to Feature Selection -- the notebook prototype ran Steps 1-4
    # against the pre-engineering feature_table_30min, which has no
    # equivalent of its own; ml_features_demand_v1 has both stages baked
    # into one mart, so this is the closest re-runnable equivalent.
    engineered_cols = [c for c in df.columns if c.startswith("demand_lag_")] + [
        "demand_rolling_avg_7d",
        "demand_rolling_std_7d",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "month_sin",
        "month_cos",
    ]
    metadata_cols = ("is_gap_filled", "data_quality_status", "ts")

    summary = run_steps_1_2_4(
        df,
        identifier_cols=("region", "ts_30"),
        metadata_cols=tuple(engineered_cols) + metadata_cols,
    )
    print(f"candidates: {len(summary.candidate_cols)} rows={len(df)}")
    print(f"Step 1 (structural hygiene) dropped: {summary.structural.drop_cols}")
    print(
        f"Step 2 (bottom {summary.mutual_information.drop_fraction:.1%} MI) "
        f"dropped: {summary.mutual_information.drop_cols}"
    )
    print(
        f"Step 4 (|corr| > {summary.multicollinearity.correlation_threshold}) "
        f"dropped: {summary.multicollinearity.drop_cols}"
    )
    print(f"-> kept {len(summary.kept_cols)}: {summary.kept_cols}")

    pacf_result = step3_pacf_lag_selection(df, "demand_mw", region="NSW1")
    print(f"Step 3 (PACF, NSW1): {pacf_result.proposed_lag_significance}")

    print(
        "Step 5 (TFT VSN gating) needs a trained DemandTFT's own test "
        "split + region mapping -- call "
        "service.feature_selection.step5_tft_vsn_gating directly against "
        "a loaded production TFT, not part of this summary."
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ecoLens forecasting pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    train_parser = sub.add_parser(
        "train", help="full train -> evaluate -> promote-if-better cycle"
    )
    train_parser.add_argument(
        "--no-colab",
        action="store_true",
        help="skip the Colab GPU bridge even if NTFY_TOPIC is set, train locally",
    )
    sub.add_parser(
        "train-tft",
        help="full TFT train -> evaluate -> promote-if-better cycle (local only, no Colab bridge yet)",
    )
    sub.add_parser(
        "train-timesfm",
        help=(
            "train TimesFM's calibration head -> evaluate -> promote-if-better "
            "(frozen pretrained backbone, ~2GB download on first run)"
        ),
    )
    sub.add_parser(
        "train-fuel-ensemble",
        help=(
            "train the 16-fuel LightGBM ensemble -> evaluate -> "
            "promote-if-better (root TODO.md's Normalization Constraint Layer)"
        ),
    )
    tune_parser = sub.add_parser("tune", help="Optuna hyperparameter search")
    tune_parser.add_argument("--n-trials", type=int, default=None)
    sub.add_parser(
        "evaluate", help="re-evaluate the current production model against fresh data"
    )
    sub.add_parser("status", help="current production model status")
    sub.add_parser(
        "online-finetune", help="lightweight fine-tune of the current production model"
    )
    sub.add_parser(
        "online-finetune-tft",
        help="lightweight fine-tune of the current production TFT (static encoder frozen)",
    )
    sub.add_parser(
        "online-finetune-timesfm",
        help="lightweight fine-tune of the current production TimesFM calibration head",
    )
    sub.add_parser(
        "feature-selection",
        help="re-run Feature Selection Steps 1/2/3/4 against the live warehouse mart",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commands = {
        "train": lambda: cmd_train(no_colab=args.no_colab),
        "train-tft": lambda: cmd_train_tft(),
        "train-timesfm": lambda: cmd_train_timesfm(),
        "train-fuel-ensemble": lambda: cmd_train_fuel_ensemble(),
        "tune": lambda: cmd_tune(args.n_trials),
        "evaluate": lambda: cmd_evaluate(),
        "status": lambda: cmd_status(),
        "online-finetune": lambda: cmd_online_finetune(),
        "online-finetune-tft": lambda: cmd_online_finetune_tft(),
        "online-finetune-timesfm": lambda: cmd_online_finetune_timesfm(),
        "feature-selection": lambda: cmd_feature_selection(),
    }
    return asyncio.run(commands[args.command]())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "parse_args"]
