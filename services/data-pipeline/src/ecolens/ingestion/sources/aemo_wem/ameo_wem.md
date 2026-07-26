# Data Card: `ecolens-aemo-wem-v1`

> Short-form spec for the AEMO WEM (Western Australian Wholesale Electricity
> Market) dataset. Schema aligned with `ecolens-aemo-nem-v1` (41 columns,
> compatible warehouse layout).

---

## 1. Overview

| Field | Value |
| :--- | :--- |
| **Dataset** | `ecolens-aemo-wem-v1` v1.0.0 (2026-07-26) |
| **Source** | AEMO WEM Market Data (`data.wa.aemo.com.au`) + WEMDE Dispatch Engine v2 API |
| **Storage** | PostgreSQL 16, database `ecolens`, schema `market_data`, table `aemo_wem_dispatch_5min` (declarative partitioning by `ts` month, single region `WEM`). Nightly Parquet export to S3 for analytical workloads. |
| **Refresh** | 5-min live (post-reform WEMDE) + 30-min trading interval settlement + monthly archive |
| **Retention** | 14 years hot in PostgreSQL (2012-07 → present). Pre-2012 WEM data (2006-09 → 2012-06) by direct request to AEMO WEM Operations. |
| **Schema compat** | Shares 41 columns with NEM dataset; `region` is always `WEM` (single region); `interconnector_*_mw` always NULL (isolated grid). |

**Purpose:** LSTM/TFT demand forecasting for WA, Scope 1+2 emissions accounting, SWIS capacity planning. Runs in parallel with the NEM forecaster — same model architecture, different region.
**Out of scope:** financial trading, SCADA control, PII (none present), non-AU markets, NZ inter-island flows (different market entirely).

---

## 2. Schema (41 columns, primary key `(ts, region)`, region always `WEM`)

| Column | Type | Null | Description (WEM-specific) |
| :--- | :--- | :--- | :--- |
| `ts` | `TIMESTAMP(TZ)` | no | Dispatch interval start, 5-min (post-reform) or 30-min (pre-reform), ISO 8601 + Australia/Perth tz |
| `network_code` | `VARCHAR(4)` | no | `WEM` (always) |
| `region` | `VARCHAR(4)` | no | `WEM` (always — single SWIS region) |
| `interval_minutes` | `SMALLINT` | no | `5` (post-2023-10-01 WEMDE) \| `30` (legacy 2006-2023 STEM) |
| `data_quality_status` | `VARCHAR(16)` | no | `raw` \| `interim` \| `final` \| `revised` \| `missing` \| `estimated` |
| `schema_version` | `VARCHAR(10)` | no | semver, e.g. `1.0.0` |
| `demand_mw` | `DOUBLE` | yes | Operational demand in SWIS (MW), 0–5,000 |
| `demand_forecast_mw` | `DOUBLE` | yes | AEMO pre-dispatch forecast (MW) |
| `price_mwh` | `DOUBLE` | yes | Reference trading price (AUD/MWh). WEM is energy + 5 ESS (Essential System Services) co-optimised, but energy-only price reported here. Range: -1,000 to 1,000 (capped; much narrower than NEM). |
| `market_value_aud` | `DOUBLE` | yes | Total market value for the interval (AUD) |
| `coal_black_mw` … `other_mw` | `DOUBLE` | yes | Generation per fuel (16 fuel types). WEM has very little coal — Muja/Collie are the only units, scheduled for closure 2024-2030. |
| `total_generation_mw` | `DOUBLE` | no | Sum of all generation, net of charging/pumping (WEM has minimal hydro/battery) |
| `renewable_generation_mw` | `DOUBLE` | yes | Wind + solar + rooftop PV + biomass |
| `renewable_proportion` | `DOUBLE` | yes | renewable / total, 0–1 |
| `emissions_intensity_kgco2e_per_mwh` | `DOUBLE` | yes | Scope 1+2 location-based, 0–2,000 |
| `emissions_kgco2e` | `DOUBLE` | yes | Absolute emissions for the interval |
| `interconnector_imports_mw` | `DOUBLE` | yes | **Always NULL** — WEM (SWIS) is isolated, no NEM interconnection |
| `interconnector_exports_mw` | `DOUBLE` | yes | **Always NULL** |
| `net_import_mw` | `DOUBLE` | yes | **Always NULL** |
| `fcas_enablement_aud` | `DOUBLE` | yes | Total ESS (Essential System Services) payment for the interval. Post-reform, WEM has 5 ESS markets (Raise, Lower, Regulation). |
| `source` | `VARCHAR(32)` | no | `wemde_dispatch` \| `wemdepi_archive` \| `wem_stem` \| `openelectricity` \| `ecolens_forecast` |
| `source_url` | `VARCHAR(1024)` | yes | Direct upstream URL (audit) |
| `source_record_id` | `VARCHAR(256)` | yes | Upstream row ID |
| `ingest_run_id` | `UUID` | no | UUID v4 of the pipeline run that loaded this record |
| `fetched_at` | `TIMESTAMP(TZ)` | no | UTC when upstream row was pulled |
| `ingested_at` | `TIMESTAMP(TZ)` | no | UTC when written to warehouse |
| `pipeline_version` | `VARCHAR(16)` | yes | Fetcher version, e.g. `0.4.2` |
| `notes` | `VARCHAR(1024)` | yes | Free-text annotation (often "WEMDE reform boundary" or "STEM legacy interval") |

