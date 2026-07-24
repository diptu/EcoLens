"""Pydantic models for the OpenElectricity v1.0 canonical schema.

Optional, for call sites that want stronger typing than a plain dict —
`OpenElectricityFetcher.fetch()` and `OpenElectricityFacilityFetcher.
fetch_facilities()` still return `list[dict]` (matching what
`bulk_upsert` and the pandera validator in
`ecolens.ingestion.validators.openelectricity` expect); nothing in the
pipeline requires these models today.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OpenElectricityMixDoc(BaseModel):
    """One row of `raw.openelectricity_mix` v1.0 — see schema.OUTPUT_COLUMNS."""

    model_config = ConfigDict(extra="allow")  # per-fuel columns vary by fetch window

    ts: str
    network_code: Literal["NEM", "WEM"]
    region: str
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


class OpenElectricityFacilityDoc(BaseModel):
    """One row of `raw.openelectricity_facilities` v1.0 — see schema.FACILITY_OUTPUT_COLUMNS."""

    model_config = ConfigDict(extra="allow")

    facility_id: str | None = None
    unit_id: str | None = None
    name: str | None = None
    network: str
    region: str | None = None
    fuel_type: str | None = None
    fuel_category: str | None = None
    capacity_registered_mw: float | None = None
    capacity_maximum_mw: float | None = None
    status: str | None = None
    commission_date: str | None = None
    expected_closure_date: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    state: str | None = None
    postcode: str | None = None
    schema_version: str
    source: str
    ingested_at: datetime
