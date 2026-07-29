"""AEMO WEM dispatch ingestion package.

Split by concern (layers, not just files, since the ingestion module's
restructure):
  ecolens.ingestion.schema.aemo_wem   configuration: FACILITY_FUELTECH_MAP, FUEL_MAP, OUTPUT_COLUMNS
  ecolens.ingestion.model.aemo_wem    optional Pydantic model for stricter typing
  client.py         infrastructure: WEMDE data-portal HTTP client (SCADA/demand/price)
  transformers.py   domain logic: reshaping/merging feeds, data-quality fixes
  engine.py         orchestration: AEMOWEMFetcher

Re-exports everything a caller previously got from the flat
`ecolens.ingestion.sources.aemo_wem` package, from these new locations.

See engine.py's module docstring for the full data-source design notes.
"""

from __future__ import annotations

from ecolens.ingestion.model.aemo_wem import AemoWemMixDoc
from ecolens.ingestion.schema.aemo_wem import (
    FACILITY_FUELTECH_MAP,
    FUEL_MAP,
    OUTPUT_COLUMNS,
    WEM_REGION,
)

from .client import AEMOWEMClient
from .engine import AEMOWEMFetcher
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
