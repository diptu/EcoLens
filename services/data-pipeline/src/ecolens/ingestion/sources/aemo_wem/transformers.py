"""Reshape raw WEM SCADA/demand/price records into canonical v1.0 documents.

Pure(ish) pandas transforms plus data-quality normalization — no
network I/O (see client.py for that). `build_day_frame` takes the
`{"scada": [...], "demand": [...], "price": [...]}` dict `client.py`
fetched for one day and produces that day's canonical rows.

WEM is a single zone (the South West Interconnected System) — every
row uses region="WEM", unlike NEM which splits per-region demand/price
from a network-level fueltech row.
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

from .schema import FUEL_MAP, WEM_REGION

log = get_logger(__name__)

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
)


def build_day_frame(
    raw: dict[str, list[dict]], facility_map: dict[str, str]
) -> pd.DataFrame:
    """Turn one day's raw {"scada", "demand", "price"} records into canonical rows."""
    wide = aggregate_facilities_to_fueltechs(raw.get("scada", []), facility_map)
    wide = apply_fuel_map(wide)

    demand = extract_demand(raw.get("demand", []))
    if not demand.empty:
        wide = wide.merge(demand, on="ts", how="outer")

    price = extract_price(raw.get("price", []))
    if not price.empty:
        wide = wide.merge(price, on="ts", how="outer")

    return compute_derived(wide)


