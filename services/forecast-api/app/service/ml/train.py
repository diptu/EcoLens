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
from collections.abc import Callable, Sequence
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
from torch import nn
from torch.utils.data import ConcatDataset, DataLoader

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
    load_ml_features_v1_imputed_fraction,
    load_ml_features_v1_training_data,
    load_training_data,
    split_by_date,
    split_by_time,
)
from app.service.ml.demand_data_offline import (
    load_demand_training_data_from_master,
    load_holidays_from_master,
)
from app.service.ml.device import get_device
from app.service.ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_features
from app.service.ml.losses import demand_loss
from app.models.ml import DemandLSTM
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class TrainConfig:
    # Literal defaults kept in sync with `Settings`' own (both changed
    # together, `app/core/config.py`'s own comments have the full
    # rationale) -- a real training run always goes through
    # `from_settings()` below, which reads `Settings` directly regardless
    # of what's written here, but a stale-looking literal default here
    # once caused real confusion about what a training run actually uses
    # (this dataclass said 0.2/48/48, `Settings` said 0.5/48/48 -- only
    # the latter was real). Not worth repeating.
    lookback: int = 24
    horizon: int = 48
    hidden_size: int = 128
    num_layers: int = 2
    dropout: float = 0.25
    weight_decay: float = 1e-5
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
    # 49/49/2 (2026-08-09, changed from 60/20/20) -- real, measured
    # constraint, not a style preference: NEM regions only have ~300 real
    # hourly rows (~14 days incl. gaps) each. At `horizon=48`, `cal_frac`
    # halves whatever `val_frac` allocates (see `_split_val_for_
    # calibration`), so the old 20% val share only gave each of
    # earlystop-val/cal a ~30-row slice -- less than `horizon` itself, so
    # 0 real windows for every NEM region regardless of `lookback`
    # (confirmed empirically against the real windowing code, not
    # assumed: `got 336/0/0 windows` on a real training run). 49/49 gives
    # earlystop-val/cal each a ~73-row slice (49% * 0.5 of ~300),
    # comfortably above `horizon=48`, and empirically yields real
    # non-trivial window counts per NEM region (~64 train / ~26 val / ~27
    # cal); `train`'s own 49% share (~147 rows) still comfortably clears
    # `lookback+horizon=72`. `test` shrinks to ~2% (often 0 rows) --
    # accepted: `test_loader`/`test_mape` are already fully optional
    # (`registry.py`'s `promote_version` docstring: "neither gate blocks
    # if its signal is simply absent"), unlike train/val/cal, which
    # `train_model` requires non-empty. `val`/`cal` were the two splits
    # data volume was actually starving here.
    train_frac: float = 0.49
    val_frac: float = 0.49

    # Explicit calendar-boundary split, as an alternative to
    # `train_frac`/`val_frac` above -- when `train_start` is set (the
    # other five must then be set too), `train_model` uses
    # `ml/data.py`'s `split_by_date` instead of `split_by_time`/fractions,
    # per-region, and also caps the test split's upper bound at
    # `test_end` (the frac-based path leaves test open-ended: "everything
    # after val_end"). All `None` (the default) preserves the fraction-
    # based behavior above untouched.
    train_start: pd.Timestamp | None = None
    train_end: pd.Timestamp | None = None
    val_start: pd.Timestamp | None = None
    val_end: pd.Timestamp | None = None
    test_start: pd.Timestamp | None = None
    test_end: pd.Timestamp | None = None

    # `False` disables `train_loader`'s per-epoch reshuffling -- windows
    # are then presented in the same region-grouped, chronological order
    # `ConcatDataset`/`DemandDataset` build them in, every epoch. `True`
    # (the default) matches every prior training run on this model.
    shuffle: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        # `Self`, not `TrainConfig` -- `TFTTrainConfig` (`train_tft.py`)
        # subclasses this and relies on `TFTTrainConfig.from_settings(...)`
        # actually returning a `TFTTrainConfig` (with its own `n_heads`
        # default intact), not a plain `TrainConfig` upcast.
        return cls(
            # Dedicated demand-model fields, not the shared
            # `model_lookback`/`model_horizon` `EnergyTrainConfig` also
            # reads (see `Settings.model_demand_lookback`'s own comment
            # for why these are separate).
            lookback=settings.model_demand_lookback,
            horizon=settings.model_demand_horizon,
            hidden_size=settings.model_hidden_size,
            num_layers=settings.model_num_layers,
            dropout=settings.model_dropout,
            weight_decay=settings.model_weight_decay,
            lr=settings.model_train_lr,
            epochs=settings.model_train_epochs,
            batch_size=settings.model_batch_size,
            quantile_weight=settings.model_quantile_weight,
            conformal_alpha=settings.conformal_alpha,
            cal_frac=settings.model_cal_frac,
            early_stopping_patience=settings.model_early_stopping_patience,
        )

    def as_mlflow_params(self) -> dict[str, object]:
        params: dict[str, object] = {
            "lookback": self.lookback,
            "horizon": self.horizon,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "weight_decay": self.weight_decay,
            "lr": self.lr,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "quantile_weight": self.quantile_weight,
            "conformal_alpha": self.conformal_alpha,
            "cal_frac": self.cal_frac,
            "early_stopping_patience": self.early_stopping_patience,
            "train_frac": self.train_frac,
            "val_frac": self.val_frac,
            "shuffle": self.shuffle,
        }
        if self.train_start is not None:
            params.update(
                {
                    "train_start": self.train_start.isoformat(),
                    "train_end": self.train_end.isoformat(),
                    "val_start": self.val_start.isoformat(),
                    "val_end": self.val_end.isoformat(),
                    "test_start": self.test_start.isoformat(),
                    "test_end": self.test_end.isoformat(),
                }
            )
        return params


