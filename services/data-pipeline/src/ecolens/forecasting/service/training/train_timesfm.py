"""Training loop for `TimesFMCalibrationHead` -- a parallel module to
`train.py`/`train_tft.py`, not a modification of either. Structurally
different from both in one respect: TimesFM's own forward pass is frozen
(no gradient ever flows through it), so its output for a fixed input never
changes between epochs. Running the real 200M-param backbone once per
epoch would be pure waste -- this module precomputes its raw output for
every split *once*, then trains the small head against those cached
arrays for as many epochs as early stopping needs. `DEVICE`/`_git_sha()`
are reused from `train.py`; `_region_to_idx` is reused from `train_tft.py`
(purely data-driven, no TFT-specific behavior).
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

import mlflow
import torch
from torch.utils.data import DataLoader, TensorDataset

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead
from ecolens.forecasting.schema.features import (
    TARGET_INDEX,
    FeatureScaler,
    Split,
    WindowedDataset,
)

from ..mlops.registry import log_model_artifacts
from ..timesfm_backbone import FrozenTimesFM, TimesFMBackbone
from .losses import DemandForecastLoss
from .train import DEVICE, _git_sha
from .train_tft import _region_to_idx

log = get_logger(__name__)


@dataclass
class RawForecast:
    """TimesFM's frozen output for one split, normalized into this repo's
    scaled units (see `model/timesfm_head.py`'s docstring for why) --
    computed once per split, reused across every training epoch and by
    `evaluation/evaluate_timesfm.py`, since the frozen backbone's output
    for a fixed input never changes.
    """

    p10: torch.Tensor  # (n, horizon), scaled
    p50: torch.Tensor
    p90: torch.Tensor


@dataclass
class TimesFMTrainResult:
    run_id: str
    model: TimesFMCalibrationHead
    dataset: WindowedDataset
    region_to_idx: dict[str, int]
    raw_forecasts: dict[str, RawForecast]  # "train"/"val"/"calibration"/"test"
    best_val_loss: float
    epochs_trained: int


def _precompute_raw(
    backbone: TimesFMBackbone, split: Split, scaler: FeatureScaler, *, horizon: int
) -> RawForecast:
    """Runs the frozen TimesFM backbone once over every window in `split`.
    TimesFM needs raw MW-scale context (it does its own internal
    normalization) -- reconstructed from `split.x`'s already-scaled
    `demand_mw` column via the existing inverse transform, rather than
    threading a second, unscaled copy of the data through
    `windowing.py`/`schema/features.py`. Its raw MW-scale output is then
    normalized back into this repo's scaled units for the head to train
    against.
    """
    raw_context = scaler.inverse_transform_target(split.x[:, :, TARGET_INDEX].numpy())
    p10_mw, p50_mw, p90_mw = backbone.forecast_raw(raw_context, horizon=horizon)
    mean, std = scaler.mean[TARGET_INDEX], scaler.std[TARGET_INDEX]
    return RawForecast(
        p10=torch.tensor((p10_mw - mean) / std, dtype=torch.float32),
        p50=torch.tensor((p50_mw - mean) / std, dtype=torch.float32),
        p90=torch.tensor((p90_mw - mean) / std, dtype=torch.float32),
    )


def _precompute_all_raw(
    backbone: TimesFMBackbone, dataset: WindowedDataset
) -> dict[str, RawForecast]:
    """Runs the frozen backbone once per split, for all four splits --
    factored out of `train_timesfm_model` so `online_timesfm.py`'s
    fine-tune path (which also needs every split's raw forecast, for
    `evaluate_timesfm_model` afterward, not just train/val for its own
    training loop) can reuse it rather than duplicating this same dict
    comprehension.
    """
    return {
        name: _precompute_raw(backbone, split, dataset.scaler, horizon=dataset.horizon)
        for name, split in (
            ("train", dataset.train),
            ("val", dataset.val),
            ("calibration", dataset.calibration),
            ("test", dataset.test),
        )
    }


def _region_idx_tensor(split: Split, region_to_idx: dict[str, int]) -> torch.Tensor:
    return torch.tensor([region_to_idx[r] for r in split.region], dtype=torch.long)


def _loader(
    raw: RawForecast,
    split: Split,
    region_to_idx: dict[str, int],
    batch_size: int,
    *,
    shuffle: bool,
) -> DataLoader:
    ridx = _region_idx_tensor(split, region_to_idx)
    return DataLoader(
        TensorDataset(raw.p10, raw.p50, raw.p90, ridx, split.y),
        batch_size=batch_size,
        shuffle=shuffle,
    )


def _run_epoch(
    model: TimesFMCalibrationHead,
    loader: DataLoader,
    loss_fn: DemandForecastLoss,
    optimizer: torch.optim.Optimizer | None,
) -> float:
    model.train(optimizer is not None)
    total_loss = 0.0
    n = 0
    with torch.set_grad_enabled(optimizer is not None):
        for p10b, p50b, p90b, ridxb, yb in loader:
            p10b, p50b, p90b = p10b.to(DEVICE), p50b.to(DEVICE), p90b.to(DEVICE)
            ridxb, yb = ridxb.to(DEVICE), yb.to(DEVICE)
            if optimizer is not None:
                optimizer.zero_grad()
            outputs = model(p10b, p50b, p90b, ridxb)
            loss, _ = loss_fn(outputs, yb)
            if optimizer is not None:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * p50b.size(0)
            n += p50b.size(0)
    return total_loss / n


def train_timesfm_model(
    dataset: WindowedDataset,
    settings: Settings | None = None,
    *,
    backbone: TimesFMBackbone | None = None,
    log_to_mlflow: bool = True,
) -> TimesFMTrainResult:
    """Fits a `TimesFMCalibrationHead` on top of TimesFM's frozen output,
    early-stopping on `dataset.val` -- same early-stopping/best-checkpoint
    contract as `train.py`/`train_tft.py`'s own training loops.

    `backbone` defaults to a real `FrozenTimesFM()` (lazy-loads the ~2GB
    pretrained checkpoint on first use); tests inject a fake instead so
    the default test suite never downloads or runs the real model.
    """
    settings = settings or get_settings()
    backbone = backbone or FrozenTimesFM(settings=settings)
    region_to_idx = _region_to_idx(dataset)

    log.info(
        "training_timesfm.precompute_start",
        num_regions=len(region_to_idx),
        train_samples=len(dataset.train.x),
    )
    raw_forecasts = _precompute_all_raw(backbone, dataset)
    log.info("training_timesfm.precompute_complete")

    model = TimesFMCalibrationHead(
        horizon=dataset.horizon,
        num_regions=len(region_to_idx),
        static_dim=settings.model_timesfm_static_dim,
        hidden_dim=settings.model_timesfm_hidden_dim,
        dropout=settings.model_timesfm_dropout,
    ).to(DEVICE)

    loss_fn = DemandForecastLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=settings.model_timesfm_train_lr)

    train_loader = _loader(
        raw_forecasts["train"],
        dataset.train,
        region_to_idx,
        settings.model_timesfm_batch_size,
        shuffle=True,
    )
    val_loader = _loader(
        raw_forecasts["val"],
        dataset.val,
        region_to_idx,
        settings.model_timesfm_batch_size,
        shuffle=False,
    )

    best_val_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    epochs_since_improvement = 0
    epochs_trained = 0

    if log_to_mlflow:
        mlflow.set_experiment(settings.mlflow_experiment_name_timesfm)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            params: dict[str, int | float | str] = {
                "lookback": dataset.lookback,
                "horizon": dataset.horizon,
                "timesfm_repo_id": settings.timesfm_repo_id,
                "hidden_dim": settings.model_timesfm_hidden_dim,
                "static_dim": settings.model_timesfm_static_dim,
                "num_regions": len(region_to_idx),
                "dropout": settings.model_timesfm_dropout,
                "lr": settings.model_timesfm_train_lr,
                "batch_size": settings.model_timesfm_batch_size,
                "train_samples": len(dataset.train.x),
                "val_samples": len(dataset.val.x),
            }
            sha = _git_sha()
            if sha:
                params["git_sha"] = sha
            mlflow.log_params(params)

        for epoch in range(settings.model_timesfm_train_epochs):
            train_loss = _run_epoch(model, train_loader, loss_fn, optimizer)
            val_loss = _run_epoch(model, val_loader, loss_fn, None)
            epochs_trained = epoch + 1

            if log_to_mlflow:
                mlflow.log_metrics(
                    {"train_loss": train_loss, "val_loss": val_loss}, step=epoch
                )
            log.info(
                "training_timesfm.epoch",
                epoch=epoch,
                train_loss=round(train_loss, 4),
                val_loss=round(val_loss, 4),
            )

            if val_loss < best_val_loss - 1e-6:
                best_val_loss = val_loss
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                epochs_since_improvement = 0
            else:
                epochs_since_improvement += 1
                if epochs_since_improvement >= settings.model_early_stop_patience:
                    log.info(
                        "training_timesfm.early_stop",
                        epoch=epoch,
                        best_val_loss=round(best_val_loss, 4),
                    )
                    break

        if best_state is not None:
            model.load_state_dict(best_state)

        run_id = run.info.run_id if run is not None else ""
        if log_to_mlflow:
            mlflow.log_metric("best_val_loss", best_val_loss)
            mlflow.log_dict(dataset.scaler.to_dict(), "scaler.json")
            mlflow.log_dict(region_to_idx, "region_index.json")
            mlflow.log_dict(
                {"repo_id": settings.timesfm_repo_id}, "timesfm_backbone.json"
            )
            log_model_artifacts(model)

    log.info(
        "training_timesfm.complete",
        run_id=run_id,
        best_val_loss=round(best_val_loss, 4),
        epochs_trained=epochs_trained,
    )
    return TimesFMTrainResult(
        run_id=run_id,
        model=model,
        dataset=dataset,
        region_to_idx=region_to_idx,
        raw_forecasts=raw_forecasts,
        best_val_loss=best_val_loss,
        epochs_trained=epochs_trained,
    )


__all__ = [
    "RawForecast",
    "TimesFMTrainResult",
    "train_timesfm_model",
    "_precompute_all_raw",
]
