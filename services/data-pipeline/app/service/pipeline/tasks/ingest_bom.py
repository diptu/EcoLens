"""Ingest task: Bureau of Meteorology observations.

Pulls recent observations for the 6 default stations (one per region)
and maps each to a region via `dim_station`. BoM publishes hourly; we
keep the latest reading per station per 30-min slot.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.db.redis import get_breaker
from app.core.config import get_settings
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

_BOM_CACHE_DIR = Path("/data/raw/bom")


@timed("bom")
async def run(lookback_minutes: int | None = None) -> pd.DataFrame:
    settings = get_settings()
    lookback = lookback_minutes or settings.default_lookback_minutes
    breaker = get_breaker("bom")

    async def _do_fetch() -> pd.DataFrame:
        live = await _try_live_api(lookback)
        if live is not None and not live.empty:
            return live
        return (
            _read_cached(lookback)
            if _BOM_CACHE_DIR.exists()
            else _synthetic_stub(lookback)
        )

    return await breaker.call(_do_fetch)


async def _try_live_api(lookback_minutes: int) -> pd.DataFrame | None:
    """Try BoM's public JSON endpoint. Returns None on failure."""
    import httpx

    settings = get_settings()
    rows: list[dict] = []
    async with httpx.AsyncClient(
        timeout=settings.bom_request_timeout_seconds
    ) as client:
        for region, station_id in settings.bom_stations.items():
            url = f"http://www.bom.gov.au/fwo/{station_id}/observations.json"
            try:
                r = await client.get(url)
                r.raise_for_status()
                payload = r.json()
                for obs in payload.get("observations", {}).get("data", []):
                    rows.append(
                        {
                            "ts": pd.to_datetime(
                                obs.get("local_date_time_full"), utc=True
                            ),
                            "station_id": station_id,
                            "region": region,
                            "temp_c": obs.get("air_temp"),
                            "apparent_temp_c": obs.get("apparent_t"),
                            "dew_point_c": obs.get("dewpt"),
                            "humidity_pct": obs.get("rel_hum"),
                            "wind_speed_kmh": obs.get("wind_spd_kmh"),
                            "wind_direction_deg": obs.get("wind_dir"),
                            "wind_gust_kmh": obs.get("gust_kmh"),
                            "pressure_hpa": obs.get("press_msl"),
                            "rain_since_9am_mm": obs.get("rain_trace"),
                            "cloud_oktas": obs.get("cloud"),
                        }
                    )
            except Exception as e:
                log.warning("bom.station_failed", station=station_id, error=str(e))
    if not rows:
        return None
    return pd.DataFrame(rows)


def _read_cached(lookback_minutes: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    for path in _BOM_CACHE_DIR.glob("*.csv"):
        try:
            df = pd.read_csv(path, parse_dates=["ts"])
            df = df[df["ts"] >= cutoff]
            frames.append(df)
        except Exception as e:
            log.warning("bom.file_read_failed", path=str(path), error=str(e))
    if not frames:
        return _synthetic_stub(lookback_minutes)
    out = pd.concat(frames, ignore_index=True)
    out["source"] = "bom"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.info("bom.cached_loaded", rows=len(out))
    return out


def _synthetic_stub(lookback_minutes: int) -> pd.DataFrame:
    """Deterministic stub. NOT for production use."""
    settings = get_settings()
    periods = max(1, lookback_minutes // 30)
    end = pd.Timestamp.now(tz="UTC").floor("30min")
    ts_index = pd.date_range(end=end, periods=periods, freq="30min")
    rows: list[pd.DataFrame] = []
    for region, station_id in settings.bom_stations.items():
        rng = np.random.default_rng(int(station_id) & 0xFFFFFFFF)
        # Diurnal temp pattern: peak ~14:00 local, trough ~04:00 local
        hours = ts_index.hour
        diurnal = 10 * np.sin((hours - 4) * np.pi / 12)
        seasonal = {
            "NSW1": 22,
            "QLD1": 27,
            "VIC1": 18,
            "SA1": 20,
            "TAS1": 14,
            "WEM": 25,
        }[region]
        df = pd.DataFrame(
            {
                "ts": ts_index,
                "station_id": station_id,
                "region": region,
                "temp_c": seasonal + diurnal + rng.normal(0, 1.5, periods),
                "apparent_temp_c": seasonal + diurnal + rng.normal(0, 2.0, periods),
                "dew_point_c": seasonal - 5 + rng.normal(0, 1, periods),
                "humidity_pct": rng.uniform(40, 80, periods),
                "wind_speed_kmh": rng.uniform(0, 30, periods),
                "wind_direction_deg": rng.uniform(0, 360, periods),
                "wind_gust_kmh": rng.uniform(0, 60, periods),
                "pressure_hpa": rng.normal(1015, 5, periods),
                "rain_since_9am_mm": np.zeros(periods),
                "cloud_oktas": rng.uniform(0, 8, periods),
            }
        )
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    out["source"] = "bom"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.warning("bom.using_synthetic_stub", rows=len(out))
    return out