# ──────────────────────────────────────────────────────────────────
# facilityScada → per-fueltech aggregation
# ──────────────────────────────────────────────────────────────────
def aggregate_facilities_to_fueltechs(
    scada_rows: list[dict], facility_map: dict[str, str]
) -> pd.DataFrame:
    """Aggregate per-facility SCADA values to network-level per-(ts, fueltech).

    WEM's `quantity` field uses the same sign convention as NEM's
    TOTALCLEARED — positive for generation, negative for load
    (battery charging) — confirmed live against COLLIE_ESR1. Unlike
    TOTALCLEARED, `quantity` is energy in MWh for the 5-minute
    interval, not instantaneous MW — confirmed live: BW1_BLUEWATERS_G2
    (217 MW nameplate) reports ~17.9 MWh/interval, which ×12 (5 min =
    1/12 hour) gives ~215 MW, matching a baseload coal unit running
    near capacity. Scale by 12 to get average MW.
    """
    if not scada_rows:
        return pd.DataFrame(columns=["region", "ts"])

    df = pd.DataFrame(scada_rows).drop_duplicates(subset=["code", "dispatchInterval"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce") * 12
    df["fueltech"] = df["code"].map(facility_map)
    unmapped = df[df["fueltech"].isna()]["code"].unique()
    if len(unmapped):
        log.warning(
            "aemo_wem.facility.unmapped",
            count=len(unmapped),
            sample=list(unmapped[:10]),
        )
        df["fueltech"] = df["fueltech"].fillna("unknown")

    df["ts"] = pd.to_datetime(df["dispatchInterval"], errors="coerce")
    df["mw"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)

    # Battery: split charge vs discharge
    df["mw_charge"] = df["mw"].where(df["mw"] < 0, 0.0).abs()
    df["mw"] = df["mw"].where(df["mw"] > 0, 0.0)

    discharge = (
        df.groupby(["ts", "fueltech"], as_index=False)["mw"]
        .sum()
        .rename(columns={"mw": "mw_discharge"})
    )
    charge = (
        df[df["fueltech"] == "battery"]
        .groupby(["ts"], as_index=False)["mw_charge"]
        .sum()
        .rename(columns={"mw_charge": "battery_charge_mw"})
    )
    wide = discharge.pivot_table(
        index=["ts"],
        columns="fueltech",
        values="mw_discharge",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    if not charge.empty:
        wide = wide.merge(charge, on=["ts"], how="left")
        wide["battery_charge_mw"] = wide["battery_charge_mw"].fillna(0.0)
    wide["region"] = WEM_REGION
    return wide


def apply_fuel_map(wide: pd.DataFrame) -> pd.DataFrame:
    """Rename fueltech columns using FUEL_MAP and aggregate duplicates."""
    if wide.empty:
        return wide
    non_canonical = {"region", "ts", "battery_charge_mw"}
    new_cols: dict[str, str] = {}
    for col in wide.columns:
        if col in non_canonical:
            continue
        mapped = FUEL_MAP.get(col)
        if mapped is not None:
            new_cols[col] = mapped
    wide = wide.rename(columns=new_cols)
    canonical_cols = [c for c in wide.columns if c not in non_canonical]
    wide_canon = wide[canonical_cols].T.groupby(level=0).sum().T
    for col in non_canonical:
        if col in wide.columns:
            wide_canon[col] = wide[col]
    return wide_canon


# ──────────────────────────────────────────────────────────────────
# operationalDemandWithdrawal / referenceTradingPrice
# ──────────────────────────────────────────────────────────────────
def extract_demand(demand_rows: list[dict]) -> pd.DataFrame:
    if not demand_rows:
        return pd.DataFrame(columns=["ts", "demand_mw"])
    df = pd.DataFrame(demand_rows).drop_duplicates(subset=["dispatchInterval"])
    out = pd.DataFrame()
    out["ts"] = pd.to_datetime(df["dispatchInterval"], errors="coerce")
    out["demand_mw"] = pd.to_numeric(df["operationalDemand"], errors="coerce")
    return out


def extract_price(price_rows: list[dict]) -> pd.DataFrame:
    """30-min reference trading price — only aligns with every 6th 5-min
    SCADA/demand row; the merge in `build_day_frame` leaves price_mwh
    null on the timestamps in between, which is correct (WEM doesn't
    publish a 5-min price)."""
    if not price_rows:
        return pd.DataFrame(columns=["ts", "price_mwh"])
    df = pd.DataFrame(price_rows).drop_duplicates(subset=["tradingInterval"])
    out = pd.DataFrame()
    out["ts"] = pd.to_datetime(df["tradingInterval"], errors="coerce")
    out["price_mwh"] = pd.to_numeric(df["referenceTradingPrice"], errors="coerce")
    return out


# ──────────────────────────────────────────────────────────────────
# Derived columns + metadata
# ──────────────────────────────────────────────────────────────────
def compute_derived(wide: pd.DataFrame) -> pd.DataFrame:
    """Add total_generation_mw, renewable_proportion, and metadata.

    WEM is currently islanded (no interconnectors) — those columns
    are always 0, matching openelectricity.py's WEM convention.
    """
    if wide.empty:
        return wide
    present_gen_cols = [c for c in GENERATION_COLUMNS if c in wide.columns]
    battery_charge = (
        wide["battery_charge_mw"].fillna(0)
        if "battery_charge_mw" in wide.columns
        else 0.0
    )
    if present_gen_cols:
        wide["total_generation_mw"] = (
            wide[present_gen_cols].sum(axis=1, skipna=True) - battery_charge
        )
    else:
        wide["total_generation_mw"] = None

    renewable_cols = [c for c in RENEWABLE_CANONICAL_COLUMNS if c in wide.columns]
    if renewable_cols and "total_generation_mw" in wide.columns:
        renew_gen = wide[renewable_cols].sum(axis=1, skipna=True)
        total = wide["total_generation_mw"].replace(0, pd.NA)
        # 0..100 (percent), matching openelectricity.py's scale.
        wide["renewable_proportion"] = ((renew_gen / total) * 100).astype("Float64")
    else:
        wide["renewable_proportion"] = None

    wide["region"] = WEM_REGION
    wide["network_code"] = "WEM"
    wide["source"] = "aemo_wem"
    wide["schema_version"] = SCHEMA_VERSION
    wide["interconnector_imports_mw"] = 0
    wide["interconnector_exports_mw"] = 0
    wide["net_import_mw"] = 0
    now = pd.Timestamp.now(tz="UTC")
    wide["ingested_at"] = now
    wide["fetched_at"] = now
    wide["data_quality_status"] = "final"
    return wide


# ──────────────────────────────────────────────────────────────────
# Data-quality fixes + diagnostics (mirrors openelectricity.py / aemo_nem.py)
# ──────────────────────────────────────────────────────────────────
def apply_data_quality_fixes(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the same data quality fixes as aemo_nem.py:
      1. NaN → None (so MongoDB stores null, not NaN)
      2. emissions_intensity > 100 → /1000 (g/MWh → kg/MWh)
      3. generation columns → clip(lower=0) (metering noise)

    renewable_proportion is already 0..100; interconnector_*_mw is
    always 0 (WEM is islanded) — no fixups needed for either here.
    """
    cleaned: list[dict[str, Any]] = []
    for doc in docs:
        for k, v in list(doc.items()):
            if isinstance(v, float) and pd.isna(v):
                doc[k] = None
        em = doc.get("emissions_intensity_kgco2e_per_mwh")
        if em is not None and em > 100:
            doc["emissions_intensity_kgco2e_per_mwh"] = em / 1000.0
        for col in _GENERATION_DIAGNOSTIC_COLUMNS:
            v = doc.get(col)
            if v is not None and v < 0:
                doc[col] = 0
        cleaned.append(doc)
    return cleaned


def diagnose(docs: list[dict[str, Any]]) -> None:
    """Log data-quality warnings (e.g. fuel column all-zero for the whole window)."""
    if not docs:
        return
    df = pd.DataFrame(docs)
    for col in _GENERATION_DIAGNOSTIC_COLUMNS:
        if col not in df.columns:
            continue
        non_null = df[col].dropna()
        if len(non_null) == 0:
            log.warning("aemo_wem.diag.all_null", column=col)
        elif (non_null == 0).all():
            log.warning(
                "aemo_wem.diag.all_zero",
                column=col,
                note="Possibly missing facility codes in FACILITY_FUELTECH_MAP, or actual zero generation",
            )
