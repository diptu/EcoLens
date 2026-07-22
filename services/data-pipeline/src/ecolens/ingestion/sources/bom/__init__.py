"""BoM (Bureau of Meteorology) v1.0 ingestion package.

Split by concern:
  schema.py                    configuration: station map, physical bounds, output columns
  client.py                    infrastructure: live HTTP client, decodes wire JSON responses
  cache.py                     infrastructure: local CSV cache tier (dev/CI fallback)
  transformers.py               domain logic: normalization, data-quality fixes, synthetic stub
  engine.py                    orchestration: BomFetcher (3-tier live/cache/synthetic)
  historical_client.py          infrastructure: Open-Meteo (ERA5) HTTP client
  historical_transformers.py   domain logic: Open-Meteo URL building + response parsing
  historical.py                 orchestration: HistoricalFetcher (2-3yr backfill via ERA5)
  models.py                    optional Pydantic model for stricter typing

See engine.py's / historical.py's module docstrings for the full
fetcher design notes.
"""

from __future__ import annotations

from .client import BomClient
from .engine import BomFetcher
from .historical import HistoricalFetcher
from .historical_client import OpenMeteoClient
from .models import BomObservationDoc
from .schema import (
    AUSTRALIA_UTC_OFFSETS,
    DEFAULT_BOM_STATIONS,
    ERA5_LAG_DAYS,
    OBSERVATION_OUTPUT_COLUMNS,
    PHYSICAL_BOUNDS,
    SCHEMA_VERSION,
    STATION_COORDS,
    STATION_NAME_MAP,
)
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
    "STATION_NAME_MAP",
    "STATION_COORDS",
    "PHYSICAL_BOUNDS",
    "OBSERVATION_OUTPUT_COLUMNS",
    "ERA5_LAG_DAYS",
    "normalize_observation",
    "apply_data_quality_fixes",
    "synthetic_stub",
    "diagnose",
]
