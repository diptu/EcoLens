"""Incremental (warm-started) training — `TODO.md`'s "Event-Driven
Pipeline Trigger for Online/Incremental Model Training", item 3's note:

    true *incremental* (warm-started, weights-persist-between-runs)
    training is a real, separate change from `ml/train.py`'s current
    from-scratch-every-run loop -- it needs the trainer to load the
    previous Production/Staging version's weights (`mlops.registry.
    get_version_in_stage` already exists for this) as its starting point
    instead of a freshly-initialized DemandLSTM, plus a much
    shorter/lighter fine-tuning loop than a full epochs=50 retrain.

`train_and_register_incremental` is that trainer: it's what
`app.service.training_worker.handle_training_trigger` (the RabbitMQ
consumer, `TODO.md` item 3's "resilient message consumer... in the
forecasting service" — which per README's "forecast-api never trains"
boundary rule lives in *this* service, not forecast-api) calls once it
receives a training-trigger event.

Deliberately reuses, not reimplements: `ml.train.train_model`'s
`warm_start_state_dict` parameter for the actual fine-tune loop,
`ml.train.log_and_register_run` for MLflow logging/registration (the
same "Model Lifecycle & Governance" machinery item 4 says already exists
and is reusable as-is), and `mlops.registry.get_version_in_stage` for
finding what to warm-start from. The only genuinely new logic here is
resolving *which* previous version to fine-tune from and downloading its
`serving/model_state_dict.pt` artifact + architecture hyperparams so the
freshly constructed `DemandLSTM` is a shape-for-shape match before
`load_state_dict` runs.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import mlflow
import mlflow.artifacts
import pandas as pd
import torch
from mlflow.tracking import MlflowClient

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.service.ml import divergence
from app.service.ml.data import load_holidays, load_training_data
from app.service.ml.train import (
    TrainAndRegisterResult,
    TrainConfig,
    log_and_register_run,
    train_model,
)
from app.service.mlops.registry import Stage, get_version_in_stage
from app.service.mlops.tracking import configure_mlflow
from app.core.logging import get_logger

log = get_logger(__name__)

# Checked in order when `stage` isn't given explicitly -- warm-start from
# whatever's actually serving if there is one, else the best in-review
# candidate, rather than refusing just because nothing's reached
# Production yet.
_FALLBACK_STAGES: tuple[Stage, ...] = ("Production", "Staging")


@dataclass
class WarmStart:
    run_id: str
    version: str
    stage: str
    state_dict: dict[str, torch.Tensor]
    hidden_size: int
    num_layers: int
    dropout: float
    horizon: int
    lookback: int


def get_warm_start(model_name: str, stage: Stage | None = None) -> WarmStart | None:
    """The version to fine-tune from: `stage` if given, else `Production`
    falling back to `Staging`. `None` if the registry has nothing in
    either (a real, expected state before the first `ecolens-pipeline
    train` + promotion has ever happened -- not an error the caller
    should silently swallow).

    Downloads the same `serving/model_state_dict.pt` artifact
    `ml.train.log_and_register_run` writes on every run, plus the
    architecture hyperparams already logged as that run's params
    (`hidden_size`/`num_layers`/`dropout`/`horizon`/`lookback`) — so the
    `TrainConfig` `train_and_register_incremental` builds from this
    always matches the state dict's shapes exactly, rather than trusting
    `Settings`' current defaults to still agree with whatever config
    trained the version being warm-started from.
    """
    stages: Sequence[Stage] = (stage,) if stage else _FALLBACK_STAGES
    version = None
    resolved_stage = ""
    for candidate_stage in stages:
        version = get_version_in_stage(model_name, candidate_stage)
        if version is not None:
            resolved_stage = candidate_stage
            break
    if version is None:
        return None
    # mlflow's own stub types `ModelVersion.run_id` as `str | None`, but a
    # version that `mlflow.register_model` created always has one -- it's
    # the very run that produced the artifact being registered.
    run_id = version.run_id
    assert run_id is not None, (  # nosec B101 -- internal invariant for type-narrowing, not a security check; see comment above
        f"{model_name!r} v{version.version} has no run_id"
    )

    client = MlflowClient()
    run = client.get_run(run_id)
    params = run.data.params

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir
        )
        # weights_only=True: this file is always a plain state_dict this same
        # pipeline wrote via mlflow.artifacts (never an externally-sourced
        # file), but there's no reason to allow arbitrary-object unpickling
        # when only tensors are ever stored here.
        state_dict = torch.load(
            Path(local_dir) / "model_state_dict.pt",
            map_location=torch.device("cpu"),
            weights_only=True,
        )

    return WarmStart(
        run_id=run_id,
        version=version.version,
        stage=resolved_stage,
        state_dict=state_dict,
        hidden_size=int(params["hidden_size"]),
        num_layers=int(params["num_layers"]),
        dropout=float(params["dropout"]),
        horizon=int(params["horizon"]),
        lookback=int(params["lookback"]),
    )


async def train_and_register_incremental(
    model_name: str,
    regions: Sequence[str],
    since: pd.Timestamp,
    *,
    settings: Settings | None = None,
    stage: Stage | None = None,
    register: bool = True,
) -> TrainAndRegisterResult:
    """The incremental counterpart to `ml.train.train_and_register`:
    fine-tunes from the current `Production`/`Staging` version's weights
    (`get_warm_start`) on only the data since `since` (`ml/data.py`'s
    `load_training_data(..., since=...)`, item 5's "non-blocking /
    incremental data access" point), for `Settings.
    incremental_train_epochs` epochs at `Settings.incremental_train_lr`
    — a much shorter, lighter pass than `train_and_register`'s
    `epochs=50` from-scratch default.

    Raises `ValueError` if there's nothing to warm-start from yet (run a
    full `train` first) or if the `since`-bounded window has no rows —
    both real, expected failure modes for an event firing before the
    warehouse has ever been fully trained on, not something to silently
    train an empty/randomly-initialized model against.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    warm_start = get_warm_start(model_name, stage)
    if warm_start is None:
        raise ValueError(
            f"no Production/Staging version of {model_name!r} to warm-start from -- "
            "run `ecolens-pipeline train` (a full retrain) and promote it first"
        )

    config = replace(
        TrainConfig.from_settings(settings),
        hidden_size=warm_start.hidden_size,
        num_layers=warm_start.num_layers,
        dropout=warm_start.dropout,
        horizon=warm_start.horizon,
        lookback=warm_start.lookback,
        epochs=settings.incremental_train_epochs,
        lr=settings.incremental_train_lr,
    )

    async with get_session() as db:
        raw_df = await load_training_data(db, regions, since=since)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in the warehouse for regions={list(regions)} "
            f"since={since} -- the incremental window may be too narrow"
        )

    result = train_model(
        raw_df,
        config,
        holidays=holidays_df,
        warm_start_state_dict=warm_start.state_dict,
    )

    # Catastrophic-forgetting guard (`todo-model-training.md` Phase 4):
    # real weight-norm drift from the last full retrain, logged alongside
    # this run -- `None` (nothing to compare against yet, e.g. the very
    # first incremental run after a fresh registry) logs nothing rather
    # than a misleading zero.
    drift_report = divergence.check_drift(result.model.state_dict(), model_name)
    extra_params: dict[str, object] = {}
    if drift_report is not None:
        extra_params["drift_relative_l2"] = drift_report.relative_l2_drift
        extra_params["drift_exceeded_threshold"] = drift_report.exceeded_threshold
        extra_params["drift_compared_against_run_id"] = (
            drift_report.compared_against_run_id
        )
        if drift_report.exceeded_threshold:
            log.warning(
                "incremental.drift_threshold_exceeded",
                model_name=model_name,
                relative_l2_drift=drift_report.relative_l2_drift,
                threshold=drift_report.threshold,
                compared_against_run_id=drift_report.compared_against_run_id,
            )

    log.info(
        "incremental.trained",
        model_name=model_name,
        warm_start_run_id=warm_start.run_id,
        warm_start_stage=warm_start.stage,
        since=str(since),
        n_train_windows=result.n_train_windows,
    )
    return log_and_register_run(
        result,
        config,
        regions,
        model_name,
        register=register,
        extra_tags={
            "training_type": "incremental",
            "warm_start_run_id": warm_start.run_id,
            "warm_start_stage": warm_start.stage,
        },
        extra_params=extra_params,
    )
