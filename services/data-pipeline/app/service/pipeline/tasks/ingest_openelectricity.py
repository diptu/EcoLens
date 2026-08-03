"""Ingest task: OpenElectricity generation mix + intensity.

Pulls the last `lookback_minutes` minutes of NEM + WEM data, pivots the
long-form SDK output into our wide `raw.openelectricity_mix` schema,
and lands+loads in one round-trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.service.emissions import fetch_emissions, fetch_network_data
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import standard_run

log = get_logger(__name__)

# Map OE fuel types to our column names. Anything not in this map lands
# in `other_mw` to keep the schema stable across upstream changes.
_FUEL_COLUMN_MAP: dict[str, str] = {
    "coal": "coal_mw",
    "black_coal": "coal_mw",
    "brown_coal": "coal_mw",
    "gas": "gas_mw",
    "ccgt": "gas_mw",
    "ocgt": "gas_mw",
    "hydro": "hydro_mw",
    "wind": "wind_mw",
    "solar": "solar_utility_mw",
    "solar_utility": "solar_utility_mw",
    "solar_rooftop": "solar_rooftop_mw",
    "battery": "battery_discharge_mw",
    "battery_discharging": "battery_discharge_mw",
    "battery_charging": "battery_charge_mw",
    "pumped_hydro": "pumped_hydro_mw",
    "biomass": "biomass_mw",
    "distillate": "distillate_mw",
    "diesel": "distillate_mw",
}

# Columns we always populate, in the order they should appear in the
# destination table.
_FUEL_COLUMNS: tuple[str, ...] = (
    "coal_mw",
    "gas_mw",
    "hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "battery_discharge_mw",
    "battery_charge_mw",
    "pumped_hydro_mw",
    "biomass_mw",
    "distillate_mw",
)

# Fallback interval when there are too few timestamps to infer the real
# one from the data (see `_infer_interval_hours`) -- NEM's dispatch
# cadence, the best available guess in that situation.
_FALLBACK_INTERVAL_HOURS = 5 / 60


@standard_run(
    source="openelectricity",
    table="openelectricity_mix",
)
async def run(lookback_minutes: int | None = None) -> pd.DataFrame:
    """Pull the last `lookback_minutes` from OE, return a wide-form df.

    The decorator handles anomaly scanning, DuckDB staging, publishing,
    and logging.
    """
    settings = get_settings()
    lookback = lookback_minutes or settings.default_lookback_minutes
    since = datetime.now(timezone.utc) - timedelta(minutes=lookback)

    # Network + region pairs we care about
    networks = [
        ("NEM", "NSW1"),
        ("NEM", "QLD1"),
        ("NEM", "VIC1"),
        ("NEM", "SA1"),
        ("NEM", "TAS1"),
        ("WEM", "WEM"),
    ]

    frames: list[pd.DataFrame] = []
    emissions_by_network: dict[str, pd.DataFrame] = {}
    for net, region in networks:
        try:
            long_df = await fetch_network_data(net, since=since)
            if long_df.empty:
                continue
        except Exception as e:
            # One region failing shouldn't kill the whole run; log and
            # continue. The decorator will record the run as success
            # if at least one region lands.
            log.warning("oe.region_failed", network=net, region=region, error=str(e))
            continue

        if net not in emissions_by_network:
            # Emissions is enrichment, not primary data -- a failure here
            # shouldn't drop the generation row that already succeeded,
            # it should just leave intensity_kg_per_mwh unpopulated for
            # this network (matching the pre-D71 default for everything).
            try:
                emissions_by_network[net] = await _fetch_total_emissions(net, since)
            except Exception as e:
                log.warning("oe.emissions_fetch_failed", network=net, error=str(e))
                emissions_by_network[net] = pd.DataFrame(
                    columns=["ts", "total_emissions_kg"]
                )

        wide = _pivot_long_to_wide(long_df, net, region, emissions_by_network[net])
        frames.append(wide)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    # Add bookkeeping columns
    out["source"] = "openelectricity"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    return out


async def _fetch_total_emissions(network: str, since: datetime) -> pd.DataFrame:
    """Total emissions (all fuel types summed) per `ts`, for one network.

    Returns columns `ts`, `total_emissions_kg` — empty (but correctly
    shaped, so downstream code doesn't need a special case) if OE
    returns nothing.
    """
    long_df = await fetch_emissions(network, since=since)
    if long_df.empty or "ts" not in long_df.columns or "value" not in long_df.columns:
        return pd.DataFrame(columns=["ts", "total_emissions_kg"])
    return (
        long_df.groupby("ts", as_index=False)["value"]
        .sum()
        .rename(columns={"value": "total_emissions_kg"})
    )


def _infer_interval_hours(ts: pd.Series) -> float:
    """Infer the data's interval length in hours from the spacing between
    consecutive timestamps, rather than assuming a fixed cadence — OE's
    query interval isn't pinned to an explicit value in `fetch_network_data`
    today, so hardcoding e.g. "5 minutes" here could silently drift out of
    sync with reality."""
    unique_ts = pd.Series(ts.unique()).sort_values()
    if len(unique_ts) < 2:
        return _FALLBACK_INTERVAL_HOURS
    median_delta = unique_ts.diff().dropna().median()
    return median_delta.total_seconds() / 3600


def _pivot_long_to_wide(
    long_df: pd.DataFrame,
    network: str,
    region: str,
    emissions_by_ts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convert OE long-form to our wide schema.

    Input columns (typical): `ts`, `fuel_type`, `value`
    Output columns: ts, network_code, region, <all _FUEL_COLUMNS>, total_generation_mw,
                     total_renewable_mw, demand_mw, price_mwh, intensity_kg_per_mwh

    `intensity_kg_per_mwh` is `total_emissions_kg / (total_generation_mw *
    interval_hours)` — `None` if `emissions_by_ts` wasn't supplied/empty,
    or for any interval where nothing generated (would be a division by
    zero otherwise).
    """
    if "ts" not in long_df.columns or "fuel_type" not in long_df.columns:
        # Defensive: if the SDK returns a different shape, log and return empty
        log.warning("oe.unexpected_shape", columns=list(long_df.columns))
        return pd.DataFrame()

    pivoted = long_df.pivot_table(
        index="ts",
        columns="fuel_type",
        values="value",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()

    # Rename to our column convention
    rename: dict[str, str] = {}
    for col in pivoted.columns:
        if col == "ts":
            continue
        mapped = _FUEL_COLUMN_MAP.get(str(col).lower(), None)
        if mapped is not None and mapped not in rename.values():
            rename[col] = mapped
        # We drop unmapped columns; OE occasionally adds new fuel types

    out = pivoted.rename(columns=rename)

    # Add missing fuel columns (default 0)
    for col in _FUEL_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0

    # Bookkeeping
    out["network_code"] = network
    out["region"] = region
    out["total_generation_mw"] = out[list(_FUEL_COLUMNS)].sum(axis=1)
    out["total_renewable_mw"] = (
        out["wind_mw"]
        + out["solar_utility_mw"]
        + out["solar_rooftop_mw"]
        + out["hydro_mw"]
        + out["biomass_mw"]
    )

    # Pull demand + price from the long-form df if present
    for kind, col in (("demand", "demand_mw"), ("price", "price_mwh")):
        rows = (
            long_df[long_df["fuel_type"] == kind]
            if "fuel_type" in long_df.columns
            else None
        )
        if rows is not None and not rows.empty:
            demand_by_ts = rows.groupby("ts")["value"].sum()
            out = out.merge(
                demand_by_ts.rename(col).reset_index(),
                on="ts",
                how="left",
            )
        else:
            out[col] = None

    out["intensity_kg_per_mwh"] = None
    if emissions_by_ts is not None and not emissions_by_ts.empty:
        interval_hours = _infer_interval_hours(out["ts"])
        merged = out.merge(emissions_by_ts, on="ts", how="left")
        generation_mwh = (merged["total_generation_mw"] * interval_hours).replace(
            0, np.nan
        )
        out["intensity_kg_per_mwh"] = merged["total_emissions_kg"] / generation_mwh

    return out
