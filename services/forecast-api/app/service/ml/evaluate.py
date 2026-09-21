"""Walk-forward backtesting harness (`todo-model-training.md` Phase 0,
data-pipeline's own `TODO.md` `ECO-M10`).

Real, honest evaluation over MULTIPLE rolling origins spread across a
historical window -- not the one train/test split `ml/train.py`'s
`TrainResult.test_metrics` already reports (that single-split number is
still useful as a training-time signal, but a lucky/unlucky split can
mislead; walk-forward re-forecasts from several different points in time
and averages, the same discipline `notebooks/model-training.ipynb`'s
by-hand baseline comparison already does manually). This is what every
later phase's "did this actually help" claim (TimesFM vs LSTM vs TFT vs
blend, pruned vs unpruned, promoted vs current) gets checked against --
build it once here, reuse everywhere else.

Model-agnostic by design: anything that can produce a P10/P50/P90
forecast from one region's engineered feature history up to a rolling
origin satisfies `Forecaster` (see below) and plugs into the same
`evaluate_walk_forward` loop. `LSTMForecaster` wraps a loaded
`DemandLSTM` + its scalers + conformal calibration; `BaselineForecaster`
wraps `app/models/baseline.py`'s pure function. Neither
`evaluate_walk_forward` nor `evaluate_and_log` know or care which one
they're scoring -- a future TFT/TimesFM adapter (Phases 1-2) is just
another `Forecaster` implementation, no harness changes needed.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import joblib
import mlflow
import mlflow.artifacts
import numpy as np
import onnxruntime
import pandas as pd
import torch
from mlflow.tracking import MlflowClient

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.baseline import seasonal_naive_forecast
from app.models.ml import DemandLSTM
from app.models.tft import DemandTFT
from app.models.timesfm_adapter import (
    DEFAULT_MAX_CONTEXT,
    DEFAULT_MAX_HORIZON,
    TIMESFM_REPO_ID,
    TIMESFM_REVISION,
    load_timesfm_forecaster,
)
from app.service.ml.bias_correction import DemandBiasCorrection
from app.service.ml.conformal import ConformalCalibration, empirical_coverage
from app.service.ml.data import apply_scalers, load_holidays, load_training_data
from app.service.ml.features import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    add_calendar_features,
    add_region_dummies,
    build_features,
)
from app.service.ml.train import mape
from app.service.ml.train_tft import DECODER_COLUMNS, ENCODER_COLUMNS
from app.service.mlops.tracking import configure_mlflow
from app.core.logging import get_logger

log = get_logger(__name__)


class Forecaster(Protocol):
    """Anything that can produce a `horizon`-step P10/P50/P90 forecast
    from one region's engineered feature history up to and including a
    rolling origin. `DemandLSTM`/TFT/TimesFM (once they exist) all
    satisfy this the same way `app/models/ml.py`'s `DemandForecast`
    already unifies their raw `forward()` outputs -- this harness never
    imports a specific architecture, only this shape."""

    name: str

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`history`: `build_features`'s output for ONE region, sorted by
        `ts` ascending, ending at the forecast origin (the last row is
        the most recently observed timestep -- nothing after it is
        visible to the forecast). Returns `(p10, p50, p90)`, each shape
        `(horizon,)`, in real target units (MW) -- never the model's
        internal scaled space. A forecaster that can't produce a
        prediction at this origin (not enough history, a required
        feature is NaN) returns all-NaN arrays rather than raising --
        `evaluate_walk_forward` treats that origin as unscored, not a
        hard failure of the whole backtest.
        """
        ...


@dataclass
class BaselineForecaster:
    """Wraps `app/models/baseline.py`'s seasonal-naive forecaster behind
    the `Forecaster` protocol -- the "always available, nothing to load"
    floor every other forecaster is measured against (`todo-model-
    training.md` Phase 0's own framing)."""

    period_steps: int
    n_periods: int = 8
    name: str = "seasonal_naive"

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        forecast = seasonal_naive_forecast(
            history[TARGET_COLUMN],
            horizon=horizon,
            period_steps=self.period_steps,
            n_periods=self.n_periods,
        )
        return (
            forecast["p10"].to_numpy(),
            forecast["p50"].to_numpy(),
            forecast["p90"].to_numpy(),
        )


def _inverse(scaler: object, values: np.ndarray, region: str | None = None) -> np.ndarray:
    """`scaler` is a per-region `dict[str, StandardScaler]` for any model
    trained after `ml/train.py`'s per-region target-scaling fix
    (2026-08-15) -- `region` picks that region's own scaler. Still
    accepts a bare `StandardScaler` (the pre-fix global-scaler shape)
    for backward compatibility with already-registered versions, so
    evaluating an old version doesn't break just because new ones train
    differently."""
    if isinstance(scaler, dict):
        if region is None:
            raise ValueError("per-region target_scaler requires `region`")
        region_scaler = scaler.get(region)
        if region_scaler is None:
            return np.full(values.shape, np.nan)
        scaler = region_scaler
    return scaler.inverse_transform(values.reshape(-1, 1)).reshape(-1)  # type: ignore[attr-defined]