### Emission factors (default, IPCC AR5 + AEMO NGES, kg CO₂e/MWh)

Same factor table as NEM (see NEM card §2). Note that the WEM mix is dominated by gas (≈55%) and wind/solar (≈35%); coal contributes <10% and is on a retirement glide-path.

---

## 3. Source endpoints

| URL | Cadence | Coverage | Auth |
| :--- | :--- | :--- | :--- |
| `https://data.wa.aemo.com.au/market-data/wemde/dispatchSolution/dispatchData/current/` | 5 min | last 7 days (live WEMDE) | none (public) |
| `https://data.wa.aemo.com.au/market-data/wemde/dispatchSolution/dispatchData/rolling-12-month/` | daily | last 12 months | none (public) |
| `https://data.wa.aemo.com.au/market-data/wemde/Historical-Data-Archive/` | monthly | 2023-10 → present (per-day CSVs) | none (public) |
| `https://data.wa.aemo.com.au/market-data/Public-Reports/STEM-Archive/` | monthly | 2012-07 → 2023-09 (legacy STEM, 30-min) | none (public) |
| `https://apis.prod.aemo.com.au:9319/WEM/v2/dispatchSolution` | 5 min | live (cert-auth) | DigiCert TLS cert required |
| `https://apis.prod.aemo.com.au:9319/WEM/v2/preDispatch` | 30 min | 48 h ahead (cert-auth) | DigiCert TLS cert required |
| `https://apis.prod.aemo.com.au:9319/WEM/v2/weekAheadDispatch` | daily | 7 d ahead (cert-auth) | DigiCert TLS cert required |

**Reform boundary:** 2023-10-01 00:00:00 AWST. Pre-2023-10-01 uses legacy STEM (30-min). Post-2023-10-01 uses WEMDE (5-min dispatch + 30-min trading).

**Archive URL pattern** (verified live 2026-07-26): `market-data/wemde/dispatchSolution/dispatchData/current/` returns per-day CSVs. Filename pattern: `MarketDataDispatchData_YYYYMMDD.csv`.

---

## 4. Data quality rules

### Null thresholds (drop + alert if exceeded)

| Column(s) | Threshold |
| :--- | :--- |
| `ts`, `region`, `network_code`, `schema_version`, `data_quality_status`, `total_generation_mw`, `source`, `ingest_run_id`, `fetched_at`, `ingested_at` | **0%** |
| `demand_mw` (when `final` / `revised`) | **0%** |
| `price_mwh` (when `final`) | **0%** |
| Fuel type columns | **0%** nulls (replace with 0) |
| `interconnector_*_mw`, `net_import_mw` | **expected NULL** — WEM is isolated. If non-null, alert. |

