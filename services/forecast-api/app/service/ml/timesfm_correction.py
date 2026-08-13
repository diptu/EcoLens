"""Residual-correction layer on top of frozen TimesFM (`TODO.md`'s
"Step 3 -- make transfer learning for TimesFM actually true, the honest
way"): since the real TimesFM checkpoint can't be retrained or
fine-tuned (`app/models/timesfm_adapter.py`'s own docstring), this
module builds a small, genuinely trainable model *on top of* its frozen
zero-shot output -- a lightweight Ridge regression that learns to
predict TimesFM's own historical point-forecast error
(`Error_t = Actual_t - TimesFM_Pred_t`) from context available at the
forecast origin, and corrects future forecasts by that learned amount.
This is what makes "continuously adapts" honestly true for TimesFM's
contribution too: the Ridge model *can* be retrained as new data lands,
same as the LSTM/TFT incremental paths, even though TimesFM's own
weights never move.

Two entrypoints, matching `train_tft.py`'s split:

- `train_correction_model` -- the pure, DB/MLflow-free training loop.
  Takes an already-`build_features`'d multi-region DataFrame and a
  loaded `TimesFMForecaster` in, returns a `TimesFMCorrectionResult` out.
- `train_and_register_correction` -- the real orchestration: queries the
  warehouse, loads TimesFM, calls `train_correction_model`, and logs
  everything to MLflow under its own `timesfm_demand_correction`
  registry entry (never `lstm_demand`/`lstm_demand_tft` -- same
  naming-discipline note `train_tft.py` documents).

`CorrectedTimesFMForecaster` implements `ml/evaluate.py`'s `Forecaster`
protocol directly, so the existing walk-forward harness
(`evaluate_walk_forward`) scores the corrected system with zero harness
changes -- `evaluate_timesfm_correction_and_log` below is just that
harness pointed at three candidates (corrected, raw TimesFM, seasonal
baseline) instead of one.

**Design choice, stated honestly:** the correction is a single learned
per-horizon-step *shift* (`corrected = raw + ridge.predict(features)`),
applied identically to TimesFM's raw P10/P50/P90 before conformal
recalibration widens/tightens the shifted interval back to its real
target coverage. A separate model per quantile would be more expressive
but isn't what "lightweight regression on historical residuals" (the
brief this was built against) asked for -- this is the standard,
simplest form of that idea, not a corner cut silently.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import joblib
import mlflow
import mlflow.artifacts
import mlflow.sklearn
import numpy as np
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.preprocessing import StandardScaler

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.timesfm_adapter import (
    DEFAULT_MAX_CONTEXT,
    DEFAULT_MAX_HORIZON,
    TIMESFM_REPO_ID,
    TIMESFM_REVISION,
    TimesFMForecaster,
    load_timesfm_forecaster,
)
from app.service.ml.conformal import (
    ConformalCalibration,
    empirical_coverage,
    fit_conformal,
)
from app.service.ml.data import load_holidays, load_training_data
from app.service.ml.demand_data_offline import (
    load_demand_training_data_from_master,
    load_holidays_from_master,
)
from app.service.ml.evaluate import (
    BaselineForecaster,
    EvaluationReport,
    EvaluationRunResult,
    _infer_period_steps,
    evaluate_walk_forward,
)
from app.service.ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_features
from app.service.ml.train import mape, rmse
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha
from app.core.logging import get_logger

log = get_logger(__name__)

# `timesfm_demand_correction` -- a distinct registry entry from
# `lstm_demand`/`lstm_demand_tft` (same naming-discipline note
# `train_tft.py`'s `TFT_MODEL_NAME` documents): this is a Ridge
# regression's weights, not a comparable "version" of either.
TIMESFM_CORRECTION_MODEL_NAME = "timesfm_demand_correction"

# How many of `history`'s most recent 1-step-ahead points to re-forecast
# with the raw (uncorrected) TimesFM model, to build the "recent lag
# error" features -- kept small since each window value adds one more
# real TimesFM inference call per `predict()`/dataset row.
DEFAULT_LAG_WINDOWS: tuple[int, ...] = (1, 3)

# Real, measured need (2026-08-10): a first pass with a fixed `alpha=1.0`
# against `FEATURE_COLUMNS`' full ~40-column set (204 real train rows at
# `n_origins_per_region=60`) badly overfit -- held-out test MAPE got
# *worse* than raw TimesFM (4.45% -> 6.96%). `CorrectionConfig.ridge_alpha
# = None` (the default) cross-validates alpha per horizon-step target
# against this grid instead of trusting one guessed value, exactly the
# fix that real failure needed.
DEFAULT_RIDGE_ALPHAS: tuple[float, ...] = (1.0, 10.0, 50.0, 100.0, 300.0, 1000.0, 3000.0)


@dataclass
class CorrectionConfig:
    horizon: int = 6
    # Per-region evenly-spaced walk-forward origins used to build the
    # training dataset -- bounded (not "every row") because each origin
    # costs `1 + max(lag_windows)` real TimesFM inference calls (see
    # `_recent_lag_errors`); 60/region * 6 regions * 4 calls is already a
    # real multi-minute CPU cost, not free.
    n_origins_per_region: int = 60
    lag_windows: tuple[int, ...] = DEFAULT_LAG_WINDOWS
    # `None` (the default): cross-validate alpha per horizon-step target
    # via `RidgeCV(alphas=DEFAULT_RIDGE_ALPHAS, alpha_per_target=True)`,
    # fit only on the train split (cal/test stay untouched by this
    # search, same disjointness `cal_frac` already guarantees for
    # conformal calibration). A specific float pins a single shared alpha
    # instead -- mainly for reproducing/debugging one exact run.
    ridge_alpha: float | None = None
    conformal_alpha: float = 0.2
    # Chronological train/cal/test split of the *origin* dataset (not
    # `TrainConfig`'s raw-row fractions) -- train fits the Ridge
    # coefficients, cal is held out for `fit_conformal` (never seen by
    # Ridge, same disjointness reasoning `ml/train.py`'s own
    # `_split_val_for_calibration` documents), test is the honest
    # raw-vs-corrected comparison reported in `metrics`.
    train_frac: float = 0.6
    cal_frac: float = 0.2
    max_context: int = DEFAULT_MAX_CONTEXT


def _feature_names(horizon: int, lag_windows: tuple[int, ...]) -> list[str]:
    return (
        list(FEATURE_COLUMNS)
        + [f"timesfm_p50_h{i + 1}" for i in range(horizon)]
        + [f"timesfm_width_h{i + 1}" for i in range(horizon)]
        + [f"lag_error_{w}" for w in lag_windows]
    )


def _recent_lag_errors(
    forecaster: TimesFMForecaster, history: pd.DataFrame, lag_windows: tuple[int, ...]
) -> np.ndarray:
    """Real, causal "how wrong has raw TimesFM been lately" features --
    computed from `history` alone (never anything after the forecast
    origin), so this works identically whether called from the training
    dataset builder or `CorrectedTimesFMForecaster.predict` at serving
    time. For each of the last `max(lag_windows)` rows with a real next
    row inside `history`, re-forecasts 1 step ahead with the raw
    (uncorrected) model and scores it against what `history` itself
    already shows happened -- then averages those errors over each
    window in `lag_windows`. `0.0` (a neutral "no known recent error",
    not `NaN`) where fewer real points are available than a window needs
    -- an early origin having no error history yet is real and expected,
    not a reason to drop the row.
    """
    max_w = max(lag_windows)
    n = len(history)
    errors: list[float] = []
    for i in range(max(0, n - 1 - max_w), n - 1):
        sub_history = history.iloc[: i + 1]
        actual_next = history[TARGET_COLUMN].iloc[i + 1]
        if pd.isna(actual_next):
            continue
        _, p50_1, _ = forecaster.predict(sub_history, 1)
        if np.isnan(p50_1).any():
            continue
        errors.append(float(actual_next) - float(p50_1[0]))

    errors_arr = np.array(errors, dtype=np.float64)
    return np.array(
        [
            float(np.mean(errors_arr[-w:])) if errors_arr.size > 0 else 0.0
            for w in lag_windows
        ],
        dtype=np.float64,
    )


def _build_feature_row(
    forecaster: TimesFMForecaster,
    history: pd.DataFrame,
    horizon: int,
    lag_windows: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """One correction-model input row at `history`'s last timestep (the
    forecast origin), plus the raw TimesFM `(p10, p50, p90)` it was built
    from. `None` if TimesFM can't forecast from this origin, or the
    origin's own `FEATURE_COLUMNS` (exogenous/temporal/lag context --
    `ml/features.py`'s real weather/generation-mix/calendar/demand-lag
    columns) aren't fully populated -- same "unscored, not a hard
    failure" contract every other `Forecaster` in this codebase follows.
    """
    p10, p50, p90 = forecaster.predict(history, horizon)
    if np.isnan(p50).any():
        return None

    origin_row = history.iloc[-1]
    exogenous = origin_row[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    if np.isnan(exogenous).any():
        return None

    width = p90 - p10
    lag_errors = _recent_lag_errors(forecaster, history, lag_windows)
    features = np.concatenate([exogenous, p50, width, lag_errors])
    return features, p10, p50, p90


def build_correction_dataset(
    engineered: pd.DataFrame,
    forecaster: TimesFMForecaster,
    horizon: int,
    *,
    n_origins_per_region: int,
    lag_windows: tuple[int, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list]:
    """Real walk-forward pass over `engineered` (`build_features`'
    multi-region output) -- same evenly-spaced-origin selection
    `evaluate_walk_forward` uses (`np.linspace` over each region's own
    valid origin range), just building a *training* row per origin
    instead of only a scored metric. Returns `(X, y, p10, p50, p90,
    actual, meta)`: `y` is the real residual target
    (`actual - raw_p50`), `meta` is each row's `(region, ts)` so the
    caller can split chronologically without re-deriving it.
    """
    rows_x: list[np.ndarray] = []
    rows_y: list[np.ndarray] = []
    rows_p10: list[np.ndarray] = []
    rows_p50: list[np.ndarray] = []
    rows_p90: list[np.ndarray] = []
    rows_actual: list[np.ndarray] = []
    meta: list[tuple[str, pd.Timestamp]] = []

    for region, region_df in engineered.groupby("region"):
        region_df = region_df.sort_values("ts").reset_index(drop=True)
        n = len(region_df)
        last_valid_origin = n - horizon - 1
        first_valid_origin = 0
        if last_valid_origin < first_valid_origin:
            continue
        span = last_valid_origin - first_valid_origin + 1
        origins = sorted(
            set(
                np.linspace(
                    first_valid_origin,
                    last_valid_origin,
                    min(n_origins_per_region, span),
                    dtype=int,
                ).tolist()
            )
        )

        for origin in origins:
            history = region_df.iloc[: origin + 1]
            actual = (
                region_df[TARGET_COLUMN].iloc[origin + 1 : origin + 1 + horizon].to_numpy()
            )
            if len(actual) < horizon or np.isnan(actual).any():
                continue
            built = _build_feature_row(forecaster, history, horizon, lag_windows)
            if built is None:
                continue
            features, p10, p50, p90 = built
            rows_x.append(features)
            rows_y.append(actual - p50)
            rows_p10.append(p10)
            rows_p50.append(p50)
            rows_p90.append(p90)
            rows_actual.append(actual)
            meta.append((str(region), region_df["ts"].iloc[origin]))

    if not rows_x:
        return (
            np.empty((0, 0)),
            np.empty((0, horizon)),
            np.empty((0, horizon)),
            np.empty((0, horizon)),
            np.empty((0, horizon)),
            np.empty((0, horizon)),
            [],
        )

    return (
        np.stack(rows_x),
        np.stack(rows_y),
        np.stack(rows_p10),
        np.stack(rows_p50),
        np.stack(rows_p90),
        np.stack(rows_actual),
        meta,
    )


@dataclass
class TimesFMCorrectionResult:
    ridge: Ridge | RidgeCV
    feature_scaler: StandardScaler
    feature_names: list[str]
    calibration: ConformalCalibration
    lag_windows: tuple[int, ...]
    horizon: int
    n_train: int
    n_cal: int
    n_test: int
    metrics: dict[str, float] = field(default_factory=dict)


def train_correction_model(
    engineered: pd.DataFrame,
    forecaster: TimesFMForecaster,
    config: CorrectionConfig,
) -> TimesFMCorrectionResult:
    """The pure, DB/MLflow-free half -- `train_tft_model`'s counterpart
    for the correction layer. Raises `ValueError` if the walk-forward
    pass over `engineered` couldn't produce enough real scored origins to
    fit anything meaningful from, same "a 404-shaped problem, not a
    silent zero-sample fit" contract `train_model`/`train_tft_model`
    already follow.
    """
    x, y, p10, p50, p90, actual, meta = build_correction_dataset(
        engineered,
        forecaster,
        config.horizon,
        n_origins_per_region=config.n_origins_per_region,
        lag_windows=config.lag_windows,
    )
    if len(meta) < 10:
        raise ValueError(
            "not enough real scored TimesFM origins to train a correction "
            f"model (horizon={config.horizon}) -- got {len(meta)}, need >= 10"
        )

    order = np.argsort([ts for _, ts in meta])
    x, y, p10, p50, p90, actual = (
        x[order],
        y[order],
        p10[order],
        p50[order],
        p90[order],
        actual[order],
    )

    n = len(order)
    n_train = min(max(1, int(n * config.train_frac)), n - 2)
    n_cal = min(max(1, int(n * config.cal_frac)), n - n_train - 1)
    train_idx = slice(0, n_train)
    cal_idx = slice(n_train, n_train + n_cal)
    test_idx = slice(n_train + n_cal, n)

    feature_scaler = StandardScaler().fit(x[train_idx])
    x_train_scaled = feature_scaler.transform(x[train_idx])
    if config.ridge_alpha is None:
        ridge: Ridge | RidgeCV | RidgeCV = RidgeCV(
            alphas=DEFAULT_RIDGE_ALPHAS, alpha_per_target=True
        ).fit(x_train_scaled, y[train_idx])
    else:
        ridge = Ridge(alpha=config.ridge_alpha).fit(x_train_scaled, y[train_idx])

    def _corrected(idx: slice) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        correction = ridge.predict(feature_scaler.transform(x[idx]))
        return p10[idx] + correction, p50[idx] + correction, p90[idx] + correction

    cal_lo, _, cal_hi = _corrected(cal_idx)
    calibration = fit_conformal(actual[cal_idx], cal_lo, cal_hi, alpha=config.conformal_alpha)

    metrics: dict[str, float] = {}
    if test_idx.stop > test_idx.start:
        test_lo, test_mid, test_hi = _corrected(test_idx)
        cal_test_lo, cal_test_hi = calibration.apply(test_lo, test_hi)
        raw_test_mape = mape(p50[test_idx], actual[test_idx])
        corrected_test_mape = mape(test_mid, actual[test_idx])
        metrics = {
            "raw_test_mape": raw_test_mape,
            "raw_test_rmse": rmse(p50[test_idx], actual[test_idx]),
            "raw_test_coverage": empirical_coverage(
                actual[test_idx], p10[test_idx], p90[test_idx]
            ),
            "corrected_test_mape": corrected_test_mape,
            "corrected_test_rmse": rmse(test_mid, actual[test_idx]),
            "corrected_test_coverage_raw": empirical_coverage(
                actual[test_idx], test_lo, test_hi
            ),
            "corrected_test_coverage_calibrated": empirical_coverage(
                actual[test_idx], cal_test_lo, cal_test_hi
            ),
            # Real "Consistency" signal (2026-08-10, same real quantity
            # `ml/evaluate.py`'s `EvaluationReport.mean_interval_width`/
            # `ml/train.py`'s `test_interval_width_*_mw` track for the
            # other architectures) -- mean P10-P90 width in MW, before
            # and after this layer's own conformal recalibration.
            "raw_test_interval_width_mw": float(
                np.mean(p90[test_idx] - p10[test_idx])
            ),
            "corrected_test_interval_width_raw_mw": float(np.mean(test_hi - test_lo)),
            "corrected_test_interval_width_calibrated_mw": float(
                np.mean(cal_test_hi - cal_test_lo)
            ),
        }
        if raw_test_mape:
            metrics["mape_lift_pct"] = (
                100 * (raw_test_mape - corrected_test_mape) / raw_test_mape
            )

    return TimesFMCorrectionResult(
        ridge=ridge,
        feature_scaler=feature_scaler,
        feature_names=_feature_names(config.horizon, config.lag_windows),
        calibration=calibration,
        lag_windows=config.lag_windows,
        horizon=config.horizon,
        n_train=n_train,
        n_cal=n_cal,
        n_test=max(0, n - n_train - n_cal),
        metrics=metrics,
    )


@dataclass
class TrainAndRegisterCorrectionResult:
    run_id: str
    model_version: str | None
    metrics: dict[str, float]


def log_and_register_correction_run(
    result: TimesFMCorrectionResult,
    config: CorrectionConfig,
    regions: Sequence[str],
    model_name: str,
    *,
    register: bool,
    data_source: str,
) -> TrainAndRegisterCorrectionResult:
    """`log_and_register_run`'s counterpart for a frozen-base-model
    correction layer (`TODO.md`'s "Step 4 -- adapt MLflow tracking for a
    frozen asset"): rather than a torch checkpoint, this logs the real
    TimesFM checkpoint's own identity (`timesfm_repo_id`/
    `timesfm_revision` -- pinned tags, not a binary MLflow has no reason
    to own a second copy of) alongside the Ridge model's real weights
    (`serving/ridge_model.joblib`) and the honest raw-vs-corrected
    walk-forward metrics `train_correction_model` computed on a held-out
    test split.
    """
    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "horizon": config.horizon,
                "n_origins_per_region": config.n_origins_per_region,
                "lag_windows": ",".join(str(w) for w in config.lag_windows),
                "ridge_alpha": config.ridge_alpha,
                "conformal_alpha": config.conformal_alpha,
                "train_frac": config.train_frac,
                "cal_frac": config.cal_frac,
                "max_context": config.max_context,
                "regions": ",".join(regions),
                "data_source": data_source,
                "n_features": len(result.feature_names),
                "n_train": result.n_train,
                "n_cal": result.n_cal,
                "n_test": result.n_test,
            }
        )
        mlflow.set_tags(
            {
                "git_sha": git_sha() or "unknown",
                "architecture": "timesfm_correction",
                "base_model": "timesfm",
                "timesfm_repo_id": TIMESFM_REPO_ID,
                "timesfm_revision": TIMESFM_REVISION,
            }
        )
        if result.metrics:
            mlflow.log_metrics(result.metrics)
        mlflow.log_dict(result.calibration.to_dict(), "conformal_calibration.json")

        with tempfile.TemporaryDirectory() as tmpdir:
            joblib.dump(result.ridge, Path(tmpdir) / "ridge_model.joblib")
            joblib.dump(result.feature_scaler, Path(tmpdir) / "feature_scaler.joblib")
            (Path(tmpdir) / "feature_names.json").write_text(
                json.dumps(result.feature_names)
            )
            mlflow.log_artifacts(tmpdir, artifact_path="serving")

        # MLflow-native log (registry/pyfunc support) -- `mlflow.
        # register_model` (via `register_model` below) needs a real
        # `runs:/{run_id}/model` artifact to register from, same
        # two-artifacts-for-two-consumers reasoning `log_and_register_run`
        # documents for the torch models.
        mlflow.sklearn.log_model(result.ridge, artifact_path="model")

        run_id = run.info.run_id

    model_version = None
    if register:
        version = register_model(run_id, model_name)
        model_version = version.version

    return TrainAndRegisterCorrectionResult(
        run_id=run_id, model_version=model_version, metrics=result.metrics
    )


async def train_and_register_correction(
    model_name: str,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    config: CorrectionConfig | None = None,
    register: bool = True,
    since: pd.Timestamp | None = None,
    data_source: str = "fct_energy_demand",
) -> TrainAndRegisterCorrectionResult:
    """The real, DB + MLflow-backed entrypoint -- `ecolens-forecast
    train-timesfm-correction`'s real path."""
    settings = settings or get_settings()
    config = config or CorrectionConfig()
    configure_mlflow(settings)

    forecaster = load_timesfm_forecaster(
        max_context=config.max_context,
        max_horizon=max(config.horizon, DEFAULT_MAX_HORIZON),
    )

    if data_source == "r2_master":
        raw_df = load_demand_training_data_from_master(regions, since=since)
        holidays_df = load_holidays_from_master()
    else:
        async with get_session() as db:
            raw_df = await load_training_data(db, regions, since=since)
            holidays_df = await load_holidays(db)

    if raw_df.empty:
        raise ValueError(
            f"no training data found in {data_source!r} for regions={list(regions)}"
        )

    engineered = build_features(raw_df, holidays=holidays_df)
    result = train_correction_model(engineered, forecaster, config)
    return log_and_register_correction_run(
        result, config, regions, model_name, register=register, data_source=data_source
    )