@dataclass
class LSTMForecaster:
    """Wraps a loaded `DemandLSTM` + its fitted per-region feature
    scalers + target scaler + (optional) conformal calibration behind the
    `Forecaster` protocol. `calibration=None` reports the model's raw,
    uncalibrated P10/P90 -- `evaluate_and_log` runs both a calibrated and
    an uncalibrated `LSTMForecaster` so a calibration's real effect on
    coverage is visible in the same report, not assumed from training-
    time numbers alone.

    The model's own trained `horizon` is fixed at construction (its
    output layer has that many units) -- `predict` raises `ValueError` if
    asked for a different one rather than silently truncating/padding.
    """

    model: DemandLSTM
    feature_scalers: dict[str, object]
    target_scaler: object
    lookback: int
    calibration: ConformalCalibration | None = None
    bias_correction: DemandBiasCorrection | None = None
    name: str = "lstm"

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if horizon != self.model.horizon:
            raise ValueError(
                f"{self.name}: was trained with horizon={self.model.horizon}, "
                f"can't evaluate at horizon={horizon}"
            )
        nan_result = (np.full(horizon, np.nan),) * 3
        if len(history) < self.lookback:
            return nan_result

        window = history.iloc[-self.lookback :]
        region = window["region"].iloc[-1]
        scaler = self.feature_scalers.get(region)
        if scaler is None:
            return nan_result
        scaled = apply_scalers(window, {region: scaler})

        x = scaled[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float32)
        if np.isnan(x).any():
            return nan_result

        self.model.eval()
        with torch.no_grad():
            out = self.model(torch.from_numpy(x).unsqueeze(0))

        p10 = _inverse(self.target_scaler, out.p10[0].numpy(), region=region)
        p50 = _inverse(self.target_scaler, out.p50[0].numpy(), region=region)
        p90 = _inverse(self.target_scaler, out.p90[0].numpy(), region=region)
        if self.bias_correction is not None:
            p10, p50, p90 = self.bias_correction.apply(region, p10, p50, p90)
        if self.calibration is not None:
            p10, p90 = self.calibration.apply(p10, p90)
        return p10, p50, p90


@dataclass
class TFTForecaster:
    """Wraps a loaded `DemandTFT` behind the `Forecaster` protocol.
    Unlike `LSTMForecaster`, this needs more than `history` alone:
    `DemandTFT`'s decoder consumes `DECODER_COLUMNS` (`train_tft.py`'s
    `KNOWN_FUTURE_COLUMNS`) for the `horizon` steps *ahead* of the
    forecast origin, which `history` (data up to and including the
    origin) never contains. Real, not approximated: these are pure
    functions of the timestamp itself (`ml/features.py`'s
    `add_calendar_features`), so they're synthesized directly from
    `history`'s own inferred cadence rather than needing a second query.
    """

    model: DemandTFT
    feature_scalers: dict[str, object]
    target_scaler: object
    lookback: int
    calibration: ConformalCalibration | None = None
    bias_correction: DemandBiasCorrection | None = None
    holidays: pd.DataFrame | None = None
    name: str = "tft"

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if horizon != self.model.horizon:
            raise ValueError(
                f"{self.name}: was trained with horizon={self.model.horizon}, "
                f"can't evaluate at horizon={horizon}"
            )
        nan_result = (np.full(horizon, np.nan),) * 3
        if len(history) < self.lookback:
            return nan_result

        window = history.iloc[-self.lookback :]
        region = window["region"].iloc[-1]
        scaler = self.feature_scalers.get(region)
        if scaler is None:
            return nan_result
        scaled_window = apply_scalers(window, {region: scaler})

        x_enc = scaled_window[list(ENCODER_COLUMNS)].to_numpy(dtype=np.float32)
        if np.isnan(x_enc).any():
            return nan_result

        step = window["ts"].diff().dropna().median()
        if pd.isna(step) or step <= pd.Timedelta(0):
            return nan_result
        future_ts = pd.date_range(
            window["ts"].iloc[-1] + step, periods=horizon, freq=step
        )
        future_df = add_calendar_features(
            pd.DataFrame({"ts": future_ts, "region": region}), holidays=self.holidays
        )
        # `DECODER_COLUMNS` (`KNOWN_FUTURE_COLUMNS`) includes the region
        # one-hot block (`ml/features.py`'s `_REGION_COLUMNS`) alongside
        # the calendar block `add_calendar_features` alone produces --
        # without this, `future_df[list(DECODER_COLUMNS)]` below raised a
        # real `KeyError` on every actual `TFTForecaster.predict` call
        # (confirmed live, 2026-08-10: `evaluate-tft` failed 100% of the
        # time with "['region_NSW1', ...] not in index"), not something
        # data volume or region coverage could ever fix.
        future_df = add_region_dummies(future_df)
        x_dec = future_df[list(DECODER_COLUMNS)].to_numpy(dtype=np.float32)
        if np.isnan(x_dec).any():
            return nan_result

        self.model.eval()
        with torch.no_grad():
            out = self.model(
                torch.from_numpy(x_enc).unsqueeze(0),
                torch.from_numpy(x_dec).unsqueeze(0),
            )

        p10 = _inverse(self.target_scaler, out.p10[0].numpy(), region=region)
        p50 = _inverse(self.target_scaler, out.p50[0].numpy(), region=region)
        p90 = _inverse(self.target_scaler, out.p90[0].numpy(), region=region)
        if self.bias_correction is not None:
            p10, p50, p90 = self.bias_correction.apply(region, p10, p50, p90)
        if self.calibration is not None:
            p10, p90 = self.calibration.apply(p10, p90)
        return p10, p50, p90


