"""AEMO NEM dispatch ingestion package.

Split by concern:
  schema.py         configuration: DUID_FUELTECH_MAP, FUEL_MAP, OUTPUT_COLUMNS
  client.py         infrastructure: NEMWeb HTTP client, decodes the MMS multi-table CSV
  transformers.py   domain logic: reshaping/merging tables, data-quality fixes
  engine.py         orchestration: AEMONEMFetcher
  models.py         optional Pydantic model for stricter typing

See engine.py's module docstring for the full data-source design notes.
"""

from __future__ import annotations

from .client import AEMONEMClient
from .engine import AEMONEMFetcher
from .models import AemoNemMixDoc
from .schema import (
    DUID_FUELTECH_MAP,
    FUEL_MAP,
    NEM_REGIONS,
    OUTPUT_COLUMNS,
    TABLE_NATURAL_KEYS,
)
from .transformers import (
    aggregate_duids_to_fueltechs,
    aggregate_to_network,
    apply_data_quality_fixes,
    apply_fuel_map,
    build_day_frame,
    compute_derived,
    diagnose,
    extract_regionsum,
)

__all__ = [
    "AEMONEMClient",
    "AEMONEMFetcher",
    "AemoNemMixDoc",
    "DUID_FUELTECH_MAP",
    "FUEL_MAP",
    "NEM_REGIONS",
    "OUTPUT_COLUMNS",
    "TABLE_NATURAL_KEYS",
    "aggregate_duids_to_fueltechs",
    "aggregate_to_network",
    "apply_data_quality_fixes",
    "apply_fuel_map",
    "build_day_frame",
    "compute_derived",
    "diagnose",
    "extract_regionsum",
]
