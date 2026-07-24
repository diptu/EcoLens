"""Reshape long-form per-metric DataFrames into canonical v1.0 documents.

Pure(ish) pandas transforms plus data-quality normalization — no
network I/O (see client.py for that). `merge_network`/`minimal_doc`
take the dict of per-metric DataFrames that `engine.py` collected for
one network and produce the final wide-form canonical rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .schema import (
    DATA_QUALITY_NORMALIZATION,
    FUEL_MAP,
    GENERATION_COLUMNS,
    OUTPUT_COLUMNS,
    RENEWABLE_CANONICAL_COLUMNS,
    SCHEMA_VERSION,
)

log = get_logger(__name__)


def normalize_data_quality(raw: str | None) -> str:
    """Map any raw status string to a canonical tier.

    Returns one of: "forecast" | "realtime" | "preliminary" |
                   "final" | "revised" | "unknown"
    """
    if not raw:
        return "unknown"
    norm = DATA_QUALITY_NORMALIZATION.get(str(raw).lower().strip())
    return norm if norm is not None else "unknown"


def merge_network(
    network: str,
    frames: dict[str, pd.DataFrame | None],
    since: datetime,
) -> pd.DataFrame | None:
    """Merge every metric for one network into the v1.0 canonical schema."""
    power = frames.get("power")
    if power is None or power.empty:
        log.warning("oe.merge.no_power", network=network)
        return minimal_doc(frames, network, since)

    # 1. Pivot to wide: index=ts, region; columns=fuel; values=mw
    wide = power.pivot_table(
        index=["ts", "region"],
        columns="fuel",
        values="mw",
        aggfunc="sum",
        fill_value=0.0,
    )

    # 2. Rename columns using FUEL_MAP. v1.0 does NOT aggregate
    #    after the rename — each canonical column has at most one
    #    raw fueltech (since FUEL_MAP uses 1:1 mapping for coal/gas
    #    after disaggregation). Only biomass is still aggregated
    #    (bioenergy_biogas + bioenergy_biomass → biomass_mw).
    new_cols: dict[str, str] = {}
    for col in wide.columns:
        mapped = FUEL_MAP.get(col.lower())
        if mapped is not None:
            new_cols[col] = mapped
        else:
            log.debug("oe.merge.unmapped_fuel", network=network, fuel=col)
    wide = wide.rename(columns=new_cols)

    # 2b. Aggregate ONLY columns that share a canonical name
    #     (this is the bioenergy case in v1.0 — biogas + biomass
    #     both map to biomass_mw). Coal and gas are 1:1 now.
    wide = wide.T.groupby(level=0).sum().T

    # 3. Outer-join each scalar metric on (ts, region). Curtailment is
    #    scalar per-fuel here too — curtailment_solar_utility and
    #    curtailment_wind are separate real API metrics, each
    #    returning one "_total" series (secondary_grouping has no
    #    effect on curtailment), so they join like any other
    #    scalar metric rather than needing a fuel pivot.
    for metric_name, col_name in (
        ("price", "price_mwh"),
        ("demand", "demand_mw"),
        ("emissions", "emissions_intensity_kgco2e_per_mwh"),
        ("renewable_proportion", "renewable_proportion"),
        ("market_value", "market_value"),
        ("curtailment_solar_utility", "curtailment_solar_utility_mw"),
        ("curtailment_wind", "curtailment_wind_mw"),
    ):
        df = frames.get(metric_name)
        if df is not None and not df.empty:
            df_indexed = df.set_index(["ts", "region"])[[col_name]]
            wide = wide.join(df_indexed, how="outer")

    # 5. Outer-join interconnector_imports / interconnector_exports
    for flow_metric, target_col in (
        ("interconnector_imports", "interconnector_imports_mw"),
        ("interconnector_exports", "interconnector_exports_mw"),
    ):
        df = frames.get(flow_metric)
        if df is not None and not df.empty:
            wide = wide.join(
                df.rename(columns={"flow_mw": target_col}).set_index(["ts", "region"])[
                    [target_col]
                ],
                how="outer",
            )

    def _col_or_zero(name: str) -> pd.Series:
        # `wide.get(name, 0)` degrades to a plain int (no .fillna())
        # when the column never got joined in — e.g. WEM genuinely
        # has no interconnector data. Return a zero Series instead.
        return (
            wide[name].fillna(0)
            if name in wide.columns
            else pd.Series(0.0, index=wide.index)
        )

    # 6. net_import_mw = imports - exports
    wide["net_import_mw"] = _col_or_zero("interconnector_imports_mw") - _col_or_zero(
        "interconnector_exports_mw"
    )

    # 7. Compute renewable_proportion if API didn't return it.
    if (
        "renewable_proportion" not in wide.columns
        or wide["renewable_proportion"].isna().all()
    ):
        renewable_cols = [c for c in RENEWABLE_CANONICAL_COLUMNS if c in wide.columns]
        # Not every fuel type reports data in every fetch window (e.g.
        # WEM has no coal_brown; a window may have zero gas_other
        # readings) — pivot_table only creates columns for fuels
        # actually present, so index against present_gen_cols, not
        # the full GENERATION_COLUMNS tuple.
        present_gen_cols = [c for c in GENERATION_COLUMNS if c in wide.columns]
        if renewable_cols:
            total_gen = wide[present_gen_cols].sum(axis=1, skipna=True)
            renew_gen = wide[renewable_cols].sum(axis=1, skipna=True)
            # API-native scale is 0..100 (confirmed live: unit "%"),
            # not 0..1 — match it so the column has one consistent
            # scale regardless of which path populated it.
            wide["renewable_proportion"] = (
                (renew_gen / total_gen.replace(0, pd.NA)) * 100
            ).astype("Float64")
        else:
            wide["renewable_proportion"] = None

    # 7b. Compute market_value if API didn't return it.
    #     market_value = price_mwh * demand_mw * (interval_hours)
    #     For 5-min intervals, interval_hours = 5/60.
    if "market_value" not in wide.columns or wide["market_value"].isna().all():
        if "price_mwh" in wide.columns and "demand_mw" in wide.columns:
            # Default interval = 5min = 1/12 hour
            wide["market_value"] = (
                pd.to_numeric(wide["price_mwh"], errors="coerce")
                * pd.to_numeric(wide["demand_mw"], errors="coerce")
                * (5.0 / 60.0)
            )

    # 8. Recompute total_generation_mw (excluding battery_charge).
    present_gen_cols = [c for c in GENERATION_COLUMNS if c in wide.columns]
    wide["total_generation_mw"] = wide[present_gen_cols].sum(
        axis=1, skipna=True
    ) - _col_or_zero("battery_charge_mw")

    # 9. Reset index, fill missing canonical columns with None.
    wide = wide.reset_index()
    for col in OUTPUT_COLUMNS:
        if col not in wide.columns:
            wide[col] = None

    # 10. Cast numerics.
    numeric_cols = [
        "demand_mw",
        "price_mwh",
        "market_value",
        "coal_black_mw",
        "coal_brown_mw",
        "gas_ccgt_mw",
        "gas_ocgt_mw",
        "gas_other_mw",
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_discharge_mw",
        "battery_charge_mw",
        "pumped_hydro_mw",
        "biomass_mw",
        "distillate_mw",
        "curtailment_solar_utility_mw",
        "curtailment_wind_mw",
        "emissions_intensity_kgco2e_per_mwh",
        "interconnector_imports_mw",
        "interconnector_exports_mw",
        "net_import_mw",
        "renewable_proportion",
    ]
    for col in numeric_cols:
        if col in wide.columns:
            wide[col] = pd.to_numeric(wide[col], errors="coerce")

    # 11. Metadata
    wide["network_code"] = network
    wide["source"] = "openelectricity"
    wide["schema_version"] = SCHEMA_VERSION
    now = pd.Timestamp.now(tz="UTC")
    wide["ingested_at"] = now
    wide["fetched_at"] = now
    wide["ingest_run_id"] = None  # filled by the caller

    # 12. Default data_quality_status if not present
    if (
        "data_quality_status" not in wide.columns
        or wide["data_quality_status"].isna().all()
    ):
        wide["data_quality_status"] = "realtime"

    return wide[OUTPUT_COLUMNS]


def minimal_doc(
    frames: dict[str, pd.DataFrame | None],
    network: str,
    since: datetime,
) -> pd.DataFrame | None:
    """If `power` is missing but other metrics are present, still emit rows."""
    scaffold: pd.DataFrame | None = None
    for metric_name, col_name in (
        ("price", "price_mwh"),
        ("demand", "demand_mw"),
        ("emissions", "emissions_intensity_kgco2e_per_mwh"),
        ("renewable_proportion", "renewable_proportion"),
        ("market_value", "market_value"),
    ):
        df = frames.get(metric_name)
        if df is not None and not df.empty:
            indexed = df.set_index(["ts", "region"])[[col_name]]
            scaffold = (
                indexed if scaffold is None else scaffold.join(indexed, how="outer")
            )
    if scaffold is None:
        return None
    out = scaffold.reset_index()
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out["network_code"] = network
    out["source"] = "openelectricity"
    out["schema_version"] = SCHEMA_VERSION
    now = pd.Timestamp.now(tz="UTC")
    out["ingested_at"] = now
    out["fetched_at"] = now
    out["data_quality_status"] = "realtime"
    return out[OUTPUT_COLUMNS]


def diagnose_data_quality(df: pd.DataFrame) -> None:
    """Detect WEM-style data gaps: a fueltech that's 0 for the whole window.

    WEM has historically had patchy field population. A fuel type
    that is 0 for the entire fetch window is almost certainly a
    data-source gap, not "actually zero generation". Logs a warning
    so the on-call can investigate.
    """
    network = df["network_code"].iloc[0] if not df.empty else "?"
    for col in (
        "coal_black_mw",
        "coal_brown_mw",
        "gas_ccgt_mw",
        "gas_ocgt_mw",
        "gas_other_mw",
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_discharge_mw",
        "biomass_mw",
        "distillate_mw",
    ):
        if col not in df.columns:
            continue
        non_null = df[col].dropna()
        if len(non_null) == 0:
            log.warning("oe.diag.all_null", column=col, network=network)
        elif (non_null == 0).all():
            log.warning(
                "oe.diag.all_zero",
                column=col,
                network=network,
                note="Likely WEM data-source gap, not actual zero generation",
            )


# ════════════════════════════════════════════════════════════════════
# Schema migration helper (v0.x → v1.0)
# ════════════════════════════════════════════════════════════════════
def migrate_v0_to_v1(doc: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v0.x OpenElectricity document to v1.0 in place.

    Used by the data-pipeline's one-time migration job when upgrading
    the schema. The function:
      1. Splits `coal_mw` into `coal_black_mw` + `coal_brown_mw` if
         the per-coal-type columns aren't already present.
      2. Splits `gas_mw` into `gas_ccgt_mw` + `gas_ocgt_mw` + `gas_other_mw`.
      3. Renames `status` → `data_quality_status`.
      4. Renames `flow_imports_mw` → `interconnector_imports_mw` (and exports).
      5. Drops `curtailment_mw` (the total) — derive from per-fuel if needed.
      6. Adds `schema_version: "1.0"`.

    Returns the migrated document. Safe to call on documents that
    are already v1.0 (no-op).
    """
    if doc.get("schema_version") == SCHEMA_VERSION:
        return doc

    # Coal split
    if "coal_mw" in doc and "coal_black_mw" not in doc:
        # We can't recover the split from the aggregated value.
        # Default to black for WEM (mostly black coal); leave null for NEM.
        # In practice, the v0 docs came from the old buggy fetcher
        # which had coal_black + coal_brown as separate columns anyway
        # (the FUEL_MAP rename was broken). So try to find them.
        if "coal_black" in doc:
            doc["coal_black_mw"] = doc["coal_black"]
        if "coal_brown" in doc:
            doc["coal_brown_mw"] = doc["coal_brown"]
        # Drop the (incorrect) aggregated value
        doc.pop("coal_mw", None)

    # Gas split
    if "gas_mw" in doc and "gas_ccgt_mw" not in doc:
        if "gas_ccgt" in doc:
            doc["gas_ccgt_mw"] = doc["gas_ccgt"]
        if "gas_ocgt" in doc:
            doc["gas_ocgt_mw"] = doc["gas_ocgt"]
        # Aggregate the 3 minor types into gas_other_mw
        gas_other = sum(
            float(doc.pop(k, 0) or 0) for k in ("gas_recip", "gas_steam", "gas_wcmg")
        )
        if gas_other or "gas_other_mw" in doc:
            doc["gas_other_mw"] = gas_other
        doc.pop("gas_mw", None)

    # Status rename
    if "status" in doc and "data_quality_status" not in doc:
        doc["data_quality_status"] = normalize_data_quality(doc["status"])
        # Keep the raw value under data_quality_status for audit
        doc.pop("status", None)

    # Flow rename
    if "flow_imports_mw" in doc and "interconnector_imports_mw" not in doc:
        doc["interconnector_imports_mw"] = doc.pop("flow_imports_mw")
    if "flow_exports_mw" in doc and "interconnector_exports_mw" not in doc:
        doc["interconnector_exports_mw"] = doc.pop("flow_exports_mw")

    # Drop total curtailment (can be derived in dbt if needed)
    doc.pop("curtailment_mw", None)

    # Bump schema version
    doc["schema_version"] = SCHEMA_VERSION
    return doc
