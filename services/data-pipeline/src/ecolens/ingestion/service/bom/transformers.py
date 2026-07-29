"""BoM observation normalization, data-quality fixes, and synthetic stub.

Pure(ish) pandas/dict transforms — no network I/O (see client.py for
that, cache.py for the local CSV tier). `normalize_observation` turns
one raw BoM v1 `/observations` response into a v1.0 row;
`apply_data_quality_fixes` and `synthetic_stub` are shared by every
fetch tier in engine.py.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from ecolens.shared.observability.logging import get_logger

from ecolens.ingestion.schema.bom import (
    AUSTRALIA_UTC_OFFSETS,
    DEW_POINT_MAGNUS_A,
    DEW_POINT_MAGNUS_B,
    PHYSICAL_BOUNDS,
    SCHEMA_VERSION,
    STATION_NAME_MAP,
    WIND_DIRECTION_DEGREES,
)

log = get_logger(__name__)


def _dew_point_magnus(temp_c: float | None, humidity_pct: float | None) -> float | None:
    """Magnus-Tetens approximation — the v1 API doesn't return dew point
    directly, unlike the legacy endpoint's `dewpt` field.
    """
    if temp_c is None or humidity_pct is None or humidity_pct <= 0:
        return None
    a, b = DEW_POINT_MAGNUS_A, DEW_POINT_MAGNUS_B
    try:
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100.0)
        return (b * alpha) / (a - alpha)
    except (ValueError, ZeroDivisionError):
        return None


def normalize_observation(
    payload: dict[str, Any],
    region: str,
    geohash: str,
    now: pd.Timestamp,
) -> dict[str, Any] | None:
    """Map one BoM v1 `/locations/{geohash}/observations` response to a
    v1.0 row.

    Returns None if the payload has no usable `data`/observation time.
    The station identity (`station_id`/`station_name`) comes from the
    response itself (`data.station.bom_id`/`.name`) — the v1 API
    resolves `geohash` to its nearest station, which isn't necessarily
    the same station the legacy hardcoded IDs pointed at, so ecoLens
    trusts the response rather than a local map.
    """
    data = payload.get("data")
    if not data:
        return None
    metadata = payload.get("metadata") or {}
    obs_time = metadata.get("observation_time")
    if not obs_time:
        return None
    ts_utc = pd.to_datetime(obs_time, utc=True, errors="coerce")
    if pd.isna(ts_utc):
        return None
    ts_30 = ts_utc.floor("30min")
    if ts_30.tzinfo is None:
        ts_30 = ts_30.tz_localize("UTC")

    station = data.get("station") or {}
    station_id = station.get("bom_id") or geohash
    station_name = station.get("name", "Unknown")

    wind = data.get("wind") or {}
    gust = data.get("gust") or {}

    temp_c = data.get("temp")
    humidity_pct = data.get("humidity")
    wind_direction = wind.get("direction")

    return {
        "ts": ts_30,
        "region": region,
        "station_id": station_id,
        "station_name": station_name,
        "schema_version": SCHEMA_VERSION,
        "temp_c": temp_c,
        "apparent_temp_c": data.get("temp_feels_like"),
        "dew_point_c": _dew_point_magnus(temp_c, humidity_pct),
        "humidity_pct": humidity_pct,
        "wind_speed_kmh": wind.get("speed_kilometre"),
        "wind_direction_deg": (
            WIND_DIRECTION_DEGREES.get(wind_direction) if wind_direction else None
        ),
        "wind_gust_kmh": gust.get("speed_kilometre"),
        "pressure_hpa": None,  # not in v1 -- use Open-Meteo (historical.py) for this
        "rain_since_9am_mm": data.get("rain_since_9am"),
        "rain_last_hour_mm": None,  # filled in by apply_data_quality_fixes
        "cloud_oktas": None,  # not in v1 -- use Open-Meteo for this
        "cloud_cover_pct": None,  # not in v1 -- use Open-Meteo for this
        "data_quality_status": "preliminary",
        "source": "bom",
        "ingest_run_id": None,  # filled in by the caller
        "ingested_at": now,
        "fetched_at": now,
    }


def apply_data_quality_fixes(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the 5 data quality fixes:

    1. NaN -> None  (so MongoDB stores null, not NaN)
    2. Physical bounds clamp  (sensor noise / spikes)
    3. Wind direction -> wrap to [0, 360)  (BEFORE physical bounds)
    4. Humidity -> clamp to [0, 100]
    5. Compute rain_last_hour_mm from rain_since_9am_mm delta
    """
    by_region: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        by_region.setdefault(doc.get("region", ""), []).append(doc)

    cleaned: list[dict[str, Any]] = []
    for region, group in by_region.items():
        group_sorted = sorted(group, key=lambda d: d.get("ts") or datetime.min)
        prev_rain: float | None = None
        prev_ts: datetime | None = None
        for doc in group_sorted:
            # Fix #1: NaN -> None
            for k, v in list(doc.items()):
                try:
                    if isinstance(v, float) and np.isnan(v):
                        doc[k] = None
                except (TypeError, ValueError):
                    pass
            # Fix #3: wind direction wrap (BEFORE physical bounds so 400 -> 40, not 360 -> 0)
            wd = doc.get("wind_direction_deg")
            if wd is not None:
                doc["wind_direction_deg"] = wd % 360.0
            # Fix #2: physical bounds
            for col, (lo, hi) in PHYSICAL_BOUNDS.items():
                v = doc.get(col)
                if v is None:
                    continue
                if v < lo:
                    doc[col] = lo
                elif v > hi:
                    doc[col] = hi
            # Fix #4: humidity bounds (explicit; redundant with #2 but matches the contract)
            h = doc.get("humidity_pct")
            if h is not None:
                doc["humidity_pct"] = max(0.0, min(100.0, h))
            # Fix #5: rain_last_hour_mm (delta of rain_since_9am)
            rain = doc.get("rain_since_9am_mm")
            ts = doc.get("ts")
            if rain is not None and prev_rain is not None and prev_ts is not None:
                if ts is not None and (ts - prev_ts) <= timedelta(hours=2):
                    delta = rain - prev_rain
                    # If the 9am bucket reset (rain dropped), use 0 as the delta
                    doc["rain_last_hour_mm"] = max(0.0, delta)
                else:
                    doc["rain_last_hour_mm"] = None
            else:
                doc["rain_last_hour_mm"] = None
            if rain is not None:
                prev_rain = rain
                prev_ts = ts
        cleaned.extend(group_sorted)
    return cleaned


