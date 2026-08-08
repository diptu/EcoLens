"""Assembles `ml/data.py`'s `TFTDataset` + `app/models/tft.py`'s
`DemandTFT` into an actual training run, logged to MLflow under a
*separate* registered model name (`lstm_demand_tft` by convention, not
`lstm_demand`) — `todo-model-training.md` Phase 2's own naming-discipline
note: a v1 TFT and a v7 LSTM aren't comparable versions of "the same
model", and sharing a registry name would break `promote_version`'s
gating the moment both have a "Production" version.

Deliberately mirrors `ml/train.py`'s structure and reuses everything in
it that's genuinely architecture-agnostic (`TrainResult`,
`log_and_register_run`, `mape`, `_fit_target_scaler`/`_scale_target`/
`_inverse_target`, `_split_val_for_calibration`, `demand_loss`,
`fit_conformal`/`empirical_coverage`) rather than re-deriving any of it —
see `TFTTrainConfig`'s docstring for the one place a genuine TFT-specific
field (`n_heads`) needed adding, and `log_and_register_run`'s own
docstring for why `extra_params` exists (TFT's real encoder/decoder
feature-count split doesn't fit that function's LSTM-shaped
`n_features` param).

Two entrypoints, matching `ml/train.py`'s split exactly:

- `train_tft_model` — the pure, DB/MLflow-free training loop.
- `train_and_register_tft` — the real orchestration: queries the
  warehouse, calls `train_tft_model`, logs everything to MLflow, and (by
  default) registers the result as a new `lstm_demand_tft` version.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.tft import DemandTFT
from app.service.ml.conformal import empirical_coverage, fit_conformal
from app.service.ml.data import (
    TFTDataset,
    apply_scalers,
    collate_tft,
    fit_scalers,
    load_holidays,
    load_training_data,
    split_by_time,
)
from app.service.ml.features import (
    KNOWN_FUTURE_COLUMNS,
    OBSERVED_PAST_COLUMNS,
    build_features,
)
from app.service.ml.device import get_device
from app.service.ml.losses import demand_loss
from app.service.ml.train import (
    TrainAndRegisterResult,
    TrainConfig,
    TrainResult,
    _fit_target_scaler,
    _inverse_target,
    _scale_target,
    _split_val_for_calibration,
    log_and_register_run,
    mae,
    mape,
    rmse,
)
from app.service.mlops.tracking import configure_mlflow
from app.core.logging import get_logger

log = get_logger(__name__)

ENCODER_COLUMNS: tuple[str, ...] = OBSERVED_PAST_COLUMNS + KNOWN_FUTURE_COLUMNS
DECODER_COLUMNS: tuple[str, ...] = KNOWN_FUTURE_COLUMNS

# The canonical `lstm_demand_tft` registry name -- matches `cli.py`'s
# `train-tft --model-name` default. Defined once here (not
# `Settings.mlflow_registry_model_name`, which stays `lstm_demand`) so
# `training_worker.py`/`pipeline/flows` reference the same constant
# instead of each hardcoding their own copy of the literal.
TFT_MODEL_NAME = "lstm_demand_tft"


@dataclass
class TFTTrainConfig(TrainConfig):
    """`TrainConfig` plus `n_heads` -- the one genuinely TFT-specific
    hyperparameter (`DemandTFT`'s attention head count). Every other
    field (`hidden_size`/`dropout`/`lr`/`epochs`/`batch_size`/
    `quantile_weight`/`conformal_alpha`/`cal_frac`/
    `early_stopping_patience`/`train_frac`/`val_frac`/`lookback`/
    `horizon`) applies to TFT training exactly as it does to LSTM
    training, hence subclassing rather than a separate parallel
    dataclass. `num_layers` is inherited but unused -- `DemandTFT`'s
    encoder/decoder LSTMs are fixed at one layer each (the paper's own
    design; TFT gets its depth from the VSN/GRN/attention stack, not
    from stacking LSTM layers)."""

    n_heads: int = 4

    def as_mlflow_params(self) -> dict[str, object]:
        params = super().as_mlflow_params()
        params["n_heads"] = self.n_heads
        return params


def _predict_tft(
    model: DemandTFT, loader: DataLoader, device: torch.device
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`ml/train.py`'s `_predict`, adapted for `DemandTFT`'s two-input
    `forward(x_encoder, x_decoder)` signature."""
    model.eval()
    ys, p10s, p50s, p90s = [], [], [], []
    with torch.no_grad():
        for x_enc, x_dec, y in loader:
            x_enc, x_dec, y = x_enc.to(device), x_dec.to(device), y.to(device)
            out = model(x_enc, x_dec)
            ys.append(y.cpu().numpy())
            p10s.append(out.p10.cpu().numpy())
            p50s.append(out.p50.cpu().numpy())
            p90s.append(out.p90.cpu().numpy())
    return (
        np.concatenate(ys),
        np.concatenate(p10s),
        np.concatenate(p50s),
        np.concatenate(p90s),
    )


def _compute_val_loss_tft(
    model: DemandTFT, loader: DataLoader, quantile_weight: float, device: torch.device
) -> float:
    """`ml/train.py`'s `_compute_val_loss`, adapted for `DemandTFT`'s
    two-input `forward` signature -- see that function's own docstring
    for why this (not `val_mape`) is the real, same-units counterpart to
    `train_loss` for a "training vs validation loss" chart."""
    model.eval()
    losses = []
    with torch.no_grad():
        for x_enc, x_dec, y in loader:
            x_enc, x_dec, y = x_enc.to(device), x_dec.to(device), y.to(device)
            out = model(x_enc, x_dec)
            loss = demand_loss(out, y, quantile_weight=quantile_weight)
            losses.append(loss.item())
    return float(np.mean(losses))


def train_tft_model(
    raw_df: pd.DataFrame,
    config: TFTTrainConfig,
    *,
    holidays: pd.DataFrame | None = None,
    warm_start_state_dict: dict[str, torch.Tensor] | None = None,
) -> TrainResult:
    """`DemandTFT`'s counterpart to `ml/train.py`'s `train_model` --
    same split/scale/window/train/calibrate/test structure, same
    `TrainResult` return type (genuinely architecture-agnostic, see that
    dataclass's own comment), same `ValueError`-on-insufficient-history
    behavior.

    `warm_start_state_dict`, if given, is loaded into the freshly
    constructed `DemandTFT` before training starts -- `incremental_tft.py`'s
    warm-started fine-tune path (`todo-model-training.md` Phase 4's "apply
    the same higher-frequency treatment to TFT"), mirroring `train_model`'s
    identical parameter exactly. The caller is responsible for making sure
    `config`'s architecture fields (`hidden_size`/`n_heads`/`dropout`/
    `horizon`) match whatever produced the state dict -- a mismatch
    surfaces as `load_state_dict` raising a shape error, not a silent
    no-op.
    """
    engineered = build_features(raw_df, holidays=holidays)
    split = split_by_time(
        engineered, train_frac=config.train_frac, val_frac=config.val_frac
    )
    earlystop_val, cal = _split_val_for_calibration(split.val, config.cal_frac)

    if split.train.empty or earlystop_val.empty or cal.empty:
        raise ValueError(
            "not enough history to build train/val/calibration splits "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(split.train)}/{len(earlystop_val)}/{len(cal)} rows"
        )

    scalers = fit_scalers(split.train)
    train_scaled = apply_scalers(split.train, scalers)
    val_scaled = apply_scalers(earlystop_val, scalers)
    cal_scaled = apply_scalers(cal, scalers)
    test_scaled = apply_scalers(split.test, scalers)

    target_scaler = _fit_target_scaler(split.train)
    train_scaled = _scale_target(train_scaled, target_scaler)
    val_scaled = _scale_target(val_scaled, target_scaler)
    cal_scaled = _scale_target(cal_scaled, target_scaler)
    test_scaled = _scale_target(test_scaled, target_scaler)

    def _dataset(df):
        return TFTDataset(
            df,
            encoder_columns=ENCODER_COLUMNS,
            decoder_columns=DECODER_COLUMNS,
            lookback=config.lookback,
            horizon=config.horizon,
        )

    train_ds = _dataset(train_scaled)
    val_ds = _dataset(val_scaled)
    cal_ds = _dataset(cal_scaled)
    test_ds = _dataset(test_scaled)

    if len(train_ds) == 0 or len(val_ds) == 0 or len(cal_ds) == 0:
        raise ValueError(
            "not enough history to build train/val/calibration windows "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(train_ds)}/{len(val_ds)}/{len(cal_ds)} windows"
        )

    train_loader = DataLoader(
        train_ds, batch_size=config.batch_size, shuffle=True, collate_fn=collate_tft
    )
    val_loader = DataLoader(
        val_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate_tft
    )
    cal_loader = DataLoader(
        cal_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate_tft
    )
    test_loader = (
        DataLoader(
            test_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate_tft
        )
        if len(test_ds) > 0
        else None
    )

    device = get_device()
    model = DemandTFT(
        n_encoder_features=len(ENCODER_COLUMNS),
        n_decoder_features=len(DECODER_COLUMNS),
        horizon=config.horizon,
        hidden_size=config.hidden_size,
        n_heads=config.n_heads,
        dropout=config.dropout,
    )
    if warm_start_state_dict is not None:
        model.load_state_dict(warm_start_state_dict)
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=2
    )

    best_val_mape = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    patience_counter = 0
    history: list[dict[str, float]] = []

    for epoch in range(config.epochs):
        model.train()
        train_losses = []
        for x_enc, x_dec, y in train_loader:
            x_enc, x_dec, y = x_enc.to(device), x_dec.to(device), y.to(device)
            optimizer.zero_grad()
            out = model(x_enc, x_dec)
            loss = demand_loss(out, y, quantile_weight=config.quantile_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_losses.append(loss.item())

        y_val, _, p50_val, _ = _predict_tft(model, val_loader, device)
        y_val_mw = _inverse_target(target_scaler, y_val)
        p50_val_mw = _inverse_target(target_scaler, p50_val)
        val_mape = mape(p50_val_mw, y_val_mw)
        # Real MW-unit error metrics (2026-08-05, Performance page's
        # "validation RMSE & MAE" chart) -- see `ml/train.py`'s own
        # epoch loop for the identical reasoning.
        val_rmse = rmse(p50_val_mw, y_val_mw)
        val_mae = mae(p50_val_mw, y_val_mw)
        val_loss = _compute_val_loss_tft(
            model, val_loader, config.quantile_weight, device
        )
        scheduler.step(val_mape)

        history.append(
            {
                "epoch": float(epoch),
                "train_loss": float(np.mean(train_losses)),
                "val_loss": val_loss,
                "val_mape": val_mape,
                "val_rmse": val_rmse,
                "val_mae": val_mae,
            }
        )
        log.info(
            "train_tft.epoch",
            epoch=epoch,
            train_loss=history[-1]["train_loss"],
            val_loss=val_loss,
            val_mape=val_mape,
            val_rmse=val_rmse,
            val_mae=val_mae,
        )

        if val_mape < best_val_mape - 1e-4:
            best_val_mape = val_mape
            # `.cpu()` -- see `ml/train.py`'s identical `best_state` line
            # for why (the checkpoint's later load sites all assume CPU).
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= config.early_stopping_patience:
                log.info(
                    "train_tft.early_stop", epoch=epoch, best_val_mape=best_val_mape
                )
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    y_cal, p10_cal, _, p90_cal = _predict_tft(model, cal_loader, device)
    y_cal = _inverse_target(target_scaler, y_cal)
    p10_cal = _inverse_target(target_scaler, p10_cal)
    p90_cal = _inverse_target(target_scaler, p90_cal)
    calibration = fit_conformal(y_cal, p10_cal, p90_cal, alpha=config.conformal_alpha)

    test_metrics: dict[str, float] = {}
    if test_loader is not None:
        y_test, p10_test, p50_test, p90_test = _predict_tft(model, test_loader, device)
        y_test = _inverse_target(target_scaler, y_test)
        p10_test = _inverse_target(target_scaler, p10_test)
        p50_test = _inverse_target(target_scaler, p50_test)
        p90_test = _inverse_target(target_scaler, p90_test)
        lo_calibrated, hi_calibrated = calibration.apply(p10_test, p90_test)
        test_metrics = {
            "test_mape": mape(p50_test, y_test),
            "test_coverage_raw": empirical_coverage(y_test, p10_test, p90_test),
            "test_coverage_calibrated": empirical_coverage(
                y_test, lo_calibrated, hi_calibrated
            ),
        }

    return TrainResult(
        model=model,
        calibration=calibration,
        feature_scalers=scalers,
        target_scaler=target_scaler,
        history=history,
        test_metrics=test_metrics,
        n_train_windows=len(train_ds),
        n_val_windows=len(val_ds),
        n_cal_windows=len(cal_ds),
        n_test_windows=len(test_ds),
    )


async def train_and_register_tft(
    model_name: str,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    config: TFTTrainConfig | None = None,
    register: bool = True,
    since: pd.Timestamp | None = None,
) -> TrainAndRegisterResult:
    """The real, DB + MLflow-backed TFT entrypoint -- `ecolens-pipeline
    train --architecture tft`'s real path. `model_name` should be
    `lstm_demand_tft` (or similar) by this phase's own naming-discipline
    note, never the LSTM's `lstm_demand` registry entry.

    `since`: same reasoning as `ml/train.py`'s `train_and_register` --
    `split_by_time`'s 70/15/15 split is chronological over the *entire*
    query result, so a feature only backfilled for a recent window (e.g.
    `total_generation_mw`) gets diluted across a much longer mostly-NaN
    history without this, starving train/val/calibration of real data.
    """
    settings = settings or get_settings()
    config = config or TFTTrainConfig.from_settings(settings)
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions, since=since)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in the warehouse for regions={list(regions)}"
        )

    result = train_tft_model(raw_df, config, holidays=holidays_df)
    return log_and_register_run(
        result,
        config,
        regions,
        model_name,
        register=register,
        extra_tags={"architecture": "tft"},
        extra_params={
            "n_encoder_features": len(ENCODER_COLUMNS),
            "n_decoder_features": len(DECODER_COLUMNS),
        },
    )
