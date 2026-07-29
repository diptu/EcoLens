"""Pydantic model for the AEMO NEM v1.0 canonical schema.

Optional, for call sites that want stronger typing than a plain dict —
`AEMONEMFetcher.fetch()` still returns `list[dict]` (matching what
`bulk_upsert` expects); nothing in the pipeline requires this model
today. Shares the same 34-column contract as
`ecolens.ingestion.sources.openelectricity.OpenElectricityMixDoc`
(see schema.OUTPUT_COLUMNS) — network_code is always "NEM" here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AemoNemMixDoc(BaseModel):
    """One row of `raw.aemo_nem_dispatch` v1.0 — see schema.OUTPUT_COLUMNS."""

    model_config = ConfigDict(extra="allow")

    ts: datetime
    network_code: Literal["NEM"]
    region: str  # "NEM" (network-level fueltech row) or NSW1/QLD1/VIC1/SA1/TAS1
    data_quality_status: Literal[
        "forecast", "realtime", "preliminary", "final", "revised", "unknown"
    ]
    schema_version: str

    demand_mw: float | None = None
    price_mwh: float | None = None
    market_value: float | None = None

    coal_black_mw: float | None = None
    coal_brown_mw: float | None = None
    gas_ccgt_mw: float | None = None
    gas_ocgt_mw: float | None = None
    gas_other_mw: float | None = None
    hydro_mw: float | None = None
    wind_mw: float | None = None
    solar_utility_mw: float | None = None
    solar_rooftop_mw: float | None = None
    biomass_mw: float | None = None
    pumped_hydro_mw: float | None = None
    distillate_mw: float | None = None
    battery_discharge_mw: float | None = None
    battery_charge_mw: float | None = None

    curtailment_solar_utility_mw: float | None = None
    curtailment_wind_mw: float | None = None

    total_generation_mw: float | None = None
    renewable_proportion: float | None = None  # 0..100 (percent)
    emissions_intensity_kgco2e_per_mwh: float | None = None

    interconnector_imports_mw: float | None = None
    interconnector_exports_mw: float | None = None
    net_import_mw: float | None = None

    source: str
    ingest_run_id: str | None = None
    ingested_at: datetime
    fetched_at: datetime
