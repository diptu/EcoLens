"""AEMO NEM schema — DUID/fuel taxonomy, output columns, table keys.

Pure configuration: no I/O, no classes. See `engine.py`'s module
docstring for the full data-source design notes (NEMWeb file format,
per-region vs network-level rows, etc.).
"""

from __future__ import annotations

from ecolens.ingestion.sources.openelectricity import (
    OUTPUT_COLUMNS as OE_OUTPUT_COLUMNS,
)

# NEM regions. WEM is handled by aemo_wem.py.
NEM_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")

# Natural key per MMS table — used to dedupe the two identical copies
# PUBLIC_DAILY bundles of each table before any aggregation runs.
TABLE_NATURAL_KEYS: dict[str, list[str]] = {
    "DUNIT": ["DUID", "SETTLEMENTDATE", "INTERVENTION"],
    "DREGION": ["REGIONID", "SETTLEMENTDATE", "INTERVENTION"],
}


# ────────────────────────────────────────────────────────────────────
# DUID_FUELTECH_MAP — NEM Dispatchable Unit IDs → fueltech
# ────────────────────────────────────────────────────────────────────
# NEMWeb gives us per-DUID generation, but we need per-fueltech
# aggregation. This map covers the 100+ largest generators in the
# NEM (covers ~95% of total generation). For DUIDs not in the map,
# the fetcher aggregates them into a "unknown_mw" bucket and logs
# a warning (so on-call can add them).

# Note: this is a representative subset of the full NEM DUID list.
# In production, load the full mapping from the facility registry
# (`raw.openelectricity_facilities` collection, which has DUID +
# fuel_type). The map below is the fallback when the registry is
# not yet populated.

