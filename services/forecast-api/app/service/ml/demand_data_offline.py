"""Loads the demand model's (`DemandLSTM`/`DemandTFT`, `lstm_demand`/
`lstm_demand_tft`) training data from the R2-hosted `master.duckdb`
instead of the live Postgres warehouse marts -- the same real, already-
proven bootstrap path `energy_data_offline.py` built for
`EnergyForecastLSTM`, just producing `ml/data.py`'s `_TRAINING_COLUMNS`
shape instead of `energy_data.py`'s.

Why this exists (2026-08-10): `raw_marts.fct_energy_demand` (the live
Postgres path `ml/data.py`'s `load_training_data` reads) only has ~14
days of real history for NEM regions today -- the retrain earlier this
session had to shrink the target horizon from 7 days to 48 hours purely
because of this, not because of any modeling limitation. `master.duckdb`
has real data back to 2025-07-31 for all 6 regions on a uniform 30-min
grid (~371 days, ~17,800 rows/region) -- confirmed live, not assumed.
This is a real, substantial unlock: the *data* volume was the
constraint, and this file removes it for an initial/bootstrap training
pass, without touching Postgres's own 60-day retention policy at all
(left exactly as-is, per explicit instruction -- this is an additional
data source for training, not a replacement for the live serving/
incremental-retrain path, which keeps reading Postgres).

Reuses `energy_data_offline.py`'s R2 download/cache/credential-resolution
helpers directly (`ensure_master_table`) rather than duplicating them --
same physical file, same cache path, no reason for two copies of that
logic to drift.

**Grain note, stated honestly**: `master.duckdb` is a uniform 30-minute
grid for every region (`build_master_table.py`) -- unlike the live
marts, which mix NEM's native 5-minute and WEM's native 30-minute
cadence (the reason `ml/data.py`'s live-path loaders resample to hourly
at query time). This loader resamples to hourly here too, for the same
reason and to keep the resulting windows numerically consistent with
whatever a live/incremental retrain later produces from the Postgres
path -- not because 30-min itself would be wrong, just because the
model's `lookback`/`horizon` contract is defined in hours
(`Settings.model_demand_lookback`/`model_demand_horizon`), and mixing
two different grains across a bootstrap run and a later incremental
fine-tune would silently change what a lookback/horizon step means
between the two.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import pandas as pd

from app.service.ml.energy_data_offline import ensure_master_table

# `ml/data.py`'s `_TRAINING_COLUMNS`, minus `ts`/`region` -- kept as a
# private mirror rather than imported, since `ml/data.py`'s tuple is
# private too (leading underscore) and this is a different module's
# own read of the same real contract, not a re-export.
_DEMAND_NUMERIC_COLUMNS: tuple[str, ...] = (
    "demand_mw",
    "price_mwh",
    "total_generation_mw",
    "total_renewable_mw",
    "temp_c",
    "apparent_temp_c",
    "humidity_pct",
    "wind_speed_kmh",
)


def _read_master(regions: Sequence[str], *, force_refresh: bool) -> pd.DataFrame:
    path = ensure_master_table(force_refresh=force_refresh)
    with duckdb.connect(str(path), read_only=True) as conn:
        return conn.execute(
            "SELECT * FROM master WHERE region = ANY(?) ORDER BY region, bucket_ts",
            [list(regions)],
        ).df()


def load_demand_training_data_from_master(
    regions: Sequence[str],
    *,
    since: pd.Timestamp | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """`ml/data.py`'s `load_training_data` counterpart sourced from
    `master.duckdb` -- same output shape (`_TRAINING_COLUMNS`), real
    ~1-year history instead of the live marts' current ~14-46 days.

    AEMO's own `demand_mw`/`price_mwh` are used (not OpenElectricity's
    parallel columns) -- matches `load_energy_training_data_from_master`'s
    existing choice for the same fields, so a region's demand figure
    means the same real thing whichever bootstrap loader trained a
    given architecture. `total_generation_mw`/`total_renewable_mw` come
    from OpenElectricity (AEMO's `master.duckdb` columns don't include a
    renewable breakdown) -- also matching that same precedent.
    """
    df = _read_master(regions, force_refresh=force_refresh)

    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["bucket_ts"], utc=True),
            "region": df["region"],
            "demand_mw": pd.to_numeric(df["aemo_demand_mw"], errors="coerce"),
            "price_mwh": pd.to_numeric(df["aemo_price_mwh"], errors="coerce"),
            "total_generation_mw": pd.to_numeric(
                df["oe_total_generation_mw"], errors="coerce"
            ),
            "total_renewable_mw": pd.to_numeric(
                df["oe_total_renewable_mw"], errors="coerce"
            ),
            "temp_c": pd.to_numeric(df["temp_c"], errors="coerce"),
            "apparent_temp_c": pd.to_numeric(df["apparent_temp_c"], errors="coerce"),
            "humidity_pct": pd.to_numeric(df["humidity_pct"], errors="coerce"),
            "wind_speed_kmh": pd.to_numeric(df["wind_speed_kmh"], errors="coerce"),
        }
    )

    if since is not None:
        out = out[out["ts"] >= since]

    # Hourly resample -- see module docstring for why. `avg()` over each
    # numeric column, same "an hour with partial/no real coverage stays
    # honestly NaN rather than a fabricated value" semantics `ml/data.py`'s
    # own hourly aggregation already uses for the live path.
    out = out.set_index("ts")
    hourly = (
        out.groupby("region")[list(_DEMAND_NUMERIC_COLUMNS)]
        .resample("1h")
        .mean()
        .reset_index()
    )
    return hourly.sort_values(["region", "ts"]).reset_index(drop=True)


def load_holidays_from_master(*, force_refresh: bool = False) -> pd.DataFrame:
    """`ml/data.py`'s `load_holidays` counterpart sourced from
    `master.duckdb` -- same `(date, region)` shape. Identical to
    `energy_data_offline.load_holidays_from_master`; kept as a separate
    top-level function here (not just re-exported) so this module's own
    callers don't need to know the holiday data happens to live in the
    same physical file as the energy-forecast bootstrap path.
    """
    path = ensure_master_table(force_refresh=force_refresh)
    with duckdb.connect(str(path), read_only=True) as conn:
        return conn.execute(
            "SELECT DISTINCT CAST(bucket_ts AS DATE) AS date, region "
            "FROM master WHERE holiday_name IS NOT NULL"
        ).df()
