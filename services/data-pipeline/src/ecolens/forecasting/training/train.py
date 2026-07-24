"""ECO-112 (training loop): fits a `DemandLSTM` against a
`WindowedDataset`, early-stopping on validation loss, logging params/
metrics/the model itself to MLflow on every run.

Defaults to CPU, deliberately -- not a portability afterthought (see
`strategy.md` §3 on `state_dict` + `map_location`), but because
`nn.LSTM` on PyTorch's MPS backend (Apple Silicon) has a history of
missing/incorrect fused-kernel support. Nothing here hardcodes `cpu`
except this one `torch.device(...)` call: it auto-upgrades to `cuda`
when a CUDA device is actually present (e.g. the Colab GPU bridge in
`training/colab_dispatch.py` runs this same code unmodified on a T4),
and `ECOLENS_TRAIN_DEVICE` overrides it explicitly either way.
"""

from __future__ import annotations

import copy
import os
import subprocess  # nosec B404 - only used for a fixed, argument-free `git rev-parse HEAD` in _git_sha()
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

import mlflow
import torch
from torch.utils.data import DataLoader, TensorDataset

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..features import FEATURE_COLUMNS, Split, WindowedDataset
from ..mlops.registry import log_model_artifacts
from ..models.lstm import DemandLSTM
from .losses import DemandForecastLoss

log = get_logger(__name__)

DEVICE = torch.device(
    os.environ.get("ECOLENS_TRAIN_DEVICE")
    or ("cuda" if torch.cuda.is_available() else "cpu")
)


@dataclass
class TrainResult:
    run_id: str
    model: DemandLSTM
    dataset: WindowedDataset
    best_val_loss: float
    epochs_trained: int
    # Adam's per-parameter momentum/variance buffers at the same epoch
    # `model`'s weights were snapshotted from (see train_model()'s "new
    # best" tracking) -- None only if training ran zero epochs. Restore
    # via a fresh `torch.optim.Adam(...)` + `.load_state_dict(...)` to
    # continue training on a later data chunk without Adam's momentum
    # resetting to zero (training/incremental.py's whole reason to exist).
    optimizer_state: dict[str, Any] | None = None