def synthetic_stub(
    stations: dict[str, str],
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Deterministic stub. NOT for production use.

    Uses a seeded PRNG per station (so re-runs produce identical
    output). Diurnal temperature pattern (peak ~14:00 local, trough
    ~04:00 local) and seasonal baseline per region.
    """
    slots = pd.date_range(
        start=pd.Timestamp(since.astimezone(timezone.utc)).floor("30min"),
        end=pd.Timestamp(until.astimezone(timezone.utc)).ceil("30min"),
        freq="30min",
        tz="UTC",
    )
    if len(slots) == 0:
        return []

    seasonal_baseline = {
        "NSW1": [26, 26, 25, 22, 19, 17, 16, 18, 20, 23, 24, 26],
        "QLD1": [30, 30, 29, 27, 25, 23, 22, 23, 26, 28, 29, 30],
        "VIC1": [26, 26, 24, 20, 17, 14, 13, 15, 17, 20, 22, 24],
        "SA1": [29, 29, 26, 22, 19, 16, 15, 16, 19, 22, 25, 28],
        "TAS1": [21, 21, 19, 16, 13, 11, 10, 12, 14, 16, 18, 20],
        "WEM": [31, 31, 29, 25, 22, 19, 18, 19, 21, 24, 27, 30],
    }
    month = datetime.now(tz=timezone.utc).month

    rows: list[dict[str, Any]] = []
    for region, station_id in stations.items():
        rng = np.random.default_rng(int(station_id) & 0xFFFFFFFF)
        hours_local = (slots.hour + AUSTRALIA_UTC_OFFSETS.get(region, 10)) % 24
        # Diurnal: peak at 14:00, trough at 04:00
        diurnal = 8 * np.sin((hours_local - 4) * np.pi / 12)
        baseline = seasonal_baseline.get(region, seasonal_baseline["NSW1"])[month - 1]
        n = len(slots)
        temp = baseline + diurnal + rng.normal(0, 1.5, n)
        for i, ts in enumerate(slots):
            rows.append(
                {
                    "ts": ts,
                    "region": region,
                    "station_id": station_id,
                    "station_name": STATION_NAME_MAP.get(station_id, "Unknown"),
                    "schema_version": SCHEMA_VERSION,
                    "temp_c": float(temp[i]),
                    "apparent_temp_c": float(temp[i] + rng.normal(0, 1.5)),
                    "dew_point_c": float(temp[i] - 5 + rng.normal(0, 1)),
                    "humidity_pct": float(rng.uniform(40, 80)),
                    "wind_speed_kmh": float(rng.uniform(0, 30)),
                    "wind_direction_deg": float(rng.uniform(0, 360)),
                    "wind_gust_kmh": float(rng.uniform(0, 60)),
                    "pressure_hpa": float(rng.normal(1015, 5)),
                    "rain_since_9am_mm": 0.0,
                    "rain_last_hour_mm": 0.0,
                    "cloud_oktas": float(rng.uniform(0, 8)),
                    "cloud_cover_pct": float(rng.uniform(0, 8) * 12.5),
                    "data_quality_status": "preliminary",
                    "source": "bom",
                    "ingest_run_id": str(uuid.uuid4()),
                    "ingested_at": pd.Timestamp.now(tz="UTC"),
                    "fetched_at": pd.Timestamp.now(tz="UTC"),
                }
            )
    log.warning("bom.synthetic_stub.used", rows=len(rows), slots=len(slots))
    return rows


def diagnose(docs: list[dict[str, Any]]) -> None:
    """Log high-null columns and per-region row counts."""
    if not docs:
        log.warning("bom.diagnose.empty")
        return
    df = pd.DataFrame(docs)
    null_pct = df.isna().mean().round(3)
    for col in null_pct.index:
        pct = null_pct[col]
        if pct > 0.5:
            log.warning("bom.diagnose.high_null", col=col, null_pct=pct)
    counts = df["region"].value_counts().to_dict()
    log.info("bom.diagnose.complete", rows=len(docs), per_region=counts)
