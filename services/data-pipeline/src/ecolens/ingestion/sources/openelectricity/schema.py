"""OpenElectricity v1.0 schema — fuel/metric taxonomy, output columns, capabilities.

Pure configuration: no I/O, no classes. See `engine.py`'s module
docstring for the full v1.0 design rationale (coal/gas disaggregation,
renamed fields, the market_value addition, etc.).
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────────────
# Schema version — bump when adding/removing/renaming columns
# ────────────────────────────────────────────────────────────────────
SCHEMA_VERSION: str = "1.0"


# ────────────────────────────────────────────────────────────────────
# Timezone handling
# ────────────────────────────────────────────────────────────────────
# Neither NEM (AEST) nor WEM (AWST) observes daylight saving. The OE
# API expects NAIVE network-local timestamps — not UTC, not tz-aware.
NETWORK_UTC_OFFSET_HOURS: dict[str, int] = {
    "NEM": 10,  # AEST = UTC+10
    "WEM": 8,  # AWST = UTC+8
}

NETWORK_TIMEZONE_LABEL: dict[str, str] = {
    "NEM": "Australia/Brisbane",
    "WEM": "Australia/Perth",
}


# ────────────────────────────────────────────────────────────────────
# FUEL_MAP v1.0 — disaggregated coal and gas (was aggregated in v0.x)
# ────────────────────────────────────────────────────────────────────
# Maps every fueltech value the v4 API actually returns → canonical
# column name. v1.0 split coal_black/coal_brown and gas_ccgt/gas_ocgt
# (and aggregated the 3 minor gas types into gas_other_mw).
#
# No aggregation happens after the rename — every raw fueltech gets
# its own column. This is the key design change from v0.x where
# coal_black + coal_brown both mapped to coal_mw.
FUEL_MAP: dict[str, str] = {
    # Coal: DISAGGREGATED (v1.0 change)
    "coal_black": "coal_black_mw",
    "coal_brown": "coal_brown_mw",
    # Gas: CCGT and OCGT kept disaggregated; the other 3 aggregated
    # into gas_other_mw (v1.0 change).
    "gas_ccgt": "gas_ccgt_mw",
    "gas_ocgt": "gas_ocgt_mw",
    "gas_recip": "gas_other_mw",
    "gas_steam": "gas_other_mw",
    "gas_wcmg": "gas_other_mw",
    # Bioenergy: aggregated (small share, similar bidding behaviour)
    "bioenergy_biogas": "biomass_mw",
    "bioenergy_biomass": "biomass_mw",
    # Battery (charging is a load, not generation)
    "battery_discharging": "battery_discharge_mw",
    "battery_charging": "battery_charge_mw",
    # Hydro / pumped hydro (API uses "pumps", not "pumped_hydro")
    "hydro": "hydro_mw",
    "pumps": "pumped_hydro_mw",
    # Wind + solar (utility + rooftop)
    "wind": "wind_mw",
    "solar_utility": "solar_utility_mw",
    "solar_rooftop": "solar_rooftop_mw",
    # Distillate (diesel peakers)
    "distillate": "distillate_mw",
}

# Reverse map: canonical column → raw fueltech values that feed it
# (used by the renewable_proportion computation and the data-quality
# diagnostics).
CANONICAL_TO_RAW: dict[str, list[str]] = {}
for _raw, _canon in FUEL_MAP.items():
    CANONICAL_TO_RAW.setdefault(_canon, []).append(_raw)


# Renewable fueltechs (for renewable_proportion calculation).
# Hydro + wind + solar + biomass are the canonical renewables.
RENEWABLE_CANONICAL_COLUMNS: frozenset[str] = frozenset(
    {
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "biomass_mw",
    }
)

# All generation columns (for total_generation_mw recomputation).
# Excludes battery_charge (a load) and gas_other details (captured
# in gas_other_mw as a single value).
GENERATION_COLUMNS: tuple[str, ...] = (
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
    "pumped_hydro_mw",
    "biomass_mw",
    "distillate_mw",
)


# ────────────────────────────────────────────────────────────────────
# Data-quality normalization
# ────────────────────────────────────────────────────────────────────
# OE returns data quality at multiple points (per-row, per-series,
# response-level). Values vary across API versions. We normalize them
# to a fixed set:
#
#   "forecast"     pre-dispatch projections (hours to days ahead)
#   "realtime"     5-min dispatch (subject to revisions)
#   "preliminary"  initial settlement (4 days post-interval)
#   "final"        final settlement (36+ months post-interval)
#   "revised"      after a market notice correction
#   "unknown"      no status provided
#
# For ML training, filter to data_quality_status="final" — every
# other tier is subject to revision.
DATA_QUALITY_NORMALIZATION: dict[str, str] = {
    # Forecast tier
    "forecast": "forecast",
    "predicted": "forecast",
    "scheduled": "forecast",  # AEMO pre-dispatch schedule = a forecast
    "p30": "forecast",  # 30-min pre-dispatch
    "p5": "forecast",  # 5-min pre-dispatch
    # Realtime tier
    "realtime": "realtime",
    "real-time": "realtime",
    "dispatch": "realtime",  # 5-min dispatch
    "5min": "realtime",
    "active": "realtime",  # OE v4 sometimes uses "active"
    # Settlement tiers
    "preliminary": "preliminary",
    "initial": "preliminary",
    "final": "final",
    "finalized": "final",
    # Revision tier
    "revised": "revised",
    "revised-1": "revised",
    "revised-2": "revised",
}

VALID_DATA_QUALITY_TIERS: frozenset[str] = frozenset(
    {
        "forecast",
        "realtime",
        "preliminary",
        "final",
        "revised",
        "unknown",
    }
)


# ────────────────────────────────────────────────────────────────────
# Network capabilities
# ────────────────────────────────────────────────────────────────────
# Documents which metrics are available per network. The fetcher uses
# this to skip metrics that the network doesn't support (e.g. WEM
# has no interconnector flows since it's currently islanded).
#
# v1.0 change: WEM `interconnector_*` flags flipped to True even
# though the values are currently always null/0 — this is future-proof
# for when WEM gets interconnectors (SWIS expansion is in planning).
NETWORK_CAPABILITIES: dict[str, dict[str, bool]] = {
    "NEM": {
        "power": True,
        "price": True,
        "demand": True,
        "emissions": True,
        "curtailment_solar_utility": True,
        "curtailment_wind": True,
        "renewable_proportion": True,
        "interconnector_imports": True,
        "interconnector_exports": True,
        "market_value": True,
    },
    "WEM": {
        "power": True,
        "price": True,
        "demand": True,
        "emissions": True,  # available but sometimes null
        "curtailment_solar_utility": True,
        "curtailment_wind": True,
        "renewable_proportion": True,
        # WEM is currently islanded; columns are reserved (null/0)
        # so the schema is stable when interconnectors come online.
        "interconnector_imports": True,
        "interconnector_exports": True,
        "market_value": True,
    },
}


# ────────────────────────────────────────────────────────────────────
# Output schema v1.0 (canonical columns in every MongoDB document)
# ────────────────────────────────────────────────────────────────────
# The fetcher always emits the full column set so the dbt downstream
# doesn't have to handle missing keys. Any value can be `None` if OE
# didn't return the data for that (network, ts).
OUTPUT_COLUMNS: list[str] = [
    # ── Identity ───────────────────────────────────────────────
    "ts",
    "network_code",
    "region",
    "data_quality_status",  # v1.0 rename: was "status"
    "schema_version",  # v1.0 addition
    # ── Market ─────────────────────────────────────────────────
    "demand_mw",
    "price_mwh",
    "market_value",  # v1.0 addition
    # ── Generation — Coal & Gas (DISAGGREGATED in v1.0) ────────
    "coal_black_mw",  # v1.0 split (was coal_mw)
    "coal_brown_mw",  # v1.0 split (was coal_mw)
    "gas_ccgt_mw",  # v1.0 split (was gas_mw)
    "gas_ocgt_mw",  # v1.0 split (was gas_mw)
    "gas_other_mw",  # v1.0 new (recip + steam + wcmg)
    # ── Generation — Renewables & Other ─────────────────────────
    "hydro_mw",
    "wind_mw",
    "solar_utility_mw",
    "solar_rooftop_mw",
    "biomass_mw",
    "pumped_hydro_mw",
    "distillate_mw",
    "battery_discharge_mw",
    # ── Storage / Load ───────────────────────────────────────────
    "battery_charge_mw",
    # ── Curtailment (per-fuel only in v1.0; total is derived) ──
    "curtailment_solar_utility_mw",
    "curtailment_wind_mw",
    # ── Derived ────────────────────────────────────────────────
    "total_generation_mw",
    "renewable_proportion",  # 0..100, percent renewable (API-native unit is "%")
    "emissions_intensity_kgco2e_per_mwh",
    # ── Interconnectors (renamed from "Flows" in v1.0) ─────────
    "interconnector_imports_mw",  # v1.0 rename: was flow_imports_mw
    "interconnector_exports_mw",  # v1.0 rename: was flow_exports_mw
    "net_import_mw",  # imports - exports
    # ── Metadata ───────────────────────────────────────────────
    "source",
    "ingest_run_id",
    "ingested_at",
    "fetched_at",
]


# Real API metric enum values that differ from our internal metric
# keys (used in NETWORK_CAPABILITIES/DEFAULT_METRICS and threaded
# through the merge code). Anything not listed here uses the same
# name on both sides.
METRIC_API_NAME: dict[str, str] = {
    "interconnector_imports": "flow_imports",
    "interconnector_exports": "flow_exports",
}

# Which endpoint host serves each metric. `power`, `emissions` and
# `market_value` live under /v4/data/network/{network}; everything
# else (price, demand, curtailment_*, renewable_proportion, the flow
# metrics) lives under the separate /v4/market/network/{network}
# endpoint — confirmed against the real API's openapi.json, not
# assumed from naming.
METRIC_ENDPOINT: dict[str, str] = {
    "power": "data",
    "emissions": "data",
    "market_value": "data",
    "price": "market",
    "demand": "market",
    "curtailment_solar_utility": "market",
    "curtailment_wind": "market",
    "renewable_proportion": "market",
    "interconnector_imports": "market",
    "interconnector_exports": "market",
}

DEFAULT_METRICS: tuple[str, ...] = (
    "power",
    "price",
    "demand",
    "emissions",
    "curtailment_solar_utility",
    "curtailment_wind",
    "renewable_proportion",
    "interconnector_imports",
    "interconnector_exports",
    "market_value",
)


# ────────────────────────────────────────────────────────────────────
# Facility registry output schema (v1.0)
# ────────────────────────────────────────────────────────────────────
FACILITY_OUTPUT_COLUMNS: list[str] = [
    "facility_id",
    "unit_id",
    "name",
    "network",
    "region",
    "fuel_type",
    "fuel_category",
    "capacity_registered_mw",
    "capacity_maximum_mw",
    "status",
    "commission_date",
    "expected_closure_date",
    "latitude",
    "longitude",
    "state",
    "postcode",
    "schema_version",
    "source",
    "ingested_at",
]
