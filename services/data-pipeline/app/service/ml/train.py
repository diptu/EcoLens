"""Assembles `ml/data.py` + `ml/features.py` + `ml/model.py` +
`ml/losses.py` + `ml/conformal.py` into an actual training run, and logs
it to MLflow (`README.md` § MLflow, `TODO.md`'s Forecasting section item
2/3).

Two entrypoints:

- `train_model` — the pure, DB/MLflow-free training loop. Takes an
  already-fetched long-form `DataFrame` (`ml/data.py`'s
  `load_training_data` shape) in, returns a `TrainResult` out. Unit-
  tested directly with synthetic data (`tests/test_train.py`) — no
  Postgres, no MLflow server needed to verify the training mechanics
  themselves are correct.
- `train_and_register` — the real orchestration: queries the warehouse,
  calls `train_model`, logs everything to MLflow, and (by default)
  registers the result as a new model version. This is what `ecolens-
  pipeline train` (`cli.py`) and `pipeline.flows.daily_demand`
  (`README.md`'s Prefect example) actually call.

**Simplifications versus `README.md`'s fuller vision**, stated here rather
than left implicit: trains with plain PyTorch (`torch.optim`), not
PyTorch Lightning — the training loop below is straightforward enough
(single model, single GPU-optional device, no distributed training) that
Lightning's abstraction isn't pulling its weight as a new dependency.
`make tune` (`TODO.md` item) does a small grid search, not Optuna, for
the same reason. The training set is snapshotted in-process (one
`pandas.DataFrame` in memory), not materialized to a Parquet file on S3 —
`README.md`'s "never trains on a live Postgres connection" property still
holds (`load_training_data` is one read, then everything downstream is
in-memory), just without the separate artifact-store hop.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import mlflow
import mlflow.pytorch
import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.service.ml.conformal import (
    ConformalCalibration,
    empirical_coverage,
    fit_conformal,
)
from app.service.ml.data import (
    DemandDataset,
    apply_scalers,
    collate,
    fit_scalers,
    load_holidays,
    load_training_data,
    split_by_time,
)
from app.service.ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_features
from app.service.ml.losses import demand_loss
from app.models.ml import DemandLSTM
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class TrainConfig:
    lookback: int = 48
    horizon: int = 48
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.2
    lr: float = 1e-3
    epochs: int = 50
    batch_size: int = 64
    quantile_weight: float = 1.0
    conformal_alpha: float = 0.2
    # Fraction of the (chronologically later) validation split reserved
    # for conformal calibration rather than early-stopping -- these must
    # be disjoint samples: calibrating on the same data early-stopping
    # already picked the best epoch against would let that epoch-
    # selection signal leak into the coverage guarantee.
    cal_frac: float = 0.5
    early_stopping_patience: int = 5
    train_frac: float = 0.7
    val_frac: float = 0.15

    @classmethod
    def from_settings(cls, settings: Settings) -> TrainConfig:
        return cls(
            lookback=settings.model_lookback,
            horizon=settings.model_horizon,
            hidden_size=settings.model_hidden_size,
            num_layers=settings.model_num_layers,
            dropout=settings.model_dropout,
            lr=settings.model_train_lr,
            epochs=settings.model_train_epochs,
            batch_size=settings.model_batch_size,
            quantile_weight=settings.model_quantile_weight,
            conformal_alpha=settings.conformal_alpha,
            cal_frac=settings.model_cal_frac,
            early_stopping_patience=settings.model_early_stopping_patience,
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
            "quantile_weight": self.quantile_weight,
            "conformal_alpha": self.conformal_alpha,
            "cal_frac": self.cal_frac,
            "early_stopping_patience": self.early_stopping_patience,
            "train_frac": self.train_frac,
            "val_frac": self.val_frac,
        }


@dataclass
class TrainResult:
    model: DemandLSTM
    calibration: ConformalCalibration
    feature_scalers: dict[str, StandardScaler]
    target_scaler: StandardScaler
    history: list[dict[str, float]] = field(default_factory=list)
    test_metrics: dict[str, float] = field(default_factory=dict)
    n_train_windows: int = 0
    n_val_windows: int = 0
    n_cal_windows: int = 0
    n_test_windows: int = 0


def mape(pred: np.ndarray, target: np.ndarray) -> float:
    """Mean absolute percentage error, in percent. Rows where `target==0`
    are excluded (a zero-demand interval is never real for this domain,
    but dividing by it would be undefined) rather than silently producing
    `inf`/`nan`."""
    mask = target != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((target[mask] - pred[mask]) / target[mask])) * 100)


def _fit_target_scaler(
    train: pd.DataFrame, target_col: str = TARGET_COLUMN
) -> StandardScaler:
    """One scaler across every region combined (not `ml.data.fit_scalers`'
    per-region scalers) — simpler, and avoids needing to track which
    region each `DemandDataset` window came from just to pick the right
    inverse-transform later. A documented simplification for `TODO.md`'s
    v0 (single-region training, per `README.md`'s Roadmap) — precise
    enough there; a genuinely multi-region model would want this
    per-region like the feature scalers."""
    scaler = StandardScaler()
    scaler.fit(train[[target_col]].dropna().to_numpy())
    return scaler


def _scale_target(
    df: pd.DataFrame, scaler: StandardScaler, target_col: str = TARGET_COLUMN
) -> pd.DataFrame:
    out = df.copy()
    mask = out[target_col].notna()
    out.loc[mask, target_col] = scaler.transform(
        out.loc[mask, [target_col]].to_numpy()
    ).ravel()
    return out


def _inverse_target(scaler: StandardScaler, values: np.ndarray) -> np.ndarray:
    shape = values.shape
    return scaler.inverse_transform(values.reshape(-1, 1)).reshape(shape)


def _split_val_for_calibration(
    val: pd.DataFrame, cal_frac: float, ts_col: str = "ts"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronologically split `val` into `(earlystop_val, calibration)` —
    the later `cal_frac` fraction becomes the calibration set. Not
    `ml.data.split_by_time` (that returns a 3-way train/val/test split;
    this needs a 2-way split of an already-carved-out validation set)."""
    unique_ts = np.sort(val[ts_col].unique())
    n = len(unique_ts)
    if n < 2:
        return val, val.iloc[0:0]
    boundary_idx = max(0, int(n * (1 - cal_frac)) - 1)
    boundary = unique_ts[boundary_idx]
    return val[val[ts_col] <= boundary], val[val[ts_col] > boundary]


def _predict(
    model: DemandLSTM, loader: DataLoader
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`(y_true, p10, p50, p90)`, each concatenated across every batch in
    `loader`, shape `(n_samples, horizon)`."""
    model.eval()
    ys, p10s, p50s, p90s = [], [], [], []
    with torch.no_grad():
        for x, y in loader:
            out = model(x)
            ys.append(y.numpy())
            p10s.append(out.p10.numpy())
            p50s.append(out.p50.numpy())
            p90s.append(out.p90.numpy())
    return (
        np.concatenate(ys),
        np.concatenate(p10s),
        np.concatenate(p50s),
        np.concatenate(p90s),
    )


def train_model(
    raw_df: pd.DataFrame,
    config: TrainConfig,
    *,
    holidays: pd.DataFrame | None = None,
    warm_start_state_dict: dict[str, torch.Tensor] | None = None,
) -> TrainResult:
    """`raw_df`: `ml/data.py`'s `load_training_data` shape (long-form, one
    row per `(ts, region)`, `TARGET_COLUMN` + the raw context columns
    `ml/features.py` expects). Raises `ValueError` if there isn't enough
    history to build at least one window in each of train/val/calibration
    — a 404-shaped problem, not something to silently train on zero
    samples and report a meaningless metric for.

    `warm_start_state_dict`, if given, is loaded into the freshly
    constructed `DemandLSTM` before training starts, instead of leaving it
    randomly initialized — `ml/incremental.py`'s warm-started fine-tune
    path (`TODO.md`'s Event-Driven Pipeline Trigger item 3), as opposed to
    `train_and_register`'s always-from-scratch batch retrain. The caller
    is responsible for making sure `config`'s architecture fields
    (`hidden_size`/`num_layers`/`dropout`/`horizon`) match whatever
    produced the state dict — a mismatch surfaces as `load_state_dict`
    raising a shape error, not a silent no-op.
    """
    engineered = build_features(raw_df, holidays=holidays)
    split = split_by_time(
        engineered, train_frac=config.train_frac, val_frac=config.val_frac
    )
    earlystop_val, cal = _split_val_for_calibration(split.val, config.cal_frac)

    # Checked before fitting anything: an empty split makes
    # `StandardScaler.fit`/`DemandDataset` raise their own, less useful
    # errors first otherwise.
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

    # `demand_mw` itself (the target `DemandDataset` windows into `y`) is
    # deliberately *not* one of `fit_scalers`' `NUMERIC_COLUMNS` -- it's
    # the thing being predicted, not an input feature. But leaving it
    # raw-MW-scale (thousands) makes Huber/pinball loss converge
    # pathologically slowly: both losses' gradient w.r.t. the prediction
    # saturates at a constant magnitude once the error exceeds `delta`
    # (by design, for robustness), and Adam's per-step parameter movement
    # is roughly `lr`-sized regardless of gradient magnitude -- closing a
    # multi-thousand-MW initial gap would take on the order of
    # `gap / lr` steps. Scaling the target into the same well-conditioned
    # range as the (already-scaled) lag/rolling features fixes this the
    # standard way; predictions are inverse-transformed back to MW before
    # any metric, calibration, or serving code ever sees them.
    target_scaler = _fit_target_scaler(split.train)
    train_scaled = _scale_target(train_scaled, target_scaler)
    val_scaled = _scale_target(val_scaled, target_scaler)
    cal_scaled = _scale_target(cal_scaled, target_scaler)
    test_scaled = _scale_target(test_scaled, target_scaler)

    train_ds = DemandDataset(
        train_scaled, lookback=config.lookback, horizon=config.horizon
    )
    val_ds = DemandDataset(val_scaled, lookback=config.lookback, horizon=config.horizon)
    cal_ds = DemandDataset(cal_scaled, lookback=config.lookback, horizon=config.horizon)
    test_ds = DemandDataset(
        test_scaled, lookback=config.lookback, horizon=config.horizon
    )

    if len(train_ds) == 0 or len(val_ds) == 0 or len(cal_ds) == 0:
        raise ValueError(
            "not enough history to build train/val/calibration windows "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(train_ds)}/{len(val_ds)}/{len(cal_ds)} windows"
        )

    train_loader = DataLoader(
        train_ds, batch_size=config.batch_size, shuffle=True, collate_fn=collate
    )
    val_loader = DataLoader(
        val_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate
    )
    cal_loader = DataLoader(
        cal_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate
    )
    test_loader = (
        DataLoader(
            test_ds, batch_size=config.batch_size, shuffle=False, collate_fn=collate
        )
        if len(test_ds) > 0
        else None
    )

    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS),
        horizon=config.horizon,
        hidden_size=config.hidden_size,
        num_layers=config.num_layers,
        dropout=config.dropout,
    )
    if warm_start_state_dict is not None:
        model.load_state_dict(warm_start_state_dict)
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
        for x, y in train_loader:
            optimizer.zero_grad()
            out = model(x)
            loss = demand_loss(out, y, quantile_weight=config.quantile_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_losses.append(loss.item())

        y_val, _, p50_val, _ = _predict(model, val_loader)
        val_mape = mape(
            _inverse_target(target_scaler, p50_val),
            _inverse_target(target_scaler, y_val),
        )
        scheduler.step(val_mape)

        history.append(
            {
                "epoch": float(epoch),
                "train_loss": float(np.mean(train_losses)),
                "val_mape": val_mape,
            }
        )
        log.info(
            "train.epoch",
            epoch=epoch,
            train_loss=history[-1]["train_loss"],
            val_mape=val_mape,
        )

        if val_mape < best_val_mape - 1e-4:
            best_val_mape = val_mape
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= config.early_stopping_patience:
                log.info("train.early_stop", epoch=epoch, best_val_mape=best_val_mape)
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    # Every prediction/target from here on is inverse-transformed back to
    # real MW immediately after `_predict` -- calibration, coverage, and
    # MAPE all need to operate (and be reported) in the units
    # `README.md`'s forecast API actually returns, not the model's
    # internal scaled training space.
    y_cal, p10_cal, _, p90_cal = _predict(model, cal_loader)
    y_cal = _inverse_target(target_scaler, y_cal)
    p10_cal = _inverse_target(target_scaler, p10_cal)
    p90_cal = _inverse_target(target_scaler, p90_cal)
    calibration = fit_conformal(y_cal, p10_cal, p90_cal, alpha=config.conformal_alpha)

    test_metrics: dict[str, float] = {}
    if test_loader is not None:
        y_test, p10_test, p50_test, p90_test = _predict(model, test_loader)
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


@dataclass
class TrainAndRegisterResult:
    run_id: str
    model_version: str | None
    test_metrics: dict[str, float]
    final_val_mape: float | None


def log_and_register_run(
    result: TrainResult,
    config: TrainConfig,
    regions: Sequence[str],
    model_name: str,
    *,
    register: bool,
    extra_tags: dict[str, str] | None = None,
) -> TrainAndRegisterResult:
    """Logs one training run to MLflow (params/per-epoch metrics/test
    metrics/conformal calibration/model artifacts) and, if `register`,
    registers it as a new `model_name` version in the `None` stage.
    Shared by `train_and_register` (full retrain) and `ml.incremental`'s
    `train_and_register_incremental` (warm-started fine-tune) — *what*
    gets logged is identical between the two; only `extra_tags`
    (`training_type`/`warm_start_run_id` for the incremental path)
    differs. Promoting to `Production`/`Staging` is a separate,
    deliberately-gated step (`scripts/promote_model.sh`) for either path,
    not automatic here.
    """
    with mlflow.start_run() as run:
        mlflow.log_params(config.as_mlflow_params())
        mlflow.log_param("regions", ",".join(regions))
        mlflow.log_param("n_features", len(FEATURE_COLUMNS))
        tags = {"git_sha": git_sha() or "unknown", "target_column": TARGET_COLUMN}
        tags.update(extra_tags or {})
        mlflow.set_tags(tags)

        for epoch_metrics in result.history:
            mlflow.log_metrics(
                {
                    "train_loss": epoch_metrics["train_loss"],
                    "val_mape": epoch_metrics["val_mape"],
                },
                step=int(epoch_metrics["epoch"]),
            )
        if result.test_metrics:
            mlflow.log_metrics(result.test_metrics)
        mlflow.log_metrics(
            {
                "n_train_windows": result.n_train_windows,
                "n_val_windows": result.n_val_windows,
                "n_cal_windows": result.n_cal_windows,
                "n_test_windows": result.n_test_windows,
            }
        )
        mlflow.log_dict(result.calibration.to_dict(), "conformal_calibration.json")

        # Logged twice, deliberately, for two different consumers:
        #
        # 1. `mlflow.pytorch.log_model` -- MLflow-native (registry/pyfunc/
        #    UI "load model" support). Its pickle needs `app.models.ml.
        #    DemandLSTM` importable wherever it's unpickled, which is fine
        #    *inside this package* but not a safe assumption for
        #    `forecast-api` -- a separate service/package (see 2 below).
        # 2. A plain `state_dict` (`docs/training-strategy.md`'s own
        #    documented "Model Portability Strategy": `torch.save(model.
        #    state_dict())` / `map_location=torch.device('cpu')` on load)
        #    plus the architecture hyperparams already logged as run
        #    params above (`hidden_size`/`num_layers`/`dropout`/`horizon`/
        #    `n_features`). `forecast-api` reconstructs `DemandLSTM` from
        #    its own (intentionally duplicated, see that service's
        #    `ml/model.py`) copy of the class and loads these weights into
        #    it -- no dependency on this package's pickle, no requirement
        #    that `forecast-api`'s venv have `data-pipeline` installed.
        #    `ml.incremental`'s warm-start loader reads this same
        #    `serving/model_state_dict.pt` artifact back off a previous
        #    run to fine-tune from, for the identical reason.
        #
        # `serialization_format="pickle"` (MLflow's traditional format)
        # instead of the newer default `"pt2"`: `pt2` traces the model
        # graph by actually running `model.forward(input_example)`, which
        # means it *requires* a real `input_example` be supplied or
        # logging raises -- unnecessary ceremony for an artifact whose
        # only real job is giving `mlflow.register_model` something with
        # an `MLmodel` file to register from (2 above is what's actually
        # used for serving).
        mlflow.pytorch.log_model(
            result.model, artifact_path="model", serialization_format="pickle"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            joblib.dump(result.feature_scalers, Path(tmpdir) / "feature_scalers.joblib")
            joblib.dump(result.target_scaler, Path(tmpdir) / "target_scaler.joblib")
            torch.save(result.model.state_dict(), Path(tmpdir) / "model_state_dict.pt")
            mlflow.log_artifacts(tmpdir, artifact_path="serving")

        run_id = run.info.run_id

    model_version = None
    if register:
        version = register_model(run_id, model_name)
        model_version = version.version

    final_val_mape = result.history[-1]["val_mape"] if result.history else None
    return TrainAndRegisterResult(
        run_id=run_id,
        model_version=model_version,
        test_metrics=result.test_metrics,
        final_val_mape=final_val_mape,
    )


async def train_and_register(
    model_name: str,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    config: TrainConfig | None = None,
    register: bool = True,
) -> TrainAndRegisterResult:
    """The real, DB + MLflow-backed entrypoint — `cli.py`'s `train`
    command and `pipeline.flows.daily_demand` (`README.md`'s Prefect
    example) both call this. `register=True` (the default) registers the
    trained model as a new `model_name` version in the `None` stage —
    promoting it to `Production` is a separate, deliberately-gated step
    (`scripts/promote_model.sh`), not automatic here.
    """
    settings = settings or get_settings()
    config = config or TrainConfig.from_settings(settings)
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in the warehouse for regions={list(regions)}"
        )

    result = train_model(raw_df, config, holidays=holidays_df)
    return log_and_register_run(result, config, regions, model_name, register=register)
