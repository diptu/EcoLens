"""Incremental (warm-started) TFT training (`todo-model-training.md`
Phase 4's "apply the same higher-frequency treatment to TFT once it
exists" — it now does, Phase 2). `ml/incremental.py`'s exact structure,
mirrored for `DemandTFT`/`TFTTrainConfig`/`train_tft_model` — see that
module's docstring for the full real design rationale (resilient
consumer, warm-start-from-Production-falling-back-to-Staging, why this
lives in data-pipeline not forecast-api); this module only differs in
which architecture's classes it wires together, plus one real addition
neither the original `incremental.py` nor Phase 2's `train_tft.py` had
yet: a `divergence.check_drift` call after every fine-tune, logged
alongside the run rather than silently uncomputed (Phase 4's
catastrophic-forgetting-guard item).

`training_worker.handle_training_trigger` dispatches to this module (or
`ml.incremental`) based on the training-trigger event payload's
`architecture` field.
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
from app.service.ml import divergence
from app.service.ml.data import load_holidays, load_training_data
from app.service.ml.train import TrainAndRegisterResult, log_and_register_run
from app.service.ml.train_tft import (
    DECODER_COLUMNS,
    ENCODER_COLUMNS,
    TFTTrainConfig,
    train_tft_model,
)
from app.service.mlops.registry import Stage, get_version_in_stage
from app.service.mlops.tracking import configure_mlflow
from app.db.session import get_session
from app.core.logging import get_logger

log = get_logger(__name__)

_FALLBACK_STAGES: tuple[Stage, ...] = ("Production", "Staging")


@dataclass
class TFTWarmStart:
    run_id: str
    version: str
    stage: str
    state_dict: dict[str, torch.Tensor]
    hidden_size: int
    n_heads: int
    dropout: float
    horizon: int
    lookback: int


def get_warm_start_tft(
    model_name: str, stage: Stage | None = None
) -> TFTWarmStart | None:
    """`ml.incremental.get_warm_start`'s TFT counterpart -- identical
    stage-fallback logic and identical reasoning for downloading the
    architecture hyperparams alongside the state dict (so the
    `TFTTrainConfig` this warm-start builds always matches the state
    dict's shapes, rather than trusting `Settings`' current defaults to
    still agree with whatever config trained the version being
    warm-started from)."""
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
    run_id = version.run_id
    assert run_id is not None, (  # nosec B101 -- internal invariant for type-narrowing, matching ml.incremental.get_warm_start's identical assertion
        f"{model_name!r} v{version.version} has no run_id"
    )

    client = MlflowClient()
    run = client.get_run(run_id)
    params = run.data.params

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir
        )
        state_dict = torch.load(
            Path(local_dir) / "model_state_dict.pt",
            map_location=torch.device("cpu"),
            weights_only=True,
        )

    return TFTWarmStart(
        run_id=run_id,
        version=version.version,
        stage=resolved_stage,
        state_dict=state_dict,
        hidden_size=int(params["hidden_size"]),
        n_heads=int(params["n_heads"]),
        dropout=float(params["dropout"]),
        horizon=int(params["horizon"]),
        lookback=int(params["lookback"]),
    )


async def train_and_register_tft_incremental(
    model_name: str,
    regions: Sequence[str],
    since: pd.Timestamp,
    *,
    settings: Settings | None = None,
    stage: Stage | None = None,
    register: bool = True,
) -> TrainAndRegisterResult:
    """`ml.incremental.train_and_register_incremental`'s TFT counterpart.
    Same warm-start-then-lightly-fine-tune shape, plus a real
    catastrophic-forgetting check (`divergence.check_drift`) run after
    training and logged alongside the MLflow run via
    `log_and_register_run`'s `extra_params` -- a `None` drift result
    (nothing to compare against yet) logs nothing rather than a
    misleading zero.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    warm_start = get_warm_start_tft(model_name, stage)
    if warm_start is None:
        raise ValueError(
            f"no Production/Staging version of {model_name!r} to warm-start from -- "
            "run `ecolens-pipeline train-tft` (a full retrain) and promote it first"
        )

    config = replace(
        TFTTrainConfig.from_settings(settings),
        hidden_size=warm_start.hidden_size,
        n_heads=warm_start.n_heads,
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

    result = train_tft_model(
        raw_df,
        config,
        holidays=holidays_df,
        warm_start_state_dict=warm_start.state_dict,
    )

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
                "incremental_tft.drift_threshold_exceeded",
                model_name=model_name,
                relative_l2_drift=drift_report.relative_l2_drift,
                threshold=drift_report.threshold,
                compared_against_run_id=drift_report.compared_against_run_id,
            )

    log.info(
        "incremental_tft.trained",
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
            "architecture": "tft",
        },
        extra_params=extra_params
        | {
            "n_encoder_features": len(ENCODER_COLUMNS),
            "n_decoder_features": len(DECODER_COLUMNS),
        },
    )
