"""Ingest task: AEMO WEM (SWIS) 30-min data.

WEM is the Western Australian wholesale market. It's a separate market
from NEM: different fuel mix (heavy on coal + gas, growing wind/solar),
different time zone (WST = UTC+8, no DST), different settlement.

In production: hit https://data.wa.aemo.com.au/.
In dev: read from `/data/raw/aemo/wem/`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.db.redis import get_breaker
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

_WEM_CACHE_DIR = Path("/data/raw/aemo/wem")


@timed("aemo_wem")
async def run(lookback_minutes: int | None = None) -> pd.DataFrame:
    settings_lookup = None
    from app.core.config import get_settings

    settings_lookup = get_settings()
    lookback = lookback_minutes or settings_lookup.default_lookback_minutes
    breaker = get_breaker("aemo_wem")

    async def _do_fetch() -> pd.DataFrame:
        live = await _try_live_api(lookback)
        if live is not None and not live.empty:
            return live
        return (
            _read_cached(lookback)
            if _WEM_CACHE_DIR.exists()
            else _synthetic_stub(lookback)
        )

    return await breaker.call(_do_fetch)


async def _try_live_api(lookback_minutes: int) -> pd.DataFrame | None:
    """Try AEMO WEM's published CSV. Returns None on failure."""
    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    url = "https://data.wa.aemo.com.au/datafiles/balancing-summary/balancing-summary-30min.csv"
    try:
        async with httpx.AsyncClient(
            timeout=settings.aemo_request_timeout_seconds
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            log.info("aemo_wem.live_fetch_ok", bytes=len(r.content))
            # Real parsing would go here.
            return None
    except Exception as e:
        log.warning("aemo_wem.live_fetch_failed", error=str(e))
        return None


def _read_cached(lookback_minutes: int) -> pd.DataFrame:
    path = _WEM_CACHE_DIR / "wem.csv"
    if not path.exists():
        return _synthetic_stub(lookback_minutes)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    df = pd.read_csv(path, parse_dates=["ts"])
    df = df[df["ts"] >= cutoff]
    df["region"] = "WEM"
    df["source"] = "aemo_wem"
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    df["ingest_run_id"] = str(uuid.uuid4())
    log.info("aemo_wem.cached_loaded", rows=len(df))
    return df


def _synthetic_stub(lookback_minutes: int) -> pd.DataFrame:
    """Deterministic stub. NOT for production use."""
    periods = max(1, lookback_minutes // 30)
    end = pd.Timestamp.now(tz="UTC").floor("30min")
    ts_index = pd.date_range(end=end, periods=periods, freq="30min")
    rng = np.random.default_rng(0xC0FFEE)
    df = pd.DataFrame(
        {
            "ts": ts_index,
            "region": "WEM",
            "demand_mw": rng.normal(2500, 80, periods),
            "price_mwh": rng.normal(75, 25, periods),
            "coal_mw": rng.normal(900, 30, periods),
            "gas_mw": rng.normal(1100, 40, periods),
            "diesel_mw": rng.normal(40, 5, periods),
            "wind_mw": rng.normal(350, 60, periods),
            "solar_utility_mw": rng.normal(150, 40, periods),
            "solar_rooftop_mw": rng.normal(220, 50, periods),
            "battery_mw": rng.normal(20, 15, periods),
            "biomass_mw": rng.normal(15, 3, periods),
            "total_generation_mw": 0.0,  # filled below
        }
    )
    fuel_cols = [
        "coal_mw",
        "gas_mw",
        "diesel_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_mw",
        "biomass_mw",
    ]
    df["total_generation_mw"] = df[fuel_cols].sum(axis=1)
    df["source"] = "aemo_wem"
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    df["ingest_run_id"] = str(uuid.uuid4())
    log.warning("aemo_wem.using_synthetic_stub", rows=len(df))
    return df
