# BoM observations — weather features (temp, humidity, wind)
# Data Card: `ecolens-bom-obs-v1`

> Short-form spec for the BoM weather observations dataset.

---

## 1. Overview

| Field | Value |
| :--- | :--- |
| **Dataset** | `ecolens-bom-obs-v1` v1.0.0 (2026-07-26) |
| **Owner** | ecoLens Data Engineering — `data@ecolens.app` |
| **Source** | Bureau of Meteorology (BoM) public API + Open-Meteo ERA5 backfill |
| **Storage** | PostgreSQL 16, database `ecolens`, schema `weather`, table `bom_observations` (declarative partitioning by `ts_utc` month, sub-partitioned by `region`). Nightly Parquet export to S3. |
| **License** | BoM CC BY 4.0 + Open-Meteo CC BY 4.0 (ecoLens processing: CC BY 4.0) |
| **Refresh** | 30-min live (6 stations) + daily historical backfill |
| **Retention** | Live: 13 months. Historical: 1940-01 → present via Open-Meteo ERA5 (no BoM API access) |

**Purpose:** Input features for LSTM demand forecasting, weather analytics, solar/wind generation modelling.
**Out of scope:** Severe weather warnings (use BoM directly), aviation/marine forecasts, personal data (none present).

---

## 2. Schema (primary key `(ts_utc, station_id)`)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `ts_utc` | `TIMESTAMP(TZ)` | no | Observation timestamp, UTC, ISO 8601 |
| `station_id` | `VARCHAR(8)` | no | BoM station code (e.g. `066037` for Sydney) |
| `station_name` | `VARCHAR(128)` | yes | Human-readable name (e.g. `Sydney - Observatory Hill`) |
| `region` | `VARCHAR(4)` | no | NEM region the station maps to (`NSW1`, `QLD1`, `VIC1`, `SA1`, `TAS1`, `WEM`) |
| `lat` | `DOUBLE` | no | Station latitude (WGS84) |
| `lng` | `DOUBLE` | no | Station longitude (WGS84) |
| `elevation_m` | `DOUBLE` | yes | Station elevation above MSL (m) |
| `temperature_c` | `DOUBLE` | yes | Air temperature at 2 m (°C) |
| `dewpoint_c` | `DOUBLE` | yes | Dew point (°C) |
| `humidity_pct` | `DOUBLE` | yes | Relative humidity (%), 0–100 |
| `wind_speed_ms` | `DOUBLE` | yes | Wind speed at 10 m (m/s) |
| `wind_direction_deg` | `DOUBLE` | yes | Wind direction (degrees, 0–360, 0=N) |
| `wind_gust_ms` | `DOUBLE` | yes | Wind gust speed (m/s) |
| `solar_irradiance_wm2` | `DOUBLE` | yes | Global horizontal irradiance (W/m²) |
| `pressure_hpa` | `DOUBLE` | yes | Mean sea-level pressure (hPa) |
| `rainfall_mm` | `DOUBLE` | yes | Rainfall since last obs (mm) |
| `cloud_cover_pct` | `DOUBLE` | yes | Total cloud cover (%), 0–100 |
| `data_quality_status` | `VARCHAR(16)` | no | `raw` \| `interim` \| `final` \| `missing` \| `estimated` |
| `source` | `VARCHAR(32)` | no | `bom_observation` \| `bom_historical` \| `open_meteo_era5` |
| `source_url` | `VARCHAR(1024)` | yes | Direct API URL (audit) |
| `ingest_run_id` | `UUID` | no | UUID v4 of the pipeline run |
| `fetched_at` | `TIMESTAMP(TZ)` | no | UTC when row was pulled |
| `ingested_at` | `TIMESTAMP(TZ)` | no | UTC when written to warehouse |
| `pipeline_version` | `VARCHAR(16)` | yes | Fetcher version |
| `notes` | `VARCHAR(1024)` | yes | Free-text annotation |

---

## 3. Stations (6 active in NEM coverage)

