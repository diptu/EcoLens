"""Open-Meteo (ERA5) URL building + response parsing.

Pure functions — no network I/O (see historical_client.py for that).
`parse_open_meteo_response` maps one Open-Meteo JSON payload into v1.0
rows, duplicating each hourly reading into the two 30-min slots it
covers (`:00` and `:30`) so it lines up with the live fetcher's
30-min-slot schema and the 30-min energy fact table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .schema import (
    OPEN_METEO_BASE,
    PARAM_MAP,
    SCHEMA_VERSION,
    STATION_COORDS,
    STATION_NAME_MAP,
)

log = get_logger(__name__)


def build_open_meteo_url(region: str, start: datetime, end: datetime) -> str:
    """Build the Open-Meteo archive URL for one region and date range."""
    if region not in STATION_COORDS:
        raise ValueError(f"no coords for region {region!r}")
    lat, lon = STATION_COORDS[region]
    params = [
        f"latitude={lat}",
        f"longitude={lon}",
        f"start_date={start.strftime('%Y-%m-%d')}",
        f"end_date={end.strftime('%Y-%m-%d')}",
        "hourly=" + ",".join(PARAM_MAP.keys()),
        "timezone=UTC",
        "wind_speed_unit=kmh",
    ]
    return f"{OPEN_METEO_BASE}?{'&'.join(params)}"


def parse_open_meteo_response(
    payload: dict[str, Any],
    region: str,
    stations: dict[str, str],
) -> list[dict[str, Any]] | None:
    """Map an Open-Meteo response into v1.0 rows (two per hour: :00 and :30).

    Returns None on a malformed payload (no "hourly" key) so the
    caller can distinguish "request failed to return usable data"
    from "request succeeded with zero rows" (empty `time` array).
    """
    if "hourly" not in payload:
        log.warning(
            "bom_historical.malformed", region=region, keys=list(payload.keys())
        )
        return None
    hourly = payload["hourly"]
    times = hourly.get("time", [])
    if not times:
        return []
    n = len(times)

    # Build per-parameter arrays, defaulting to None; pad/trim to length n
    # in case Open-Meteo returns a partial response for some parameter.
    arrays: dict[str, list[Any]] = {}
    for openmeteo_name, our_name in PARAM_MAP.items():
        arr = list(hourly.get(openmeteo_name, [None] * n))
        if len(arr) < n:
            arr = arr + [None] * (n - len(arr))
        arrays[our_name] = arr[:n]

    station_id = stations.get(region, "")
    station_name = STATION_NAME_MAP.get(station_id, "Unknown")
    now = pd.Timestamp.now(tz="UTC")
    run_id = str(uuid.uuid4())
    rows: list[dict[str, Any]] = []
    for i, time_str in enumerate(times):
        try:
            ts = pd.to_datetime(time_str, utc=True)
            if pd.isna(ts):
                continue
            ts_hour = ts.floor("h")
            if ts_hour.tzinfo is None:
                ts_hour = ts_hour.tz_localize("UTC")
        except (ValueError, TypeError) as exc:
            log.debug("bom_historical.parse.timestamp_failed", error=str(exc))
            continue

        cloud_cover_pct = arrays["cloud_cover_pct"][i]
        cloud_oktas = (cloud_cover_pct / 12.5) if cloud_cover_pct is not None else None

        # Open-Meteo's `precipitation` is an hourly delta, not the
        # live fetcher's "cumulative since 09:00 local" -- there's no
        # true equivalent in ERA5, so we store the hourly value here
        # as the closest available proxy. Downstream consumers that
        # need true 9am-cumulative rain should treat backfilled rows
        # (data_quality_status="final", source="open_meteo_era5")
        # differently from live ones.
        precip = arrays["rain_since_9am_mm"][i]

        base_row = {
            "region": region,
            "station_id": station_id,
            "station_name": station_name,
            "schema_version": SCHEMA_VERSION,
            "temp_c": arrays["temp_c"][i],
            "apparent_temp_c": arrays["apparent_temp_c"][i],
            "humidity_pct": arrays["humidity_pct"][i],
            "dew_point_c": arrays["dew_point_c"][i],
            "wind_speed_kmh": arrays["wind_speed_kmh"][i],
            "wind_direction_deg": arrays["wind_direction_deg"][i],
            "wind_gust_kmh": arrays["wind_gust_kmh"][i],
            "pressure_hpa": arrays["pressure_hpa"][i],
            "rain_since_9am_mm": precip,
            "rain_last_hour_mm": None,  # filled in by apply_data_quality_fixes
            "cloud_oktas": cloud_oktas,
            "cloud_cover_pct": cloud_cover_pct,
            "data_quality_status": "final",  # ERA5 is post-processed reanalysis
            "source": "open_meteo_era5",
            "ingest_run_id": run_id,
            "ingested_at": now,
            "fetched_at": now,
        }
        # ERA5 is hourly; the schema is 30-min. Duplicate the hourly
        # reading into both half-hour slots it covers.
        rows.append({"ts": ts_hour, **base_row})
        rows.append({"ts": ts_hour + timedelta(minutes=30), **base_row})
    return rows


__all__ = ["build_open_meteo_url", "parse_open_meteo_response"]
