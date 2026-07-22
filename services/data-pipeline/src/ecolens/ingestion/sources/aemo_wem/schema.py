"""AEMO WEM schema — facility/fuel taxonomy, output columns.

Pure configuration: no I/O, no classes. See `engine.py`'s module
docstring for the full data-source design notes (WEMDE data portal
format, single-zone rows, etc.).
"""

from __future__ import annotations

from ecolens.ingestion.sources.openelectricity import (
    OUTPUT_COLUMNS as OE_OUTPUT_COLUMNS,
)

# WEM is one zone (the South West Interconnected System) — unlike NEM
# there are no sub-regions, so every document uses region="WEM".
WEM_REGION = "WEM"


# ────────────────────────────────────────────────────────────────────
# FACILITY_FUELTECH_MAP — WEM facility codes → fueltech
# ────────────────────────────────────────────────────────────────────
# Unlike NEM's DUID_FUELTECH_MAP, there's no existing curated list or
# an AEMO-published fuel-type column to build from — WEM's facility
# registry (data.wa.aemo.com.au/public/public-data/datafiles/facilities/
# facilities.csv) gives "Facility Type" (Scheduled Generator /
# Intermittent Non-Scheduled Generator / load) but not fuel type.
#
# This map is hand-classified from the 76 facility codes actually
# observed in live facilityScada data (2026-07-19), using facility
# naming (e.g. "_WF1" = wind, "_PV1" = solar, "_ESR"/"BESS" = battery)
# plus general knowledge of major WA generation assets (Synergy's
# Muja/Collie coal fleet, Pinjar/Kwinana/Kemerton/Mungarra/West
# Kalgoorlie gas peaker fleet, the WA Government's Tesla-built
# batteries, known landfill-gas sites). Deliberately partial — a
# dozen ambiguous codes (small cogen plants, unclear abbreviations)
# are left unmapped rather than guessed, falling through to "unknown"
# with a warning log, same as NEM's DUID_FUELTECH_MAP handles its
# unmapped DUIDs.
FACILITY_FUELTECH_MAP: dict[str, str] = {
    # ── Coal (Collie basin, Synergy/IPP-owned) ──────────────────
    "MUJA_G7": "coal_black",
    "MUJA_G8": "coal_black",
    "COLLIE_G1": "coal_black",
    "BW1_BLUEWATERS_G2": "coal_black",
    "BW2_BLUEWATERS_G1": "coal_black",
    # ── Gas CCGT (combined cycle) ────────────────────────────────
    "COCKBURN_CCG1": "gas_ccgt",
    "NEWGEN_KWINANA_CCG1": "gas_ccgt",
    # ── Gas OCGT (Synergy's peaking fleet + independents) ───────
    "PINJAR_GT1": "gas_ocgt",
    "PINJAR_GT2": "gas_ocgt",
    "PINJAR_GT3": "gas_ocgt",
    "PINJAR_GT4": "gas_ocgt",
    "PINJAR_GT5": "gas_ocgt",
    "PINJAR_GT7": "gas_ocgt",
    "PINJAR_GT9": "gas_ocgt",
    "PINJAR_GT10": "gas_ocgt",
    "PINJAR_GT11": "gas_ocgt",
    "KWINANA_GT2": "gas_ocgt",
    "KWINANA_GT3": "gas_ocgt",
    "KEMERTON_GT11": "gas_ocgt",
    "KEMERTON_GT12": "gas_ocgt",
    "MUNGARRA_GT1": "gas_ocgt",
    "MUNGARRA_GT3": "gas_ocgt",
    "WEST_KALGOORLIE_GT2": "gas_ocgt",
    "WEST_KALGOORLIE_GT3": "gas_ocgt",
    "NEWGEN_NEERABUP_GT1": "gas_ocgt",
    "PERTHENERGY_KWINANA_GT1": "gas_ocgt",
    # ── Wind ──────────────────────────────────────────────────────
    "ALBANY_WF1": "wind",
    "ALINTA_WWF": "wind",
    "BADGINGARRA_WF1": "wind",
    "BLAIRFOX_BEROSRD_WF1": "wind",
    "BLAIRFOX_KARAKIN_WF1": "wind",
    "BLAIRFOX_WESTHILLS_WF3": "wind",
    "BREMER_BAY_WF1": "wind",
    "DCWL_DENMARK_WF1": "wind",
    "EDWFMAN_WF1": "wind",
    "FLATROCKS_WF1": "wind",
    "GRASMERE_WF1": "wind",
    "INVESTEC_COLLGAR_WF1": "wind",
    "KALBARRI_WF1": "wind",
    "MWF_MUMBIDA_WF1": "wind",
    "SKYFRM_MTBARKER_WF1": "wind",
    "WARRADARGE_WF1": "wind",
    "YANDIN_WF1": "wind",
    # ── Solar (utility-scale) ────────────────────────────────────
    "AMBRISOLAR_PV1": "solar_utility",
    "GREENOUGH_RIVER_PV1": "solar_utility",
    "MERSOLAR_PV1": "solar_utility",
    "NORTHAM_SF_PV1": "solar_utility",
    "SBSOLAR1_CUNDERDIN_PV1": "solar_utility",
    # ── Battery (WEM naming: "ESR" = Energy Storage Resource) ───
    "ALINTA_WGP_ESR1": "battery",
    "COLLIE_BESS2": "battery",
    "COLLIE_ESR1": "battery",
    "COLLIE_ESR4": "battery",
    "COLLIE_ESR5": "battery",
    "KWINANA_ESR1": "battery",
    "KWINANA_ESR2": "battery",
    "TESLA_GERALDTON_G1": "battery",
    "TESLA_KEMERTON_G1": "battery",
    "TESLA_NORTHAM_G1": "battery",
    "TESLA_PICTON_G1": "battery",
    # ── Biomass (landfill gas + biogas) ──────────────────────────
    "BIOGAS01": "biomass",
    "RED_HILL": "biomass",
    "ROCKINGHAM": "biomass",
    "SOUTH_CARDUP": "biomass",
    "TAMALA_PARK": "biomass",
}


# ────────────────────────────────────────────────────────────────────
# FUEL_MAP — same v1.0 canonical columns as openelectricity.py
# ────────────────────────────────────────────────────────────────────
FUEL_MAP: dict[str, str | None] = {
    "coal_black": "coal_black_mw",
    "coal_brown": "coal_brown_mw",
    "gas_ccgt": "gas_ccgt_mw",
    "gas_ocgt": "gas_ocgt_mw",
    "gas_other": "gas_other_mw",
    "hydro": "hydro_mw",
    "pumped_hydro": "pumped_hydro_mw",
    "wind": "wind_mw",
    "solar_utility": "solar_utility_mw",
    "solar_rooftop": "solar_rooftop_mw",
    "biomass": "biomass_mw",
    "distillate": "distillate_mw",
    "battery": "battery_discharge_mw",
    "battery_discharge": "battery_discharge_mw",
    "battery_charge": "battery_charge_mw",
    "unknown": None,  # logged separately, not stored
}


# ────────────────────────────────────────────────────────────────────
# Output schema — same 34 columns as openelectricity.py v1.0
# ────────────────────────────────────────────────────────────────────
OUTPUT_COLUMNS: list[str] = list(OE_OUTPUT_COLUMNS)
