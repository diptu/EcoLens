"""Pandera schema for normalized BoM observation docs.

Validates the records produced by `BomFetcher.fetch()` (live/cache/
synthetic, source="bom") and `HistoricalFetcher.fetch_all_stations()`
(ERA5 backfill, source="open_meteo_era5") before they're upserted
into MongoDB (INGESTION.md pipeline step 4, run ahead of step 5's
bulk upsert). Both fetchers emit the same 22-column v1.0 schema.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from ecolens.ingestion.validators.common import clean_nan


class BomObservationSchema(pa.DataFrameModel):
    ts: Series[pd.Timestamp] = pa.Field(nullable=False)
    region: Series[str] = pa.Field(isin=["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"])
    station_id: Series[str] = pa.Field(nullable=False)
    temp_c: Series[float] = pa.Field(nullable=True, ge=-10.0, le=50.0)
    humidity_pct: Series[float] = pa.Field(nullable=True, ge=0.0, le=100.0)
    source: Series[str] = pa.Field(isin=["bom", "open_meteo_era5"])

    class Config:
        strict = False
        coerce = True
        unique = ["station_id", "ts"]


def validate(docs: list[dict]) -> list[dict]:
    """Validate normalized BoM docs, returning them unchanged (schema-coerced) on success.

    Raises `pandera.errors.SchemaError` on the first violation.
    """
    if not docs:
        return docs

    df = BomObservationSchema.validate(pd.DataFrame(docs), lazy=False)
    return clean_nan(df.to_dict("records"))


__all__ = ["BomObservationSchema", "validate"]
