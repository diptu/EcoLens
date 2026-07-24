"""OpenElectricity (OpenNEM) v1.0 ingestion package.

Split by concern:
  schema.py         configuration: FUEL_MAP, OUTPUT_COLUMNS, metric/network tables
  client.py         infrastructure: SDK/httpx API client, decodes wire responses
  transformers.py   domain logic: reshaping/merging frames, data-quality normalization
  engine.py         orchestration: OpenElectricityFetcher / OpenElectricityFacilityFetcher
  models.py         optional Pydantic models for stricter typing

See engine.py's module docstring for the full v1.0 schema design notes.
"""

from __future__ import annotations

from .client import OpenElectricityClient
from .engine import OpenElectricityFacilityFetcher, OpenElectricityFetcher
from .models import OpenElectricityFacilityDoc, OpenElectricityMixDoc
from .schema import (
    CANONICAL_TO_RAW,
    DATA_QUALITY_NORMALIZATION,
    DEFAULT_METRICS,
    FACILITY_OUTPUT_COLUMNS,
    FUEL_MAP,
    GENERATION_COLUMNS,
    METRIC_API_NAME,
    METRIC_ENDPOINT,
    NETWORK_CAPABILITIES,
    NETWORK_TIMEZONE_LABEL,
    NETWORK_UTC_OFFSET_HOURS,
    OUTPUT_COLUMNS,
    RENEWABLE_CANONICAL_COLUMNS,
    SCHEMA_VERSION,
    VALID_DATA_QUALITY_TIERS,
)
from .transformers import (
    diagnose_data_quality,
    merge_network,
    migrate_v0_to_v1,
    minimal_doc,
    normalize_data_quality,
)

__all__ = [
    "OpenElectricityClient",
    "OpenElectricityFetcher",
    "OpenElectricityFacilityFetcher",
    "OpenElectricityMixDoc",
    "OpenElectricityFacilityDoc",
    "SCHEMA_VERSION",
    "NETWORK_UTC_OFFSET_HOURS",
    "NETWORK_TIMEZONE_LABEL",
    "FUEL_MAP",
    "CANONICAL_TO_RAW",
    "RENEWABLE_CANONICAL_COLUMNS",
    "GENERATION_COLUMNS",
    "DATA_QUALITY_NORMALIZATION",
    "VALID_DATA_QUALITY_TIERS",
    "NETWORK_CAPABILITIES",
    "OUTPUT_COLUMNS",
    "METRIC_API_NAME",
    "METRIC_ENDPOINT",
    "DEFAULT_METRICS",
    "FACILITY_OUTPUT_COLUMNS",
    "merge_network",
    "minimal_doc",
    "diagnose_data_quality",
    "normalize_data_quality",
    "migrate_v0_to_v1",
]
