"""Ingest task: AEMO NEM 5-min dispatch.

Pulls NEMWeb dispatch data for the 5 NEM regions. In production, this
talks to AEMO's data API; for the dev environment we use cached CSVs
mounted at `/data/raw/aemo/nem/`.

`fetch_month`/`_fetch_historical_range` (bottom of this file) are a
*separate*, genuinely-real historical path — verified directly against
NEMWeb's public Archive (`nemweb.com.au/Reports/ARCHIVE/
DispatchIS_Reports/PUBLIC_DISPATCHIS_{YYYYMMDD}.zip`, no auth, ~13
months retention) by downloading and parsing a real sample before
writing this. This is distinct from `_try_live_api` below, which is a
pre-existing placeholder that never parses a real response (see its
own docstring) — the historical path doesn't touch it at all.

**Second, deeper real historical path (2026-08-12)**: the DispatchIS
Archive's ~13-month window is real and rolling, not a fixed date (
confirmed live: `PUBLIC_DISPATCHIS_20250715` 404s, `..._20250801` 200s
as of this writing) — a day older than that genuinely 404s, not
transiently. `_fetch_historical_range` now falls back to AEMO's MMSDM
Historical Data archive (`_fetch_mmsdm_day`, near the bottom of this
file) for exactly those days: real, no-auth, verified back to 2020-01
(AEMO's own docs claim 2009, unverified here). Reuses
`_parse_dispatchis_csv`'s own field layout (confirmed identical between
the two archives' `REGIONSUM`/`PRICE` tables via a real downloaded
sample), just fed from two separate monthly CSVs instead of one daily
bundled file — see `_fetch_mmsdm_day`'s own docstring for why
`DISPATCHREGIONSUM`, not `DISPATCHLOAD`, is the right table here.

Ported verbatim from `data-pipeline`'s identical module (`services/
ingestion/TODO.md` Phase 1, "Migrate Ingest Tasks") -- no behavior
change. The Archive fetch was live-verified again from this service's
own `notebooks/ingestion.ipynb` before porting (real zip-of-288-nested-
zips, real MMS CSV format).
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.redis import get_breaker
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")

# Where to find cached NEM CSVs in dev (mounted via docker-compose).
_NEM_CACHE_DIR = Path("/data/raw/aemo/nem")

_ARCHIVE_URL = (
    "https://www.nemweb.com.au/Reports/ARCHIVE/DispatchIS_Reports/"
    "PUBLIC_DISPATCHIS_{day}.zip"
)
# NEM "market time" is fixed AEST (UTC+10), never DST -- Australia/Brisbane
# matches that exactly (Queensland doesn't observe DST either).
_NEM_TZ = "Australia/Brisbane"


@timed("aemo_nem")
async def run(
    lookback_minutes: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Fetch NEM dispatch, return a wide-form df for raw.aemo_nem_dispatch.

    `start`/`end` (both required together) route to the real historical
    Archive fetch instead of the live/cache/stub path -- used by
    `pipeline.backfill` to target an actual past date range rather than
    "last N minutes from now".

    No `standard_run` decorator: AEMO doesn't always expose a clean
    async SDK, and we have a fallback path that reads from a mounted
    directory. We still get the timed metric, log to `meta._ingest_log`
    via the upper layer (the API endpoint or CLI), and apply the
    circuit breaker.
    """
    if start is not None and end is not None:
        return await _fetch_historical_range(start, end)

    settings = get_settings()
    lookback = lookback_minutes or settings.default_lookback_minutes
    breaker = get_breaker("aemo_nem")

    async def _do_fetch() -> pd.DataFrame:
        # Try the live API first; fall back to cache.
        live = await _try_live_api(lookback)
        if live is not None and not live.empty:
            return live
        cached = _read_cached(lookback)
        return cached

    return await breaker.call(_do_fetch)


