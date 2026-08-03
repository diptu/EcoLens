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


def build_features(
    df: pd.DataFrame, holidays: pd.DataFrame | None = None
) -> pd.DataFrame:
    out = add_calendar_features(df, holidays=holidays)
    out = add_weather_derived(out)
    out = add_cross_region_context(out)
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
    + _LAG_COLUMNS
    + _ROLLING_COLUMNS
)

#: The subset of `FEATURE_COLUMNS` the feature scaler was actually fit
#: on (data-pipeline's `service/ml/data.py`'s `fit_scalers`/`NUMERIC_COLUMNS`) --
#: cyclical encodings are already in `[-1, 1]` and the calendar flags are
#: already `0`/`1`, so neither was scaled at training time either.
#: `api/v1/forecast/routes.py`'s inference path must only transform these
#: columns, not all of `FEATURE_COLUMNS`, or `StandardScaler.transform`
#: raises on the column-count mismatch.
NUMERIC_COLUMNS: tuple[str, ...] = (
    _RAW_CONTEXT_COLUMNS
    + _WEATHER_DERIVED_COLUMNS
    + _CROSS_REGION_COLUMNS
    + _LAG_COLUMNS
    + _ROLLING_COLUMNS
)