@dataclass
class ONNXForecaster:
    """Wraps a user-uploaded ONNX model behind the `Forecaster` protocol
    -- `app/service/ml/onnx_import.py`'s validation pipeline is what
    actually constructs one of these (never built from an untrusted
    `.onnx` file without going through that validation first). Unlike
    `LSTMForecaster`/`TFTForecaster`, the model itself is opaque (an
    `onnxruntime.InferenceSession`, not a known `nn.Module`) -- every
    other piece of information `predict` needs (which of this system's
    own `FEATURE_COLUMNS` it consumes, in what order, which output
    tensor is which quantile) comes from the manifest the upload
    declared and `onnx_import.py` already cross-checked against the
    graph's own real I/O shapes at import time, not re-derived here.

    `feature_columns` is a real, possibly-proper subset of the global
    `FEATURE_COLUMNS` `LSTMForecaster`/`TFTForecaster` always use in
    full -- see `docs/onnx-model-import.md`'s manifest schema: an
    uploaded model only has to consume *some* of this system's own
    engineered features, in its own declared order, not all of them.

    `output_type="point"` models have no real p10/p90 of their own --
    `predict` feeds the same `p50` in for both before calibration, so
    `self.calibration.apply` (if a calibration was shipped/fit) produces
    a real symmetric band (`ConformalCalibration.apply(lo, hi) = (lo -
    q, hi + q)`); with no calibration, bounds stay honestly zero-width
    rather than a fabricated interval (`docs/onnx-model-import.md`'s own
    noted scope cut: this codebase does not yet auto-fit calibration for
    a point-only upload that ships none).
    """

    session: onnxruntime.InferenceSession
    feature_columns: tuple[str, ...]
    input_name: str
    output_type: str  # "point" | "quantile3"
    output_names: dict[str, str]  # {"p10","p50","p90"} or {"point"}
    feature_scalers: dict[str, object]
    target_scaler: object
    lookback: int
    calibration: ConformalCalibration | None = None
    bias_correction: DemandBiasCorrection | None = None
    name: str = "onnx_custom"

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        nan_result = (np.full(horizon, np.nan),) * 3
        if len(history) < self.lookback:
            return nan_result

        window = history.iloc[-self.lookback :]
        region = window["region"].iloc[-1]
        scaler = self.feature_scalers.get(region)
        if scaler is None:
            return nan_result
        scaled = apply_scalers(window, {region: scaler})

        x = scaled[list(self.feature_columns)].to_numpy(dtype=np.float32)
        if np.isnan(x).any():
            return nan_result

        outputs = self.session.run(None, {self.input_name: x[None, :, :]})
        by_name = dict(zip((o.name for o in self.session.get_outputs()), outputs, strict=True))

        if self.output_type == "quantile3":
            p10_raw = by_name[self.output_names["p10"]][0]
            p50_raw = by_name[self.output_names["p50"]][0]
            p90_raw = by_name[self.output_names["p90"]][0]
        else:
            p50_raw = by_name[self.output_names["point"]][0]
            p10_raw = p50_raw
            p90_raw = p50_raw

        p10 = _inverse(self.target_scaler, p10_raw, region=region)
        p50 = _inverse(self.target_scaler, p50_raw, region=region)
        p90 = _inverse(self.target_scaler, p90_raw, region=region)
        if self.bias_correction is not None:
            p10, p50, p90 = self.bias_correction.apply(region, p10, p50, p90)
        if self.calibration is not None:
            p10, p90 = self.calibration.apply(p10, p90)
        return p10, p50, p90


def _pinball_loss(pred: np.ndarray, target: np.ndarray, quantile: float) -> float:
    """Same formula as `ml/losses.py`'s `pinball_loss`, in numpy rather
    than torch -- this is a reported *metric* over a finished backtest,
    not a training-time loss that needs autograd."""
    error = target - pred
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


@dataclass
class EvaluationReport:
    model_name: str
    region: str
    horizon: int
    n_origins: int
    mape: float
    rmse: float
    pinball_loss_10: float
    pinball_loss_50: float
    pinball_loss_90: float
    empirical_coverage: float
    # Real "Consistency" signal (2026-08-10, dashboard Model Comparison
    # page): mean `p90 - p10` in MW over every scored origin -- the
    # actual width of the interval this candidate served, whichever
    # candidate it is (a `_raw` forecaster's uncalibrated width, a
    # calibrated one's post-conformal width, or the seasonal baseline's).
    # Narrower for the same coverage is genuinely "more confident," which
    # is what a real Consistency comparison between architectures needs
    # -- nothing here approximates or fabricates it from another metric.
    mean_interval_width: float
    # `mae`/`mean_error` (2026-08-10, dashboard Model Performance page):
    # real MAE (mean absolute error, MW) and real ME/bias (mean signed
    # error, `p50 - actual`, MW -- positive means this candidate tends to
    # over-forecast, negative under-forecast) over every scored origin.
    # Same `pred50`/`actual` arrays `rmse` already reduces, just a
    # different real reduction -- not a second, separately-fetched
    # metric. `rmse`/`mape` alone can't answer "is this candidate
    # systematically biased" (RMSE is magnitude-only, squared-error-
    # weighted; MAPE is magnitude-only, percentage-scaled) -- ME is the
    # one real signed signal for that.
    mae: float
    mean_error: float

    def as_mlflow_metrics(self) -> dict[str, float]:
        return {
            "eval_mape": self.mape,
            "eval_rmse": self.rmse,
            "eval_pinball_p10": self.pinball_loss_10,
            "eval_pinball_p50": self.pinball_loss_50,
            "eval_pinball_p90": self.pinball_loss_90,
            "eval_coverage": self.empirical_coverage,
            "eval_interval_width": self.mean_interval_width,
            "eval_n_origins": float(self.n_origins),
            "eval_mae": self.mae,
            "eval_mean_error": self.mean_error,
        }


