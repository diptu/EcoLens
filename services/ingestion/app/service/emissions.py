"""OpenElectricity SDK wrappers.

Thin async wrappers around the official `openelectricity` PyPI package,
returning long-form `pandas.DataFrame`s (`ts`, `fuel_type`, `value`) —
that's the shape `app.service.pipeline.tasks.ingest_openelectricity` pivots
into our wide `raw.openelectricity_mix` schema.

Ported verbatim from `data-pipeline`'s identical module
(`services/ingestion/TODO.md` Phase 1, "Migrate Ingest Tasks") — no
behavior change.

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

**Real, live-confirmed hang found + fixed (2026-08-13), while running a
real multi-month historical backfill for the first time**: `_fetch_metric`
awaited `client.get_network_data(...)` with no timeout at all. The
installed SDK's `_build_session` (`openelectricity/client.py`) forces
`aiohttp`'s `ThreadedResolver` for DNS instead of the C-ares
`AsyncResolver` (its own comment explains why -- a different, unrelated
DNS-failure workaround), but a stalled OS-level `getaddrinfo()` call
inside that resolver's worker thread isn't reliably interrupted by
`aiohttp`'s own per-request timeout machinery -- confirmed live: a real
backfill process sat with **zero CPU activity, no exception, no log
line** on one single day's request for 20+ minutes before it was killed
by hand. Every call normally takes ~1-2s (this module's own docstring
already knew that), so a real stall there is silent and unbounded, not
just slow. Fixed by wrapping the call in `asyncio.wait_for` with a
generous-but-bounded timeout, retried a few times with a **fresh**
`AsyncOEClient`/connection each attempt (reusing the same stuck
connection would just hang again) -- same jittered-backoff shape
`pipeline.http_retry.fetch_with_retry` already uses for the `httpx`-based
ingest sources, not reusable here as-is since this SDK is
`aiohttp`-based and raises different exception types, but the same
pattern. A timeout that exhausts all retries still raises, same as any
other real error -- `ingest_openelectricity._fetch_all_regions`'s
existing per-region `try/except Exception` already logs and moves on to
the next region/day rather than losing the whole run.

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

import asyncio
import random
from datetime import datetime, timedelta, timezone

import aiohttp
import pandas as pd
from openelectricity import AsyncOEClient, DataMetric
from openelectricity.models.timeseries import TimeSeriesResponse

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_LONG_FORM_COLUMNS = ("ts", "fuel_type", "value")

# A real call normally takes ~1-2s (module docstring) -- generous
# headroom over that, but still bounded, so a genuine stall (see module
# docstring's "Real, live-confirmed hang" note) fails fast instead of
# hanging forever.
_REQUEST_TIMEOUT_SECONDS = 45.0
_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 1.0


def _to_records_linear(self: TimeSeriesResponse) -> list[dict]:
    """Drop-in replacement for the installed SDK's own `TimeSeriesResponse.
    to_records()` (`openelectricity/models/timeseries.py`), monkeypatched
    on below. The original re-scans the entire `records` list built so
    far -- calling `.isoformat()` on every existing record's interval --
    for every single point, an O(n^2) merge live-confirmed to make a
    single day's fetch take 30-60+ minutes once a network-region's real
    fueltech-grouping count grew large enough (`ingest_openelectricity.
    py`'s own docstring already knew this path was O(n^2) and kept calls
    to one day at a time for it, but hadn't hit a slow-enough day yet to
    need this). Same output shape/semantics, just an O(1) dict lookup
    (keyed by the same `(timestamp, sorted groupings)` identity) instead
    of a linear scan, making the whole merge O(n).
    """
    if not self.data:
        return []

    records: list[dict] = []
    index: dict[tuple, dict] = {}

    for series in self.data:
        for result in series.results:
            groupings = {
                k: v
                for k, v in result.columns.__dict__.items()
                if v is not None and k != "unit_code"
            }
            sorted_groupings = tuple(sorted(groupings.items()))

            for point in result.data:
                record_key = (point.timestamp.isoformat(), sorted_groupings)
                existing_record = index.get(record_key)

                if existing_record is not None:
                    existing_record[series.metric] = point.value
                else:
                    record = {
                        "interval": self._create_network_date(
                            point.timestamp, series.network_timezone_offset
                        ),
                        **groupings,
                        series.metric: point.value,
                    }
                    records.append(record)
                    index[record_key] = record

    return records


TimeSeriesResponse.to_records = _to_records_linear

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

    response: TimeSeriesResponse | None = None
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            # A fresh client (and connection) each attempt -- retrying
            # against the same stuck connection would just hang again.
            async with AsyncOEClient(api_key=settings.oe_api_key) as client:
                response = await asyncio.wait_for(
                    client.get_network_data(
                        network_code=network_code,
                        metrics=[metric],
                        date_start=naive_local_since,
                        date_end=naive_local_until,
                        network_region=network_region,
                        secondary_grouping="fueltech",
                    ),
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
            break
        except (TimeoutError, aiohttp.ClientError) as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS - 1:
                delay = _BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 0.25)
                log.warning(
                    "oe.fetch_metric_retry",
                    attempt=attempt + 1,
                    max_attempts=_MAX_ATTEMPTS,
                    sleep_seconds=round(delay, 2),
                    network_code=network_code,
                    metric=metric.value,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

    if response is None:
        assert last_error is not None  # noqa: S101 -- loop above always sets it before falling through
        raise last_error

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
