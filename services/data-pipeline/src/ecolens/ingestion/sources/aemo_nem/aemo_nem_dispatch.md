# AEMO NEM — Australian electricity market demand/price/fuel-mix time series
# Data Card: `ecolens-aemo-nem-v1`

> Short-form spec for the AEMO NEM market dataset. Full version: `aemo_nem_data_card.md` (16 KB).

---

## 1. Overview

| Field | Value |
| :--- | :--- |
| **Dataset** | `ecolens-aemo-nem-v1` v1.0.0 (2026-07-26) |
| **Source** | AEMO NEMWeb public archive (`nemweb.com.au`) |
| **Storage** | PostgreSQL 16, database `ecolens`, schema `market_data`, table `aemo_nem_dispatch_5min` (declarative partitioning by `ts` month, sub-partitioned by `region`). Nightly Parquet export to S3 for analytical workloads. |
| **Refresh** | 5-min live + daily settlement + monthly archive |
| **Retention** | 1 years hot in PostgreSQL (2025-08 → present); |
**Purpose:** LSTM,TFT demand forecasting, Scope 1+2 emissions accounting, interconnector analytics.
**Out of scope:** financial trading, SCADA control, PII (none present), non-AU markets.

---

## 2. Schema (41 columns, primary key `(ts, region)`)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `ts` | `TIMESTAMP(TZ)` | no | Interval start, ISO 8601 + Australia/Sydney tz |
| `network_code` | `VARCHAR(4)` | no | `NEM` |
| `region` | `VARCHAR(4)` | no | `NEM` \| `NSW1` \| `QLD1` \| `VIC1` \| `SA1` \| `TAS1` |
| `interval_minutes` | `SMALLINT` | no | `5` (post-2021-10) \| `30` (legacy) |
| `data_quality_status` | `VARCHAR(16)` | no | `raw` \| `interim` \| `final` \| `revised` \| `missing` \| `estimated` |
| `schema_version` | `VARCHAR(10)` | no | semver, e.g. `1.0.0` |
| `demand_mw` | `DOUBLE` | yes | Operational demand (MW), 0–100,000 |
| `demand_forecast_mw` | `DOUBLE` | yes | AEMO pre-dispatch forecast (MW) |
| `price_mwh` | `DOUBLE` | yes | Regional reference price (AUD/MWh), -1,000 to 16,600 |
| `market_value_aud` | `DOUBLE` | yes | Total market value for the region (AUD) |
| `coal_black_mw` … `other_mw` | `DOUBLE` | yes | Generation per fuel (16 fuel types). 0 = none. Hydro can be negative when pumping. |
| `total_generation_mw` | `DOUBLE` | no | Sum of all generation, net of charging/pumping |
| `renewable_generation_mw` | `DOUBLE` | yes | Wind + solar + hydro + biomass + geothermal |
| `renewable_proportion` | `DOUBLE` | yes | renewable / total, 0–1 |
| `emissions_intensity_kgco2e_per_mwh` | `DOUBLE` | yes | Scope 1+2 location-based, 0–2,000 |
| `emissions_kgco2e` | `DOUBLE` | yes | Absolute emissions for the interval |
| `interconnector_imports_mw` | `DOUBLE` | yes | Inbound interconnector flow (MW) |
| `interconnector_exports_mw` | `DOUBLE` | yes | Outbound interconnector flow (MW) |
| `net_import_mw` | `DOUBLE` | yes | imports − exports (MW) |
| `fcas_enablement_aud` | `DOUBLE` | yes | Total FCAS payment for the region |
| `source` | `VARCHAR(32)` | no | `nemweb_mmsdm` \| `nemweb_dispatchis` \| `nemweb_daily` \| `openelectricity` \| … |
| `source_url` | `VARCHAR(1024)` | yes | Direct upstream URL (audit) |
| `source_record_id` | `VARCHAR(256)` | yes | Upstream row ID |
| `ingest_run_id` | `UUID` | no | UUID v4 of the pipeline run that loaded this record |
| `fetched_at` | `TIMESTAMP(TZ)` | no | UTC when upstream row was pulled |
| `ingested_at` | `TIMESTAMP(TZ)` | no | UTC when written to warehouse |
| `pipeline_version` | `VARCHAR(16)` | yes | Fetcher version, e.g. `0.4.2` |
| `notes` | `VARCHAR(1024)` | yes | Free-text annotation |

### Emission factors (default, IPCC AR5 + AEMO NGES, kg CO₂e/MWh)

