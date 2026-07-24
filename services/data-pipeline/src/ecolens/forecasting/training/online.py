"""ECO-118 (part 1): "online"/incremental learning, defined.

Root `TODO.md` left this as an open design decision -- "periodic
fine-tune on the newest window vs. a scheduled full retrain" -- rather
than assume one. Decision, made here rather than left open indefinitely:
**online learning means fine-tuning the current production model's
weights on the most recent window of data**, a few epochs at a reduced
learning rate, producing a new candidate version. It does **not** mean
training from scratch, and a fine-tuned candidate is **never**
auto-promoted just for being freshest -- it goes through the exact
same `mlops/promote.py` gate (beat the current production MAPE on a
real held-out split) as a full retrain does. A full from-scratch
`train_model` run on a fresh snapshot (root TODO's weekly-rebuild
cadence, see `werehouse.md`) remains the periodic heavy path; this is
the lighter-weight in-between that keeps the model from going stale
between those.

This matches `strategy.md`'s "Shadow Training (GPU-Worker)" framing:
whichever process runs this (a cron job today, per ECO-119's
orchestration decision) is `data-pipeline`, out of process from
`forecast-api`'s low-latency serving path, which only ever polls the
registry for a new `production`-aliased version (ECO-F04) -- it never
runs a training step itself.
"""

from __future__ import annotations

import copy
from contextlib import nullcontext
from dataclasses import dataclass

import mlflow
import torch

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..features import WindowedDataset
from ..mlops.registry import log_model_artifacts
from ..models.lstm import DemandLSTM
from .losses import DemandForecastLoss
from .train import DEVICE, _loader, _run_epoch

log = get_logger(__name__)

DEFAULT_FINE_TUNE_EPOCHS = 3
DEFAULT_LR_SCALE = 0.1


@dataclass
class OnlineFineTuneResult:
    run_id: str
    model: DemandLSTM
    final_val_loss: float


def fine_tune(
    base_model: DemandLSTM,
    dataset: WindowedDataset,
    settings: Settings | None = None,
    *,
    epochs: int = DEFAULT_FINE_TUNE_EPOCHS,
    lr_scale: float = DEFAULT_LR_SCALE,
    log_to_mlflow: bool = True,
) -> OnlineFineTuneResult:
    """Fine-tunes a *copy* of `base_model` (never mutates the caller's
    model in place -- the caller almost certainly still needs the
    original, e.g. to keep serving from while this runs) on `dataset`
    for a short, reduced-learning-rate run.
    """
    settings = settings or get_settings()
    model = copy.deepcopy(base_model).to(DEVICE)
    loss_fn = DemandForecastLoss()
    optimizer = torch.optim.Adam(
        model.parameters(), lr=settings.model_train_lr * lr_scale
    )

    train_loader = _loader(dataset.train, settings.model_batch_size, shuffle=True)
    val_loader = _loader(dataset.val, settings.model_batch_size, shuffle=False)

    if log_to_mlflow:
        # See train.py's identical guard: without this, the run silently
        # lands outside the configured experiment.
        mlflow.set_experiment(settings.mlflow_experiment_name)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            mlflow.log_params(
                {
                    "fine_tune": True,
                    "fine_tune_epochs": epochs,
                    "lr_scale": lr_scale,
                    "base_lr": settings.model_train_lr,
                }
            )
        val_loss = float("inf")
        for epoch in range(epochs):
            train_loss = _run_epoch(model, train_loader, loss_fn, optimizer)
            val_loss = _run_epoch(model, val_loader, loss_fn, None)
            if log_to_mlflow:
                mlflow.log_metrics(
                    {"train_loss": train_loss, "val_loss": val_loss}, step=epoch
                )
            log.info(
                "online.fine_tune_epoch",
                epoch=epoch,
                train_loss=round(train_loss, 4),
                val_loss=round(val_loss, 4),
            )

        run_id = run.info.run_id if run is not None else ""
        if log_to_mlflow:
            mlflow.log_metric("final_val_loss", val_loss)
            mlflow.log_dict(dataset.scaler.to_dict(), "scaler.json")
            log_model_artifacts(model)

    log.info(
        "online.fine_tune_complete", run_id=run_id, final_val_loss=round(val_loss, 4)
    )
    return OnlineFineTuneResult(run_id=run_id, model=model, final_val_loss=val_loss)


__all__ = [
    "OnlineFineTuneResult",
    "fine_tune",
    "DEFAULT_FINE_TUNE_EPOCHS",
    "DEFAULT_LR_SCALE",
]