@dataclass
class TrainResult:
    # `nn.Module`, not `DemandLSTM` -- `log_and_register_run` only ever
    # treats `model` as a generic torch module (`mlflow.pytorch.log_model`
    # + `.state_dict()`), so this is genuinely architecture-agnostic and
    # is reused as-is by `train_tft.py` (`todo-model-training.md` Phase
    # 2) for `DemandTFT`, not just `DemandLSTM`.
    model: nn.Module
    calibration: ConformalCalibration
    feature_scalers: dict[str, StandardScaler]
    target_scaler: StandardScaler
    history: list[dict[str, float]] = field(default_factory=list)
    test_metrics: dict[str, float] = field(default_factory=dict)
    n_train_windows: int = 0
    n_val_windows: int = 0
    n_cal_windows: int = 0
    n_test_windows: int = 0


def state_dict_bytes(model: nn.Module) -> int:
    """Real on-disk size of `torch.save(model.state_dict())` -- the exact
    artifact `log_and_register_run` persists as `serving/model_state_dict.pt`
    and what `forecast-api` actually loads at serving time, not a
    parameter-count estimate. Same measurement approach as `ml/prune.py`'s
    `_artifact_bytes` (kept separate rather than imported -- that one is a
    private, pruning-specific helper; this is the general-purpose version
    every training run logs)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "model_state_dict.pt"
        torch.save(model.state_dict(), path)
        return path.stat().st_size


def mape(pred: np.ndarray, target: np.ndarray) -> float:
    """Mean absolute percentage error, in percent. Rows where `target==0`
    are excluded (a zero-demand interval is never real for this domain,
    but dividing by it would be undefined) rather than silently producing
    `inf`/`nan`."""
    mask = target != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((target[mask] - pred[mask]) / target[mask])) * 100)


def rmse(pred: np.ndarray, target: np.ndarray) -> float:
    """Root mean square error, in the same real units as `pred`/`target`
    (MW, once called on inverse-scaled values -- same convention `mape`
    above already uses). No zero-target masking needed here (unlike
    `mape`, this never divides by `target`)."""
    return float(np.sqrt(np.mean((pred - target) ** 2)))


def mae(pred: np.ndarray, target: np.ndarray) -> float:
    """Mean absolute error, in the same real units as `pred`/`target`
    (MW). Same no-masking reasoning as `rmse`."""
    return float(np.mean(np.abs(pred - target)))


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
    model: DemandLSTM, loader: DataLoader, device: torch.device
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`(y_true, p10, p50, p90)`, each concatenated across every batch in
    `loader`, shape `(n_samples, horizon)`."""
    model.eval()
    ys, p10s, p50s, p90s = [], [], [], []
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            out = model(x)
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