| Fuel | Factor | Fuel | Factor |
| :--- | ---: | :--- | ---: |
| Coal (black) | 820 | Hydro | 5 |
| Coal (brown) | 1,200 | Wind | 10 |
| Gas (CCGT) | 370 | Solar (utility) | 30 |
| Gas (OCGT) | 520 | Solar (rooftop) | 40 |
| Gas (steam) | 700 | Battery | 50 |
| Distillate | 800 | Biomass | 50 |
| Other | 500 | | |

---

## 3. Source endpoints

| URL | Cadence | Coverage |
| :--- | :--- | :--- |
| `nemweb.com.au/REPORTS/CURRENT/DispatchIS_Reports/PUBLIC_DISPATCHIS_*.zip` | 5 min | last 60 days |
| `nemweb.com.au/REPORTS/ARCHIVE/Daily_Reports/PUBLIC_DAILY_YYYYMM01.zip` | daily | last ~12 months |
| `nemweb.com.au/Data_Archive/.../MMSDM/YYYY/MMSDM_YYYY_MM/.../PUBLIC_ARCHIVE#<TABLE>#FILE##YYYYMM010000.zip` | monthly | 2010-01 → present (per-table) |
| `nemweb.com.au/Data_Archive/.../MMSDM/YYYY/MMSDM_YYYY_MM.zip` | monthly | 2010-01 → 2025-12 (single zip, all tables) |
| `nemweb.com.au/Data_Archive/.../MMSDM/2009/MMSDM_2009_MM.zip` | monthly | 2009-07 → 2009-12 |

---

## 4. Data quality rules

### Null thresholds (drop + alert if exceeded)

| Column(s) | Threshold |
| :--- | :--- |
| `ts`, `region`, `network_code`, `schema_version`, `data_quality_status`, `total_generation_mw`, `source`, `ingest_run_id`, `fetched_at`, `ingested_at` | **0%** |
| `demand_mw` (when `final` / `revised`) | **0%** |
| `price_mwh` (when `final`) | **0%** |
| Fuel type columns | **0%** nulls (replace with 0) |

### Freshness SLA

| Status | Max staleness |
| :--- | :--- |
| `raw` | 10 min |
| `interim` | 30 min |
| `final` | 4 h |
| `revised` | 7 days |

### Range constraints

| Field | Range |
| :--- | :--- |
| `demand_mw`, `total_generation_mw` | 0–100,000 |
| `price_mwh` | -1,000 to 16,600 |
| `renewable_proportion` | 0–1 |
| `emissions_intensity_kgco2e_per_mwh` | 0–2,000 |
| `interconnector_*_mw` | -3,000 to 3,000 |

### Consistency (per record)

- `sum(generation_by_fuel_mw) ≈ total_generation_mw` (±1% for pumping/charging)
- `net_import_mw == interconnector_imports_mw - interconnector_exports_mw`
- `demand_mw ≈ total_generation_mw + net_import_mw` (±5% for interconnector losses)
- `renewable_proportion × total_generation_mw ≈ renewable_generation_mw`

### Automated checks

JSON Schema 2020-12 validation + 32-expectation Great Expectations suite (`great_expectations_suite.json`) + dbt tests + PagerDuty alert if null rate > 0% for 5+ min on critical columns.

### Known caveats

- `solar_rooftop_mw` is an estimate (AEMO UIGF), not measured. Actuals lag ~4 weeks.
- Pre-2009-07 not on public archive. Request from AEMO directly.
- Settlement revisions create new rows (not overwrites). Filter to latest `fetched_at`.

---

## 5. Versioning

| Version | Date | Notes |
| :--- | :--- | :--- |
| `1.0.0` | 2026-07-26 | Initial production release |
| `1.1.0` | Q3 2026 (planned) | Add `rooftop_pv_actual_mw` (lagged actuals) |
| `1.2.0` | Q4 2026 (planned) | Add `battery_soc_mwh` (state of charge) |
| `2.0.0` | 2027 (planned) | Merge WEM into same schema |

Major bumps on: required field added, type change, enum value removed. Schema retained for 12 months after a major release.

---

## 6. Contact

- **Email**: `data@ecolens.app`
- **On-call**: PagerDuty `ecolens-data-pipeline`
- **Runbook**: <https://ecolens.app/runbooks/aemo-nem-pipeline>
- **Status**: <https://status.ecolens.app>
- **Schema repo**: <https://github.com/ecolens/schemas/tree/main/market_data>

## 7. Citation

> ecoLens AEMO NEM Data Card v1.0, accessed [date]. Derived from AEMO NEMWeb
> public archive (<https://www.nemweb.com.au>) under AEMO Copyright Permissions
> Notice. ecoLens processing licensed CC BY 4.0.