| `station_id` | Name | `region` | `lat` / `lng` | Source |
| :--- | :--- | :--- | :--- | :--- |
| `066037` | Sydney — Observatory Hill | NSW1 | -33.86 / 151.21 | BoM live + ERA5 |
| `040913` | Brisbane Airport | QLD1 | -27.39 / 153.13 | BoM live + ERA5 |
| `086338` | Melbourne Airport | VIC1 | -37.67 / 144.83 | BoM live + ERA5 |
| `023034` | Adelaide Airport | SA1 | -34.95 / 138.52 | BoM live + ERA5 |
| `094029` | Hobart (Ellerslie Rd) | TAS1 | -42.88 / 147.33 | BoM live + ERA5 |
| `009021` | Perth Airport | WEM | -31.93 / 115.98 | BoM live + ERA5 |

---

## 4. Source endpoints

| URL | Cadence | Coverage |
| :--- | :--- | :--- |
| `api.bom.gov.au/v1/observations/...` | 30 min | last 7 days (live) |
| `api.bom.gov.au/v1/historical/...` | daily | last 2 years (climat) |
| `archive-api.open-meteo.com/v1/archive` | one-shot | 1940-01 → 7 days ago (ERA5) |
| `api.open-meteo.com/v1/forecast` | hourly | next 16 days (forecast) |

---

## 5. Data quality rules

### Null thresholds

| Column(s) | Threshold |
| :--- | :--- |
| `ts_utc`, `station_id`, `region`, `lat`, `lng`, `data_quality_status`, `source`, `ingest_run_id`, `fetched_at`, `ingested_at` | **0%** |
| `temperature_c`, `humidity_pct` | **0%** when station online |
| `wind_speed_ms`, `solar_irradiance_wm2` | **≤ 5%** (sensor outages OK) |
| `rainfall_mm` | can be 0 (= no rain) — NOT treated as null |

### Freshness SLA

| Source | Max staleness |
| :--- | :--- |
| `bom_observation` (live) | 45 min |
| `bom_historical` | 1 day |
| `open_meteo_era5` | 7 days (ERA5 finalization) |

### Range constraints

| Field | Range |
| :--- | :--- |
| `temperature_c` | -50 to +60 |
| `humidity_pct` | 0–100 |
| `wind_speed_ms` | 0–75 (record gusts) |
| `wind_direction_deg` | 0–360 |
| `solar_irradiance_wm2` | 0–1,400 (above-atmosphere) |
| `pressure_hpa` | 870–1,084 |
| `rainfall_mm` | 0–500 (single-obs maximum) |

### Consistency

- `0 ≤ cloud_cover_pct ≤ 100`
- `humidity_pct` consistent with `dewpoint_c` and `temperature_c` (Magnus formula)
- `solar_irradiance_wm2` near zero when `is_night = true` (lat/lng + ts)

### Automated checks

JSON Schema 2020-12 + Great Expectations suite (in `weather/expectations/`) + dbt tests + PagerDuty if null rate on critical column > 0% for 1+ hour.

### Known caveats

- BoM live API requires a registered `BOM_API_KEY` header (free, register at bom.gov.au/weather-data).
- Open-Meteo ERA5 has 5-7 day finalization lag — not suitable for the most recent week.
- 6 stations are sparse; sub-region weather (e.g. Hunter Valley vs. Sydney metro) is approximated by the nearest station.
- Solar irradiance at night = 0; some legacy data has NaN instead of 0 (coerced at ingest).

---

## 6. Versioning

| Version | Date | Notes |
| :--- | :--- | :--- |
| `1.0.0` | 2026-07-26 | Initial production release. 6 stations, 30-min grain, ERA5 backfill. |
| `1.1.0` | Q4 2026 (planned) | Add 4 more stations (Adelaide, Newcastle, Wollongong, Geelong) for sub-region granularity. |

Major bumps on: required field added, type change, enum removed. Schema retained for 12 months after a major release.

---

## 7. Contact

- **Email**: `data@ecolens.app`
- **On-call**: PagerDuty `ecolens-data-pipeline`
- **Runbook**: <https://ecolens.app/runbooks/bom-pipeline>
- **Status**: <https://status.ecolens.app>
- **Schema repo**: <https://github.com/ecolens/schemas/tree/main/weather>

## 8. Citation

> ecoLens BoM Observations Data Card v1.0, accessed [date]. Derived from the
> Australian Bureau of Meteorology (bom.gov.au) under CC BY 4.0, supplemented
> with Open-Meteo ERA5 reanalysis. ecoLens processing licensed CC BY 4.0.
