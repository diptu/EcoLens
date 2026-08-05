"""Ingest task: OpenElectricity generation mix + intensity.

Pulls the last `lookback_minutes` minutes of NEM (per-region:
NSW1/QLD1/VIC1/SA1/TAS1) + WEM data, pivots the long-form SDK output
into our wide `raw.openelectricity_mix` schema. A plain fetch function
returning a raw `pd.DataFrame` -- same shape as `ingest_aemo_nem.py`/
`ingest_bom.py` -- `registry.run_source` applies staging/publishing/
logging dynamically at call time (2026-08-05, `oe` un-self-wrapped; see
`run`'s own docstring for why). `region` on the output is a real,
region-scoped OE query (`network_region=`, `todo-model-training.md`'s OE
region-join blocker, fixed the same day) — not a network-wide total
relabeled per region, which is what this used to silently do.

`start`/`end` (both required together) route to `_fetch_historical_range`
instead of the `lookback_minutes` path -- same `pipeline.backfill`
convention as `ingest_aemo_nem.py`/`ingest_bom.py`. One day at a time,
deliberately -- `emissions.py`'s module docstring covers why (the SDK's
own `to_records()` is O(n²) in point count; a single 3-day, 6-region
query took 86s live, a single-day one ~1-2s per call). Real, live-
verified 2026-08-05: this is what actually landed the first non-trivial
OE backfill (21 real days, all 6 regions) this codebase has ever had.

Ported verbatim from `data-pipeline`'s identical module (`services/
ingestion/TODO.md` Phase 1, "Migrate Ingest Tasks") -- no behavior
change. Live-verified against the real SDK from this service's own
`notebooks/ingestion.ipynb` before porting (real records shaped
`{interval, fueltech, power}`, matching `_pivot_long_to_wide`'s
assumptions below).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.service.emissions import fetch_emissions, fetch_network_data

log = get_logger(__name__)

# Map OE fuel types to our column names. Anything not in this map is
# genuinely dropped (there is no `other_mw` catch-all column in
# `raw.openelectricity_mix` -- the comment that used to claim one existed
# here was simply wrong, not describing real behavior) -- intentional for
# non-generation fuel_types (`imports`/`exports`/`interconnector`/
# `aggregator_vpp`/`aggregator_dr`), a real gap for anything else new OE
# adds later.
#
# Keys matching `openelectricity.types.UnitFueltechType` (the SDK's own
# canonical enum, read directly, not guessed) were added/corrected
# 2026-08-05 after live-verifying against the real API for the first
# time (previously unreachable -- `OE_API_KEY` was unset, see
# `emissions.py`'s module docstring): the *actual* values OE returns are
# `coal_black`/`coal_brown` (not `"coal"`/`"black_coal"`/`"brown_coal"`),
# `gas_ccgt`/`gas_ocgt`/`gas_steam`/`gas_recip`/`gas_wcmg` (not
# `"gas"`/`"ccgt"`/`"ocgt"`), `bioenergy_biomass`/`bioenergy_biogas` (not
# `"biomass"`), and `pumps` (not `"pumped_hydro"`) -- the old key set was
# never once observed live, and confirmed live 2026-08-05 to silently
# drop **every real coal_black/coal_brown/gas_ccgt/gas_ocgt row**, i.e.
# the single largest share of real generation, out of
# `total_generation_mw` -- a completely different, more severe bug than
# the region-scoping/timezone ones fixed alongside it, only found because
# fixing those finally made a real API response available to inspect.
_FUEL_COLUMN_MAP: dict[str, str] = {
    "coal_black": "coal_mw",
    "coal_brown": "coal_mw",
    "coal": "coal_mw",  # legacy/unconfirmed alias, kept harmless
    "black_coal": "coal_mw",
    "brown_coal": "coal_mw",
    "gas_ccgt": "gas_mw",
    "gas_ocgt": "gas_mw",
    "gas_steam": "gas_mw",
    "gas_recip": "gas_mw",
    "gas_wcmg": "gas_mw",
    "gas": "gas_mw",  # legacy/unconfirmed alias, kept harmless
    "ccgt": "gas_mw",
    "ocgt": "gas_mw",
    "hydro": "hydro_mw",
    "hydro_and_storage": "hydro_mw",
    "wind": "wind_mw",
    "wind_offshore": "wind_mw",
    "solar": "solar_utility_mw",
    "solar_thermal": "solar_utility_mw",
    "solar_utility": "solar_utility_mw",
    "solar_rooftop": "solar_rooftop_mw",
    "battery": "battery_discharge_mw",
    "battery_discharging": "battery_discharge_mw",
    "battery_charging": "battery_charge_mw",
    "pumps": "pumped_hydro_mw",
    "pumped_hydro": "pumped_hydro_mw",  # legacy/unconfirmed alias, kept harmless
    "bioenergy_biomass": "biomass_mw",
    "bioenergy_biogas": "biomass_mw",
    "biomass": "biomass_mw",  # legacy/unconfirmed alias, kept harmless
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


# Network + region pairs we care about. NEM's 5 entries each get a
# genuinely region-scoped query (`network_region=` below) -- WEM has no
# sub-regions of its own (its network_code IS its only region, same
# convention this codebase already uses for AEMO WEM), so it queries at
# network level with no `network_region`.
_NETWORKS: tuple[tuple[str, str], ...] = (
    ("NEM", "NSW1"),
    ("NEM", "QLD1"),
    ("NEM", "VIC1"),
    ("NEM", "SA1"),
    ("NEM", "TAS1"),
    ("WEM", "WEM"),
)


async def _fetch_all_regions(
    since: datetime, until: datetime | None = None
) -> pd.DataFrame:
    """One real, region-scoped fetch per entry in `_NETWORKS` -- shared
    by both `run()`'s `lookback_minutes` path and
    `_fetch_historical_range`'s per-day backfill path, so there's only
    one place that knows how to ask OE for "every region, for this
    window" correctly."""
    frames: list[pd.DataFrame] = []
    for net, region in _NETWORKS:
        # `todo-model-training.md`'s OE region-join blocker: passing
        # `network_region` here (fixed 2026-08-05, see `emissions.py`'s
        # module docstring) is what makes this a real per-region query
        # instead of 5 identical network-wide calls mislabeled by region.
        oe_region = region if net == "NEM" else None
        try:
            long_df = await fetch_network_data(
                net, since=since, network_region=oe_region, until=until
            )
            if long_df.empty:
                continue
        except Exception as e:
            # One region failing shouldn't kill the whole run; log and
            # continue. The decorator will record the run as success
            # if at least one region lands.
            log.warning("oe.region_failed", network=net, region=region, error=str(e))
            continue

        # Emissions is enrichment, not primary data -- a failure here
        # shouldn't drop the generation row that already succeeded, it
        # should just leave intensity_kg_per_mwh unpopulated for this
        # region (matching the pre-D71 default for everything). Fetched
        # per-region (not cached by network) for the same reason
        # generation is: NEM's 5 regions each need their own real
        # numbers, not one network-wide total copied 5 times.
        try:
            emissions_for_region = await _fetch_total_emissions(
                net, since, network_region=oe_region, until=until
            )
        except Exception as e:
            log.warning(
                "oe.emissions_fetch_failed", network=net, region=region, error=str(e)
            )
            emissions_for_region = pd.DataFrame(columns=["ts", "total_emissions_kg"])

        wide = _pivot_long_to_wide(long_df, net, region, emissions_for_region)
        frames.append(wide)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


