"""Feature engineering — **intentionally duplicated, byte-for-byte
(besides this docstring), from `data-pipeline`'s `app.service.ml.
energy_features`**, same reasoning `features.py`'s own docstring
documents for the single-task model: `EnergyForecastLSTM` was trained
against exactly the columns `build_features` produces here, in this
order (`FEATURE_COLUMNS`) — this service has to reproduce that pipeline
exactly at inference time. **Kept in sync by hand.**

Feature engineering for `EnergyForecastLSTM` (`app/models/
energy_forecast_lstm.py`) — the multi-task demand + generation-mix model.

Reconciles two things that don't line up by name or by grain:

1. **Names.** `services/ingestion/scripts/select_features.py`'s real,
   executed feature selection (`data/training/selected_features.json`)
   ran against `master.duckdb`'s columns (`aemo_demand_mw`,
   `oe_wind_mw`, `relative_humidity_pct`, ...). The live warehouse mart
   this service actually trains against
   (`raw_marts.fct_energy_demand`, built from `int_demand_with_weather.
   sql`) has differently-named columns (`demand_mw`, `wind_mw`,
   `humidity_pct`, ...) — see `_SELECTED_FEATURE_MAP` below for the
   explicit name reconciliation, feature by feature, not a blind
   rename.

2. **Grain.** `master.duckdb` bucket-averages everything onto a uniform
   30-minute grid (`services/ingestion/scripts/build_master_table.py`),
   so `selected_features.json`'s `..._lag_1`/`..._lag_336` mean exactly
   "30 minutes ago" / "7 days ago" for every region alike. The live
   mart is at each source's *native* cadence — NEM dispatch is 5-minute,
   WEM is 30-minute (`app/service/ml/features.py`'s own documented
   "accepted trade-off" note, which resolves this by NOT caring what a
   lag *count* means in wall-clock terms). This module makes the
   opposite, deliberate choice: because the real, executed feature
   selection specifically found particular *wall-clock* depths
   important (e.g. "7 days ago", "24h rolling std"), silently reusing
   `features.py`'s row-offset convention here would quietly change what
   those findings mean per-region (WEM's `lag_336` would stay 7 days,
   NEM's would become 28 hours) -- not an acceptable trade-off for a
   feature set whose whole justification is "this exact depth was
   measured to matter". `_steps_for_hours` converts a wall-clock depth
   into each region's own native step count instead.

`build_features` produces `FEATURE_COLUMNS` (model input) plus
`DEMAND_TARGET_COLUMN`/`GENERATION_TARGET_COLUMNS` (left as plain
columns, not consumed by feature engineering -- `energy_data.
build_training_windows` slices them out separately).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

DEMAND_TARGET_COLUMN = "demand_mw"

#: Same 5 buckets as `int_demand_with_weather.sql`'s generation CTE and
#: `EnergyForecastLSTM`'s `generation_sources` dim -- order matters, must
#: stay in sync with both (and with `service/ml/emission_factors.
#: GENERATION_BUCKET_FUEL_TYPES`'s keys, cross-checked in tests).
GENERATION_TARGET_COLUMNS: tuple[str, ...] = ("coal_mw", "gas_mw", "wind_mw", "solar_mw", "other_mw")

_NEM_REGIONS = frozenset({"NSW1", "QLD1", "VIC1", "SA1", "TAS1"})
_NATIVE_CADENCE_MINUTES: dict[str, int] = {**dict.fromkeys(_NEM_REGIONS, 5), "WEM": 30}
_DEFAULT_CADENCE_MINUTES = 30  # falls back to WEM's cadence for an unrecognised region code


def _native_cadence_minutes(region: str) -> int:
    return _NATIVE_CADENCE_MINUTES.get(region, _DEFAULT_CADENCE_MINUTES)


def _steps_for_hours(hours: float, region: str) -> int:
    """How many native rows correspond to `hours` wall-clock time for
    `region`. `max(1, ...)` -- a depth shorter than a region's own
    native cadence still means "at least the previous row", not `0`
    (a no-op lag)."""
    return max(1, round((hours * 60) / _native_cadence_minutes(region)))


#: The deepest wall-clock feature dependency `build_features` computes
#: (the 7-day/168h demand and wind lags) -- how far back a caller needs
#: real data before the *first* row of a `build_features` output has
#: every lag/rolling column fully populated (non-NaN).
MAX_LOOKBACK_HOURS: float = 24 * 7


def warmup_rows_for_region(region: str) -> int:
    """How many extra native rows a caller needs *before* the window it
    actually wants, so every row in that window has fully-populated
    (non-NaN) lag/rolling features once `build_features` runs --
    inference-time counterpart to `EnergyForecastDataset`'s
    training-time per-region windowing (which drops rows with a `NaN`
    instead, since it can afford to)."""
    return _steps_for_hours(MAX_LOOKBACK_HOURS, region)


def _per_region_transform(
    df: pd.DataFrame,
    col: str,
    hours: float,
    transform: Callable[[pd.Series, int], pd.Series],
    group_col: str = "region",
    ts_col: str = "ts",
) -> pd.Series:
    """Apply `transform(series, native_step_count)` independently per
    `group_col` group (never crosses a region boundary, same reasoning
    as `features.add_lag_and_rolling`), with `native_step_count` computed
    per-region from `hours` via `_steps_for_hours` -- the one thing this
    differs from `features.py`'s shared-step-count version. Returns a
    `Series` aligned to `df`'s original index."""
    ordered = df.sort_values([group_col, ts_col])
    result = pd.Series(index=ordered.index, dtype=float)
    for region, idx in ordered.groupby(group_col, sort=False).groups.items():
        steps = _steps_for_hours(hours, str(region))
        result.loc[idx] = transform(ordered.loc[idx, col], steps).to_numpy()
    return result.reindex(df.index)