def evaluate_walk_forward(
    forecaster: Forecaster,
    df: pd.DataFrame,
    horizon: int,
    *,
    n_origins: int = 10,
    min_history: int = 1,
) -> EvaluationReport:
    """Walk-forward backtest of `forecaster` against `df` (`build_features`'
    output for ONE region, any row order -- sorted here). Picks up to
    `n_origins` evenly-spaced forecast origins (excluding the last
    `horizon` rows, which need real future rows to score against, and the
    first `min_history - 1` rows, which don't have enough context yet),
    forecasts `horizon` steps ahead from each, and scores against what
    actually happened.

    Origins where the forecaster returns NaN (not enough real history/
    features at that point) or where the actual outcome itself has a gap
    are skipped and don't count toward the reported `n_origins` -- an
    honest "how many origins actually scored" ships on the report, not
    silently assumed to equal the requested count. Returns an all-NaN
    report (n_origins=0) if nothing scored at all, rather than raising --
    a region/config combination with too little dense data is a real,
    reportable outcome (as `notebooks/model-training.ipynb`'s region-
    completeness diagnostic already found for several NEM regions), not
    something this harness should crash on.
    """
    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    region = str(df["region"].iloc[0]) if "region" in df.columns and n else ""

    last_valid_origin = n - horizon - 1
    first_valid_origin = min_history - 1
    if last_valid_origin < first_valid_origin:
        return EvaluationReport(
            model_name=forecaster.name,
            region=region,
            horizon=horizon,
            n_origins=0,
            mape=float("nan"),
            rmse=float("nan"),
            pinball_loss_10=float("nan"),
            pinball_loss_50=float("nan"),
            pinball_loss_90=float("nan"),
            empirical_coverage=float("nan"),
            mean_interval_width=float("nan"),
            mae=float("nan"),
            mean_error=float("nan"),
        )

    span = last_valid_origin - first_valid_origin + 1
    candidate_origins = sorted(
        set(
            np.linspace(
                first_valid_origin, last_valid_origin, min(n_origins, span), dtype=int
            ).tolist()
        )
    )

    pred10s, pred50s, pred90s, actuals = [], [], [], []
    for origin in candidate_origins:
        history = df.iloc[: origin + 1]
        actual = df[TARGET_COLUMN].iloc[origin + 1 : origin + 1 + horizon].to_numpy()
        if len(actual) < horizon or np.isnan(actual).any():
            continue
        p10, p50, p90 = forecaster.predict(history, horizon)
        if np.isnan(p50).any():
            continue
        pred10s.append(p10)
        pred50s.append(p50)
        pred90s.append(p90)
        actuals.append(actual)

    if not actuals:
        return EvaluationReport(
            model_name=forecaster.name,
            region=region,
            horizon=horizon,
            n_origins=0,
            mape=float("nan"),
            rmse=float("nan"),
            pinball_loss_10=float("nan"),
            pinball_loss_50=float("nan"),
            pinball_loss_90=float("nan"),
            empirical_coverage=float("nan"),
            mean_interval_width=float("nan"),
            mae=float("nan"),
            mean_error=float("nan"),
        )

    pred10 = np.stack(pred10s)
    pred50 = np.stack(pred50s)
    pred90 = np.stack(pred90s)
    actual = np.stack(actuals)

    return EvaluationReport(
        model_name=forecaster.name,
        region=region,
        horizon=horizon,
        n_origins=len(actuals),
        mape=mape(pred50, actual),
        rmse=float(np.sqrt(np.mean((pred50 - actual) ** 2))),
        pinball_loss_10=_pinball_loss(pred10, actual, 0.1),
        pinball_loss_50=_pinball_loss(pred50, actual, 0.5),
        pinball_loss_90=_pinball_loss(pred90, actual, 0.9),
        empirical_coverage=empirical_coverage(actual, pred10, pred90),
        mean_interval_width=float(np.mean(pred90 - pred10)),
        mae=float(np.mean(np.abs(pred50 - actual))),
        mean_error=float(np.mean(pred50 - actual)),
    )


@dataclass
class RecentBacktestPoint:
    ts: pd.Timestamp
    actual: float | None
    p10: float
    p50: float
    p90: float
    #: Real, not derived client-side -- 1-indexed hours-ahead-of-its-own-
    #: origin this point was predicted at (the horizon step of the real
    #: walk-forward window it came from). Lets a caller build a genuine
    #: "accuracy by horizon" breakdown (error at 1h-ahead vs. 24h-ahead
    #: vs. 48h-ahead) from real per-step data instead of only the
    #: aggregate `evaluate_walk_forward` report.
    step_hours: int


def evaluate_recent_actual_vs_predicted(
    forecaster: Forecaster,
    df: pd.DataFrame,
    horizon: int,
    *,
    days_back: float = 7,
    min_history: int = 1,
) -> list[RecentBacktestPoint]:
    """Real walk-forward re-forecast covering roughly the last `days_back`
    days of `df` (`build_features`'s output for ONE region), ending at
    the last real origin `df` actually has -- same "as fresh as the real
    data allows, never pretend to reach wall-clock now" honesty
    `RealEmissionsTrend`'s (services/dashboard) forecast band already
    follows for the live forecast.

    Unlike `evaluate_walk_forward` just above (one aggregate MAPE/RMSE/
    coverage report), this returns the real per-step `(ts, actual, p10,
    p50, p90)` tuples a chart needs. Origins walk backward from the most
    recent valid one in non-overlapping `horizon`-sized windows -- so the
    predicted curve is one continuous real line ending at the same real
    point the actual line does, not `evaluate_walk_forward`'s evenly-
    spread sampling across the *whole* history (which would leave real
    gaps between scored windows, wrong for a continuous trend chart).

    A step whose real actual value is missing (a genuine warehouse gap --
    same real-gap reality this platform already discloses elsewhere
    rather than papering over) still keeps its real predicted point;
    `actual` is `None` for that one step, not the whole origin dropped --
    a partial real gap shouldn't blank out days of real, valid
    predictions around it.
    """
    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    last_valid_origin = n - horizon - 1
    first_valid_origin = min_history - 1
    if last_valid_origin < first_valid_origin:
        return []

    cutoff_ts = df["ts"].iloc[-1] - pd.Timedelta(days=days_back)
    origins: list[int] = []
    o = last_valid_origin
    while o >= first_valid_origin:
        origins.append(o)
        if df["ts"].iloc[o] <= cutoff_ts:
            break
        o -= horizon
    origins.sort()

    points: list[RecentBacktestPoint] = []
    for origin in origins:
        history = df.iloc[: origin + 1]
        p10, p50, p90 = forecaster.predict(history, horizon)
        if np.isnan(p50).any():
            continue
        window = df.iloc[origin + 1 : origin + 1 + horizon]
        for i, (_, row) in enumerate(window.iterrows()):
            actual = row[TARGET_COLUMN]
            points.append(
                RecentBacktestPoint(
                    ts=row["ts"],
                    actual=None if pd.isna(actual) else float(actual),
                    p10=float(p10[i]),
                    p50=float(p50[i]),
                    p90=float(p90[i]),
                    step_hours=i + 1,
                )
            )
    return points