async def _fetch_historical_range(start: datetime, end: datetime) -> pd.DataFrame:
    """Real historical backfill, one calendar day at a time --
    `[start.date(), end.date()]` inclusive, matching
    `ingest_aemo_nem.py`/`ingest_bom.py`'s own historical-range
    convention exactly (`pipeline.backfill`'s `backfill_day` always
    calls with `start == end`, one day per call).

    Deliberately day-chunked rather than one wide query for the whole
    range: `emissions.py`'s module docstring / this module's own
    docstring cover why (a single 3-day, 6-region query took 86s live --
    the SDK's own `to_records()` is O(n²) in point count -- a single day
    is ~1-2s per call instead).
    """
    frames: list[pd.DataFrame] = []
    current = start.date()
    while current <= end.date():
        day_start = datetime(
            current.year, current.month, current.day, tzinfo=timezone.utc
        )
        day_end = day_start + timedelta(days=1)
        day_df = await _fetch_all_regions(day_start, until=day_end)
        if not day_df.empty:
            frames.append(day_df)
        current += timedelta(days=1)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


async def run(
    lookback_minutes: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Pull OE data, return a wide-form df for raw.openelectricity_mix.

    `start`/`end` (both required together) route to the real historical
    per-day backfill instead of `lookback_minutes` -- see module
    docstring.

    Deliberately *not* `@standard_run`-decorated (2026-08-05, un-self-
    wrapped -- was previously decorated here, at import time, with a
    fixed `triggered_by="manual"` baked in via closure that
    `registry.run_source`'s own `triggered_by` argument couldn't
    override for this source, silently mislabeling every OE backfill's
    `meta._ingest_log` rows as `trigger='manual'` instead of
    `'backfill'` -- confirmed live: the dashboard's `pollBackfillSummary`
    filters on `trigger === "backfill"`, so a real, successfully-running
    OE backfill showed zero progress there). Now matches
    `ingest_aemo_nem.py`/`ingest_bom.py`'s own pattern exactly: a plain
    fetch function returning a raw `pd.DataFrame`, with
    `registry.SOURCES["oe"].self_wrapped = False` so `run_source`
    applies `standard_run` (anomaly scanning, DuckDB staging, RabbitMQ
    publish, `meta._ingest_log` logging) dynamically at call time, with
    whatever `triggered_by` the actual caller passed.
    """
    if start is not None and end is not None:
        out = await _fetch_historical_range(start, end)
    else:
        settings = get_settings()
        lookback = lookback_minutes or settings.default_lookback_minutes
        since = datetime.now(timezone.utc) - timedelta(minutes=lookback)
        out = await _fetch_all_regions(since)

    if out.empty:
        return pd.DataFrame()

    # Add bookkeeping columns
    out["source"] = "openelectricity"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    return out


async def _fetch_total_emissions(
    network: str,
    since: datetime,
    network_region: str | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Total emissions (all fuel types summed) per `ts`, for one network
    (or one region within it, if `network_region` is given), optionally
    bounded to `[since, until)` for a historical day-chunk.

    Returns columns `ts`, `total_emissions_kg` — empty (but correctly
    shaped, so downstream code doesn't need a special case) if OE
    returns nothing.
    """
    long_df = await fetch_emissions(
        network, since=since, network_region=network_region, until=until
    )
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

    # Map + aggregate to our column convention. More than one real OE
    # fuel_type can land on the same destination column -- e.g. "battery"
    # and "battery_discharging" both map to `battery_discharge_mw`, and
    # the real API sends both simultaneously (confirmed live 2026-08-05).
    # A naive 1:1 rename (the previous version of this code) silently
    # leaves the second one un-renamed instead of summing it in -- not
    # just a missed few MW: the un-renamed column (e.g. literally named
    # `"battery_discharging"`) has no matching column in
    # `raw.openelectricity_mix` at all, so the Postgres load itself
    # failed outright (`column "battery_discharging" ... does not
    # exist"`, confirmed live) the first time this ran end-to-end with a
    # real key. Grouping by destination column and summing is correct
    # for both reasons: no silent generation loss, and no orphaned
    # column reaching the load step.
    mapped_groups: dict[str, list[str]] = {}
    for col in pivoted.columns:
        if col == "ts":
            continue
        mapped = _FUEL_COLUMN_MAP.get(str(col).lower(), None)
        if mapped is not None:
            mapped_groups.setdefault(mapped, []).append(col)
        # We drop unmapped columns; OE occasionally adds new fuel types

    out = pivoted[["ts"]].copy()
    for dest_col, source_cols in mapped_groups.items():
        out[dest_col] = pivoted[source_cols].sum(axis=1)

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
