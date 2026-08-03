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

from app.db.redis import get_breaker
from app.core.config import get_settings
from app.core.logging import get_logger
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
# Sample the 30-min marks only, not all 288 5-min intervals/day -- matches
# task.md's own documented "5-min -> 30-min resampled" granularity and
# keeps a month's worth of nested-zip extraction to ~1,440 files instead
# of ~8,640.
_SAMPLED_MINUTES = {0, 30}


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

    settings = get_settings()
    # AEMO's current data API surface. Real endpoint may differ; this
    # is a placeholder that returns None on failure so the cached
    # fallback path kicks in.
    url = "https://www.aemo.com.au/aemo/data/api/REPORT/NEMDispatchData/PUBLISH"
    try:
        async with httpx.AsyncClient(
            timeout=settings.aemo_request_timeout_seconds
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
    """One row per (30-min interval, region) across every day in
    `[start.date(), end.date()]` inclusive, fetched from NEMWeb's real
    public Archive -- not the live/cache/stub path above. A day that
    fails (404 outside the ~13-month retention window, network error,
    unexpected format) is logged and skipped rather than aborting the
    whole range, same "one bad unit shouldn't sink the batch" pattern
    the rest of this codebase uses.
    """
    import httpx

    frames: list[pd.DataFrame] = []
    day = start.date()
    end_date = end.date()
    async with httpx.AsyncClient(
        timeout=60, headers={"User-Agent": "Mozilla/5.0"}
    ) as client:
        while day <= end_date:
            try:
                day_df = await _fetch_archive_day(client, day)
                if not day_df.empty:
                    frames.append(day_df)
                log.info("aemo_nem.archive_day_fetched", day=str(day), rows=len(day_df))
            except Exception as exc:  # noqa: BLE001 - one bad day shouldn't abort the range
                log.warning("aemo_nem.archive_day_failed", day=str(day), error=str(exc))
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
    """One day's Archive zip -- a zip-of-288-nested-zips (one per 5-min
    dispatch interval); only the ones landing on a 30-min mark
    (`_SAMPLED_MINUTES`) are extracted and parsed."""
    url = _ARCHIVE_URL.format(day=day.strftime("%Y%m%d"))
    resp = await client.get(url)
    resp.raise_for_status()

    outer = zipfile.ZipFile(io.BytesIO(resp.content))
    rows: list[dict] = []
    for name in outer.namelist():
        minute_match = _interval_minute(name)
        if minute_match is None or minute_match not in _SAMPLED_MINUTES:
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