def _infer_period_steps(df: pd.DataFrame, ts_col: str = "ts") -> int:
    """Real daily-seasonality period, in rows, inferred from `df`'s own
    median timestamp gap -- not assumed from the model's textbook 5-min
    cadence. NEM data is real-5-min, WEM is real-30-min, and even NEM
    regions have gaps once restricted to a dense window
    (`notebooks/model-training.ipynb`'s Section 2 hit exactly this: a
    hardcoded 5-min assumption made every baseline forecast in a sparser
    window come back NaN)."""
    step_s = df[ts_col].diff().dt.total_seconds().dropna().median()
    if not step_s or step_s <= 0:
        raise ValueError(
            "cannot infer a seasonal period -- fewer than 2 distinct real "
            "timestamps in this window"
        )
    return max(1, round(86400 / step_s))


@dataclass
class _RegisteredRunArtifacts:
    """The parts of a registered run every `load_registered_*_model`
    needs, factored out so each just adds its own architecture-specific
    model construction on top -- downloading/state-dict/scaler/
    calibration loading is identical regardless of architecture."""

    params: dict[str, str]
    state_dict: dict[str, torch.Tensor]
    feature_scalers: dict[str, object]
    target_scaler: object
    calibration: ConformalCalibration | None
    bias_correction: DemandBiasCorrection | None


def _load_registered_run_artifacts(
    model_name: str, version: str | int
) -> _RegisteredRunArtifacts:
    client = MlflowClient()
    model_version = client.get_model_version(model_name, str(version))
    run_id = model_version.run_id
    assert run_id is not None, (  # nosec B101 -- internal invariant for type-narrowing; every version `mlflow.register_model` creates has a run_id
        f"{model_name!r} v{version} has no run_id"
    )
    run = client.get_run(run_id)
    params = run.data.params

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir
        )
        # weights_only=True: this file is always a plain state_dict this
        # same pipeline wrote (never externally sourced) -- see
        # `ml.incremental.get_warm_start`'s identical comment.
        state_dict = torch.load(
            Path(local_dir) / "model_state_dict.pt",
            map_location=torch.device("cpu"),
            weights_only=True,
        )
        feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
        target_scaler = joblib.load(Path(local_dir) / "target_scaler.joblib")

    try:
        cal_dict = mlflow.artifacts.load_dict(
            f"runs:/{run_id}/conformal_calibration.json"
        )
        calibration = ConformalCalibration.from_dict(cal_dict)
    except Exception:
        # A run logged before conformal calibration existed, or the
        # artifact is otherwise missing -- evaluate the raw model rather
        # than failing the whole backtest over a missing nice-to-have.
        calibration = None

    try:
        bias_dict = mlflow.artifacts.load_dict(
            f"runs:/{run_id}/demand_bias_correction.json"
        )
        bias_correction = DemandBiasCorrection.from_dict(bias_dict)
    except Exception:
        # A run logged before `TODO.md` Phase 3 existed -- same "evaluate
        # the raw model rather than failing the whole backtest" reasoning
        # as `calibration` just above.
        bias_correction = None

    return _RegisteredRunArtifacts(
        params=params,
        state_dict=state_dict,
        feature_scalers=feature_scalers,
        target_scaler=target_scaler,
        calibration=calibration,
        bias_correction=bias_correction,
    )


def load_registered_model(model_name: str, version: str | int) -> LSTMForecaster:
    """Downloads a specific registered version's weights + scalers +
    conformal calibration and wraps them as an `LSTMForecaster`.
    `ml.incremental.get_warm_start`'s sibling, but resolved by explicit
    `version` (what you evaluate a specific candidate against) rather
    than by registry stage (what the *next* training run warm-starts
    from) -- evaluating a not-yet-promoted Staging/None-stage candidate
    is exactly this harness's job, so it can't only look up by stage.
    """
    artifacts = _load_registered_run_artifacts(model_name, version)
    params = artifacts.params

    model = DemandLSTM(
        n_features=len(FEATURE_COLUMNS),
        horizon=int(params["horizon"]),
        hidden_size=int(params["hidden_size"]),
        num_layers=int(params["num_layers"]),
        dropout=float(params["dropout"]),
    )
    model.load_state_dict(artifacts.state_dict)
    model.eval()

    return LSTMForecaster(
        model=model,
        feature_scalers=artifacts.feature_scalers,
        target_scaler=artifacts.target_scaler,
        lookback=int(params["lookback"]),
        calibration=artifacts.calibration,
        bias_correction=artifacts.bias_correction,
        name=f"{model_name}_v{version}",
    )


def load_registered_tft_model(
    model_name: str, version: str | int, holidays: pd.DataFrame | None = None
) -> TFTForecaster:
    """`load_registered_model`'s TFT counterpart. Needs
    `n_encoder_features`/`n_decoder_features` from the run's params --
    logged via `train_tft.py`'s `log_and_register_run(..., extra_params=
    ...)` call specifically because they don't fit generically into
    `FEATURE_COLUMNS`' single count the way `load_registered_model`
    above uses it."""
    artifacts = _load_registered_run_artifacts(model_name, version)
    params = artifacts.params

    model = DemandTFT(
        n_encoder_features=int(params["n_encoder_features"]),
        n_decoder_features=int(params["n_decoder_features"]),
        horizon=int(params["horizon"]),
        hidden_size=int(params["hidden_size"]),
        n_heads=int(params["n_heads"]),
        dropout=float(params["dropout"]),
    )
    model.load_state_dict(artifacts.state_dict)
    model.eval()

    return TFTForecaster(
        model=model,
        feature_scalers=artifacts.feature_scalers,
        target_scaler=artifacts.target_scaler,
        lookback=int(params["lookback"]),
        calibration=artifacts.calibration,
        bias_correction=artifacts.bias_correction,
        holidays=holidays,
        name=f"{model_name}_v{version}",
    )


