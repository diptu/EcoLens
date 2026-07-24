"""AEMO WEM dispatch ingestion package.

Split by concern:
  schema.py         configuration: FACILITY_FUELTECH_MAP, FUEL_MAP, OUTPUT_COLUMNS
  client.py         infrastructure: WEMDE data-portal HTTP client (SCADA/demand/price)
  transformers.py   domain logic: reshaping/merging feeds, data-quality fixes
  engine.py         orchestration: AEMOWEMFetcher
  models.py         optional Pydantic model for stricter typing

See engine.py's module docstring for the full data-source design notes.
"""

from __future__ import annotations

from .client import AEMOWEMClient
from .engine import AEMOWEMFetcher
from .models import AemoWemMixDoc
from .schema import FACILITY_FUELTECH_MAP, FUEL_MAP, OUTPUT_COLUMNS, WEM_REGION
from .transformers import (
    aggregate_facilities_to_fueltechs,
    apply_data_quality_fixes,
    apply_fuel_map,
    build_day_frame,
    compute_derived,
    diagnose,
    extract_demand,
    extract_price,
)

__all__ = [
    "AEMOWEMClient",
    "AEMOWEMFetcher",
    "AemoWemMixDoc",
    "FACILITY_FUELTECH_MAP",
    "FUEL_MAP",
    "OUTPUT_COLUMNS",
    "WEM_REGION",
    "aggregate_facilities_to_fueltechs",
    "apply_data_quality_fixes",
    "apply_fuel_map",
    "build_day_frame",
    "compute_derived",
    "diagnose",
    "extract_demand",
    "extract_price",
]
