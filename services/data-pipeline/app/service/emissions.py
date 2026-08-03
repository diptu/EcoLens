"""OpenElectricity SDK wrappers.

Thin async wrappers around the official `openelectricity` PyPI package,
returning long-form `pandas.DataFrame`s (`ts`, `fuel_type`, `value`) —
that's the shape `app.service.pipeline.tasks.ingest_openelectricity` pivots
into our wide `raw.openelectricity_mix` schema.

`settings.oe_api_key` is optional (anonymous access is rate-limited, not
rejected outright) — a missing/invalid key surfaces as an exception from
the SDK's HTTP call, which `ingest_openelectricity.run()` already catches
per-network rather than failing the whole run.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from openelectricity import AsyncOEClient, DataMetric

from app.core.config import get_settings

_LONG_FORM_COLUMNS = ("ts", "fuel_type", "value")


async def _fetch_metric(
    network_code: str, since: datetime, metric: DataMetric
) -> pd.DataFrame:
    settings = get_settings()
    async with AsyncOEClient(api_key=settings.oe_api_key) as client:
        response = await client.get_network_data(
            network_code=network_code,
            metrics=[metric],
            date_start=since,
            secondary_grouping="fueltech",
        )

    records = response.to_records()
    if not records:
        return pd.DataFrame(columns=list(_LONG_FORM_COLUMNS))

    df = pd.DataFrame(records)
    df = df.rename(
        columns={"interval": "ts", "fueltech": "fuel_type", metric.value: "value"}
    )
    return df[list(_LONG_FORM_COLUMNS)]


async def fetch_network_data(network_code: str, since: datetime) -> pd.DataFrame:
    """Power generation by fuel type for `network_code` since `since`.

    Long-form: one row per `(ts, fuel_type)`, `value` in MW.
    """
    return await _fetch_metric(network_code, since, DataMetric.POWER)


async def fetch_emissions(network_code: str, since: datetime) -> pd.DataFrame:
    """Emissions by fuel type for `network_code` since `since`.

    Long-form: one row per `(ts, fuel_type)`, `value` in kgCO2e.
    """
    return await _fetch_metric(network_code, since, DataMetric.EMISSIONS)