@dataclass
class CorrectedTimesFMForecaster:
    """Wraps a frozen `TimesFMForecaster` + trained Ridge correction
    model behind `ml/evaluate.py`'s `Forecaster` protocol -- plugs
    directly into `evaluate_walk_forward` (`TODO.md`'s "Step 2 --
    formalize the walk-forward evaluation harness": this *is* that
    lock-down, reusing the existing harness rather than a parallel one)
    with zero harness changes, the same way `LSTMForecaster`/
    `TFTForecaster` already do for their architectures.
    """

    timesfm: TimesFMForecaster
    ridge: Ridge | RidgeCV
    feature_scaler: StandardScaler
    lag_windows: tuple[int, ...]
    horizon: int
    calibration: ConformalCalibration | None = None
    name: str = "timesfm_corrected"

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        built = _build_feature_row(self.timesfm, history, horizon, self.lag_windows)
        if built is None:
            return (np.full(horizon, np.nan),) * 3
        features, p10, p50, p90 = built
        correction = self.ridge.predict(self.feature_scaler.transform(features.reshape(1, -1)))[
            0
        ]
        lo, mid, hi = p10 + correction, p50 + correction, p90 + correction
        if self.calibration is not None:
            lo, hi = self.calibration.apply(lo, hi)
        return lo, mid, hi


