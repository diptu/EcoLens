"""Root TODO.md's "Fine tuning" section, "TFT monthly fine-tune": LR
`1e-5`, 2-3 epochs, static embeddings frozen -- only VSN/attention/decoder
adapt. Mirrors `training/online.py`'s LSTM fine-tune shape (never mutates
the caller's model, short run at a reduced LR, never auto-promoted --
goes through the same `mlops/promote.py` gate as a full `train_tft_model`
run), generalized to `DemandTFT`'s architecture and the extra per-sample
`region_idx` tensor `training/train_tft.py`'s loader already builds.

"Static embeddings frozen" here means the static covariate encoder's own
parameters (`region_embedding`, `static_grn_selection`, `static_grn_state`,
`static_grn_enrichment`) -- everything that determines *how a region gets
turned into a context vector* stays exactly as originally trained.
Everything that *consumes* that context and processes the temporal
sequence keeps adapting: the temporal VSN, the LSTM encoder, self-
attention, the position-wise GRN, and the three output heads -- this
repo's TFT has no literal seq2seq decoder (see `model/tft.py`'s own
docstring on why), so "decoder" in the TODO's wording maps onto that
whole post-static-encoding processing chain.

Reuses `train_tft.py`'s private `_loader`/`_run_epoch` (already shaped
for TFT's 3-tensor batches) rather than duplicating them -- same
import-a-sibling-module's-private-helper precedent `online.py` itself
sets by importing `train.py`'s `_loader`/`_run_epoch`.
"""

from __future__ import annotations

import copy
from contextlib import nullcontext
from dataclasses import dataclass

import mlflow
import torch

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ecolens.forecasting.model.tft import DemandTFT
from ecolens.forecasting.schema.features import WindowedDataset

from ..mlops.registry import log_model_artifacts
from .losses import DemandForecastLoss
from .train import DEVICE
from .train_tft import _loader, _run_epoch

log = get_logger(__name__)

DEFAULT_FINE_TUNE_EPOCHS = 3
DEFAULT_LR = 1e-5

# The static covariate encoder's own parameters -- frozen during
# fine-tuning, see module docstring for why.
_FROZEN_SUBMODULES = (
    "region_embedding",
    "static_grn_selection",
    "static_grn_state",
    "static_grn_enrichment",
)


@dataclass
class TFTOnlineFineTuneResult:
    run_id: str
    model: DemandTFT
    final_val_loss: float


def _freeze_static_encoder(model: DemandTFT) -> None:
    for name in _FROZEN_SUBMODULES:
        for param in getattr(model, name).parameters():
            param.requires_grad = False


def fine_tune_tft(
    base_model: DemandTFT,
    dataset: WindowedDataset,
    region_to_idx: dict[str, int],
    settings: Settings | None = None,
    *,
    epochs: int = DEFAULT_FINE_TUNE_EPOCHS,
    lr: float = DEFAULT_LR,
    log_to_mlflow: bool = True,
) -> TFTOnlineFineTuneResult:
    """Fine-tunes a *copy* of `base_model` (never mutates the caller's
    model in place -- same reasoning as `online.py`'s `fine_tune()`) with
    its static covariate encoder frozen.

    `region_to_idx` must be the *original* training run's mapping (logged
    as that run's `region_index.json` MLflow artifact), not one freshly
    derived from `dataset` -- the frozen `region_embedding`'s rows are
    indexed by that original mapping, so reindexing from a
    possibly-different region set in the fine-tune buffer would silently
    feed the wrong embedding row for a region.
    """
    settings = settings or get_settings()
    log.info("training_tft.device", device=str(DEVICE))
    model = copy.deepcopy(base_model).to(DEVICE)
    _freeze_static_encoder(model)

    loss_fn = DemandForecastLoss()
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(trainable_params, lr=lr)

    train_loader = _loader(
        dataset.train, region_to_idx, settings.model_tft_batch_size, shuffle=True
    )
    val_loader = _loader(
        dataset.val, region_to_idx, settings.model_tft_batch_size, shuffle=False
    )

    if log_to_mlflow:
        mlflow.set_experiment(settings.mlflow_experiment_name_tft)
    run_ctx = mlflow.start_run() if log_to_mlflow else nullcontext()
    with run_ctx as run:
        if log_to_mlflow:
            mlflow.log_params(
                {
                    "fine_tune": True,
                    "fine_tune_epochs": epochs,
                    "lr": lr,
                    "frozen_submodules": ",".join(_FROZEN_SUBMODULES),
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
                "online_tft.fine_tune_epoch",
                epoch=epoch,
                train_loss=round(train_loss, 4),
                val_loss=round(val_loss, 4),
            )

        run_id = run.info.run_id if run is not None else ""
        if log_to_mlflow:
            mlflow.log_metric("final_val_loss", val_loss)
            mlflow.log_dict(dataset.scaler.to_dict(), "scaler.json")
            mlflow.log_dict(region_to_idx, "region_index.json")
            log_model_artifacts(model)

    log.info(
        "online_tft.fine_tune_complete", run_id=run_id, final_val_loss=round(val_loss, 4)
    )
    return TFTOnlineFineTuneResult(run_id=run_id, model=model, final_val_loss=val_loss)


__all__ = [
    "TFTOnlineFineTuneResult",
    "fine_tune_tft",
    "DEFAULT_FINE_TUNE_EPOCHS",
    "DEFAULT_LR",
]
