"""Pandera schema for normalized public-holiday docs.

Validates the records produced by `HolidayFetcher.fetch()` before
they're upserted into MongoDB (INGESTION.md pipeline step 4, run
ahead of step 5's bulk upsert).
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from ecolens.ingestion.validators.common import clean_nan


class HolidaySchema(pa.DataFrameModel):
    date: Series[str] = pa.Field(nullable=False)
    region: Series[str] = pa.Field(isin=["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"])
    state: Series[str] = pa.Field(isin=["NSW", "QLD", "VIC", "SA", "TAS", "WA"])
    holiday_name: Series[str] = pa.Field(nullable=False)
    holiday_type: Series[str] = pa.Field(
        isin=["national", "state", "regional", "bank", "observance"]
    )
    source: Series[str] = pa.Field(nullable=False)

    class Config:
        strict = False
        coerce = True
        unique = ["region", "date"]


def validate(docs: list[dict]) -> list[dict]:
    """Validate normalized holiday docs, returning them unchanged (schema-coerced) on success.

    Raises `pandera.errors.SchemaError` on the first violation.
    """
    if not docs:
        return docs

    df = HolidaySchema.validate(pd.DataFrame(docs), lazy=False)
    return clean_nan(df.to_dict("records"))


__all__ = ["HolidaySchema", "validate"]