def _fmt_hours(hours: float) -> str:
    """Deterministic, not "pretty" -- always `Xm`/`Xh`, never auto-folds
    into `Xd` (a `24`-vs-`1d` guessing rule silently broke every column
    name below it the first time this was written with one; caught by
    `build_features`'s own smoke test producing named columns that
    didn't match `FEATURE_COLUMNS`). Callers that want a week label pass
    `24 * 7` and get `"168h"`, not `"7d"` -- verbose but unambiguous."""
    if hours < 1:
        return f"{int(round(hours * 60))}m"
    return f"{int(hours) if hours == int(hours) else hours}h"


def add_lag_hours(df: pd.DataFrame, col: str, hours: float) -> pd.DataFrame:
    out = df.copy()
    out[f"{col}_lag_{_fmt_hours(hours)}"] = _per_region_transform(
        df, col, hours, lambda s, k: s.shift(k)
    )
    return out


def add_rolling_mean_hours(df: pd.DataFrame, col: str, hours: float) -> pd.DataFrame:
    out = df.copy()
    out[f"{col}_rolling_mean_{_fmt_hours(hours)}"] = _per_region_transform(
        df, col, hours, lambda s, k: s.shift(1).rolling(k, min_periods=1).mean()
    )
    return out


def add_rolling_std_hours(df: pd.DataFrame, col: str, hours: float) -> pd.DataFrame:
    out = df.copy()
    out[f"{col}_rolling_std_{_fmt_hours(hours)}"] = _per_region_transform(
        df, col, hours, lambda s, k: s.shift(1).rolling(k, min_periods=1).std()
    )
    return out


