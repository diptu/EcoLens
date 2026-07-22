"""Reshape raw AEMO MMS tables into canonical v1.0 documents.

Pure(ish) pandas transforms plus data-quality normalization — no
network I/O (see client.py for that). `build_day_frame` takes the
`{"DUNIT": df, "DREGION": df}` dict `client.py` decoded for one day
and produces that day's canonical rows.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ecolens.ingestion.sources.openelectricity import (
    GENERATION_COLUMNS,
    RENEWABLE_CANONICAL_COLUMNS,
    SCHEMA_VERSION,
)
from ecolens.shared.observability.logging import get_logger

from .schema import FUEL_MAP

log = get_logger(__name__)

# Columns that are never per-fuel — excluded from the FUEL_MAP rename/
# aggregation pass in `apply_fuel_map`.
_NON_CANONICAL_COLUMNS: frozenset[str] = frozenset(
    {
        "region",
        "ts",
        "demand_mw",
        "price_mwh",
        "scheduled_demand_mw",
        "interconnector_imports_mw",
        "interconnector_exports_mw",
        "net_import_mw",
        "battery_charge_mw",
    }
)

_GENERATION_DIAGNOSTIC_COLUMNS: tuple[str, ...] = (
    "coal_black_mw",
    "coal_brown_mw",
    "gas_ccgt_mw",
    "gas_ocgt_mw",
    "gas_other_mw",
    "hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
    "distillate_mw",
    "battery_discharge_mw",
    "pumped_hydro_mw",
)


def build_day_frame(
    tables: dict[str, pd.DataFrame], duid_map: dict[str, str]
) -> pd.DataFrame:
    """Turn one day's raw {"DUNIT", "DREGION"} tables into canonical rows.

    DUNIT (per-unit generation) has no REGIONID — generation can only
    be attributed at network level from this file. DREGION (demand/
    price/interconnector) is genuinely per-region. So this emits two
    row shapes per timestamp: one network-level row (region="NEM")
    carrying the fueltech mix, and one row per real NEM region
    (NSW1/QLD1/VIC1/SA1/TAS1) carrying demand/price/interconnector
    flow with generation columns left null. Both share the (region,
    ts) unique key, so they upsert independently.
    """
    per_fueltech = aggregate_duids_to_fueltechs(
        tables.get("DUNIT", pd.DataFrame()), duid_map
    )
    per_fueltech = apply_fuel_map(per_fueltech)
    per_fueltech = compute_derived(per_fueltech)

    per_region_meta = extract_regionsum(tables.get("DREGION", pd.DataFrame()))
    per_region_meta["network_code"] = "NEM"
    per_region_meta["source"] = "aemo_nem"
    per_region_meta["schema_version"] = SCHEMA_VERSION
    now = pd.Timestamp.now(tz="UTC")
    per_region_meta["ingested_at"] = now
    per_region_meta["fetched_at"] = now
    per_region_meta["data_quality_status"] = "final"

    return pd.concat([per_fueltech, per_region_meta], ignore_index=True)


# ──────────────────────────────────────────────────────────────────
# DUNIT → per-fueltech aggregation
# ──────────────────────────────────────────────────────────────────
def aggregate_duids_to_fueltechs(
    dunit_df: pd.DataFrame, duid_map: dict[str, str]
) -> pd.DataFrame:
    """Aggregate per-DUID dispatch values to network-level per-(ts, fueltech).

    DUNIT has no REGIONID — only DUID — so this cannot attribute
    generation to a specific NEM region; it aggregates to a single
    "NEM" row per ts instead (see `build_day_frame`'s docstring).
    """
    if dunit_df.empty:
        return pd.DataFrame(columns=["region", "ts", "fueltech", "mw", "mw_charge"])

    dunit_df = dunit_df.copy()
    # Two rows exist per (DUID, ts) when AEMO runs an intervention
    # pricing pass — INTERVENTION=="0" is the physical dispatch run;
    # including both would double-count generation.
    if "INTERVENTION" in dunit_df.columns:
        dunit_df = dunit_df[dunit_df["INTERVENTION"] == "0"]

    # Map DUIDs to fueltechs. Unmapped DUIDs go to "unknown" with
    # a warning (so on-call can add them to the map).
    dunit_df["fueltech"] = dunit_df["DUID"].map(duid_map)
    unmapped = dunit_df[dunit_df["fueltech"].isna()]["DUID"].unique()
    if len(unmapped):
        log.warning(
            "aemo_nem.duid.unmapped", count=len(unmapped), sample=list(unmapped[:10])
        )
        dunit_df["fueltech"] = dunit_df["fueltech"].fillna("unknown")

    # TOTALCLEARED is AEMO's cleared dispatch target per DUID —
    # positive for generation, negative for load (battery charging).
    dunit_df["mw"] = pd.to_numeric(dunit_df["TOTALCLEARED"], errors="coerce").fillna(
        0.0
    )
    dunit_df["ts"] = pd.to_datetime(
        dunit_df["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S", errors="coerce"
    )

    # Battery: split charge vs discharge
    dunit_df["mw_charge"] = dunit_df["mw"].where(dunit_df["mw"] < 0, 0.0).abs()
    dunit_df["mw"] = dunit_df["mw"].where(dunit_df["mw"] > 0, 0.0)

    # Aggregate by (ts, fueltech) for discharge
    discharge = (
        dunit_df.groupby(["ts", "fueltech"], as_index=False)["mw"]
        .sum()
        .rename(columns={"mw": "mw_discharge"})
    )
    # Aggregate charge separately (only battery has charge)
    charge = (
        dunit_df[dunit_df["fueltech"] == "battery"]
        .groupby(["ts"], as_index=False)["mw_charge"]
        .sum()
        .rename(columns={"mw_charge": "battery_charge_mw"})
    )
    # Wide pivot of discharge: one row per ts, columns = fueltech
    wide = discharge.pivot_table(
        index=["ts"],
        columns="fueltech",
        values="mw_discharge",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    # Join battery_charge
    if not charge.empty:
        wide = wide.merge(charge, on=["ts"], how="left")
        wide["battery_charge_mw"] = wide["battery_charge_mw"].fillna(0.0)
    wide["region"] = "NEM"
    return wide


# ──────────────────────────────────────────────────────────────────
# DREGION → demand, price, interconnector net flow
# ──────────────────────────────────────────────────────────────────
def extract_regionsum(df: pd.DataFrame) -> pd.DataFrame:
    """Per-region demand, price, and interconnector net flow from DREGION.

    DREGION carries RRP (regional reference price, $/MWh) and
    NETINTERCHANGE (net MW flowing into the region across all its
    interconnectors) directly — there's no separate interconnector
    table in this report to join against.
    """
    cols = [
        "region",
        "ts",
        "demand_mw",
        "price_mwh",
        "scheduled_demand_mw",
        "interconnector_imports_mw",
        "interconnector_exports_mw",
        "net_import_mw",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    if "INTERVENTION" in df.columns:
        df = df[df["INTERVENTION"] == "0"]
    out = pd.DataFrame()
    out["ts"] = pd.to_datetime(
        df["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S", errors="coerce"
    )
    out["region"] = df["REGIONID"]
    out["demand_mw"] = pd.to_numeric(df["TOTALDEMAND"], errors="coerce")
    out["price_mwh"] = pd.to_numeric(df["RRP"], errors="coerce")
    out["scheduled_demand_mw"] = pd.to_numeric(
        df.get("DEMANDFORECAST"), errors="coerce"
    )
    net_interchange = pd.to_numeric(df["NETINTERCHANGE"], errors="coerce")
    out["net_import_mw"] = net_interchange
    out["interconnector_imports_mw"] = net_interchange.clip(lower=0)
    out["interconnector_exports_mw"] = (-net_interchange).clip(lower=0)
    return out[cols]


# ──────────────────────────────────────────────────────────────────
# FUEL_MAP + derived columns
# ──────────────────────────────────────────────────────────────────
def apply_fuel_map(wide: pd.DataFrame) -> pd.DataFrame:
    """Rename fueltech columns using FUEL_MAP and aggregate duplicates."""
    if wide.empty:
        return wide
    new_cols: dict[str, str] = {}
    for col in wide.columns:
        if col in _NON_CANONICAL_COLUMNS:
            continue
        mapped = FUEL_MAP.get(col)
        if mapped is not None:
            new_cols[col] = mapped
    wide = wide.rename(columns=new_cols)
    # Aggregate columns that share a canonical name (shouldn't happen
    # with the current DUID map, but be safe).
    canonical_cols = [c for c in wide.columns if c not in _NON_CANONICAL_COLUMNS]
    wide_canon = wide[canonical_cols].T.groupby(level=0).sum().T
    # Rejoin with non-canonical columns
    for col in _NON_CANONICAL_COLUMNS:
        if col in wide.columns:
            wide_canon[col] = wide[col]
    return wide_canon


def col_or_zero(df: pd.DataFrame, name: str) -> pd.Series:
    # `df.get(name, 0)` degrades to a plain int (no .fillna()) when
    # the column was never present — e.g. no battery DUIDs that day.
    return df[name].fillna(0) if name in df.columns else pd.Series(0.0, index=df.index)


def compute_derived(wide: pd.DataFrame) -> pd.DataFrame:
    """Add total_generation_mw, renewable_proportion, and metadata."""
    if wide.empty:
        return wide
    # total_generation_mw (excluding battery charge)
    present_gen_cols = [c for c in GENERATION_COLUMNS if c in wide.columns]
    if present_gen_cols:
        wide["total_generation_mw"] = wide[present_gen_cols].sum(
            axis=1, skipna=True
        ) - col_or_zero(wide, "battery_charge_mw")
    else:
        wide["total_generation_mw"] = None
    # renewable_proportion — 0..100 (percent), matching
    # openelectricity.py's API-native scale so both sources are
    # directly comparable/unionable downstream.
    renewable_cols = [c for c in RENEWABLE_CANONICAL_COLUMNS if c in wide.columns]
    if renewable_cols and "total_generation_mw" in wide.columns:
        renew_gen = wide[renewable_cols].sum(axis=1, skipna=True)
        total = wide["total_generation_mw"].replace(0, pd.NA)
        wide["renewable_proportion"] = ((renew_gen / total) * 100).astype("Float64")
    else:
        wide["renewable_proportion"] = None
    # Metadata
    wide["network_code"] = "NEM"
    wide["source"] = "aemo_nem"
    wide["schema_version"] = SCHEMA_VERSION
    now = pd.Timestamp.now(tz="UTC")
    wide["ingested_at"] = now
    wide["fetched_at"] = now
    wide["data_quality_status"] = "final"  # NEMWeb files are settled data
    return wide


def aggregate_to_network(wide: pd.DataFrame) -> pd.DataFrame:
    """Roll up per-region rows to one row per (network="NEM", ts)."""
    if wide.empty or "region" not in wide.columns:
        return wide
    # Sum generation, demand; weighted-avg for proportions/intensities
    gen_cols = [c for c in GENERATION_COLUMNS if c in wide.columns]
    agg: dict[str, str] = {}
    for c in gen_cols:
        agg[c] = "sum"
    for c in (
        "demand_mw",
        "scheduled_demand_mw",
        "interconnector_imports_mw",
        "interconnector_exports_mw",
        "battery_charge_mw",
    ):
        if c in wide.columns:
            agg[c] = "sum"
    grouped = wide.groupby("ts", as_index=False).agg(agg)
    grouped["region"] = "NEM"
    # Recompute total_generation_mw at network level
    present = [c for c in GENERATION_COLUMNS if c in grouped.columns]
    grouped["total_generation_mw"] = grouped[present].sum(
        axis=1, skipna=True
    ) - col_or_zero(grouped, "battery_charge_mw")
    # Network-level interconnector flows = 0 (closed system)
    grouped["interconnector_imports_mw"] = 0
    grouped["interconnector_exports_mw"] = 0
    grouped["net_import_mw"] = 0
    # Re-apply FUEL_MAP and derived (in case columns changed)
    grouped = apply_fuel_map(grouped)
    grouped = compute_derived(grouped)
    return grouped


# ──────────────────────────────────────────────────────────────────
# Data-quality fixes + diagnostics (mirrors openelectricity.py)
# ──────────────────────────────────────────────────────────────────
def apply_data_quality_fixes(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the same data quality fixes as openelectricity.py:
      1. NaN → None (so MongoDB stores null, not NaN)
      2. emissions_intensity > 100 → /1000 (g/MWh → kg/MWh)
      3. interconnector_*_mw at network level → 0 (closed system)
      4. generation columns → clip(lower=0) (metering noise)

    renewable_proportion is already computed on the 0..100 scale in
    compute_derived (matching openelectricity.py) — no fixup needed here.
    """
    cleaned: list[dict[str, Any]] = []
    for doc in docs:
        for k, v in list(doc.items()):
            # Fix #1: NaN → None
            if isinstance(v, float) and pd.isna(v):
                doc[k] = None
        # Fix #2: emissions_intensity g/MWh → kg/MWh
        em = doc.get("emissions_intensity_kgco2e_per_mwh")
        if em is not None and em > 100:
            doc["emissions_intensity_kgco2e_per_mwh"] = em / 1000.0
        # Fix #3: network-level interconnector flows = 0
        if doc.get("region") == doc.get("network_code"):
            doc["interconnector_imports_mw"] = 0
            doc["interconnector_exports_mw"] = 0
            doc["net_import_mw"] = 0
        # Fix #4: clip generation columns to ≥ 0
        for col in _GENERATION_DIAGNOSTIC_COLUMNS:
            v = doc.get(col)
            if v is not None and v < 0:
                doc[col] = 0
        cleaned.append(doc)
    return cleaned


def diagnose(docs: list[dict[str, Any]]) -> None:
    """Log WEM-style data-quality warnings (e.g. fuel column all-zero)."""
    if not docs:
        return
    df = pd.DataFrame(docs)
    for col in _GENERATION_DIAGNOSTIC_COLUMNS:
        if col not in df.columns:
            continue
        non_null = df[col].dropna()
        if len(non_null) == 0:
            log.warning("aemo_nem.diag.all_null", column=col)
        elif (non_null == 0).all():
            log.warning(
                "aemo_nem.diag.all_zero",
                column=col,
                note="Possibly missing DUIDs in DUID_FUELTECH_MAP, or actual zero generation",
            )