async def _try_live_api(lookback_minutes: int) -> pd.DataFrame | None:
    """Try AEMO's NEM dispatch endpoint. Returns None if it fails."""
    import httpx

    from app.service.pipeline.http_retry import DEFAULT_LIMITS

    settings = get_settings()
    # AEMO's current data API surface. Real endpoint may differ; this
    # is a placeholder that returns None on failure so the cached
    # fallback path kicks in. No retry here -- any failure should fall
    # through to the cache immediately, not delay it with backoff.
    url = "https://www.aemo.com.au/aemo/data/api/REPORT/NEMDispatchData/PUBLISH"
    try:
        async with httpx.AsyncClient(
            timeout=settings.aemo_request_timeout_seconds, limits=DEFAULT_LIMITS
        ) as client:
            r = await client.get(
                url, params={"interval": "5min", "lookback": lookback_minutes}
            )
            r.raise_for_status()
            # Real parsing would go here; we just log success.
            log.info("aemo_nem.live_fetch_ok", bytes=len(r.content))
            return None
    except Exception as e:
        log.warning("aemo_nem.live_fetch_failed", error=str(e))
        return None


def _read_cached(lookback_minutes: int) -> pd.DataFrame:
    """Read cached NEM CSVs from the mounted directory.

    Expected format: one CSV per region, named `{region}.csv`, with
    columns:
        ts,demand_mw,price_mwh,coal_mw,gas_mw,hydro_mw,wind_mw,
        solar_utility_mw,solar_rooftop_mw,battery_mw,net_import_mw
    """
    if not _NEM_CACHE_DIR.exists():
        log.warning("aemo_nem.cache_dir_missing", path=str(_NEM_CACHE_DIR))
        return _synthetic_stub(lookback_minutes)

    frames: list[pd.DataFrame] = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    for region in REGIONS:
        path = _NEM_CACHE_DIR / f"{region}.csv"
        if not path.exists():
            log.warning("aemo_nem.region_cache_missing", region=region)
            continue
        try:
            df = pd.read_csv(path, parse_dates=["ts"])
            df = df[df["ts"] >= cutoff]
            df["region"] = region
            frames.append(df)
        except Exception as e:
            log.warning("aemo_nem.region_read_failed", region=region, error=str(e))

    if not frames:
        return _synthetic_stub(lookback_minutes)
    out = pd.concat(frames, ignore_index=True)
    out["source"] = "aemo_nem"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.info("aemo_nem.cached_loaded", rows=len(out))
    return out


