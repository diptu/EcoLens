"""OpenElectricity SDK wrappers.

Thin async wrappers around the official `openelectricity` PyPI package,
returning long-form `pandas.DataFrame`s (`ts`, `fuel_type`, `value`) —
that's the shape `app.service.pipeline.tasks.ingest_openelectricity` pivots
into our wide `raw.openelectricity_mix` schema.

`settings.oe_api_key` is typed optional, but the installed SDK
(`openelectricity>=0.11.3`) does NOT support anonymous access despite what
this docstring used to say -- `AsyncOEClient.__init__` raises
`OpenElectricityError` immediately if neither `api_key` nor the
`OPENELECTRICITY_API_KEY` env var is set (confirmed directly against
`openelectricity/client.py`), before any HTTP call is even made. Without
a real key, every network's fetch in `ingest_openelectricity.run()` raises
this on construction, gets caught by that function's per-network
try/except, and the run completes as `status=success, rows_landed=0` --
which reads as "nothing new today," not "this source is completely
broken." Confirmed the hard way: `raw.openelectricity_mix` (and
everything downstream of it -- `int_mix_share` -> `int_fuel_emissions` ->
`int_carbon_intensity` -> `fct_carbon_intensity`/`fct_emissions_5min`,
i.e. every emissions-intensity mart, `GET /v1/emissions*`, and the
dashboard's "Emissions Trend"/"Carbon Intensity" cards) sat 8+ days stale
purely because `OE_API_KEY` was unset -- AEMO NEM/WEM ingestion kept
landing fresh rows the entire time, completely unaffected, because none
of this depends on AEMO data at all.

`network_region` (`todo-model-training.md`'s OE region-join blocker,
fixed 2026-08-05): `AsyncOEClient.get_network_data`'s own real, typed
signature (confirmed by reading the installed SDK directly, not
guessed) accepts a `network_region: str | None` param the previous
version of this module never passed -- every call queried at whole-
*network* granularity only (NEM or WEM combined), never per-region.
`ingest_openelectricity.py` used to call this once per NEM region
(NSW1/QLD1/VIC1/SA1/TAS1) but always with the same network-only query,
then labelled the (identical, network-wide) result with each region's
code in turn -- meaning even a real (not just NULL-blocked) run would
have written 5 duplicate rows with `NSW1`'s `total_generation_mw` equal
to `QLD1`'s equal to `VIC1`'s etc., silently masquerading as real
per-region data. Passing `network_region` now asks OE for genuinely
region-scoped numbers, matching AEMO's own bidding-region codes
(`NSW1`/`QLD1`/`VIC1`/`SA1`/`TAS1`) -- the same codes this codebase
already uses everywhere else for these regions, not a new convention
invented here.

**Second, previously-unobservable bug found + fixed the same day, once
a real `OE_API_KEY` was actually available to test against the live
API for the first time**: OE's `/data/network/{code}` endpoint rejects a
timezone-aware `date_start` outright (`"Date start must be timezone
naive and in network time"`, confirmed live) -- but the SDK's own
`get_network_data` just does `date_start.isoformat()` on whatever's
passed, and `since` here has always been UTC-aware
(`datetime.now(timezone.utc) - timedelta(...)`,
`ingest_openelectricity.py`). Every OE call would have failed this way
regardless of the `network_region` fix above -- this was unreachable
code before today because `OE_API_KEY` being unset always raised first,
on client construction. Separately, the SDK's own `to_records()`
(`TimeSeriesResponse._create_network_date`, read directly) returns each
point's `interval` as a **naive datetime already shifted into network
local time**, not UTC -- silently reusing it as `ts` would misalign
every OE row against AEMO's UTC `ts` by the network's fixed UTC offset
once joined. NEM reports in fixed AEST (UTC+10, no DST) and WEM in fixed
AWST (UTC+8, no DST) -- confirmed against real API responses' own
`date_start`/`date_end` fields, not assumed. `_fetch_metric` now
converts `since` to naive network-local time before querying, and
converts the response's `ts` back to real UTC before returning it --
both directions of the same fixed, network-specific offset. Live-
verified against the real OE API this session (200 OK, real per-region
records returned for NEM/WEM alike).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from openelectricity import AsyncOEClient, DataMetric

from app.core.config import get_settings

_LONG_FORM_COLUMNS = ("ts", "fuel_type", "value")

# OE's API reports (and expects `date_start` in) each network's own
# fixed local time, not UTC -- confirmed live against real API responses
# (`date_start`/`date_end` in returned payloads use these exact
# offsets). Both NEM (AEST) and WEM (AWST) are fixed, no daylight
# saving, in OE's own market-time convention.
_NETWORK_UTC_OFFSET_HOURS: dict[str, int] = {"NEM": 10, "WEM": 8}


def _network_timezone(network_code: str) -> timezone:
    return timezone(timedelta(hours=_NETWORK_UTC_OFFSET_HOURS.get(network_code, 10)))


async def _fetch_metric(
    network_code: str,
    since: datetime,
    metric: DataMetric,
    network_region: str | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    settings = get_settings()
    tz = _network_timezone(network_code)
    # OE rejects a tz-aware `date_start`/`date_end` -- naive, in the
    # network's own local time, is what its API actually expects (see
    # module docstring).
    naive_local_since = since.astimezone(tz).replace(tzinfo=None)
    naive_local_until = until.astimezone(tz).replace(tzinfo=None) if until else None

    async with AsyncOEClient(api_key=settings.oe_api_key) as client:
        response = await client.get_network_data(
            network_code=network_code,
            metrics=[metric],
            date_start=naive_local_since,
            date_end=naive_local_until,
            network_region=network_region,
            secondary_grouping="fueltech",
        )

    records = response.to_records()
    if not records:
        return pd.DataFrame(columns=list(_LONG_FORM_COLUMNS))

    df = pd.DataFrame(records)
    df = df.rename(
        columns={"interval": "ts", "fueltech": "fuel_type", metric.value: "value"}
    )
    # The SDK returns `interval` as naive network-local time, not UTC
    # (see module docstring) -- localize then convert back to real UTC
    # so `ts` is directly comparable with AEMO's UTC timestamps
    # downstream (`int_demand_with_weather.sql`'s as-of join).
    df["ts"] = df["ts"].dt.tz_localize(tz).dt.tz_convert("UTC")
    return df[list(_LONG_FORM_COLUMNS)]


async def fetch_network_data(
    network_code: str,
    since: datetime,
    network_region: str | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Power generation by fuel type for `network_code`, in `[since,
    until)` -- `until` omitted (the default) means "through now".

    `network_region` (e.g. `"NSW1"`) scopes the query to one region
    within a multi-region network -- omitted (the default) queries the
    whole network combined, the only mode this used to support at all.

    Long-form: one row per `(ts, fuel_type)`, `value` in MW.
    """
    return await _fetch_metric(
        network_code, since, DataMetric.POWER, network_region, until
    )


async def fetch_emissions(
    network_code: str,
    since: datetime,
    network_region: str | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Emissions by fuel type for `network_code`, in `[since, until)`.
    Same `network_region`/`until` scoping as `fetch_network_data`.

    Long-form: one row per `(ts, fuel_type)`, `value` in kgCO2e.
    """
    return await _fetch_metric(
        network_code, since, DataMetric.EMISSIONS, network_region, until
    )
