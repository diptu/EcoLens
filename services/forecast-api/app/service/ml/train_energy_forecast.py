"""Assembles `energy_features.py` + `energy_data.py` + `models/
energy_forecast_lstm.py` + `losses.energy_forecast_loss` into a real
training run for the multi-task demand + generation-mix model, logged to
MLflow under a distinct registered model name (`DEFAULT_MODEL_NAME`) --
same "a new architecture gets its own MLflow model name, not a version
of an unrelated one" decision `train_tft.py` already made for
`lstm_demand_tft` vs `lstm_demand`.

Mirrors `ml/train.py`'s `train_model`/`log_and_register_run`/
`train_and_register` three-entrypoint shape closely, on purpose --
same architecture-agnostic MLflow logging pattern, same train/val split,
same early-stopping-on-MAPE loop. Two deliberate differences from
`train.py`, both scoped-out-not-forgotten for this first pass:

- **No conformal calibration.** `services/forecast-api/notebooks/
  lstm.ipynb`'s own docstring already flags this: "Final probabilistic
  calibration of derived carbon metrics should be performed downstream
  using predictive sampling and/or conformal calibration" -- the
  monotonic-quantile heads (`app/models/energy_forecast_lstm.py`)
  already guarantee non-crossing P10/P50/P90, which is what made
  `train.py`'s conformal step worth adding *on top of* for `DemandLSTM`
  too; extending calibration to a second target (generation, per
  source) is real additional design work, not attempted here.
- **Two targets, one combined loss.** `energy_forecast_loss` weights
  demand vs. generation pinball loss (`demand_weight`/
  `generation_weight`, both default `1.0`, matching the notebook's own
  `EnergyForecastLoss` defaults) rather than picking one target to
  early-stop against exclusively -- early stopping here watches
  combined validation MAPE (mean of demand MAPE and generation MAPE
  across all 5 buckets), not demand alone.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import joblib
import mlflow
import mlflow.pytorch
import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.energy_forecast_lstm import P50, EnergyForecastLSTM
from app.service.ml.data import apply_scalers, fit_scalers, load_holidays, split_by_time
from app.service.ml.device import get_device
from app.service.ml.energy_data import (
    EnergyForecastDataset,
    collate_energy,
    load_energy_training_data,
)
from app.service.ml.energy_features import (
    DEMAND_TARGET_COLUMN,
    FEATURE_COLUMNS,
    GENERATION_TARGET_COLUMNS,
    build_features,
)
from app.service.ml.losses import energy_forecast_loss
from app.service.ml.train import mae, mape, rmse, state_dict_bytes
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha

log = get_logger(__name__)

DEFAULT_MODEL_NAME = "energy_forecast_multi_task"


@dataclass
class EnergyTrainConfig:
    # Row-offset lookback/horizon, not wall-clock -- same accepted
    # trade-off `ml/features.py`'s own module comment documents (NEM is
    # 5-min native, WEM 30-min; a fixed row count means different
    # wall-clock depth per region). `energy_features.py`'s lag/rolling
    # *features* are wall-clock-aware (its own module docstring explains
    # why that distinction matters there); the Dataset-level window size
    # inherits the existing, already-accepted `Settings.model_lookback`/
    # `model_horizon` convention rather than reopening it here.
    lookback: int = 48
    horizon: int = 48
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.2
    lr: float = 1e-3
    epochs: int = 50
    batch_size: int = 64
    demand_weight: float = 1.0
    generation_weight: float = 1.0
    early_stopping_patience: int = 5
    train_frac: float = 0.6
    val_frac: float = 0.2

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            lookback=settings.model_lookback,
            horizon=settings.model_horizon,
            hidden_size=settings.model_hidden_size,
            num_layers=settings.model_num_layers,
            dropout=settings.model_dropout,
            lr=settings.model_train_lr,
            epochs=settings.model_train_epochs,
            batch_size=settings.model_batch_size,
        )

    def as_mlflow_params(self) -> dict[str, object]:
        return {
            "lookback": self.lookback,
            "horizon": self.horizon,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "lr": self.lr,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "demand_weight": self.demand_weight,
            "generation_weight": self.generation_weight,
            "early_stopping_patience": self.early_stopping_patience,
            "train_frac": self.train_frac,
            "val_frac": self.val_frac,
            "generation_sources": len(GENERATION_TARGET_COLUMNS),
        }


@dataclass
class EnergyTrainResult:
    model: EnergyForecastLSTM
    feature_scalers: dict[str, StandardScaler]
    demand_scaler: StandardScaler
    generation_scaler: StandardScaler
    history: list[dict[str, float]] = field(default_factory=list)
    test_metrics: dict[str, float] = field(default_factory=dict)
    n_train_windows: int = 0
    n_val_windows: int = 0
    n_test_windows: int = 0


def _fit_demand_scaler(train: pd.DataFrame) -> StandardScaler:
    scaler = StandardScaler()
    scaler.fit(train[[DEMAND_TARGET_COLUMN]].dropna().to_numpy())
    return scaler


def _fit_generation_scaler(train: pd.DataFrame) -> StandardScaler:
    """One scaler across all 5 generation buckets combined (same
    simplification `ml/train.py`'s `_fit_target_scaler` documents for
    demand, extended one step further here: all buckets share a
    magnitude scale close enough that a per-bucket scaler isn't worth
    the extra bookkeeping for a first pass)."""
    scaler = StandardScaler()
    values = train[list(GENERATION_TARGET_COLUMNS)].dropna().to_numpy().reshape(-1, 1)
    scaler.fit(values)
    return scaler


def _scale_targets(
    df: pd.DataFrame, demand_scaler: StandardScaler, generation_scaler: StandardScaler
) -> pd.DataFrame:
    out = df.copy()
    demand_mask = out[DEMAND_TARGET_COLUMN].notna()
    out.loc[demand_mask, DEMAND_TARGET_COLUMN] = demand_scaler.transform(
        out.loc[demand_mask, [DEMAND_TARGET_COLUMN]].to_numpy()
    ).ravel()

    for col in GENERATION_TARGET_COLUMNS:
        mask = out[col].notna()
        out.loc[mask, col] = generation_scaler.transform(out.loc[mask, [col]].to_numpy()).ravel()
    return out


def _inverse(scaler: StandardScaler, values: np.ndarray) -> np.ndarray:
    shape = values.shape
    return scaler.inverse_transform(values.reshape(-1, 1)).reshape(shape)


def _predict(
    model: EnergyForecastLSTM, loader: DataLoader, device: torch.device
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`(demand_true, demand_p50, generation_true, generation_p50)`,
    concatenated across every batch."""
    model.eval()
    demand_trues, demand_p50s, gen_trues, gen_p50s = [], [], [], []
    with torch.no_grad():
        for x, demand_y, generation_y in loader:
            x, demand_y, generation_y = (
                x.to(device),
                demand_y.to(device),
                generation_y.to(device),
            )
            out = model(x)
            demand_trues.append(demand_y.cpu().numpy())
            demand_p50s.append(out.demand[..., P50].cpu().numpy())
            gen_trues.append(generation_y.cpu().numpy())
            gen_p50s.append(out.generation[..., P50].cpu().numpy())
    return (
        np.concatenate(demand_trues),
        np.concatenate(demand_p50s),
        np.concatenate(gen_trues),
        np.concatenate(gen_p50s),
    )