def load_registered_correction_model(
    model_name: str,
    version: str | int,
    *,
    max_context: int = DEFAULT_MAX_CONTEXT,
) -> CorrectedTimesFMForecaster:
    """`load_registered_tft_model`'s counterpart for the correction
    layer -- downloads the Ridge model + feature scaler + conformal
    calibration `log_and_register_correction_run` persisted, and loads
    (compiling fresh, same real cost `load_timesfm_forecaster`'s own
    docstring discloses) the exact pinned TimesFM checkpoint the run's
    own `timesfm_repo_id`/`timesfm_revision` tags recorded.
    """
    client = MlflowClient()
    model_version = client.get_model_version(model_name, str(version))
    assert model_version.run_id is not None  # nosec B101 -- internal invariant for type-narrowing; every version `mlflow.register_model` creates has a run_id
    run_id = model_version.run_id
    run = client.get_run(run_id)
    params = run.data.params
    horizon = int(params["horizon"])
    lag_windows = tuple(int(w) for w in params["lag_windows"].split(","))

    with tempfile.TemporaryDirectory() as tmpdir:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path="serving", dst_path=tmpdir
        )
        ridge = joblib.load(Path(local_dir) / "ridge_model.joblib")
        feature_scaler = joblib.load(Path(local_dir) / "feature_scaler.joblib")

    try:
        cal_dict = mlflow.artifacts.load_dict(
            f"runs:/{run_id}/conformal_calibration.json"
        )
        calibration = ConformalCalibration.from_dict(cal_dict)
    except Exception:
        calibration = None

    forecaster = load_timesfm_forecaster(
        max_context=max_context, max_horizon=max(horizon, DEFAULT_MAX_HORIZON)
    )
    return CorrectedTimesFMForecaster(
        timesfm=forecaster,
        ridge=ridge,
        feature_scaler=feature_scaler,
        lag_windows=lag_windows,
        horizon=horizon,
        calibration=calibration,
        name=f"{model_name}_v{version}",
    )