### Freshness SLA

| Status | Max staleness |
| :--- | :--- |
| `raw` | 10 min |
| `interim` | 30 min |
| `final` | 4 h |
| `revised` | 7 days |

### Range constraints (WEM-specific)

| Field | Range |
| :--- | :--- |
| `demand_mw`, `total_generation_mw` | 0–5,000 (WEM SWIS is ~10% the size of NEM) |
| `price_mwh` | -1,000 to 1,000 (narrower than NEM; no $16,600 cap) |
| `renewable_proportion` | 0–1 |
| `emissions_intensity_kgco2e_per_mwh` | 0–2,000 |
| `interconnector_*_mw` | **always NULL** |

### Consistency (per record)

- `sum(generation_by_fuel_mw) ≈ total_generation_mw` (±1%)
- `demand_mw ≈ total_generation_mw` (±5% for rooftop PV estimate)
- `renewable_proportion × total_generation_mw ≈ renewable_generation_mw`
- (interconnector checks skipped — WEM is isolated)

### Automated checks

JSON Schema 2020-12 validation + 32-expectation Great Expectations suite (`great_expectations_wem_suite.json`, shares 28 expectations with NEM suite) + dbt tests + PagerDuty alert if null rate > 0% for 5+ min on critical columns.

### Known caveats

- **Reform boundary (2023-10-01)**: 30-min STEM and 5-min WEMDE data have different columns, prices, and intervals. Fetcher must dispatch to different parsers by `ts < '2023-10-01 AWST'`.
- **Coal retirement**: Muja and Collie coal units are closing on a 2024-2030 schedule. Pre-2024 data shows ~20% coal; post-2026 shows <5%. Code that assumes constant fuel mix will break.
- **Pre-2012 data**: WEM (then called SWIS market) starts 2006-09-21 but AEMO's public archive only goes back to 2012-07-01. Older data requires direct request.
- **Settlement prices** differ from dispatch prices. `price_mwh` here is dispatch; settlement price is in the `SETTLEMENT_SCHED` table.
- **ESS markets**: post-reform, WEM has 5 separate ESS markets (Regulation Raise/Lower, Contingency Raise/Lower, RoCoF). `fcas_enablement_aud` here is the sum across all 5.
- **No interconnectors**: 4 of the 41 columns are always NULL (`interconnector_imports_mw`, `interconnector_exports_mw`, `net_import_mw`, plus `interconnector_*` checks). Don't drop the columns — they keep the schema aligned with NEM for the merger in v2.0.

---

## 5. Versioning

| Version | Date | Notes |
| :--- | :--- | :--- |
| `1.0.0` | 2026-07-26 | Initial production release. 5-min WEMDE + 30-min STEM unified schema. Single `WEM` region. |
| `1.1.0` | Q3 2026 (planned) | Add `ess_raise_mw`, `ess_lower_mw`, `ess_regulation_mw` (per-market ESS split) |
| `1.2.0` | Q4 2026 (planned) | Add `settlement_price_mwh` (separate from dispatch price) |
| `2.0.0` | 2027 (planned) | **Merge with NEM**: drop `network_code` since NEM and WEM share the schema; add `interconnector` rows to handle any future NEM-WEM link. |

Major bumps on: required field added, type change, enum value removed. Schema retained for 12 months after a major release.

---

## 6. Contact

- **Email**: `data@ecolens.app`
- **WEM operations**: `wa.rtm@aemo.com.au` (AEMO WEM Real-Time Market Management)
- **On-call**: PagerDuty `ecolens-data-pipeline`
- **Runbook**: <https://ecolens.app/runbooks/aemo-wem-pipeline>
- **Status**: <https://status.ecolens.app>
- **Schema repo**: <https://github.com/ecolens/schemas/tree/main/market_data/wem>

## 7. Citation

> ecoLens AEMO WEM Data Card v1.0, accessed [date]. Derived from AEMO WEM
> Market Data (<https://data.wa.aemo.com.au>) under AEMO Copyright Permissions
> Notice. ecoLens processing licensed CC BY 4.0.
