"""BoM v1.0 schema — station map, physical bounds, output columns.

Pure configuration: no I/O, no classes. See `engine.py`'s module
docstring for the fetcher design (3-tier live/cache/synthetic).
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────────────
# Schema version — bump when adding/removing/renaming columns
# ────────────────────────────────────────────────────────────────────
SCHEMA_VERSION: str = "1.0"


# ────────────────────────────────────────────────────────────────────
# Source constants
# ────────────────────────────────────────────────────────────────────
BOM_BASE_URL = "http://www.bom.gov.au/fwo"
BOM_OBSERVATIONS_PATH = "/observations.json"
BOM_USER_AGENT = (
    "ecoLens/0.2.0 (https://github.com/diptu/ecoLens) contact: ops@ecolens.app"
)
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5

# Local CSV cache layout: <cache_dir>/observations_<region>_<YYYYMMDD>.csv
# (cache_dir itself comes from Settings.bom_cache_dir, see config.py)

# ────────────────────────────────────────────────────────────────────
# Historical (Open-Meteo / ERA5) source constants — historical_client.py
# ────────────────────────────────────────────────────────────────────
# The live observations.json endpoint only returns ~24-48h of history.
# For LSTM training we need 2-3 years, so historical_client.py backfills
# from Open-Meteo's free ERA5 reanalysis archive instead (same physics,
# it assimilates BoM observations; no missing values, no quality flags).
OPEN_METEO_BASE = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_TIMEOUT_SECONDS = (
    60.0  # larger than the live TIMEOUT_SECONDS -- big date ranges
)

# ERA5 has a known production lag of ~5 days (the model needs to
# stabilize after the real-time window). Backfill up to that point;
# the live fetcher covers the rest.
ERA5_LAG_DAYS = 5

# Open-Meteo's hard per-request limit on a date range.
OPEN_METEO_MAX_CHUNK_DAYS = 365

# Open-Meteo hourly parameter name -> our v1.0 schema field.
PARAM_MAP: dict[str, str] = {
    "temperature_2m": "temp_c",
    "apparent_temperature": "apparent_temp_c",
    "relative_humidity_2m": "humidity_pct",
    "dew_point_2m": "dew_point_c",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_direction_10m": "wind_direction_deg",
    "wind_gusts_10m": "wind_gust_kmh",
    "surface_pressure": "pressure_hpa",
    "precipitation": "rain_since_9am_mm",
    "cloud_cover": "cloud_cover_pct",
}

# Australian state -> UTC offset (no DST in any of these — handy
# because BoM's local_date_time_full is in local time but we want
# UTC for the dbt join).
AUSTRALIA_UTC_OFFSETS: dict[str, int] = {
    "NSW1": 10,  # AEST (UTC+10)
    "QLD1": 10,  # AEST (no DST in QLD)
    "VIC1": 10,  # AEST (no DST in VIC)
    "SA1": 9,  # ACST (UTC+9:30, rounded to +9 here; .5 handled in the timestamp conversion)
    "TAS1": 10,  # AEST
    "WEM": 8,  # AWST (UTC+8)
}

# Default BoM station map. Six stations, one per NEM/WEM region.
DEFAULT_BOM_STATIONS: dict[str, str] = {
    "NSW1": "066037",
    "QLD1": "040913",
    "VIC1": "086282",
    "SA1": "023034",
    "TAS1": "094029",
    "WEM": "009225",
}

# Human-readable station names
STATION_NAME_MAP: dict[str, str] = {
    "066037": "Sydney - Observatory Hill",
    "040913": "Brisbane",
    "086282": "Melbourne",
    "023034": "Adelaide - Kent Town",
    "094029": "Hobart",
    "009225": "Perth",
}

# Station lat/lon (official BoM station coordinates), used by the
# historical fetcher (historical_client.py) to query Open-Meteo's
# ERA5 reanalysis archive at the exact station location.
STATION_COORDS: dict[str, tuple[float, float]] = {
    "NSW1": (-33.8576, 151.2157),  # Sydney - Observatory Hill
    "QLD1": (-27.4698, 153.0251),  # Brisbane
    "VIC1": (-37.8136, 144.9631),  # Melbourne
    "SA1": (-34.9285, 138.6007),  # Adelaide - Kent Town
    "TAS1": (-42.8821, 147.3272),  # Hobart
    "WEM": (-31.9505, 115.8605),  # Perth
}

# BoM quality flags. W (wrong) and S (suspect) -> treat as missing.
BOM_QUALITY_FLAGS = frozenset({"Y", "N", "W", "S", "A"})

# Physical bounds (used in data quality fix #2). Clamp out-of-range
# values to these limits.
PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "temp_c": (-10.0, 50.0),  # Australia: -10..50°C historically
    "apparent_temp_c": (-15.0, 55.0),
    "dew_point_c": (-20.0, 35.0),
    "humidity_pct": (0.0, 100.0),
    "wind_speed_kmh": (0.0, 250.0),  # max recorded ~408 km/h (Cyclone Olivia)
    "wind_direction_deg": (0.0, 360.0),
    "wind_gust_kmh": (0.0, 300.0),
    "pressure_hpa": (870.0, 1084.0),  # global extreme range
    "rain_since_9am_mm": (0.0, 500.0),
    "cloud_oktas": (0.0, 8.0),
}


# ────────────────────────────────────────────────────────────────────
# Output schema v1.0 (weather columns)
# ────────────────────────────────────────────────────────────────────
# 22 columns. Not the same as the energy schema (this is a
# side-dataset). The dbt weather model joins this onto the energy
# fact table on (region, ts_local).
OBSERVATION_OUTPUT_COLUMNS: list[str] = [
    # ── Identity ───────────────────────────────────────────────
    "ts",  # 30-min slot, UTC
    "region",  # NSW1 / QLD1 / VIC1 / SA1 / TAS1 / WEM
    "station_id",  # BoM station ID (6 digits, zero-padded string)
    "station_name",  # human-readable name
    "schema_version",  # v1.0
    # ── Temperature ────────────────────────────────────────────
    "temp_c",  # air temperature (°C)
    "apparent_temp_c",  # feels-like (°C)
    "dew_point_c",  # dew point (°C)
    "humidity_pct",  # relative humidity (%)
    # ── Wind ───────────────────────────────────────────────────
    "wind_speed_kmh",  # sustained wind (km/h)
    "wind_direction_deg",  # 0=N, 90=E, 180=S, 270=W
    "wind_gust_kmh",  # peak gust in last 10 min (km/h)
    # ── Pressure & rain ────────────────────────────────────────
    "pressure_hpa",  # MSL pressure (hPa)
    "rain_since_9am_mm",  # accumulated rain since 09:00 local (mm)
    "rain_last_hour_mm",  # delta from previous hour's accumulation
    # ── Sky ────────────────────────────────────────────────────
    "cloud_oktas",  # 0=clear, 8=overcast (oktas = 1/8 sky)
    "cloud_cover_pct",  # derived: oktas * 12.5 (0..100)
    # ── Metadata ───────────────────────────────────────────────
    "data_quality_status",  # "final" / "preliminary" / "unknown"
    "source",  # "bom"
    "ingest_run_id",
    "ingested_at",
    "fetched_at",
]
