"""Pandera schema for normalized OpenElectricity generation-mix docs.

Validates the records produced by `OpenElectricityFetcher._normalize()`
before they're upserted into MongoDB (INGESTION.md pipeline step 4, run
ahead of step 5's bulk upsert). Per-fuel MW columns (`wind_mw`,
`coal_black`, ...) vary by fetch depending on which fueltechs the API
returned, so the schema is `strict=False` and only pins down the columns
that are always present.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series

from ecolens.ingestion.validators.common import clean_nan


class OpenElectricityMixSchema(pa.DataFrameModel):
    ts: Series[str] = pa.Field(nullable=False)
    network_code: Series[str] = pa.Field(isin=["NEM", "WEM"])
    region: Series[str] = pa.Field(nullable=False)
    total_generation_mw: Series[float] = pa.Field(nullable=False)
    source: Series[str] = pa.Field(eq="openelectricity")

    class Config:
        strict = False
        coerce = True
        unique = ["network_code", "ts"]


def validate(docs: list[dict]) -> list[dict]:
    """Validate normalized OE docs, returning them unchanged (schema-coerced) on success.

    Raises `pandera.errors.SchemaError` on the first violation.
    """
    if not docs:
        return docs

    df = OpenElectricityMixSchema.validate(pd.DataFrame(docs), lazy=False)
    return clean_nan(df.to_dict("records"))


__all__ = ["OpenElectricityMixSchema", "validate"]
