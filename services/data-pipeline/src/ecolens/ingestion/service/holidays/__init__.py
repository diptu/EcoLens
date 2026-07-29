"""Australian public holidays v1.0 ingestion package.

Split by concern (layers, not just files, since the ingestion module's
restructure):
  ecolens.ingestion.schema.holidays   configuration: region/state maps, holiday templates, output columns
  ecolens.ingestion.model.holidays    optional Pydantic model for stricter typing
  client.py         infrastructure: HTTP client, decodes the data.gov.au wire JSON
  cache.py          infrastructure: local CSV cache tier (dev/CI fallback)
  transformers.py   domain logic: Easter computation, normalization, data-quality fixes
  engine.py         orchestration: HolidayFetcher (3-tier live/cache/synthetic)

Re-exports everything a caller previously got from the flat
`ecolens.ingestion.sources.holidays` package, from these new locations.

See engine.py's module docstring for the full fetcher design notes.
"""

from __future__ import annotations

from ecolens.ingestion.model.holidays import HolidayDoc
from ecolens.ingestion.schema.holidays import (
    HOLIDAY_OUTPUT_COLUMNS,
    NEM_REGIONS,
    REGION_TO_STATE,
    SCHEMA_VERSION,
    STATE_TO_REGIONS,
    VALID_HOLIDAY_TYPES,
    VALID_STATES,
)

from .client import HolidayClient
from .engine import HolidayFetcher
from .transformers import (
    apply_data_quality_fixes,
    attach_days_until,
    diagnose,
    easter_date,
    synthetic_stub,
)

__all__ = [
    "HolidayClient",
    "HolidayFetcher",
    "HolidayDoc",
    "SCHEMA_VERSION",
    "NEM_REGIONS",
    "REGION_TO_STATE",
    "STATE_TO_REGIONS",
    "VALID_STATES",
    "VALID_HOLIDAY_TYPES",
    "HOLIDAY_OUTPUT_COLUMNS",
    "easter_date",
    "synthetic_stub",
    "apply_data_quality_fixes",
    "attach_days_until",
    "diagnose",
]