def _compute_val_loss(
    model: DemandLSTM, loader: DataLoader, quantile_weight: float, device: torch.device
) -> float:
    """Real validation loss -- the exact same `demand_loss` (Huber P50 +
    weighted pinball P10/P90, on *scaled* targets) the training loop
    itself minimizes, just eval-mode/no-grad and on the validation
    split. Deliberately distinct from `val_mape` (an inverse-scaled-MW
    percentage-error metric computed from P50 alone, not a loss) --
    plotting `val_mape` next to `train_loss` on one "training vs
    validation loss" chart would silently compare two different units
    on one axis. Both get logged; this is what makes that comparison
    genuinely apples-to-apples."""
    model.eval()
    losses = []
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            out = model(x)
            loss = demand_loss(out, y, quantile_weight=quantile_weight)
            losses.append(loss.item())
    return float(np.mean(losses))


def train_model(
    raw_df: pd.DataFrame,
    config: TrainConfig,
    *,
    holidays: pd.DataFrame | None = None,
    warm_start_state_dict: dict[str, torch.Tensor] | None = None,
    epoch_callback: Callable[[int, dict[str, float]], None] | None = None,
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

    `epoch_callback`, if given, is invoked after every epoch's history
    entry is appended, as `epoch_callback(epoch, history[-1])`. Deliberately
    generic (not an Optuna-specific parameter) so this module stays free of
    a hard `optuna` import — `ml/tune.py`'s `tune_optuna` is the one real
    caller today, wrapping it to call `trial.report(...)` and raise
    `optuna.TrialPruned()` for real mid-training pruning of bad
    hyperparameter trials; any exception raised by the callback propagates
    out of `train_model` uncaught, aborting the run.
    """
    engineered = build_features(raw_df, holidays=holidays)

    # Per-region split boundaries (2026-08-09), not one global boundary --
    # a single `split_by_time(engineered, ...)` call computes its boundary
    # from the *union* of every region's timestamps, which real, measured
    # data showed silently starves whichever region has the shortest real
    # history (NEM regions here: only ~14 days, versus WEM's ~44) even at
    # a small horizon, because the global boundary lands wherever the
    # *longer*-history region's density dominates, not where each region's
    # own data actually is. Splitting each region against its own
    # timestamps first, then combining, is what actually gives every
    # region a fair, real split of its own history.
    use_date_split = config.train_start is not None
    per_region_split: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    for region, region_df in engineered.groupby("region"):
        if use_date_split:
            region_split = split_by_date(
                region_df,
                train_start=config.train_start,
                train_end=config.train_end,
                val_start=config.val_start,
                val_end=config.val_end,
                test_start=config.test_start,
                test_end=config.test_end,
            )
        else:
            region_split = split_by_time(
                region_df, train_frac=config.train_frac, val_frac=config.val_frac
            )
        region_earlystop_val, region_cal = _split_val_for_calibration(
            region_split.val, config.cal_frac
        )
        per_region_split[region] = (region_split.train, region_earlystop_val, region_cal)

    split_train = pd.concat([t for t, _, _ in per_region_split.values()])
    earlystop_val = pd.concat([v for _, v, _ in per_region_split.values()])
    cal = pd.concat([c for _, _, c in per_region_split.values()])

    # Checked before fitting anything: an empty split makes
    # `StandardScaler.fit`/`DemandDataset` raise their own, less useful
    # errors first otherwise.
    if split_train.empty or earlystop_val.empty or cal.empty:
        raise ValueError(
            "not enough history to build train/val/calibration splits "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(split_train)}/{len(earlystop_val)}/{len(cal)} rows"
        )

    scalers = fit_scalers(split_train)
    # `DemandDataset.min_target_ts`'s own docstring has the full rationale
    # (2026-08-09): with only ~14 days of live NEM history, a strictly
    # train-disjoint val/cal slice doesn't fit even a modest window.
    # Scalers/target_scaler are still fit on `split_train` only (no
    # leakage of distribution statistics into val/test), but *windowing*
    # now runs against the full history so val/cal/test windows' lookback
    # context can reach back across the split boundary -- only each
    # window's *target* is gated to its own split below (per-region, via
    # `min_target_ts`), so no held-out label is ever also a train label.
    full_scaled = apply_scalers(engineered, scalers)

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
    target_scaler = _fit_target_scaler(split_train)
    full_scaled = _scale_target(full_scaled, target_scaler)

    # Build one `DemandDataset` per region per split, using that region's
    # OWN boundaries (recovered the same way as the prior single-region
    # implementation: the max `ts` actually present in each of that
    # region's own split rows), then concatenate across regions --
    # `DemandDataset` already refuses to build a window spanning two
    # regions, but that guarantee only holds if it's never handed two
    # regions' rows with two DIFFERENT real boundaries conflated into one
    # `min_target_ts` in the first place.
    train_parts, val_parts, cal_parts, test_parts = [], [], [], []
    region_window_counts: dict[str, tuple[int, int, int]] = {}
    for region, (region_train, region_earlystop_val, region_cal) in per_region_split.items():
        if region_train.empty or region_earlystop_val.empty or region_cal.empty:
            log.warning(
                "train_model.region_split_empty",
                region=region,
                n_train=len(region_train),
                n_earlystop_val=len(region_earlystop_val),
                n_cal=len(region_cal),
            )
            region_window_counts[region] = (0, 0, 0)
            continue

        region_full = full_scaled[full_scaled["region"] == region]
        region_train_end = region_train["ts"].max()
        region_val_end = pd.concat([region_earlystop_val, region_cal])["ts"].max()
        region_cal_boundary = region_earlystop_val["ts"].max()

        region_train_ds = DemandDataset(
            region_full[region_full["ts"] <= region_train_end],
            lookback=config.lookback,
            horizon=config.horizon,
        )
        region_val_ds = DemandDataset(
            region_full[region_full["ts"] <= region_cal_boundary],
            lookback=config.lookback,
            horizon=config.horizon,
            min_target_ts=region_train_end,
        )
        region_cal_ds = DemandDataset(
            region_full[region_full["ts"] <= region_val_end],
            lookback=config.lookback,
            horizon=config.horizon,
            min_target_ts=region_cal_boundary,
        )
        region_test_input = (
            region_full[region_full["ts"] <= config.test_end]
            if use_date_split
            else region_full
        )
        region_test_ds = DemandDataset(
            region_test_input,
            lookback=config.lookback,
            horizon=config.horizon,
            min_target_ts=region_val_end,
        )
        region_window_counts[region] = (
            len(region_train_ds),
            len(region_val_ds),
            len(region_cal_ds),
        )
        train_parts.append(region_train_ds)
        val_parts.append(region_val_ds)
        cal_parts.append(region_cal_ds)
        test_parts.append(region_test_ds)

    log.info("train_model.region_window_counts", counts=region_window_counts)

    train_ds: ConcatDataset[tuple[torch.Tensor, torch.Tensor]] = ConcatDataset(train_parts)
    val_ds: ConcatDataset[tuple[torch.Tensor, torch.Tensor]] = ConcatDataset(val_parts)
    cal_ds: ConcatDataset[tuple[torch.Tensor, torch.Tensor]] = ConcatDataset(cal_parts)
    test_ds: ConcatDataset[tuple[torch.Tensor, torch.Tensor]] = ConcatDataset(test_parts)

    if len(train_ds) == 0 or len(val_ds) == 0 or len(cal_ds) == 0:
        raise ValueError(
            "not enough history to build train/val/calibration windows "
            f"(lookback={config.lookback}, horizon={config.horizon}) -- "
            f"got {len(train_ds)}/{len(val_ds)}/{len(cal_ds)} windows "
            f"({region_window_counts})"
        )

    train_loader = DataLoader(
        train_ds, batch_size=config.batch_size, shuffle=config.shuffle, collate_fn=collate
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

    device = get_device()
    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS),
        horizon=config.horizon,
        hidden_size=config.hidden_size,
        num_layers=config.num_layers,
        dropout=config.dropout,
    )
    if warm_start_state_dict is not None:
        model.load_state_dict(warm_start_state_dict)
    model.to(device)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=config.lr, weight_decay=config.weight_decay
    )
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
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            out = model(x)
            loss = demand_loss(out, y, quantile_weight=config.quantile_weight)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_losses.append(loss.item())

        y_val, _, p50_val, _ = _predict(model, val_loader, device)
        y_val_mw = _inverse_target(target_scaler, y_val)
        p50_val_mw = _inverse_target(target_scaler, p50_val)
        val_mape = mape(p50_val_mw, y_val_mw)
        # Real MW-unit error metrics (2026-08-05, Performance page's
        # "validation RMSE & MAE" chart) -- computed on the same
        # inverse-scaled P50-vs-actual pair `val_mape` already uses, so
        # this is genuinely free (no extra forward pass), just two more
        # real numbers from data already in hand.
        val_rmse = rmse(p50_val_mw, y_val_mw)
        val_mae = mae(p50_val_mw, y_val_mw)
        val_loss = _compute_val_loss(model, val_loader, config.quantile_weight, device)
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
            "train.epoch",
            epoch=epoch,
            train_loss=history[-1]["train_loss"],
            val_loss=val_loss,
            val_mape=val_mape,
            val_rmse=val_rmse,
            val_mae=val_mae,
        )
        if epoch_callback is not None:
            epoch_callback(epoch, history[-1])

        if val_mape < best_val_mape - 1e-4:
            best_val_mape = val_mape
            # `.cpu()` -- so the checkpoint this ultimately becomes
            # (`torch.save`'d/MLflow-logged below, and `ml/incremental.py`'s
            # warm-start reload of it) never carries a hard dependency on
            # this run's training device actually being available wherever
            # it's next loaded (`docs/training-strategy.md`'s "Model
            # Portability Strategy" -- every load site already passes
            # `map_location=torch.device("cpu")`, so this just matches that
            # contract instead of relying on `torch.load` to paper over it).
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
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
    y_cal, p10_cal, _, p90_cal = _predict(model, cal_loader, device)
    y_cal = _inverse_target(target_scaler, y_cal)
    p10_cal = _inverse_target(target_scaler, p10_cal)
    p90_cal = _inverse_target(target_scaler, p90_cal)
    calibration = fit_conformal(y_cal, p10_cal, p90_cal, alpha=config.conformal_alpha)

    test_metrics: dict[str, float] = {}
    if test_loader is not None:
        y_test, p10_test, p50_test, p90_test = _predict(model, test_loader, device)
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
    extra_params: dict[str, object] | None = None,
) -> TrainAndRegisterResult:
    """Logs one training run to MLflow (params/per-epoch metrics/test
    metrics/conformal calibration/model artifacts) and, if `register`,
    registers it as a new `model_name` version in the `None` stage.
    Shared by `train_and_register` (full retrain), `ml.incremental`'s
    `train_and_register_incremental` (warm-started fine-tune), and
    `train_tft.py`'s TFT training path (`todo-model-training.md` Phase
    2) — *what* gets logged is architecture-agnostic (`result.model` is
    only ever treated as a generic `nn.Module`); `extra_tags`
    (`training_type`/`warm_start_run_id` for the incremental path,
    `architecture` for TFT) and `extra_params` (e.g. TFT's real
    `n_encoder_features`/`n_decoder_features`, which don't fit this
    function's own LSTM-shaped `n_features` param below) are how each
    caller supplies what's genuinely architecture-specific. Promoting to
    `Production`/`Staging` is a separate, deliberately-gated step
    (`scripts/promote_model.sh`) for any path, not automatic here.
    """
    with mlflow.start_run() as run:
        mlflow.log_params(config.as_mlflow_params())
        mlflow.log_param("regions", ",".join(regions))
        # `FEATURE_COLUMNS`' count -- accurate for `DemandLSTM` (one
        # homogeneous input window), a rough total for TFT (whose real
        # encoder/decoder feature counts differ and are logged
        # separately via `extra_params`), which is why this alone isn't
        # gated behind an architecture check: it's still meaningful
        # informational context either way, just not the full picture
        # for TFT on its own.
        mlflow.log_param("n_features", len(FEATURE_COLUMNS))
        if extra_params:
            mlflow.log_params(extra_params)
        tags = {"git_sha": git_sha() or "unknown", "target_column": TARGET_COLUMN}
        tags.update(extra_tags or {})
        mlflow.set_tags(tags)

        for epoch_metrics in result.history:
            step_metrics = {
                "train_loss": epoch_metrics["train_loss"],
                "val_mape": epoch_metrics["val_mape"],
            }
            # `.get()`/`in` checks, not `[...]` -- `val_loss` (2026-08-05,
            # "training vs validation loss" chart) and `val_rmse`/`val_mae`
            # (2026-08-05, "validation RMSE & MAE" chart), both real MW-
            # unit error metrics computed alongside `val_mape`, are only
            # present in `history` dicts built by the current
            # `train_model`/`train_tft_model`; a caller passing an
            # older-shaped `TrainResult` shouldn't crash logging the
            # metrics it does have.
            for key in ("val_loss", "val_rmse", "val_mae"):
                if key in epoch_metrics:
                    step_metrics[key] = epoch_metrics[key]
            mlflow.log_metrics(step_metrics, step=int(epoch_metrics["epoch"]))
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
        # Back to CPU before anything below persists it -- training may
        # have run on `ml/device.py`'s CUDA/MPS pick, but both artifacts
        # logged below (the MLflow-native pickle and the plain
        # `state_dict`) need to load on whatever's available wherever
        # they're next read, same "Model Portability Strategy" `best_state`
        # above already follows.
        result.model.to("cpu")
        # GB (10^9 bytes, the conventional storage-size unit), not GiB
        # (2^30) -- matches how cloud artifact stores/disks report size,
        # the audience this metric is actually for.
        model_size_bytes = state_dict_bytes(result.model)
        mlflow.log_metrics(
            {
                "model_size_bytes": model_size_bytes,
                "model_size_gb": model_size_bytes / 1_000_000_000,
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
    data_source: str = "fct_energy_demand",
    extra_tags: dict[str, str] | None = None,
    since: pd.Timestamp | None = None,
) -> TrainAndRegisterResult:
    """The real, DB + MLflow-backed entrypoint — `cli.py`'s `train`
    command and `pipeline.flows.daily_demand` (`README.md`'s Prefect
    example) both call this. `register=True` (the default) registers the
    trained model as a new `model_name` version in the `None` stage —
    promoting it to `Production` is a separate, deliberately-gated step
    (`scripts/promote_model.sh`), not automatic here.

    `data_source="ml_features_v1"` (`cli.py`'s `tune-optuna` command,
    `ml/tune.py`'s `tune_optuna`) sources from the orphaned
    `ml.ml_features_demand_v1` table instead of the dbt-tracked
    `fct_energy_demand` — see `ml/data.py`'s
    `load_ml_features_v1_training_data` module comment for what that
    trades off (more history, 66% imputed rows). The real imputed
    fraction is logged as an MLflow param either way, not silently
    dropped.

    `since` (`todo-model-training.md`'s OE region-join blocker follow-up,
    2026-08-05): `split_by_time`'s 70/15/15 split is chronological over
    *every* unique `ts` in `raw_df`, applied globally, not per-region —
    if `raw_df` spans a much longer real history than the columns a
    given training run actually has non-NaN data for (e.g.
    `total_generation_mw`, only backfilled for a recent window, not the
    full ~370-day AEMO history), nearly all of the real usable rows land
    in the *test* split (the tail end of that long history), starving
    train/val/calibration of real data even though plenty of usable rows
    exist in aggregate — confirmed the hard way: a real run against the
    full history produced 20/5/0 train/val/calibration rows against
    27,328 real usable rows total. Passing `since` scopes
    `load_training_data`'s query so the 70/15/15 split happens *within*
    the window real data actually covers, not silently diluted across
    a mostly-NaN older history.
    """
    settings = settings or get_settings()
    config = config or TrainConfig.from_settings(settings)
    configure_mlflow(settings)

    extra_params: dict[str, object] = {"data_source": data_source}
    # `data_source="r2_master"` (2026-08-10): the `master.duckdb` bootstrap
    # path -- deliberately never opens a Postgres session at all, not just
    # "doesn't query fct_energy_demand". Real, explicit instruction: use
    # DuckDB's real ~1-year history for this initial training pass without
    # touching Postgres, which stays exactly at its own 60-day retention
    # policy either way (`energy_data_offline.py`'s identical bootstrap
    # path for `EnergyForecastLSTM` set this precedent).
    if data_source == "r2_master":
        raw_df = load_demand_training_data_from_master(regions, since=since)
        holidays_df = load_holidays_from_master()
    else:
        async with get_session() as db:
            if data_source == "ml_features_v1":
                raw_df = await load_ml_features_v1_training_data(db, regions)
                extra_params[
                    "imputed_fraction"
                ] = await load_ml_features_v1_imputed_fraction(db, regions)
            else:
                raw_df = await load_training_data(db, regions, since=since)
            holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in {data_source!r} for regions={list(regions)}"
        )

    result = train_model(raw_df, config, holidays=holidays_df)
    return log_and_register_run(
        result,
        config,
        regions,
        model_name,
        register=register,
        extra_tags=extra_tags,
        extra_params=extra_params,
    )
