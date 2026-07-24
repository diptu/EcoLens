"""Pydantic model for the holidays v1.0 canonical schema.

Optional, for call sites that want stronger typing than a plain dict —
`HolidayFetcher.fetch()`/`fetch_for_year()` still return `list[dict]`
(matching what `bulk_upsert` and the pandera validator in
`ecolens.ingestion.validators.holidays` expect); nothing in the
pipeline requires this model today.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HolidayDoc(BaseModel):
    """One row of `aemo_holidays` v1.0 — see schema.HOLIDAY_OUTPUT_COLUMNS."""

    model_config = ConfigDict(extra="allow")

    date: str
    region: str
    state: str
    holiday_name: str
    holiday_type: str
    schema_version: str

    is_business_day: bool = False
    is_observed: bool = False
    observed_date: str | None = None

    days_until: int | None = None
    source: str
    ingest_run_id: str | None = None
    fetched_at: datetime