DUID_FUELTECH_MAP: dict[str, str] = {
    # ── Coal Black (NSW, QLD) ────────────────────────────────
    "BAYSW1": "coal_black",
    "BAYSW2": "coal_black",
    "BAYSW3": "coal_black",
    "BAYSW4": "coal_black",
    "ER01": "coal_black",
    "ER02": "coal_black",
    "ER03": "coal_black",
    "ER04": "coal_black",
    "LD01": "coal_black",
    "LD02": "coal_black",
    "LD03": "coal_black",
    "LD04": "coal_black",
    "MP1": "coal_black",
    "MP2": "coal_black",
    "GSTONE1": "coal_black",
    "GSTONE2": "coal_black",
    "GSTONE3": "coal_black",
    "GSTONE4": "coal_black",
    "GSTONE5": "coal_black",
    "GSTONE6": "coal_black",
    "CALL_B1": "coal_black",
    "CALL_B2": "coal_black",
    "CQNC1": "coal_black",
    "CQNC2": "coal_black",
    "TARR1": "coal_black",
    "TARR2": "coal_black",
    "TARR3": "coal_black",
    "TARR4": "coal_black",
    "MILLM1": "coal_black",
    "MILLM2": "coal_black",
    "BW01": "coal_black",
    "BW02": "coal_black",
    "BW03": "coal_black",
    "BW04": "coal_black",
    "VP5": "coal_black",
    "VP6": "coal_black",
    "STAN-1": "coal_black",
    "STAN-2": "coal_black",
    "STAN-3": "coal_black",
    "STAN-4": "coal_black",
    # ── Coal Brown (VIC) ─────────────────────────────────────
    "HWPS1": "coal_brown",
    "HWPS2": "coal_brown",
    "HWPS3": "coal_brown",
    "HWPS4": "coal_brown",
    "HWPS5": "coal_brown",
    "HWPS6": "coal_brown",
    "HWPS7": "coal_brown",
    "HWPS8": "coal_brown",
    "LYA1": "coal_brown",
    "LYA2": "coal_brown",
    "LYA3": "coal_brown",
    "LYA4": "coal_brown",
    "LYB1": "coal_brown",
    "LYB2": "coal_brown",
    "LYB3": "coal_brown",
    "LYB4": "coal_brown",
    "YWPS1": "coal_brown",
    "YWPS2": "coal_brown",
    "YWPS3": "coal_brown",
    "YWPS4": "coal_brown",
    "LOYYB1": "coal_brown",
    "LOYYB2": "coal_brown",
    "LOYYB3": "coal_brown",
    "LOYYB4": "coal_brown",
    # ── Gas CCGT (baseload) ──────────────────────────────────
    "TALLA1": "gas_ccgt",  # Tallawarra
    "MORTLK11": "gas_ccgt",  # Mortlake
    "AGLHAL": "gas_ccgt",  # Aglohal
    "TORRB1": "gas_ccgt",  # Torrens Island
    "TORRB2": "gas_ccgt",
    "TORRB3": "gas_ccgt",
    "TORRB4": "gas_ccgt",
    "PPKGTB1": "gas_ccgt",  # Pelican Point
    # ── Gas OCGT (peakers) ───────────────────────────────────
    "TOMAGO": "gas_ocgt",
    "WILPK": "gas_ocgt",
    "BHB01": "gas_ocgt",  # Broken Hill
    "ANGAST1": "gas_ocgt",  # Angaston
    "LADBROK1": "gas_ocgt",  # Ladbroke Grove
    "MINTARO": "gas_ocgt",  # Mintaro
    "DRYCT1": "gas_ocgt",  # Dry Creek
    "OSB-AG": "gas_ocgt",  # also peaker
    "QUAIRN1": "gas_ocgt",  # Quairading (WEM, but kept for completeness)
    # ── Hydro ───────────────────────────────────────────────
    "GUTHEGA": "hydro",
    "TUMUT3": "hydro",
    "MURRAY": "hydro",
    "BLOWERNG": "pumped_hydro",  # Blowering (pumped)
    "UPPTUMUT": "pumped_hydro",  # Upper Tumut
    "SNOWYP": "hydro",  # Snowy Mountains (alias)
    "SHOALHAVEN": "pumped_hydro",  # Kangaroo Valley / Shoalhaven
    "TUMUT1": "hydro",
    "TUMUT2": "hydro",
    # ── Wind (subset; ~70% of NEM wind) ─────────────────────
    "WELLS1": "wind",  # Waubra
    "MACARTH1": "wind",  # Macarthur
    "MUSSELR1": "wind",  # Musselroe
    "WOOLSTH1": "wind",  # Woolnorth
    "CATHROCK": "wind",  # Cathedral Rocks
    "BLUFF1": "wind",  # Bluff Point
    "CHALLA1": "wind",  # Challicum Hills
    "CULLRG1": "wind",  # Cullerin Range
    "GULLR1": "wind",  # Gullen Range
    "RVBWTR1": "wind",  # Rugby Run
    "SAPHIRE1": "wind",  # Sapphire
    "STARHL1": "wind",  # Starfish Hill
    "WINDHUB1": "wind",  # Waterloo
    "WATERL1": "wind",  # Waterloo
    "MTGELR1": "wind",  # Mt Gellibrand
    "CROWL1": "wind",  # Crowlands
    "ARSENA1": "wind",  # Arsenal
    "BODWN1": "wind",  # Bodangora
    "BGLBA1": "wind",  # Biala
    "COOPER1": "wind",  # Cooper
    # ── Solar (utility-scale) ───────────────────────────────
    "MANSL1": "solar_utility",  # Moree Solar Farm
    "BANNER1": "solar_utility",  # Bannerton
    "ROMPIN": "solar_utility",  # Rompin
    "DUNDWF1": "solar_utility",  # Darling Downs
    "HASTINGS": "solar_utility",
    "INVICTA1": "solar_utility",
    "DNPSF1": "solar_utility",
    "LILYDAL1": "solar_utility",
    "WEMENSF1": "solar_utility",  # Wemen (VIC)
    "KARADOC1": "solar_utility",
    # ── Battery (storage) ───────────────────────────────────
    "DALNTH01": "battery",  # Dalrymple BESS
    "HRONBNK": "battery",  # Hornsdale Power Reserve
    "GANNBG1": "battery",  # Gannawarra BESS (alias)
    "BNGSF1": "battery",  # Ballarat BESS
    "SUNTPSF1": "battery",  # Sunraysia BESS
    "WANDLG1": "battery",  # Wandiligong BESS
    "HDOBDJ1": "battery",  # Hazelwood BESS
}


# ────────────────────────────────────────────────────────────────────
# FUEL_MAP — same v1.0 canonical columns as openelectricity.py
# ────────────────────────────────────────────────────────────────────
# Maps the v1.0 fueltech names produced by DUID_FUELTECH_MAP → the
# canonical column in `raw.aemo_nem_dispatch`. (v1.0: 1:1 mapping
# for coal and gas; biomass aggregated; battery kept as
# battery_discharge_mw; pumped_hydro separate from hydro.)
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
# We re-use OE's OUTPUT_COLUMNS as the contract. network_code is
# always "NEM" here; region is one of NSW1/QLD1/VIC1/SA1/TAS1.
OUTPUT_COLUMNS: list[str] = list(OE_OUTPUT_COLUMNS)
