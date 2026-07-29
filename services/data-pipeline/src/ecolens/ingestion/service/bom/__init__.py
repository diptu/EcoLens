"""BoM (Bureau of Meteorology) v1.0 ingestion package.

Split by concern (layers, not just files, since the ingestion module's
restructure):
  ecolens.ingestion.schema.bom         configuration: station map, physical bounds, output columns
  ecolens.ingestion.model.bom          optional Pydantic model for stricter typing
  client.py                    infrastructure: live HTTP client, decodes wire JSON responses
  cache.py                     infrastructure: local CSV cache tier (dev/CI fallback)
  transformers.py               domain logic: normalization, data-quality fixes, synthetic stub
  engine.py                    orchestration: BomFetcher (3-tier live/cache/synthetic)
  historical_client.py          infrastructure: Open-Meteo (ERA5) HTTP client
  historical_transformers.py   domain logic: Open-Meteo URL building + response parsing
  historical.py                 orchestration: HistoricalFetcher (2-3yr backfill via ERA5)

Re-exports everything a caller previously got from the flat
`ecolens.ingestion.sources.bom` package, from these new locations.

See engine.py's / historical.py's module docstrings for the full
fetcher design notes.
"""

from __future__ import annotations

from ecolens.ingestion.model.bom import BomObservationDoc
from ecolens.ingestion.schema.bom import (
    AUSTRALIA_UTC_OFFSETS,
    DEFAULT_BOM_GEOHASHES,
    DEFAULT_BOM_STATIONS,
    ERA5_LAG_DAYS,
    OBSERVATION_OUTPUT_COLUMNS,
    PHYSICAL_BOUNDS,
    SCHEMA_VERSION,
    STATION_COORDS,
    STATION_NAME_MAP,
    WIND_DIRECTION_DEGREES,
)

from .client import BomClient
from .engine import BomFetcher
from .historical import HistoricalFetcher
from .historical_client import OpenMeteoClient
from .transformers import (
    apply_data_quality_fixes,
    diagnose,
    normalize_observation,
    synthetic_stub,
)

__all__ = [
    "BomClient",
    "BomFetcher",
    "HistoricalFetcher",
    "OpenMeteoClient",
    "BomObservationDoc",
    "SCHEMA_VERSION",
    "AUSTRALIA_UTC_OFFSETS",
    "DEFAULT_BOM_STATIONS",
    "DEFAULT_BOM_GEOHASHES",
    "STATION_NAME_MAP",
    "STATION_COORDS",
    "PHYSICAL_BOUNDS",
    "OBSERVATION_OUTPUT_COLUMNS",
    "ERA5_LAG_DAYS",
    "WIND_DIRECTION_DEGREES",
    "normalize_observation",
    "apply_data_quality_fixes",
    "synthetic_stub",
    "diagnose",
]
