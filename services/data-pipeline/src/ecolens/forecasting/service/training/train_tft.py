"""Training loop for `DemandTFT` -- a parallel module to `train.py`, not a
modification of it. `train.py`'s `DataLoader`/`TensorDataset` calls are
2-tensor (`x`, `y`) and its `_run_epoch` hardcodes `model(xb)`; TFT needs a
third per-sample tensor (the static `region_idx` covariate). Threading an
optional third tensor through the LSTM's already-tested, in-production
training loop was judged more risk than benefit for what's otherwise a
structurally identical loop -- see this session's plan for the full
reasoning. `DEVICE` and `_git_sha()` are architecture-agnostic and reused
directly from `train.py` rather than duplicated.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

import mlflow
import torch
from torch.utils.data import DataLoader, TensorDataset

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.model.tft import DemandTFT
from ecolens.forecasting.schema.features import FEATURE_COLUMNS, Split, WindowedDataset

from ..mlops.registry import log_model_artifacts
from .losses import DemandForecastLoss
from .train import DEVICE, _git_sha

log = get_logger(__name__)


@dataclass
class TFTTrainResult:
    run_id: str
    model: DemandTFT
    dataset: WindowedDataset
    region_to_idx: dict[str, int]
    best_val_loss: float
    epochs_trained: int


def _region_to_idx(dataset: WindowedDataset) -> dict[str, int]:
    """Every region appearing in any split, sorted for a deterministic
    mapping -- built from the data itself (like the feature scaler),
    never hardcoded. All four splits share the same region set by
    construction (`windowing.py` splits chronologically *within* each
    region group), but unioning defensively costs nothing.
    """
    regions: set[str] = set()
    for split in (dataset.train, dataset.val, dataset.calibration, dataset.test):
        regions.update(split.region.unique().tolist())
    return {region: i for i, region in enumerate(sorted(regions))}


def _region_idx_tensor(split: Split, region_to_idx: dict[str, int]) -> torch.Tensor:
    return torch.tensor([region_to_idx[r] for r in split.region], dtype=torch.long)


def _loader(
    split: Split, region_to_idx: dict[str, int], batch_size: int, *, shuffle: bool
) -> DataLoader:
    ridx = _region_idx_tensor(split, region_to_idx)
    return DataLoader(
        TensorDataset(split.x, ridx, split.y), batch_size=batch_size, shuffle=shuffle
    )


def _run_epoch(
    model: DemandTFT,
    loader: DataLoader,
    loss_fn: DemandForecastLoss,
    optimizer: torch.optim.Optimizer | None,
) -> float:
    model.train(optimizer is not None)
    total_loss = 0.0
    n = 0
    with torch.set_grad_enabled(optimizer is not None):
        for xb, ridxb, yb in loader:
            xb, ridxb, yb = xb.to(DEVICE), ridxb.to(DEVICE), yb.to(DEVICE)
            if optimizer is not None:
                optimizer.zero_grad()
            outputs, _ = model(xb, ridxb)
            loss, _ = loss_fn(outputs, yb)
            if optimizer is not None:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * xb.size(0)
            n += xb.size(0)
    return total_loss / n


def train_tft_model(
    dataset: WindowedDataset,
    settings: Settings | None = None,
    *,
    log_to_mlflow: bool = True,
) -> TFTTrainResult:
    """Fits a `DemandTFT` on `dataset.train`, early-stopping on
    `dataset.val`, and returns the best-val-loss checkpoint -- same
    early-stopping/best-checkpoint contract as `train.py`'s
    `train_model()`.
    """
    settings = settings or get_settings()
    region_to_idx = _region_to_idx(dataset)

    log.info("training_tft.device", device=str(DEVICE), num_regions=len(region_to_idx))

    model = DemandTFT(
        n_features=len(FEATURE_COLUMNS),
        d_model=settings.model_tft_d_model,
        num_heads=settings.model_tft_num_heads,
        num_lstm_layers=settings.model_tft_num_lstm_layers,
        num_regions=len(region_to_idx),
        static_dim=settings.model_tft_static_dim,
        horizon=dataset.horizon,
        dropout=settings.model_tft_dropout,
    ).to(DEVICE)

    loss_fn = DemandForecastLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=settings.model_tft_train_lr)

    train_loader = _loader(
        dataset.train, region_to_idx, settings.model_tft_batch_size, shuffle=True
    )
    val_loader = _loader(
        dataset.val, region_to_idx, settings.model_tft_batch_size, shuffle=False
    )

    best_val_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    epochs_since_improvement = 0
    epochs_trained = 0

    if log_to_mlflow:
        mlflow.set_experiment(settings.mlflow_experiment_name_tft)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            params: dict[str, int | float | str] = {
                "lookback": dataset.lookback,
                "horizon": dataset.horizon,
                "n_features": len(FEATURE_COLUMNS),
                "d_model": settings.model_tft_d_model,
                "num_heads": settings.model_tft_num_heads,
                "num_lstm_layers": settings.model_tft_num_lstm_layers,
                "static_dim": settings.model_tft_static_dim,
                "num_regions": len(region_to_idx),
                "dropout": settings.model_tft_dropout,
                "lr": settings.model_tft_train_lr,
                "batch_size": settings.model_tft_batch_size,
                "train_samples": len(dataset.train.x),
                "val_samples": len(dataset.val.x),
            }
            sha = _git_sha()
            if sha:
                params["git_sha"] = sha
            mlflow.log_params(params)

        for epoch in range(settings.model_tft_train_epochs):
            train_loss = _run_epoch(model, train_loader, loss_fn, optimizer)
            val_loss = _run_epoch(model, val_loader, loss_fn, None)
            epochs_trained = epoch + 1

            if log_to_mlflow:
                mlflow.log_metrics(
                    {"train_loss": train_loss, "val_loss": val_loss}, step=epoch
                )
            log.info(
                "training_tft.epoch",
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
                        "training_tft.early_stop",
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
            log_model_artifacts(model)

    log.info(
        "training_tft.complete",
        run_id=run_id,
        best_val_loss=round(best_val_loss, 4),
        epochs_trained=epochs_trained,
    )
    return TFTTrainResult(
        run_id=run_id,
        model=model,
        dataset=dataset,
        region_to_idx=region_to_idx,
        best_val_loss=best_val_loss,
        epochs_trained=epochs_trained,
    )


__all__ = ["TFTTrainResult", "train_tft_model"]