async def evaluate_timesfm_correction_and_log(
    model_name: str,
    version: str | int,
    regions: Sequence[str],
    *,
    settings: Settings | None = None,
    horizon: int | None = None,
    n_origins: int = 10,
    baseline_period_steps: int | None = None,
) -> EvaluationRunResult:
    """`evaluate_tft_and_log`'s counterpart for the correction layer --
    same walk-forward harness, same corrected-vs-raw-vs-baseline
    three-way comparison shape `evaluate_and_log`'s
    calibrated/raw/baseline triple already established, same one-MLflow-
    run-tagged-`evaluation` logging convention. `raw` here is the plain
    `TimesFMForecaster` the registered correction version wraps -- so
    this run answers "did the correction layer actually help" against
    the exact same rolling origins, not a separately-run TimesFM
    evaluation that might land on different origins.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    corrected_forecaster = load_registered_correction_model(model_name, version)
    resolved_horizon = horizon or corrected_forecaster.horizon

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
                log.info("evaluate_timesfm_correction.skip_empty_region", region=region)
                continue

            # `TimesFMForecaster` already satisfies `Forecaster` as-is
            # (see `app/models/timesfm_adapter.py`) -- `replace(..., name=
            # ...)` just gives this evaluation run's raw candidate a
            # distinct metric-key name from the corrected one, same
            # `_raw` suffix convention `evaluate_and_log`'s own
            # `raw_forecaster` uses for the LSTM.
            raw_forecaster = replace(corrected_forecaster.timesfm, name="timesfm_raw")
            for candidate in (corrected_forecaster, raw_forecaster):
                report = evaluate_walk_forward(
                    candidate,
                    region_df,
                    resolved_horizon,
                    n_origins=n_origins,
                    min_history=1,
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
                log.info(
                    "evaluate_timesfm_correction.skip_baseline",
                    region=region,
                    reason=str(exc),
                )
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
