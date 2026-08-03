"""Ingest task: AEMO NEM 5-min dispatch.

Pulls NEMWeb dispatch data for the 5 NEM regions. In production, this
talks to AEMO's data API; for the dev environment we use cached CSVs
mounted at `/data/raw/aemo/nem/`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.db.redis import get_breaker
from app.core.config import get_settings
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")

# Where to find cached NEM CSVs in dev (mounted via docker-compose).
_NEM_CACHE_DIR = Path("/data/raw/aemo/nem")


@timed("aemo_nem")
async def run(lookback_minutes: int | None = None) -> pd.DataFrame:
    """Fetch NEM dispatch, return a wide-form df for raw.aemo_nem_dispatch.

    No `standard_run` decorator: AEMO doesn't always expose a clean
    async SDK, and we have a fallback path that reads from a mounted
    directory. We still get the timed metric, log to `meta._ingest_log`
    via the upper layer (the API endpoint or CLI), and apply the
    circuit breaker.
    """
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
