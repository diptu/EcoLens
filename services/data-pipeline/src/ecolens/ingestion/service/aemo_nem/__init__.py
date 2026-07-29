"""AEMO NEM dispatch ingestion package.

Split by concern (layers, not just files, since the ingestion module's
restructure):
  ecolens.ingestion.schema.aemo_nem   configuration: DUID_FUELTECH_MAP, FUEL_MAP, OUTPUT_COLUMNS
  ecolens.ingestion.model.aemo_nem    optional Pydantic model for stricter typing
  client.py         infrastructure: NEMWeb HTTP client, decodes the MMS multi-table CSV
  transformers.py   domain logic: reshaping/merging tables, data-quality fixes
  engine.py         orchestration: AEMONEMFetcher

Re-exports everything a caller previously got from the flat
`ecolens.ingestion.sources.aemo_nem` package, from these new locations,
so `from ecolens.ingestion.service.aemo_nem import AEMONEMFetcher` (etc.)
keeps working as one flat surface.

See engine.py's module docstring for the full data-source design notes.
"""

from __future__ import annotations

from ecolens.ingestion.model.aemo_nem import AemoNemMixDoc
from ecolens.ingestion.schema.aemo_nem import (
    DUID_FUELTECH_MAP,
    FUEL_MAP,
    NEM_REGIONS,
    OUTPUT_COLUMNS,
    TABLE_NATURAL_KEYS,
)

from .client import AEMONEMClient
from .engine import AEMONEMFetcher
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