def add_calendar_features(
    df: pd.DataFrame,
    ts_col: str = "ts",
    holidays: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """`is_holiday`/`hour_sin`/`hour_cos`/`minute`/`day_of_year` --
    `is_holiday`/`hour_sin`/`hour_cos` reuse exactly `features.
    add_calendar_features`'s own logic (same holiday-matching contract);
    `minute`/`day_of_year` are new, both real `selected_features.json`
    findings `features.py`'s calendar block doesn't compute."""
    out = df.copy()
    ts = pd.to_datetime(out[ts_col], utc=True)

    fractional_hour = ts.dt.hour + ts.dt.minute / 60.0
    out["hour_sin"] = np.sin(2 * np.pi * fractional_hour / 24.0)
    out["hour_cos"] = np.cos(2 * np.pi * fractional_hour / 24.0)
    out["minute"] = ts.dt.minute
    out["day_of_year"] = ts.dt.dayofyear

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

    return out


def build_features(df: pd.DataFrame, holidays: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run the full pipeline. Expects `df` shaped like `raw_marts.
    fct_energy_demand`: one row per `(ts, region)`, with `demand_mw`,
    `price_mwh`, `wind_mw`, `solar_mw`, `total_generation_mw`,
    `humidity_pct`, `wind_gust_kmh`, `wind_direction_deg`, `cloud_oktas`
    all present (`int_demand_with_weather.sql`'s real output columns).
    """
    out = add_calendar_features(df, holidays=holidays)

    out = add_lag_hours(out, DEMAND_TARGET_COLUMN, 0.5)  # 30m
    out = add_lag_hours(out, DEMAND_TARGET_COLUMN, 6)
    out = add_lag_hours(out, DEMAND_TARGET_COLUMN, 12)
    out = add_lag_hours(out, DEMAND_TARGET_COLUMN, 24 * 7)
    out = add_rolling_mean_hours(out, DEMAND_TARGET_COLUMN, 24)
    for hours in (3, 6, 12, 24):
        out = add_rolling_std_hours(out, DEMAND_TARGET_COLUMN, hours)

    out = add_lag_hours(out, "wind_mw", 24)
    out = add_lag_hours(out, "wind_mw", 48)
    out = add_lag_hours(out, "wind_mw", 24 * 7)
    for hours in (3, 6, 12):
        out = add_rolling_std_hours(out, "wind_mw", hours)

    for hours in (3, 6):
        out = add_rolling_std_hours(out, "solar_mw", hours)

    for hours in (3, 6, 12):
        out = add_rolling_std_hours(out, "total_generation_mw", hours)

    return out


_PASSTHROUGH_COLUMNS: tuple[str, ...] = (
    "price_mwh",
    "humidity_pct",
    "wind_gust_kmh",
    "wind_direction_deg",
    "cloud_oktas",
)
_CALENDAR_COLUMNS: tuple[str, ...] = ("is_holiday", "hour_sin", "hour_cos", "minute", "day_of_year")
_DEMAND_LAG_COLUMNS: tuple[str, ...] = (
    f"{DEMAND_TARGET_COLUMN}_lag_30m",
    f"{DEMAND_TARGET_COLUMN}_lag_6h",
    f"{DEMAND_TARGET_COLUMN}_lag_12h",
    f"{DEMAND_TARGET_COLUMN}_lag_168h",
)
_DEMAND_ROLLING_COLUMNS: tuple[str, ...] = (
    f"{DEMAND_TARGET_COLUMN}_rolling_mean_24h",
    f"{DEMAND_TARGET_COLUMN}_rolling_std_3h",
    f"{DEMAND_TARGET_COLUMN}_rolling_std_6h",
    f"{DEMAND_TARGET_COLUMN}_rolling_std_12h",
    f"{DEMAND_TARGET_COLUMN}_rolling_std_24h",
)
_WIND_COLUMNS: tuple[str, ...] = (
    "wind_mw_lag_24h",
    "wind_mw_lag_48h",
    "wind_mw_lag_168h",
    "wind_mw_rolling_std_3h",
    "wind_mw_rolling_std_6h",
    "wind_mw_rolling_std_12h",
)
_SOLAR_COLUMNS: tuple[str, ...] = ("solar_mw_rolling_std_3h", "solar_mw_rolling_std_6h")
_TOTAL_GENERATION_COLUMNS: tuple[str, ...] = (
    "total_generation_mw_rolling_std_3h",
    "total_generation_mw_rolling_std_6h",
    "total_generation_mw_rolling_std_12h",
)

#: The 30 model input columns `build_features` produces -- a direct,
#: name-and-grain-reconciled realisation of `selected_features.json`'s
#: real top-30 (see this module's docstring for the exact reconciliation
#: rules), not a re-selection.
FEATURE_COLUMNS: tuple[str, ...] = (
    _PASSTHROUGH_COLUMNS
    + _CALENDAR_COLUMNS
    + _DEMAND_LAG_COLUMNS
    + _DEMAND_ROLLING_COLUMNS
    + _WIND_COLUMNS
    + _SOLAR_COLUMNS
    + _TOTAL_GENERATION_COLUMNS
)
