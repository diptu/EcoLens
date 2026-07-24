"""Pydantic model for the BoM v1.0 canonical schema.

Optional, for call sites that want stronger typing than a plain dict —
`BomFetcher.fetch()` still returns `list[dict]` (matching what
`bulk_upsert` and the pandera validator in
`ecolens.ingestion.validators.bom` expect); nothing in the pipeline
requires this model today.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BomObservationDoc(BaseModel):
    """One row of `raw.bom_observations` v1.0 — see schema.OBSERVATION_OUTPUT_COLUMNS."""

    model_config = ConfigDict(extra="allow")

    ts: datetime
    region: str
    station_id: str
    station_name: str
    schema_version: str

    temp_c: float | None = None
    apparent_temp_c: float | None = None
    dew_point_c: float | None = None
    humidity_pct: float | None = None

    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    wind_gust_kmh: float | None = None

    pressure_hpa: float | None = None
    rain_since_9am_mm: float | None = None
    rain_last_hour_mm: float | None = None

    cloud_oktas: float | None = None
    cloud_cover_pct: float | None = None

    data_quality_status: str
    source: str
    ingest_run_id: str | None = None
    ingested_at: datetime
    fetched_at: datetime
