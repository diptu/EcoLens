"""Feature engineering for the demand-forecasting model (ECO-D31).

Input contract
--------------
Every function here operates on a long-form DataFrame — one row per
`(ts, region)` — shaped like what `analytics.fct_energy_demand` (D35's
`load_training_data` queries it) is meant to produce by joining the raw
ingestion tables (see `docs/data/ingestion-schema.md`): NEM/WEM dispatch
for demand, OpenElectricity for generation mix, BoM for weather. That dbt
model doesn't exist yet, so this module's expected input columns are
this ticket's own contract for it to satisfy, not a re-derivation of an
existing schema:

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

`build_features` calls every `add_*` function with this module's own
defaults, so its output columns match `FEATURE_COLUMNS` exactly. Calling
the `add_*` functions individually with custom `lags`/`windows` is fine
for exploration, but the result won't line up with `FEATURE_COLUMNS`
unless the defaults are used.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

TARGET_COLUMN = "demand_mw"

# Row-offsets (not minutes) -- NEM dispatch is 5-minute, WEM is 30-minute,
# so a fixed lag *count* means something different in wall-clock terms per
# region. That's an accepted trade-off: the alternative (resampling WEM to
# NEM's cadence, or vice versa) would fabricate data that was never
# actually observed.
_LAGS: tuple[int, ...] = (1, 2, 3, 6, 12)
_ROLLING_WINDOWS: tuple[int, ...] = (6, 12, 24)

# Below this, demand skews toward heating; above it, toward cooling. Not
# tuned per-region -- a single national comfort baseline is a
# simplification `add_weather_derived` makes deliberately, since
# per-region climate baselines are a bigger feature (and a modelling
# decision, not a data-engineering one) this ticket doesn't cover.
_COMFORT_TEMP_C = 18.0


def add_cyclical(df: pd.DataFrame, col: str, period: float) -> pd.DataFrame:
    """Sine/cosine-encode a cyclical numeric column (e.g. hour-of-day, period 24).

    Adds `{col}_sin`/`{col}_cos`; leaves `col` itself untouched. A plain
    integer like `hour` tells a model `23` and `0` are 23 apart when
    they're actually 1 apart — this encoding fixes that.
    """
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
    """Add hour/day-of-week/month (+ cyclical encodings), `is_weekend`, `is_holiday`.

    `holidays` is `raw.aemo_holidays`-shaped (`date`, optionally `region`).
    With a `region` column, a date only counts as a holiday for its own
    region (a NSW1 holiday shouldn't mark a WEM row); without one, every
    region is checked against the same date set. `holidays=None` (or
    empty) leaves `is_holiday` all `False` rather than raising — a caller
    without a holiday calendar handy still gets a usable feature set.
    """
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
    """Add lag and rolling-window features on `target_col`, grouped by `group_col`.

    Grouping by region (and sorting by `ts` within each group first)
    means a lag/rolling value never crosses a region boundary — row 0 of
    QLD1 doesn't get NSW1's demand as its "1 step ago" just because they
    were adjacent in an unsorted frame.

    Rolling means/stds are computed on `target_col.shift(1)` — i.e. they
    exclude the current row — so a rolling feature is never a function of
    the value it's trying to help predict. Expect `NaN` for the first
    `lag`/`window` rows of each region (warmup); that's intentional, not
    a bug — downstream training code drops or imputes them.
    """
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
    """Add heating/cooling-degree and apparent-temperature-deviation features.

    `heating_degrees`/`cooling_degrees` are the standard degree-day style
    transform (distance below/above a comfort baseline, floored at 0) —
    demand responds to *how far* the temperature is from comfortable, in
    either direction, not to the raw temperature itself.
    `apparent_temp_deviation_c` (feels-like minus actual) captures how
    much wind/humidity are amplifying the perceived temperature, which
    the raw `temp_c` alone misses.

    No-ops (adds nothing) for a column that isn't present, rather than
    raising — lets this run against a partial frame during exploration.
    """
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
    """Add system-wide demand context: total across regions at each `ts`, and this row's share of it.

    The regions are interconnected (NEM's 5 mainland-east regions trade
    over interconnectors; WEM is islanded and won't share a `ts` with any
    of them), so a region's demand isn't independent of what the rest of
    the system is doing — this gives the model that signal directly
    instead of relying on it to infer cross-region correlation on its own.
    """
    out = df.copy()
    total_by_ts = out.groupby(ts_col)[target_col].transform("sum")
    out["total_demand_all_regions_mw"] = total_by_ts
    out["demand_share_of_total"] = out[target_col] / total_by_ts.replace(0, np.nan)
    return out


def build_features(
    df: pd.DataFrame,
    holidays: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run the full feature pipeline, in the order each stage's inputs need.

    Order matters here: `add_cross_region_context` and
    `add_lag_and_rolling` both need `target_col` untouched by the earlier
    stages (they only add columns, but a caller relying on `df[target_col]`
    still being the raw value would be surprised otherwise), and
    `add_lag_and_rolling` sorts by `(region, ts)` last so every
    `add_*` before it can assume the caller's original row order.
    """
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

#: Every column `build_features` adds (plus the raw context columns it
#: passes through), in the order each group was produced. Model input
#: columns -- excludes `ts`, `region`, and `TARGET_COLUMN` itself.
FEATURE_COLUMNS: tuple[str, ...] = (
    _RAW_CONTEXT_COLUMNS
    + _CALENDAR_FLAG_COLUMNS
    + _CALENDAR_CYCLICAL_COLUMNS
    + _WEATHER_DERIVED_COLUMNS
    + _CROSS_REGION_COLUMNS
    + _LAG_COLUMNS
    + _ROLLING_COLUMNS
)

#: The subset of `FEATURE_COLUMNS` worth per-region `StandardScaler`-ing
#: (D32): unbounded magnitudes that vary by region/season. Cyclical
#: encodings are already in `[-1, 1]` and the calendar flags are already
#: `0`/`1`, so both are left out here even though they're still valid
#: model inputs via `FEATURE_COLUMNS`.
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
KNOWN_FUTURE_COLUMNS: tuple[str, ...] = (
    _CALENDAR_FLAG_COLUMNS + _CALENDAR_CYCLICAL_COLUMNS
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