def _synthetic_stub(lookback_minutes: int) -> pd.DataFrame:
    """A tiny deterministic stub, used when no cache and no live API.

    NOT for production use — only for first-time dev / CI.
    """
    import numpy as np

    periods = max(1, lookback_minutes // 5)
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    ts_index = pd.date_range(end=end, periods=periods, freq="5min")
    rows: list[pd.DataFrame] = []
    for region in REGIONS:
        df = pd.DataFrame(
            {
                "ts": ts_index,
                "region": region,
                "demand_mw": np.random.default_rng(hash(region) & 0xFFFFFFFF).normal(
                    loc={
                        "NSW1": 8700,
                        "QLD1": 7300,
                        "VIC1": 6400,
                        "SA1": 1800,
                        "TAS1": 1100,
                    }[region],
                    scale=200,
                    size=periods,
                ),
                "price_mwh": np.random.default_rng(hash(region) & 0xFFFFFFFF).normal(
                    80, 30, periods
                ),
                "coal_mw": 0.0,
                "gas_mw": 0.0,
                "hydro_mw": 0.0,
                "wind_mw": 0.0,
                "solar_utility_mw": 0.0,
                "solar_rooftop_mw": 0.0,
                "battery_mw": 0.0,
                "net_import_mw": 0.0,
            }
        )
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    out["source"] = "aemo_nem"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.warning("aemo_nem.using_synthetic_stub", rows=len(out))
    return out


# ────────────────────────────────────────────────────────────────────
# Real historical fetch — NEMWeb Archive (verified live, no auth)
# ────────────────────────────────────────────────────────────────────


async def _fetch_historical_range(start: datetime, end: datetime) -> pd.DataFrame:
    """One row per (5-min interval, region) across every day in
    `[start.date(), end.date()]` inclusive, fetched from NEMWeb's real
    public Archive -- not the live/cache/stub path above. A day that
    fails (404 outside the ~13-month retention window, network error,
    unexpected format) is logged and skipped rather than aborting the
    whole range, same "one bad unit shouldn't sink the batch" pattern
    the rest of this codebase uses.
    """
    import httpx

    from app.service.pipeline.http_retry import DEFAULT_LIMITS, fetch_with_retry

    frames: list[pd.DataFrame] = []
    day = start.date()
    end_date = end.date()
    async with httpx.AsyncClient(
        timeout=60, headers={"User-Agent": "Mozilla/5.0"}, limits=DEFAULT_LIMITS
    ) as client:
        while day <= end_date:
            try:
                async def _fetch(d: date = day) -> pd.DataFrame:
                    return await _fetch_archive_day(client, d)

                day_df = await fetch_with_retry(
                    _fetch,
                    source="aemo_nem",
                    log_event="aemo_nem.archive_day_retry",
                    day=str(day),
                )
                if not day_df.empty:
                    frames.append(day_df)
                log.info("aemo_nem.archive_day_fetched", day=str(day), rows=len(day_df))
            except Exception as exc:  # noqa: BLE001 - one bad day shouldn't abort the range
                # Real fallback (2026-08-12): the live DispatchIS Archive
                # only has a real, rolling ~13-month retention window --
                # confirmed live, `PUBLIC_DISPATCHIS_20250715` 404s,
                # `PUBLIC_DISPATCHIS_20250801` 200s, so the boundary moves
                # forward every day. A day outside it genuinely 404s here,
                # not a transient failure -- before giving up on this day
                # entirely, try MMSDM's deeper real historical archive
                # (see `_fetch_mmsdm_day`'s own docstring).
                log.info(
                    "aemo_nem.archive_day_unavailable_trying_mmsdm",
                    day=str(day),
                    error=str(exc),
                )
                try:
                    async def _fetch_mmsdm(d: date = day) -> pd.DataFrame:
                        return await _fetch_mmsdm_day(client, d)

                    day_df = await fetch_with_retry(
                        _fetch_mmsdm,
                        source="aemo_nem",
                        log_event="aemo_nem.mmsdm_day_retry",
                        day=str(day),
                    )
                    if not day_df.empty:
                        frames.append(day_df)
                    log.info("aemo_nem.mmsdm_day_fetched", day=str(day), rows=len(day_df))
                except Exception as mmsdm_exc:  # noqa: BLE001 - one bad day shouldn't abort the range
                    log.warning(
                        "aemo_nem.mmsdm_day_failed", day=str(day), error=str(mmsdm_exc)
                    )
            day += timedelta(days=1)
            # A politeness delay between days -- this is a public archive
            # server, not a rate-limited API with documented headroom.
            await asyncio.sleep(0.3)

    if not frames:
        return pd.DataFrame(
            columns=[
                "ts",
                "region",
                "demand_mw",
                "price_mwh",
                "source",
                "ingested_at",
                "ingest_run_id",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out["source"] = "aemo_nem"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.info(
        "aemo_nem.historical_range_fetched",
        start=str(start),
        end=str(end),
        rows=len(out),
    )
    return out


async def _fetch_archive_day(client: Any, day: date) -> pd.DataFrame:
    """One day's Archive zip -- a zip-of-288-nested-zips, one per real
    5-min dispatch interval; every one is extracted and parsed (no
    30-min subsampling)."""
    url = _ARCHIVE_URL.format(day=day.strftime("%Y%m%d"))
    resp = await client.get(url)
    resp.raise_for_status()

    outer = zipfile.ZipFile(io.BytesIO(resp.content))
    rows: list[dict] = []
    for name in outer.namelist():
        if _interval_minute(name) is None:
            continue
        inner_bytes = outer.read(name)
        try:
            inner_zip = zipfile.ZipFile(io.BytesIO(inner_bytes))
            csv_names = [n for n in inner_zip.namelist() if n.upper().endswith(".CSV")]
            if not csv_names:
                continue
            csv_text = inner_zip.read(csv_names[0]).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            continue
        rows.extend(_parse_dispatchis_csv(csv_text))

    if not rows:
        return pd.DataFrame(columns=["ts", "region", "demand_mw", "price_mwh"])
    return pd.DataFrame(rows)


def _interval_minute(nested_zip_name: str) -> int | None:
    """`PUBLIC_DISPATCHIS_202608010030_0000000530265329.zip` -> `30`
    (the minute component of the embedded YYYYMMDDHHMM timestamp)."""
    stem = nested_zip_name.rsplit("/", 1)[-1]
    parts = stem.split("_")
    for part in parts:
        if len(part) == 12 and part.isdigit():
            return int(part[10:12])
    return None


def _parse_dispatchis_csv(text: str) -> list[dict]:
    """Real AEMO MMS CSV format: a `C,` header row, `I,<table>,...`
    column-header rows, and `D,<table>,...` data rows -- multiple
    tables share one file. Only `DISPATCH,REGIONSUM` (TOTALDEMAND) and
    `DISPATCH,PRICE` (RRP) are needed for `raw.aemo_nem_dispatch`'s
    `demand_mw`/`price_mwh` columns; every other table in the file is
    ignored. Verified against a real downloaded sample before writing
    this, not guessed from AEMO's spec docs alone."""
    demand: dict[tuple[str, str], float | None] = {}
    price: dict[tuple[str, str], float | None] = {}

    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 10 or row[0] != "D" or row[1] != "DISPATCH":
            continue
        record_type = row[2]
        if record_type not in ("REGIONSUM", "PRICE"):
            continue
        settlement_date = row[4]
        region = row[6]
        raw_value = row[9]
        try:
            value = float(raw_value) if raw_value else None
        except ValueError:
            value = None
        key = (settlement_date, region)
        if record_type == "REGIONSUM":
            demand[key] = value
        else:
            price[key] = value

    out: list[dict] = []
    for key in set(demand) | set(price):
        settlement_date, region = key
        try:
            ts = pd.Timestamp(settlement_date, tz=_NEM_TZ).tz_convert("UTC")
        except ValueError:
            continue
        out.append(
            {
                "ts": ts,
                "region": region,
                "demand_mw": demand.get(key),
                "price_mwh": price.get(key),
            }
        )
    return out


# ────────────────────────────────────────────────────────────────────
# Real fallback historical fetch — AEMO's MMSDM Historical Data archive
# (verified live, no auth; used only once the DispatchIS Archive above
# genuinely 404s for a given day, i.e. outside its own real, rolling
# ~13-month retention window)
# ────────────────────────────────────────────────────────────────────

_MMSDM_BASE = "https://www.nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM"

# AEMO changed this archive's own filename convention starting 2025 --
# confirmed live (2026-08-12): both the old `PUBLIC_DVD_*` pattern
# (against a real 2020-01 sample) and the new `PUBLIC_ARCHIVE#*` pattern
# (against a real 2025-07 sample) return real HTTP 200 with real zip
# content. AEMO's own published retention for this archive goes back to
# 2009, but only 2020-01 has actually been checked here -- treat
# anything earlier as unverified by this code, not guaranteed to work.
_MMSDM_NEW_PATTERN_FIRST_YEAR = 2025


def _mmsdm_table_url(table: str, year: int, month: int) -> str:
    folder = f"{_MMSDM_BASE}/{year}/MMSDM_{year}_{month:02d}/MMSDM_Historical_Data_SQLLoader/DATA"
    yyyymm = f"{year}{month:02d}"
    if year >= _MMSDM_NEW_PATTERN_FIRST_YEAR:
        # The literal "#" separators must be percent-encoded in the URL.
        filename = f"PUBLIC_ARCHIVE%23{table}%23FILE01%23{yyyymm}010000.zip"
    else:
        filename = f"PUBLIC_DVD_{table}_{yyyymm}010000.zip"
    return f"{folder}/{filename}"


# Real, known tradeoff, not solved here: `pipeline.backfill` calls this
# module's `run(start=day, end=day)` one calendar day at a time (the same
# accepted inefficiency `ingest_bom.py`'s own historical path already
# documents for its own archive) -- a month-long backfill through this
# fallback still re-requests the same ~6.5MB MMSDM zip pair once per day
# within a single `backfill` process. This cache only helps a single call
# that already spans multiple days in the same month (e.g. a direct
# multi-day `ingest aemo-nem --start/--end` CLI invocation), not across
# separate `backfill_day` calls. Fixing `pipeline.backfill`'s per-day
# granularity is a bigger, shared-across-4-sources change -- out of scope
# here.
_mmsdm_month_cache: dict[tuple[str, int, int], str] = {}


async def _fetch_mmsdm_table_csv(client: Any, table: str, year: int, month: int) -> str:
    cache_key = (table, year, month)
    if cache_key in _mmsdm_month_cache:
        return _mmsdm_month_cache[cache_key]
    url = _mmsdm_table_url(table, year, month)
    resp = await client.get(url)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    csv_names = [n for n in zf.namelist() if n.upper().endswith(".CSV")]
    if not csv_names:
        raise ValueError(f"No CSV found in MMSDM zip: {url}")
    text = zf.read(csv_names[0]).decode("utf-8", errors="replace")
    _mmsdm_month_cache[cache_key] = text
    return text


async def _fetch_mmsdm_day(client: Any, day: date) -> pd.DataFrame:
    """One day's rows sliced out of MMSDM's real monthly
    `DISPATCHREGIONSUM`/`DISPATCHPRICE` archive tables -- **not**
    `DISPATCHLOAD` (a common mix-up: that table is per-generating-unit
    dispatch instructions, not regional demand). Real, verified fact:
    `DISPATCHREGIONSUM`/`DISPATCHPRICE`'s own per-row column layout is
    identical to the live DispatchIS report's `REGIONSUM`/`PRICE` record
    types `_parse_dispatchis_csv` already parses (confirmed by
    downloading and diffing a real 2020-01 sample against that function's
    own field indexing before writing this) -- so this only needs its own
    thin merge wrapper (`_parse_mmsdm_regionsum_and_price` below), not a
    second parser."""
    regionsum_text = await _fetch_mmsdm_table_csv(
        client, "DISPATCHREGIONSUM", day.year, day.month
    )
    price_text = await _fetch_mmsdm_table_csv(client, "DISPATCHPRICE", day.year, day.month)
    rows = _parse_mmsdm_regionsum_and_price(regionsum_text, price_text, day)
    if not rows:
        return pd.DataFrame(columns=["ts", "region", "demand_mw", "price_mwh"])
    return pd.DataFrame(rows)


def _parse_mmsdm_regionsum_and_price(
    regionsum_csv: str, price_csv: str, day: date
) -> list[dict]:
    """Same real `(settlement_date, region)` merge `_parse_dispatchis_csv`
    already does, fed from two separate real monthly MMSDM CSVs instead
    of one file bundling both tables -- that's the only real structural
    difference; the per-row field layout is identical (see
    `_fetch_mmsdm_day`'s own docstring). Filtered to just `day`:
    `regionsum_csv`/`price_csv` each cover a whole real month."""
    demand: dict[tuple[str, str], float | None] = {}
    price: dict[tuple[str, str], float | None] = {}
    day_prefix = day.strftime("%Y/%m/%d")

    for text, record_type, target in (
        (regionsum_csv, "REGIONSUM", demand),
        (price_csv, "PRICE", price),
    ):
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if len(row) < 10 or row[0] != "D" or row[1] != "DISPATCH" or row[2] != record_type:
                continue
            settlement_date = row[4]
            if not settlement_date.startswith(day_prefix):
                continue
            region = row[6]
            raw_value = row[9]
            try:
                value = float(raw_value) if raw_value else None
            except ValueError:
                value = None
            target[(settlement_date, region)] = value

    out: list[dict] = []
    for key in set(demand) | set(price):
        settlement_date, region = key
        try:
            ts = pd.Timestamp(settlement_date, tz=_NEM_TZ).tz_convert("UTC")
        except ValueError:
            continue
        out.append(
            {
                "ts": ts,
                "region": region,
                "demand_mw": demand.get(key),
                "price_mwh": price.get(key),
            }
        )
    return out