def load_registered_onnx_model(model_name: str, version: str | int) -> ONNXForecaster:
    """`load_registered_model`'s ONNX counterpart. Doesn't reuse
    `_load_registered_run_artifacts` (that helper's `state_dict:
    dict[str, torch.Tensor]` is specific to the `.pt` path) -- downloads
    the same `serving/` artifact directory, just reads `model.onnx`
    bytes instead of `model_state_dict.pt`. `feature_columns`/
    `input_name`/`output_type`/`output_names` come from the run's own
    logged params (`onnx_import.py`'s `_register_onnx` writes them,
    already validated against the graph's real I/O at import time --
    nothing here re-validates, this is a trusted read of an already-
    registered version)."""
    client = MlflowClient()
    model_version = client.get_model_version(model_name, str(version))
    run_id = model_version.run_id
    assert run_id is not None, (  # nosec B101 -- internal invariant for type-narrowing; every version `mlflow.register_model` creates has a run_id
        f"{model_name!r} v{version} has no run_id"
    )
    run = client.get_run(run_id)
    params = run.data.params

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir
        )
        onnx_bytes = (Path(local_dir) / "model.onnx").read_bytes()
        feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
        target_scaler = joblib.load(Path(local_dir) / "target_scaler.joblib")

    session = onnxruntime.InferenceSession(onnx_bytes, providers=["CPUExecutionProvider"])

    try:
        cal_dict = mlflow.artifacts.load_dict(f"runs:/{run_id}/conformal_calibration.json")
        calibration = ConformalCalibration.from_dict(cal_dict)
    except Exception:
        # Real, common state for an upload that shipped none -- see
        # `ONNXForecaster`'s own docstring for what this means at serve/
        # eval time (honestly zero-width bounds, not a fabricated band).
        calibration = None

    try:
        bias_dict = mlflow.artifacts.load_dict(f"runs:/{run_id}/demand_bias_correction.json")
        bias_correction = DemandBiasCorrection.from_dict(bias_dict)
    except Exception:
        bias_correction = None

    output_type = params["output_type"]
    if output_type == "quantile3":
        output_names = {
            "p10": params["output_name_p10"],
            "p50": params["output_name_p50"],
            "p90": params["output_name_p90"],
        }
    else:
        output_names = {"point": params["output_name_point"]}

    return ONNXForecaster(
        session=session,
        feature_columns=tuple(params["feature_columns"].split(",")),
        input_name=params["input_name"],
        output_type=output_type,
        output_names=output_names,
        feature_scalers=feature_scalers,
        target_scaler=target_scaler,
        lookback=int(params["lookback"]),
        calibration=calibration,
        bias_correction=bias_correction,
        name=f"{model_name}_v{version}",
    )


@dataclass
class EvaluationRunResult:
    run_id: str
    reports: list[EvaluationReport]


async def evaluate_and_log(
    model_name: str,
    version: str | int,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    horizon: int | None = None,
    n_origins: int = 10,
    baseline_period_steps: int | None = None,
) -> EvaluationRunResult:
    """The real, DB + MLflow-backed entrypoint -- `ecolens-pipeline
    evaluate` (`cli.py`) calls this. For each region, runs Phase 0's
    walk-forward harness against the registered LSTM version (both
    calibrated and raw) AND the seasonal-naive baseline, over the same
    historical window and the same rolling origins, and logs every report
    to one MLflow run tagged `evaluation` -- so "did this candidate
    actually beat the baseline" always has an honest, same-conditions
    comparison alongside it, not just the candidate's own metrics
    reported in isolation.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    lstm_forecaster = load_registered_model(model_name, version)
    resolved_horizon = horizon or lstm_forecaster.model.horizon

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)
    if raw_df.empty:
        raise ValueError(f"no data found in the warehouse for regions={list(regions)}")

    engineered = build_features(raw_df, holidays=holidays_df)

    reports: list[EvaluationReport] = []
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {
                "evaluation": "true",
                "evaluated_model": model_name,
                "evaluated_version": str(version),
            }
        )
        mlflow.log_params(
            {
                "horizon": resolved_horizon,
                "n_origins": n_origins,
                "regions": ",".join(regions),
            }
        )

        for region in regions:
            region_df = (
                engineered[engineered["region"] == region]
                .sort_values("ts")
                .reset_index(drop=True)
            )
            if region_df.empty:
                log.info("evaluate.skip_empty_region", region=region)
                continue

            # `bias_correction` deliberately left unset (defaults to
            # `None`) here too, not just `calibration` -- "_raw" means
            # the model's untouched output, no post-hoc adjustment of
            # any kind, so the report's calibrated-vs-raw comparison
            # shows the real combined effect of bias correction +
            # conformal calibration together, not just the latter.
            raw_forecaster = LSTMForecaster(
                model=lstm_forecaster.model,
                feature_scalers=lstm_forecaster.feature_scalers,
                target_scaler=lstm_forecaster.target_scaler,
                lookback=lstm_forecaster.lookback,
                calibration=None,
                name=f"{lstm_forecaster.name}_raw",
            )
            for candidate in (lstm_forecaster, raw_forecaster):
                report = evaluate_walk_forward(
                    candidate,
                    region_df,
                    resolved_horizon,
                    n_origins=n_origins,
                    min_history=candidate.lookback,
                )
                reports.append(report)
                mlflow.log_metrics(
                    {
                        f"{region}_{candidate.name}_{k}": v
                        for k, v in report.as_mlflow_metrics().items()
                    }
                )

            try:
                period_steps = baseline_period_steps or _infer_period_steps(region_df)
            except ValueError as exc:
                log.info("evaluate.skip_baseline", region=region, reason=str(exc))
                continue
            baseline_forecaster = BaselineForecaster(period_steps=period_steps)
            baseline_report = evaluate_walk_forward(
                baseline_forecaster,
                region_df,
                resolved_horizon,
                n_origins=n_origins,
                min_history=period_steps + 1,
            )
            reports.append(baseline_report)
            mlflow.log_metrics(
                {
                    f"{region}_{baseline_forecaster.name}_{k}": v
                    for k, v in baseline_report.as_mlflow_metrics().items()
                }
            )

        run_id = run.info.run_id

    return EvaluationRunResult(run_id=run_id, reports=reports)


async def evaluate_tft_and_log(
    model_name: str,
    version: str | int,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    horizon: int | None = None,
    n_origins: int = 10,
    baseline_period_steps: int | None = None,
) -> EvaluationRunResult:
    """`evaluate_and_log`'s TFT counterpart -- identical shape (same
    walk-forward harness, same calibrated-vs-raw-vs-baseline comparison,
    same one-MLflow-run-tagged-`evaluation` logging), swapped to
    `load_registered_tft_model`/`TFTForecaster`. Kept as its own function
    rather than branching inside `evaluate_and_log` -- matches this
    module's existing `evaluate_timesfm_and_log` precedent of one
    `evaluate_*_and_log` per architecture family, all built on the same
    `evaluate_walk_forward` primitive.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)
    if raw_df.empty:
        raise ValueError(f"no data found in the warehouse for regions={list(regions)}")

    tft_forecaster = load_registered_tft_model(
        model_name, version, holidays=holidays_df
    )
    resolved_horizon = horizon or tft_forecaster.model.horizon

    engineered = build_features(raw_df, holidays=holidays_df)

    reports: list[EvaluationReport] = []
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {
                "evaluation": "true",
                "evaluated_model": model_name,
                "evaluated_version": str(version),
            }
        )
        mlflow.log_params(
            {
                "horizon": resolved_horizon,
                "n_origins": n_origins,
                "regions": ",".join(regions),
            }
        )

        for region in regions:
            region_df = (
                engineered[engineered["region"] == region]
                .sort_values("ts")
                .reset_index(drop=True)
            )
            if region_df.empty:
                log.info("evaluate_tft.skip_empty_region", region=region)
                continue

            # `bias_correction` deliberately left unset here too -- same
            # reasoning as `LSTMForecaster`'s identical raw_forecaster
            # above.
            raw_forecaster = TFTForecaster(
                model=tft_forecaster.model,
                feature_scalers=tft_forecaster.feature_scalers,
                target_scaler=tft_forecaster.target_scaler,
                lookback=tft_forecaster.lookback,
                calibration=None,
                holidays=holidays_df,
                name=f"{tft_forecaster.name}_raw",
            )
            for candidate in (tft_forecaster, raw_forecaster):
                report = evaluate_walk_forward(
                    candidate,
                    region_df,
                    resolved_horizon,
                    n_origins=n_origins,
                    min_history=candidate.lookback,
                )
                reports.append(report)
                mlflow.log_metrics(
                    {
                        f"{region}_{candidate.name}_{k}": v
                        for k, v in report.as_mlflow_metrics().items()
                    }
                )

            try:
                period_steps = baseline_period_steps or _infer_period_steps(region_df)
            except ValueError as exc:
                log.info("evaluate_tft.skip_baseline", region=region, reason=str(exc))
                continue
            baseline_forecaster = BaselineForecaster(period_steps=period_steps)
            baseline_report = evaluate_walk_forward(
                baseline_forecaster,
                region_df,
                resolved_horizon,
                n_origins=n_origins,
                min_history=period_steps + 1,
            )
            reports.append(baseline_report)
            mlflow.log_metrics(
                {
                    f"{region}_{baseline_forecaster.name}_{k}": v
                    for k, v in baseline_report.as_mlflow_metrics().items()
                }
            )

        run_id = run.info.run_id

    return EvaluationRunResult(run_id=run_id, reports=reports)


