"""Feature engineering — **intentionally duplicated, byte-for-byte
(besides this docstring), from `data-pipeline`'s `app.service.ml.features`**.

`models/ml.py`'s DemandLSTM was trained against exactly the columns
`build_features` produces here, in this order (`FEATURE_COLUMNS`) — this
service has to reproduce that pipeline exactly at inference time to build
a valid model input. See `models/ml.py`'s docstring for why this is a
duplicated copy rather than an imported one, and the same "kept in sync
by hand" caveat applies here too.

Input contract
--------------
Every function here operates on a long-form DataFrame — one row per
`(ts, region)` — shaped like `raw_marts.fct_energy_demand`
(`service/ml/data.py`'s `load_latest_window`):

    ts                   timestamptz, UTC
    region               str — NSW1/QLD1/VIC1/SA1/TAS1/WEM
    demand_mw            float — the training target
    price_mwh            float, nullable
    total_generation_mw  float, nullable
    total_renewable_mw   float, nullable
    temp_c               float, nullable
    apparent_temp_c      float, nullable
    humidity_pct         float, nullable
    wind_speed_kmh       float, nullable
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

TARGET_COLUMN = "demand_mw"

_LAGS: tuple[int, ...] = (1, 2, 3, 6, 12)
_ROLLING_WINDOWS: tuple[int, ...] = (6, 12, 24)
_COMFORT_TEMP_C = 18.0

#: Same canonical region set `api/v1/regions/routes.py`'s own static list
#: uses -- one-hot region identity (`add_region_dummies`), added so a
#: single shared-weight model trained across multiple regions can learn
#: region-specific demand dynamics instead of relying on per-region
#: feature *scaling* alone to bridge the gap. Real, measured need: a
#: DemandLSTM trained across all 5 NEM regions with no region signal at
#: all scored 76.79% test_mape (vs. 3.73% single-region NSW1-only) --
#: TAS1's demand shape genuinely differs from NSW1's beyond just
#: magnitude, which scaling alone can't fix (root TODO.md's "NEM
#: (5-region sum)" item).
ALL_MODEL_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM")


def add_cyclical(df: pd.DataFrame, col: str, period: float) -> pd.DataFrame:
    out = df.copy()
    radians = 2 * np.pi * out[col].astype(float) / period
    out[f"{col}_sin"] = np.sin(radians)
    out[f"{col}_cos"] = np.cos(radians)
    return out


def add_calendar_features(
    df: pd.DataFrame,
    ts_col: str = "ts",
    holidays: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out[ts_col], utc=True)
    out["hour"] = ts.dt.hour
    out["day_of_week"] = ts.dt.dayofweek
    out["month"] = ts.dt.month
    out["is_weekend"] = out["day_of_week"].isin([5, 6])

    if holidays is not None and not holidays.empty:
        holiday_dates = pd.to_datetime(holidays["date"]).dt.date
        if "region" in holidays.columns and "region" in out.columns:
            pairs = set(zip(holidays["region"], holiday_dates, strict=True))
            out["is_holiday"] = [
                (r, d) in pairs for r, d in zip(out["region"], ts.dt.date, strict=True)
            ]
        else:
            out["is_holiday"] = ts.dt.date.isin(set(holiday_dates))
    else:
        out["is_holiday"] = False

    for col, period in (("hour", 24), ("day_of_week", 7), ("month", 12)):
        out = add_cyclical(out, col, period)

    return out


def add_lag_and_rolling(
    df: pd.DataFrame,
    target_col: str = TARGET_COLUMN,
    lags: Sequence[int] = _LAGS,
    windows: Sequence[int] = _ROLLING_WINDOWS,
    group_col: str = "region",
    ts_col: str = "ts",
) -> pd.DataFrame:
    out = df.sort_values([group_col, ts_col]).reset_index(drop=True)
    grouped_target = out.groupby(group_col, sort=False)[target_col]

    for lag in lags:
        out[f"{target_col}_lag_{lag}"] = grouped_target.shift(lag)

    for window in windows:
        out[f"{target_col}_rolling_mean_{window}"] = grouped_target.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
        )
        out[f"{target_col}_rolling_std_{window}"] = grouped_target.transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=1).std()
        )

    return out


def add_weather_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "temp_c" in out.columns:
        out["heating_degrees"] = (_COMFORT_TEMP_C - out["temp_c"]).clip(lower=0)
        out["cooling_degrees"] = (out["temp_c"] - _COMFORT_TEMP_C).clip(lower=0)
        if "apparent_temp_c" in out.columns:
            out["apparent_temp_deviation_c"] = out["apparent_temp_c"] - out["temp_c"]
    return out


def add_cross_region_context(
    df: pd.DataFrame,
    target_col: str = TARGET_COLUMN,
    group_col: str = "region",
    ts_col: str = "ts",
) -> pd.DataFrame:
    out = df.copy()
    total_by_ts = out.groupby(ts_col)[target_col].transform("sum")
    out["total_demand_all_regions_mw"] = total_by_ts
    out["demand_share_of_total"] = out[target_col] / total_by_ts.replace(0, np.nan)
    return out


def add_region_dummies(
    df: pd.DataFrame,
    regions: Sequence[str] = ALL_MODEL_REGIONS,
    group_col: str = "region",
) -> pd.DataFrame:
    """One-hot region identity, `region_{code}` per `regions` -- always
    all 6 canonical columns regardless of which regions are actually
    present in `df`, so a model trained on any subset (e.g. just the 5
    NEM regions) has the same fixed `FEATURE_COLUMNS` shape as one
    trained on a different subset later. `float` (0.0/1.0), matching
    `is_weekend`/`is_holiday`'s existing flag-column convention --
    trivially known for the entire forecast horizon (a series' region
    never changes), so this belongs in `KNOWN_FUTURE_COLUMNS` below, and
    is never scaled (`NUMERIC_COLUMNS` excludes it), same reasoning as
    those two flags.
    """
    out = df.copy()
    for code in regions:
        out[f"region_{code}"] = (out[group_col] == code).astype(float)
    return out


def build_features(
    df: pd.DataFrame, holidays: pd.DataFrame | None = None
) -> pd.DataFrame:
    out = add_calendar_features(df, holidays=holidays)
    out = add_weather_derived(out)
    out = add_cross_region_context(out)
    out = add_region_dummies(out)
    out = add_lag_and_rolling(out)
    return out


_RAW_CONTEXT_COLUMNS: tuple[str, ...] = (
    "price_mwh",
    "total_generation_mw",
    "total_renewable_mw",
    "temp_c",
    "apparent_temp_c",
    "humidity_pct",
    "wind_speed_kmh",
)
_CALENDAR_FLAG_COLUMNS: tuple[str, ...] = ("is_weekend", "is_holiday")
_CALENDAR_CYCLICAL_COLUMNS: tuple[str, ...] = (
    "hour_sin",
    "hour_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "month_sin",
    "month_cos",
)
_WEATHER_DERIVED_COLUMNS: tuple[str, ...] = (
    "heating_degrees",
    "cooling_degrees",
    "apparent_temp_deviation_c",
)
_CROSS_REGION_COLUMNS: tuple[str, ...] = (
    "total_demand_all_regions_mw",
    "demand_share_of_total",
)
_REGION_COLUMNS: tuple[str, ...] = tuple(f"region_{code}" for code in ALL_MODEL_REGIONS)
_LAG_COLUMNS: tuple[str, ...] = tuple(f"{TARGET_COLUMN}_lag_{lag}" for lag in _LAGS)
_ROLLING_COLUMNS: tuple[str, ...] = tuple(
    f"{TARGET_COLUMN}_rolling_{stat}_{window}"
    for window in _ROLLING_WINDOWS
    for stat in ("mean", "std")
)

FEATURE_COLUMNS: tuple[str, ...] = (
    _RAW_CONTEXT_COLUMNS
    + _CALENDAR_FLAG_COLUMNS
    + _CALENDAR_CYCLICAL_COLUMNS
    + _WEATHER_DERIVED_COLUMNS
    + _CROSS_REGION_COLUMNS
    + _REGION_COLUMNS
    + _LAG_COLUMNS
    + _ROLLING_COLUMNS
)

#: The subset of `FEATURE_COLUMNS` the feature scaler was actually fit
#: on (`service/ml/data.py`'s `fit_scalers`/`NUMERIC_COLUMNS`) --
#: cyclical encodings are already in `[-1, 1]`, the calendar flags and
#: region one-hot columns are already `0`/`1`, so none of those were
#: scaled at training time either. `api/v1/forecast/routes.py`'s
#: inference path must only transform these columns, not all of
#: `FEATURE_COLUMNS`, or `StandardScaler.transform` raises on the
#: column-count mismatch.
NUMERIC_COLUMNS: tuple[str, ...] = (
    _RAW_CONTEXT_COLUMNS
    + _WEATHER_DERIVED_COLUMNS
    + _CROSS_REGION_COLUMNS
    + _LAG_COLUMNS
    + _ROLLING_COLUMNS
)

#: `todo-model-training.md` Phase 2's TFT input-type classification --
#: which of `FEATURE_COLUMNS` are actually knowable for the *entire*
#: forecast horizon at serving time, not just at training time. The
#: calendar block is the only real "known future" input this project
#: has: `hour`/`day_of_week`/`month`/`is_weekend`/`is_holiday` (+ their
#: cyclical encodings) are pure functions of the timestamp itself, valid
#: arbitrarily far ahead. Everything else in `FEATURE_COLUMNS` needs a
#: live weather *forecast* feed (doesn't exist yet -- see
#: `OBSERVED_PAST_COLUMNS`'s docstring) or a live generation-mix/price
#: feed to be known ahead of time, neither of which this project has.
#: Added to this service's copy alongside the training-code migration
#: (this service trains TFT now too, not just serves LSTM) -- previously
#: only existed in data-pipeline's copy of this file.
KNOWN_FUTURE_COLUMNS: tuple[str, ...] = (
    _CALENDAR_FLAG_COLUMNS + _CALENDAR_CYCLICAL_COLUMNS + _REGION_COLUMNS
)

#: The complement of `KNOWN_FUTURE_COLUMNS` within `FEATURE_COLUMNS`:
#: real-valued only up to "now", never known ahead of the forecast
#: origin. `price_mwh`/`total_generation_mw`/`total_renewable_mw` are
#: live market feeds, not forecasts of themselves; `temp_c` et al. are
#: BoM *observations*, not a weather *forecast* feed (a real, explicitly
#: out-of-scope gap -- see `todo-model-training.md`'s non-goals); the
#: lag/rolling/cross-region columns are all direct functions of
#: `TARGET_COLUMN`'s own past values. A TFT decoder only ever sees
#: `KNOWN_FUTURE_COLUMNS` for future timesteps -- these are encoder-only
#: inputs.
OBSERVED_PAST_COLUMNS: tuple[str, ...] = tuple(
    c for c in FEATURE_COLUMNS if c not in KNOWN_FUTURE_COLUMNS
)