def _git_sha() -> str | None:
    try:
        return subprocess.run(  # nosec B603 B607 - fixed args, no user input, read-only git query
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - git metadata is best-effort, never fatal to a training run
        return None


def _loader(split: Split, batch_size: int, *, shuffle: bool) -> DataLoader:
    return DataLoader(
        TensorDataset(split.x, split.y), batch_size=batch_size, shuffle=shuffle
    )


def _run_epoch(
    model: DemandLSTM,
    loader: DataLoader,
    loss_fn: DemandForecastLoss,
    optimizer: torch.optim.Optimizer | None,
) -> float:
    """One pass over `loader`. Trains (backprop) if `optimizer` is given,
    otherwise just evaluates -- same loop, so train/val can't drift apart.
    """
    model.train(optimizer is not None)
    total_loss = 0.0
    n = 0
    with torch.set_grad_enabled(optimizer is not None):
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            if optimizer is not None:
                optimizer.zero_grad()
            outputs, _ = model(xb)
            loss, _ = loss_fn(outputs, yb)
            if optimizer is not None:
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * xb.size(0)
            n += xb.size(0)
    return total_loss / n


def train_model(
    dataset: WindowedDataset,
    settings: Settings | None = None,
    *,
    log_to_mlflow: bool = True,
    initial_model_state: dict[str, torch.Tensor] | None = None,
    initial_optimizer_state: dict[str, Any] | None = None,
) -> TrainResult:
    """Fits a `DemandLSTM` on `dataset.train`, early-stopping on
    `dataset.val`, and returns the best-val-loss checkpoint (not
    necessarily the last epoch's).

    `initial_model_state`/`initial_optimizer_state` (both optional,
    independently) turn this from "train a fresh model from scratch"
    into "continue training an existing checkpoint" --
    `training/incremental.py`'s year-by-year chunked training uses both:
    a fresh `DemandLSTM` still gets built (architecture is derived from
    `settings`/`dataset.horizon` exactly as always -- the caller's
    responsibility to keep hidden_size/num_layers/dropout/lookback/
    horizon *identical* across chunks, since a state_dict only loads
    into a matching-shaped model), then `initial_model_state` overwrites
    its random initial weights and `initial_optimizer_state` restores
    Adam's momentum/variance buffers into the freshly-constructed
    optimizer -- otherwise every chunk's Adam would restart from zero
    momentum, causing the erratic loss spikes at each chunk boundary
    this whole mechanism exists to avoid.
    """
    settings = settings or get_settings()

    log.info("training.device", device=str(DEVICE))

    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS),
        hidden_size=settings.model_hidden_size,
        num_layers=settings.model_num_layers,
        horizon=dataset.horizon,
        dropout=settings.model_dropout,
    )
    if initial_model_state is not None:
        model.load_state_dict(initial_model_state)
    model = model.to(DEVICE)

    loss_fn = DemandForecastLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=settings.model_train_lr)
    if initial_optimizer_state is not None:
        optimizer.load_state_dict(initial_optimizer_state)

    train_loader = _loader(dataset.train, settings.model_batch_size, shuffle=True)
    val_loader = _loader(dataset.val, settings.model_batch_size, shuffle=False)

    best_val_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    # Snapshotted alongside best_state (not just the final epoch's optimizer
    # state) so the returned checkpoint's weights and Adam's momentum/
    # variance buffers stay mutually consistent -- early stopping can pick
    # an *earlier* epoch as "best," and Adam's state from a later epoch
    # would reflect gradients computed against weights that checkpoint no
    # longer has.
    best_optimizer_state: dict[str, Any] | None = None
    epochs_since_improvement = 0
    epochs_trained = 0

    if log_to_mlflow:
        # Without this, mlflow.start_run() below silently lands the run in
        # whatever experiment happened to be active last (process-global
        # state) or MLflow's generic "Default" experiment -- never the
        # configured mlflow_experiment_name -- since nothing else in this
        # call path sets it.
        mlflow.set_experiment(settings.mlflow_experiment_name)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            params: dict[str, int | float | str] = {
                "lookback": dataset.lookback,
                "horizon": dataset.horizon,
                "n_features": len(FEATURE_COLUMNS),
                "hidden_size": settings.model_hidden_size,
                "num_layers": settings.model_num_layers,
                "dropout": settings.model_dropout,
                "lr": settings.model_train_lr,
                "batch_size": settings.model_batch_size,
                "train_samples": len(dataset.train.x),
                "val_samples": len(dataset.val.x),
            }
            sha = _git_sha()
            if sha:
                params["git_sha"] = sha
            mlflow.log_params(params)

        for epoch in range(settings.model_train_epochs):
            train_loss = _run_epoch(model, train_loader, loss_fn, optimizer)
            val_loss = _run_epoch(model, val_loader, loss_fn, None)
            epochs_trained = epoch + 1

            if log_to_mlflow:
                mlflow.log_metrics(
                    {"train_loss": train_loss, "val_loss": val_loss}, step=epoch
                )
            log.info(
                "training.epoch",
                epoch=epoch,
                train_loss=round(train_loss, 4),
                val_loss=round(val_loss, 4),
            )

            if val_loss < best_val_loss - 1e-6:
                best_val_loss = val_loss
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
                best_optimizer_state = copy.deepcopy(optimizer.state_dict())
                epochs_since_improvement = 0
            else:
                epochs_since_improvement += 1
                if epochs_since_improvement >= settings.model_early_stop_patience:
                    log.info(
                        "training.early_stop",
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
            log_model_artifacts(model, optimizer_state=best_optimizer_state)

    log.info(
        "training.complete",
        run_id=run_id,
        best_val_loss=round(best_val_loss, 4),
        epochs_trained=epochs_trained,
    )
    return TrainResult(
        run_id=run_id,
        model=model,
        dataset=dataset,
        best_val_loss=best_val_loss,
        epochs_trained=epochs_trained,
        optimizer_state=best_optimizer_state,
    )


__all__ = ["TrainResult", "train_model", "DEVICE"]