# `lstm_demand_timesfm` -- a distinct name from `lstm_demand`/`lstm_demand_tft`
# (Phase 1/2's own naming-discipline note): different architectures aren't
# comparable "versions" of one registered model, and TimesFM specifically
# has no versions of *our own* to register at all (zero-shot, frozen
# checkpoint) -- this is a label for evaluation runs to tag themselves
# with, not an MLflow Model Registry entry.
TIMESFM_EVALUATED_MODEL_NAME = "lstm_demand_timesfm"


async def evaluate_timesfm_and_log(
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    horizon: int = 6,
    n_origins: int = 10,
    max_context: int = DEFAULT_MAX_CONTEXT,
    baseline_period_steps: int | None = None,
) -> EvaluationRunResult:
    """TimesFM's counterpart to `evaluate_and_log` -- same walk-forward
    harness (`evaluate_walk_forward`), same per-region seasonal-naive
    baseline comparison, same "one MLflow run tagged `evaluation`"
    logging convention, but there's no MLflow-registered version to load
    (`load_timesfm_forecaster` downloads a pinned HuggingFace checkpoint
    instead of `load_registered_model`'s `runs:/.../serving` artifact) and
    no `test_metrics`/`final_val_mape` from a training loop that never
    ran. `horizon` has no natural default the way `LSTMForecaster`'s does
    (a registered version's own trained `horizon`) -- TimesFM is zero-shot
    and can forecast any horizon up to `max_horizon`, so this must be
    given explicitly.

    Real, honest cost note: constructing `TimesFMForecaster` compiles a
    real ~200M-parameter model (a real HuggingFace download the first
    time, a real torch-compile step every time) -- expect this to take
    real wall-clock seconds to low-single-digit minutes on a laptop CPU,
    not baseline/LSTM-evaluation instant.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    timesfm_forecaster = load_timesfm_forecaster(
        max_context=max_context, max_horizon=max(horizon, DEFAULT_MAX_HORIZON)
    )

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)
    if raw_df.empty:
        raise ValueError(f"no data found in the warehouse for regions={list(regions)}")

    engineered = build_features(raw_df, holidays=holidays_df)

    reports: list[EvaluationReport] = []
    with mlflow.start_run() as run:
        mlflow.set_tags(
            {
                "evaluation": "true",
                "evaluated_model": TIMESFM_EVALUATED_MODEL_NAME,
                "timesfm_repo_id": TIMESFM_REPO_ID,
                "timesfm_revision": TIMESFM_REVISION,
            }
        )
        mlflow.log_params(
            {
                "horizon": horizon,
                "n_origins": n_origins,
                "max_context": max_context,
                "regions": ",".join(regions),
            }
        )

        for region in regions:
            region_df = (
                engineered[engineered["region"] == region]
                .sort_values("ts")
                .reset_index(drop=True)
            )
            if region_df.empty:
                log.info("evaluate_timesfm.skip_empty_region", region=region)
                continue

            report = evaluate_walk_forward(
                timesfm_forecaster,
                region_df,
                horizon,
                n_origins=n_origins,
                min_history=1,
            )
            reports.append(report)
            mlflow.log_metrics(
                {
                    f"{region}_{timesfm_forecaster.name}_{k}": v
                    for k, v in report.as_mlflow_metrics().items()
                }
            )

            try:
                period_steps = baseline_period_steps or _infer_period_steps(region_df)
            except ValueError as exc:
                log.info(
                    "evaluate_timesfm.skip_baseline", region=region, reason=str(exc)
                )
                continue
            baseline_forecaster = BaselineForecaster(period_steps=period_steps)
            baseline_report = evaluate_walk_forward(
                baseline_forecaster,
                region_df,
                horizon,
                n_origins=n_origins,
                min_history=period_steps + 1,
            )
            reports.append(baseline_report)
            mlflow.log_metrics(
                {
                    f"{region}_{baseline_forecaster.name}_{k}": v
                    for k, v in baseline_report.as_mlflow_metrics().items()
                }
            )

        run_id = run.info.run_id

    return EvaluationRunResult(run_id=run_id, reports=reports)


@dataclass
class LiveEvaluationGateResult:
    passed: bool
    overall_mape: float
    reports: list[EvaluationReport]


async def run_live_evaluation_gate(
    forecaster: Forecaster,
    model_name: str,
    version: str | int,
    regions: Sequence[str],
    horizon: int,
    *,
    settings: Settings | None = None,
    n_origins: int = 5,
    max_acceptable_mape: float | None = None,
) -> LiveEvaluationGateResult:
    """`todo-model-training.md` Phase 4's "live evaluation gate": before
    a freshly-trained (typically incremental) version is even a
    promotion *candidate*, run Phase 0's walk-forward harness against
    the MOST RECENT real warehouse data -- distinct from
    `mlops.registry.promote_version`'s existing gate, which only
    compares each side's already-logged, training-time `test_mape` (a
    single split against data current *at training time*). A version
    that overfit to a short recent incremental window can still show a
    fine training-time `test_mape` while failing badly on data it
    genuinely never saw -- this is the check that catches that, using
    exactly the same walk-forward machinery every other evaluation in
    this module does.

    Tags the MLflow model version (`eval_gate_passed`/`eval_gate_mape`)
    so `mlops.registry.promote_version` (Phase 8) or a human reviewer
    can check the result without re-running this (real, not free)
    evaluation. `forecaster` must already be loaded (via
    `load_registered_model`/`load_registered_tft_model`/etc.) -- this
    function only orchestrates the fresh-data query + walk-forward
    scoring + tagging, architecture-agnostic via the same `Forecaster`
    protocol every other evaluator in this module uses.

    `max_acceptable_mape=None` (the default) still performs a real,
    meaningful check even without an explicit threshold: `passed=False`
    if evaluation couldn't produce a single real scored origin against
    fresh data at all (every region's `n_origins == 0` or NaN) -- a
    version that can't even produce a prediction against current data
    is caught here, not just versions whose accuracy number is bad.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)
    if raw_df.empty:
        raise ValueError(f"no data found in the warehouse for regions={list(regions)}")

    engineered = build_features(raw_df, holidays=holidays_df)
    min_history = getattr(forecaster, "lookback", 1)

    reports: list[EvaluationReport] = []
    for region in regions:
        region_df = (
            engineered[engineered["region"] == region]
            .sort_values("ts")
            .reset_index(drop=True)
        )
        if region_df.empty:
            continue
        report = evaluate_walk_forward(
            forecaster,
            region_df,
            horizon,
            n_origins=n_origins,
            min_history=min_history,
        )
        reports.append(report)

    scored = [r for r in reports if r.n_origins > 0 and not np.isnan(r.mape)]
    overall_mape = float(np.mean([r.mape for r in scored])) if scored else float("nan")

    passed = bool(scored)
    if passed and max_acceptable_mape is not None:
        passed = overall_mape <= max_acceptable_mape

    # Real coverage/bias visibility (`TODO.md` Phase 4) -- tagged, NOT
    # gated on: unlike `overall_mape` above, neither of these ever flips
    # `passed`. Reusing metrics `EvaluationReport` already computes (no
    # new computation) so a human/dashboard can see a candidate's real
    # coverage/bias without a hard-gate risking the exact failure mode
    # `training_worker._resolve_max_acceptable_mape`'s own real
    # 2026-08-12 bug already showed once (a hastily-added threshold that
    # silently mis-rejected a good candidate by comparing two non-
    # comparable metrics) -- watch real tag values across a few real
    # training cycles before ever turning either of these into a gate.
    overall_coverage = (
        float(np.mean([r.empirical_coverage for r in scored])) if scored else float("nan")
    )
    overall_bias = float(np.mean([r.mean_error for r in scored])) if scored else float("nan")

    client = MlflowClient()
    client.set_model_version_tag(
        model_name, str(version), "eval_gate_passed", str(passed)
    )
    client.set_model_version_tag(
        model_name, str(version), "eval_gate_mape", f"{overall_mape:.4f}"
    )
    client.set_model_version_tag(
        model_name, str(version), "eval_gate_coverage", f"{overall_coverage:.4f}"
    )
    client.set_model_version_tag(
        model_name, str(version), "eval_gate_bias_mw", f"{overall_bias:.2f}"
    )
    log.info(
        "evaluate.live_gate",
        model_name=model_name,
        version=str(version),
        passed=passed,
        overall_mape=overall_mape,
        overall_coverage=overall_coverage,
        overall_bias_mw=overall_bias,
    )

    return LiveEvaluationGateResult(
        passed=passed, overall_mape=overall_mape, reports=reports
    )