def train_energy_model(
    raw_df: pd.DataFrame,
    config: EnergyTrainConfig,
    *,
    holidays: pd.DataFrame | None = None,
) -> EnergyTrainResult:
    """`raw_df`: `energy_data.load_energy_training_data`'s shape. Raises
    `ValueError` if there isn't enough history for at least one
    train/val window each -- same fail-loud contract `ml/train.
    train_model` uses, not a silent zero-sample "success"."""
    engineered = build_features(raw_df, holidays=holidays)
    split = split_by_time(engineered, train_frac=config.train_frac, val_frac=config.val_frac)

    if split.train.empty or split.val.empty:
        raise ValueError(
            "not enough history to build train/val splits "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(split.train)}/{len(split.val)} rows"
        )

    scalers = fit_scalers(split.train, columns=FEATURE_COLUMNS)
    train_scaled = apply_scalers(split.train, scalers, columns=FEATURE_COLUMNS)
    val_scaled = apply_scalers(split.val, scalers, columns=FEATURE_COLUMNS)
    test_scaled = apply_scalers(split.test, scalers, columns=FEATURE_COLUMNS)

    demand_scaler = _fit_demand_scaler(split.train)
    generation_scaler = _fit_generation_scaler(split.train)
    train_scaled = _scale_targets(train_scaled, demand_scaler, generation_scaler)
    val_scaled = _scale_targets(val_scaled, demand_scaler, generation_scaler)
    test_scaled = _scale_targets(test_scaled, demand_scaler, generation_scaler)

    train_ds = EnergyForecastDataset(train_scaled, lookback=config.lookback, horizon=config.horizon)
    val_ds = EnergyForecastDataset(val_scaled, lookback=config.lookback, horizon=config.horizon)
    test_ds = EnergyForecastDataset(test_scaled, lookback=config.lookback, horizon=config.horizon)

    if len(train_ds) == 0 or len(val_ds) == 0:
        raise ValueError(
            "not enough history to build train/val windows "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(train_ds)}/{len(val_ds)} windows"
        )

    train_loader = DataLoader(train_ds, batch_size=config.batch_size, shuffle=True, collate_fn=collate_energy)
    val_loader = DataLoader(val_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate_energy)
    test_loader = (
        DataLoader(test_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate_energy)
        if len(test_ds) > 0
        else None
    )

    device = get_device()
    model = EnergyForecastLSTM(
        input_features=len(FEATURE_COLUMNS),
        hidden_size=config.hidden_size,
        num_layers=config.num_layers,
        horizon=config.horizon,
        dropout=config.dropout,
        generation_sources=len(GENERATION_TARGET_COLUMNS),
    )
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", patience=2)

    best_val_mape = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    patience_counter = 0
    history: list[dict[str, float]] = []

    for epoch in range(config.epochs):
        model.train()
        train_losses = []
        for x, demand_y, generation_y in train_loader:
            x, demand_y, generation_y = (
                x.to(device),
                demand_y.to(device),
                generation_y.to(device),
            )
            optimizer.zero_grad()
            out = model(x)
            losses = energy_forecast_loss(
                out,
                demand_y,
                generation_y,
                demand_weight=config.demand_weight,
                generation_weight=config.generation_weight,
            )
            losses["total_loss"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_losses.append(losses["total_loss"].item())

        demand_true, demand_p50, gen_true, gen_p50 = _predict(model, val_loader, device)
        demand_true_mw = _inverse(demand_scaler, demand_true)
        demand_p50_mw = _inverse(demand_scaler, demand_p50)
        gen_true_mw = _inverse(generation_scaler, gen_true)
        gen_p50_mw = _inverse(generation_scaler, gen_p50)

        demand_val_mape = mape(demand_p50_mw, demand_true_mw)
        generation_val_mape = mape(gen_p50_mw.ravel(), gen_true_mw.ravel())
        combined_val_mape = float(np.mean([demand_val_mape, generation_val_mape]))
        scheduler.step(combined_val_mape)

        history.append(
            {
                "epoch": float(epoch),
                "train_loss": float(np.mean(train_losses)),
                "demand_val_mape": demand_val_mape,
                "generation_val_mape": generation_val_mape,
                "val_mape": combined_val_mape,
            }
        )
        log.info("train_energy_forecast.epoch", **history[-1])

        if combined_val_mape < best_val_mape - 1e-4:
            best_val_mape = combined_val_mape
            # `.cpu()` -- see `ml/train.py`'s identical `best_state` line
            # for why (the checkpoint's later load sites all assume CPU).
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= config.early_stopping_patience:
                log.info("train_energy_forecast.early_stop", epoch=epoch, best_val_mape=best_val_mape)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    test_metrics: dict[str, float] = {}
    if test_loader is not None:
        demand_true, demand_p50, gen_true, gen_p50 = _predict(model, test_loader, device)
        demand_true_mw = _inverse(demand_scaler, demand_true)
        demand_p50_mw = _inverse(demand_scaler, demand_p50)
        gen_true_mw = _inverse(generation_scaler, gen_true)
        gen_p50_mw = _inverse(generation_scaler, gen_p50)
        # `generation_test_mape` inherits `mape()`'s zero-target masking
        # (`ml/train.py`'s own docstring: written for demand, where a
        # zero interval is never real). That assumption doesn't hold for
        # generation buckets -- zero coal in SA1, zero gas in TAS1/hydro-
        # dominant regions, etc. are real, common rows, not a
        # data-quality gap -- so this metric implicitly excludes exactly
        # those legitimately-zero rows rather than scoring them. A
        # generation-specific metric (e.g. MAE as a fraction of
        # total_generation_mw) would be more honest; not built this
        # pass, flagged here instead of silently trusted.
        test_metrics = {
            "demand_test_mape": mape(demand_p50_mw, demand_true_mw),
            "demand_test_rmse": rmse(demand_p50_mw, demand_true_mw),
            "demand_test_mae": mae(demand_p50_mw, demand_true_mw),
            "generation_test_mape": mape(gen_p50_mw.ravel(), gen_true_mw.ravel()),
        }

    return EnergyTrainResult(
        model=model,
        feature_scalers=scalers,
        demand_scaler=demand_scaler,
        generation_scaler=generation_scaler,
        history=history,
        test_metrics=test_metrics,
        n_train_windows=len(train_ds),
        n_val_windows=len(val_ds),
        n_test_windows=len(test_ds),
    )


@dataclass
class TrainAndRegisterEnergyResult:
    run_id: str
    model_version: str | None
    test_metrics: dict[str, float]
    final_val_mape: float | None


def log_and_register_energy_run(
    result: EnergyTrainResult,
    config: EnergyTrainConfig,
    regions: Sequence[str],
    model_name: str,
    *,
    register: bool,
) -> TrainAndRegisterEnergyResult:
    """Same MLflow logging shape `ml/train.log_and_register_run` uses
    (params, per-epoch step-metrics, test metrics, model artifacts twice
    -- pyfunc for the registry, plain `state_dict` for `forecast-api`'s
    duplicated-class portability, `docs/training-strategy.md`'s
    documented Model Portability Strategy) -- see that function's own
    docstring for why both. Doesn't log a `conformal_calibration.json`
    artifact (module docstring: no calibration in this first pass)."""
    with mlflow.start_run() as run:
        mlflow.log_params(config.as_mlflow_params())
        mlflow.log_param("regions", ",".join(regions))
        mlflow.log_param("n_features", len(FEATURE_COLUMNS))
        mlflow.set_tags({"git_sha": git_sha() or "unknown", "architecture": "energy_forecast_lstm"})

        for epoch_metrics in result.history:
            mlflow.log_metrics(
                {
                    "train_loss": epoch_metrics["train_loss"],
                    "val_mape": epoch_metrics["val_mape"],
                    "demand_val_mape": epoch_metrics["demand_val_mape"],
                    "generation_val_mape": epoch_metrics["generation_val_mape"],
                },
                step=int(epoch_metrics["epoch"]),
            )
        if result.test_metrics:
            mlflow.log_metrics(result.test_metrics)
        mlflow.log_metrics(
            {
                "n_train_windows": result.n_train_windows,
                "n_val_windows": result.n_val_windows,
                "n_test_windows": result.n_test_windows,
            }
        )
        # Back to CPU before anything below persists it -- see
        # `ml/train.py`'s `log_and_register_run`'s identical line for why
        # (training may have used `ml/device.py`'s CUDA/MPS pick; every
        # load site for these artifacts assumes CPU).
        result.model.to("cpu")
        model_size_bytes = state_dict_bytes(result.model)
        mlflow.log_metrics({"model_size_bytes": model_size_bytes, "model_size_gb": model_size_bytes / 1_000_000_000})

        mlflow.pytorch.log_model(result.model, artifact_path="model", serialization_format="pickle")

        with tempfile.TemporaryDirectory() as tmpdir:
            joblib.dump(result.feature_scalers, Path(tmpdir) / "feature_scalers.joblib")
            joblib.dump(result.demand_scaler, Path(tmpdir) / "demand_scaler.joblib")
            joblib.dump(result.generation_scaler, Path(tmpdir) / "generation_scaler.joblib")
            torch.save(result.model.state_dict(), Path(tmpdir) / "model_state_dict.pt")
            mlflow.log_artifacts(tmpdir, artifact_path="serving")

        run_id = run.info.run_id

    model_version = None
    if register:
        version = register_model(run_id, model_name)
        model_version = version.version

    final_val_mape = result.history[-1]["val_mape"] if result.history else None
    return TrainAndRegisterEnergyResult(
        run_id=run_id,
        model_version=model_version,
        test_metrics=result.test_metrics,
        final_val_mape=final_val_mape,
    )


async def train_and_register_energy_forecast(
    regions: Sequence[str],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    settings: Settings | None = None,
    config: EnergyTrainConfig | None = None,
    register: bool = True,
    since: pd.Timestamp | None = None,
) -> TrainAndRegisterEnergyResult:
    """The real, DB + MLflow-backed entrypoint -- `cli.py`'s
    `train-energy-forecast` command calls this, mirroring `ml/train.
    train_and_register`'s shape exactly (including the `since` scoping
    it documents for the same reason: real per-column history depth
    varies, and an unscoped chronological split can starve train/val of
    the columns that only have recent real data)."""
    settings = settings or get_settings()
    config = config or EnergyTrainConfig.from_settings(settings)
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_energy_training_data(db, regions, since=since)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(f"no training data found in fct_energy_demand for regions={list(regions)}")

    result = train_energy_model(raw_df, config, holidays=holidays_df)
    return log_and_register_energy_run(result, config, regions, model_name, register=register)
