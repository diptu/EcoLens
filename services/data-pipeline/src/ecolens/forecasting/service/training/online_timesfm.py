"""Root TODO.md's "Fine tuning" section, "TimesFM monthly fine-tune": very
small LR, 1-2 epochs, transformer backbone stays frozen, only the head
trains. Mirrors `training/online.py`/`training/online_tft.py`'s fine-tune
shape (never mutates the caller's model, short run at a reduced LR, never
auto-promoted -- goes through the same `mlops/promote.py` gate as a full
`train_timesfm_model` run).

"Transformer backbone stays frozen" needs no extra freezing logic here --
TimesFM's own forward pass is never trainable in this repo to begin with
(see `service/timesfm_backbone.py`'s `FrozenTimesFM`, always a no-grad
`forecast()` call); `TimesFMCalibrationHead` is the *only* trainable
component of this model in any training mode, unlike TFT's static/temporal
split. So "fine-tune" here just means continuing that head's training from
its current (warm-started, not random-init) weights for a couple more
epochs at a much lower LR than the original `model_timesfm_train_lr`
(1e-3) -- reuses `train_timesfm.py`'s private `_precompute_all_raw`/
`_loader`/`_run_epoch` rather than duplicating them, same
import-a-sibling-module's-private-helper precedent `online.py`/
`online_tft.py` set for `train.py`/`train_tft.py`.
"""

from __future__ import annotations

import copy
from contextlib import nullcontext
from dataclasses import dataclass

import mlflow
import torch

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead
from ecolens.forecasting.schema.features import WindowedDataset

from ..mlops.registry import log_model_artifacts
from ..timesfm_backbone import FrozenTimesFM, TimesFMBackbone
from .losses import DemandForecastLoss
from .train import DEVICE
from .train_timesfm import RawForecast, _loader, _precompute_all_raw, _run_epoch

log = get_logger(__name__)

DEFAULT_FINE_TUNE_EPOCHS = 2
# "Very small" relative to model_timesfm_train_lr's 1e-3 default, and
# smaller even than the TFT fine-tune's 1e-5 (online_tft.py) -- this
# head is already the only trainable component in *any* training mode
# for this model (see module docstring), so there's no separate
# freeze/unfreeze lever the way TFT's static-encoder split gives it;
# a lower LR than TFT's is the only knob left to make this meaningfully
# lighter-touch than a full `train_timesfm_model` run.
DEFAULT_LR = 5e-6


@dataclass
class TimesFMOnlineFineTuneResult:
    run_id: str
    model: TimesFMCalibrationHead
    raw_forecasts: dict[str, RawForecast]  # "train"/"val"/"calibration"/"test"
    final_val_loss: float


def fine_tune_timesfm(
    base_model: TimesFMCalibrationHead,
    dataset: WindowedDataset,
    region_to_idx: dict[str, int],
    settings: Settings | None = None,
    *,
    backbone: TimesFMBackbone | None = None,
    epochs: int = DEFAULT_FINE_TUNE_EPOCHS,
    lr: float = DEFAULT_LR,
    log_to_mlflow: bool = True,
) -> TimesFMOnlineFineTuneResult:
    """Fine-tunes a *copy* of `base_model` (never mutates the caller's
    model in place -- same reasoning as `online.py`/`online_tft.py`) on
    `dataset`.

    `region_to_idx` must be the *original* training run's mapping (its
    `region_index.json` MLflow artifact) -- same reasoning as
    `online_tft.py`'s `fine_tune_tft`: the head's region embedding rows
    are indexed by that original mapping, so reindexing from a
    possibly-different region set in the fine-tune buffer would silently
    feed the wrong embedding row for a region.

    Precomputes the frozen backbone's raw forecast for every split (not
    just train/val) and returns it alongside the fine-tuned model, same
    as `train_timesfm_model` -- the caller's follow-up
    `evaluate_timesfm_model` call needs the calibration/test splits' raw
    forecasts too, and TimesFM's output for a fixed input never changes,
    so there's no reason to recompute it a second time there.

    `backbone` defaults to a real `FrozenTimesFM()`; tests inject a fake
    (same as `train_timesfm_model`'s own `backbone` param) so the default
    test suite never downloads or runs the real ~2GB checkpoint.
    """
    settings = settings or get_settings()
    backbone = backbone or FrozenTimesFM(settings=settings)
    log.info("online_timesfm.device", device=str(DEVICE))
    model = copy.deepcopy(base_model).to(DEVICE)

    raw_forecasts = _precompute_all_raw(backbone, dataset)

    loss_fn = DemandForecastLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

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

    if log_to_mlflow:
        mlflow.set_experiment(settings.mlflow_experiment_name_timesfm)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            mlflow.log_params(
                {
                    "fine_tune": True,
                    "fine_tune_epochs": epochs,
                    "lr": lr,
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
                "online_timesfm.fine_tune_epoch",
                epoch=epoch,
                train_loss=round(train_loss, 4),
                val_loss=round(val_loss, 4),
            )

        run_id = run.info.run_id if run is not None else ""
        if log_to_mlflow:
            mlflow.log_metric("final_val_loss", val_loss)
            mlflow.log_dict(dataset.scaler.to_dict(), "scaler.json")
            mlflow.log_dict(region_to_idx, "region_index.json")
            mlflow.log_dict(
                {"repo_id": settings.timesfm_repo_id}, "timesfm_backbone.json"
            )
            log_model_artifacts(model)

    log.info(
        "online_timesfm.fine_tune_complete",
        run_id=run_id,
        final_val_loss=round(val_loss, 4),
    )
    return TimesFMOnlineFineTuneResult(
        run_id=run_id, model=model, raw_forecasts=raw_forecasts, final_val_loss=val_loss
    )


__all__ = [
    "TimesFMOnlineFineTuneResult",
    "fine_tune_timesfm",
    "DEFAULT_FINE_TUNE_EPOCHS",
    "DEFAULT_LR",
]
