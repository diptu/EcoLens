"""Ingest task: Bureau of Meteorology observations.

Pulls recent observations for the 6 default stations (one per region)
and maps each to a region via `dim_station`. BoM publishes hourly; we
keep the latest reading per station per 30-min slot.

`start`/`end` (both required together) route to `_fetch_historical_range`
instead of the live/cache/stub path below -- real historical weather via
Open-Meteo's ERA5 reanalysis archive, verified live before writing this
(2026-08-05). BoM's own public API (`_try_live_api`'s `fwo` JSON
endpoint) only ever exposes a rolling ~72h window with no date-range
query at all -- there is no equivalent "BoM archive" the way AEMO
publishes one for NEM/WEM dispatch. See `_fetch_historical_range`'s own
docstring for what does and doesn't map cleanly onto this module's
existing BoM-shaped schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.db.redis import get_breaker
from app.core.config import get_settings
from app.core.logging import get_logger
from app.service.pipeline.tasks._common import timed

log = get_logger(__name__)

_BOM_CACHE_DIR = Path("/data/raw/bom")


@timed("bom")
async def run(
    lookback_minutes: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """`start`/`end` route to the real historical fetch instead of the
    live/cache/stub path -- used by `pipeline.backfill` to target an
    actual past date range rather than "last N minutes from now"."""
    if start is not None and end is not None:
        return await _fetch_historical_range(start, end)

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


# ────────────────────────────────────────────────────────────────────
# Real historical fetch — Open-Meteo's ERA5 reanalysis archive
# ────────────────────────────────────────────────────────────────────

# Real lat/lon for the 6 station IDs `Settings.bom_stations` already
# uses (airport-adjacent, ~11km ERA5 grid resolution makes sub-km
# precision unnecessary) -- Open-Meteo's archive is coordinate-based,
# not BoM-station-ID-based, so this is the join between the two.
_STATION_COORDS: dict[str, tuple[float, float]] = {
    "066037": (-33.9465, 151.1731),  # Sydney Airport, NSW1
    "040913": (-27.3942, 153.1218),  # Brisbane Airport, QLD1
    "086282": (-37.6690, 144.8410),  # Melbourne Airport, VIC1
    "023034": (-34.9524, 138.5196),  # Adelaide Airport, SA1
    "094029": (-42.8362, 147.5033),  # Hobart Airport, TAS1
    "009225": (-31.9403, 115.9669),  # Perth Airport, WEM
}

_OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Requested with `timezone=UTC` so `hourly.time` comes back already in
# UTC -- no separate localize/convert step needed to match the rest of
# this schema's UTC convention.
_OPEN_METEO_HOURLY_VARS: tuple[str, ...] = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "cloud_cover",
)


async def _fetch_historical_range(start: datetime, end: datetime) -> pd.DataFrame:
    """One row per (hour, station) across `[start, end]`, real data from
    Open-Meteo's ERA5 archive -- verified live (2026-08-05) against
    real station coordinates before writing this, not assumed from
    documentation. Free, no API key, hourly, 1940-present.

    **Not a 1:1 field match with `_try_live_api`'s BoM JSON** (this
    module's schema was originally built around BoM's own field names):
    `rain_since_9am_mm` has no Open-Meteo equivalent -- BoM's own
    convention is cumulative rainfall since the last 9am reset, whereas
    Open-Meteo only reports per-hour `precipitation`, a materially
    different quantity that would be dishonest to silently relabel.
    Left `NULL` for every historical row rather than mapped to a wrong
    number. `cloud_oktas` **is** a real, documented unit conversion
    (Open-Meteo's `cloud_cover` is 0-100%; oktas is the standard 0-8
    scale, `oktas = cloud_cover_pct / 12.5`), not an approximation.

    One HTTP request per station for the whole range -- Open-Meteo's
    archive endpoint takes a date range directly, unlike AEMO's
    day-at-a-time archive files, so there's no need to loop per day.
    A station whose coordinates aren't in `_STATION_COORDS`, or whose
    request fails, is logged and skipped rather than aborting the
    other 5 -- same "one bad unit shouldn't sink the batch" pattern
    `ingest_aemo_nem.py`/`ingest_aemo_wem.py` already use.
    """
    import httpx

    frames: list[pd.DataFrame] = []
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        for region, station_id in settings.bom_stations.items():
            coords = _STATION_COORDS.get(station_id)
            if coords is None:
                log.warning(
                    "bom.no_coords_for_station", station=station_id, region=region
                )
                continue
            try:
                station_df = await _fetch_open_meteo_station(
                    client, station_id, region, coords, start, end
                )
                if not station_df.empty:
                    frames.append(station_df)
                log.info(
                    "bom.archive_station_fetched",
                    station=station_id,
                    region=region,
                    rows=len(station_df),
                )
            except Exception as exc:  # noqa: BLE001 - one bad station shouldn't abort the batch
                log.warning(
                    "bom.archive_station_failed",
                    station=station_id,
                    region=region,
                    error=str(exc),
                )

    if not frames:
        return pd.DataFrame(
            columns=[
                "ts",
                "station_id",
                "region",
                "temp_c",
                "apparent_temp_c",
                "dew_point_c",
                "humidity_pct",
                "wind_speed_kmh",
                "wind_direction_deg",
                "wind_gust_kmh",
                "pressure_hpa",
                "rain_since_9am_mm",
                "cloud_oktas",
                "source",
                "ingested_at",
                "ingest_run_id",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out["source"] = "bom"
    out["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out["ingest_run_id"] = str(uuid.uuid4())
    log.info(
        "bom.historical_range_fetched", start=str(start), end=str(end), rows=len(out)
    )
    return out


async def _fetch_open_meteo_station(
    client: Any,  # httpx.AsyncClient -- imported locally in the caller
    station_id: str,
    region: str,
    coords: tuple[float, float],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    lat, lon = coords
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "hourly": ",".join(_OPEN_METEO_HOURLY_VARS),
        "timezone": "UTC",
    }
    resp = await client.get(_OPEN_METEO_ARCHIVE_URL, params=params)
    resp.raise_for_status()
    hourly = resp.json().get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return pd.DataFrame()

    cloud_cover = hourly.get("cloud_cover", [None] * len(times))
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(times, utc=True),
            "station_id": station_id,
            "region": region,
            "temp_c": hourly.get("temperature_2m", [None] * len(times)),
            "apparent_temp_c": hourly.get("apparent_temperature", [None] * len(times)),
            "dew_point_c": hourly.get("dew_point_2m", [None] * len(times)),
            "humidity_pct": hourly.get("relative_humidity_2m", [None] * len(times)),
            "wind_speed_kmh": hourly.get("wind_speed_10m", [None] * len(times)),
            "wind_direction_deg": hourly.get("wind_direction_10m", [None] * len(times)),
            "wind_gust_kmh": hourly.get("wind_gusts_10m", [None] * len(times)),
            "pressure_hpa": hourly.get("surface_pressure", [None] * len(times)),
            "rain_since_9am_mm": [None] * len(times),
            "cloud_oktas": [
                None if c is None else round(c / 12.5, 1) for c in cloud_cover
            ],
        }
    )
