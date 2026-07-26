# OpenElectricity — cross-validation + fallback source for NEM/WEM when AEMO endpoints are down; sanity check for forecasts.

# Data Card: `ecolens-openelectricity-v1`

> Short-form spec for the OpenElectricity cross-validation / fallback dataset.
> OpenElectricity is the secondary source for NEM/WEM data; AEMO is primary.

---

## 1. Overview

| Field | Value |
| :--- | :--- |
| **Dataset** | `ecolens-openelectricity-v1` v1.0.0 (2026-07-26) |
| **Source** | OpenElectricity v4 API (`api.openelectricity.org.au/v4`), formerly OpenNEM |
| **Storage** | PostgreSQL 16, database `ecolens`, schema `market_data`, tables `openelectricity_nem_dispatch_5min` and `openelectricity_wem_dispatch_5min` (declarative partitioning by `ts`). Nightly Parquet export to S3. |
| **License** | **CC BY-NC 4.0** for Community/Academic tiers — **commercial use requires Enterprise plan** (ecoLens uses Enterprise). |
| **Refresh** | 5-min live + 1-hr/1-day rolls (depends on plan rate limits) |
| **Retention** | 2 years on Community plan; 1998 → present on Academic/Enterprise |
| **API key** | Required — `Authorization: Bearer <token>` header. Signup is waitlisted. |

**Purpose in ecoLens:** (1) **Cross-validation** — compare AEMO-pulled rows against OpenElectricity's independently cleaned data to detect ingest drift. (2) **Fallback** — when AEMO NEMWeb or WEMDEPI endpoints are down, fall back to OpenElectricity. (3) **Enrichment** — they expose `renewable_proportion`, `emissions`, `market_value` as built-in metrics (AEMO gives raw fuel mix; we'd compute these ourselves).
**Not for:** commercial redistribution without Enterprise licence, real-time SCADA, settlement-grade numbers (they have a 5-30 min AEMO-derived lag).

---

## 2. Schema (15 columns, primary key `(ts, network_code, region)`)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `ts` | `TIMESTAMP(TZ)` | no | Interval start, ISO 8601, UTC. 5-min (live), 1h/1d (backfill). |
| `network_code` | `VARCHAR(4)` | no | `NEM` \| `WEM` \| `AU` (NEM+WEM aggregate) |
| `region` | `VARCHAR(4)` | no | NEM: `NEM`/`NSW1`/`QLD1`/`VIC1`/`SA1`/`TAS1`. WEM: `WEM`. AU: `AU`. |
| `interval` | `VARCHAR(4)` | no | Original API interval: `5m` \| `1h` \| `1d` \| `7d` \| `1M` \| `3M` \| `1y` |
| `power_mw` | `DOUBLE` | yes | Instantaneous power (MW) by fuel/region |
| `energy_mwh` | `DOUBLE` | yes | Energy over the interval (MWh) |
| `price_mwh` | `DOUBLE` | yes | $/MWh (NEM: RRP, WEM: dispatch price) |
| `demand_mw` | `DOUBLE` | yes | Operational demand (MW) |
| `demand_energy_mwh` | `DOUBLE` | yes | Demand energy over the interval |
| `market_value_aud` | `DOUBLE` | yes | Total market value for the region (AUD) |
| `emissions_tonnes_co2e` | `DOUBLE` | yes | CO₂e emissions (tonnes) for the interval |
| `renewable_proportion` | `DOUBLE` | yes | Renewable fraction, 0–1 (NULL when gross demand not landed) |
| `unit_fueltech` | `VARCHAR(32)` | yes | When aggregated by facility, fuel type (e.g. `wind`, `solar_utility`, `coal_black`) |
| `source` | `VARCHAR(32)` | no | `openelectricity` |
| `fetched_at` | `TIMESTAMP(TZ)` | no | UTC when API row was pulled |
| `ingested_at` | `TIMESTAMP(TZ)` | no | UTC when written to warehouse |
| `ingest_run_id` | `UUID` | no | UUID v4 of the pipeline run |

### Network-level vs facility-level queries

| API endpoint | Grain | Use case |
| :--- | :--- | :--- |
| `GET /v4/market/network/{network_code}` | network + region aggregates | demand, price, market value, renewable proportion |
| `GET /v4/data/network/{network_code}` | network + fueltech aggregates | power, energy, emissions by fuel type |
| `GET /v4/data/facility/{network_code}` | individual facility | unit-level deep-dive |

ecoLens primarily uses the first two. Facility-level is for ad-hoc debugging.

---

## 3. Source endpoints

| URL | Cadence | Coverage | Auth |
| :--- | :--- | :--- | :--- |
| `https://api.openelectricity.org.au/v4/market/network/NEM` | 5 min | last 2 years (Community) / 1998→ (Academic/Enterprise) | Bearer token (HTTP 422 without required query params — verified live) |
| `https://api.openelectricity.org.au/v4/market/network/WEM` | 5 min | last 2 years / 2006→ | Bearer token |
| `https://api.openelectricity.org.au/v4/data/network/NEM` | 5 min | last 2 years / 1998→ | Bearer token |
| `https://api.openelectricity.org.au/v4/data/network/WEM` | 5 min | last 2 years / 2006→ | Bearer token |
| `https://api.openelectricity.org.au/v4/facilities` | static | facility metadata | Bearer token (HTTP 401 without — verified live) |
| `https://api.openelectricity.org.au/v4/user` | per-call | current API quota | Bearer token (HTTP 404 unauthenticated — oddity, likely a routing issue) |

**Required headers (every call):**
```
Authorization: Bearer <OPENELECTRICITY_API_KEY>
Content-Type: application/json
User-Agent: ecoLens/0.2.0
```

**Rate limits** (per plan — see `/api-reference/data-limits` for current numbers): Community ≈ 60 req/min, Academic ≈ 300 req/min, Enterprise negotiated. ecoLens has Enterprise.

---

## 4. Data quality rules

### Null thresholds

| Column(s) | Threshold |
| :--- | :--- |
| `ts`, `network_code`, `region`, `interval`, `source`, `ingest_run_id`, `fetched_at`, `ingested_at` | **0%** |
| `demand_mw`, `price_mwh`, `emissions_tonnes_co2e` (when interval ∈ {`5m`, `1h`, `1d`}) | **0%** |
| `unit_fueltech` (network-level rows) | **0%** (must be `all` or empty) |

### Freshness SLA

| Source / interval | Max staleness |
| :--- | :--- |
| `5m` (live) | 10 min (AEMO-derived lag) |
| `1h` | 90 min |
| `1d` | 36 h |

**Note from changelog 2026-Q2:** "The most recent 5-min interval is provisional while AEMO data is still settling" — the API now returns `null` (not `0`) for `renewable_proportion` when gross demand hasn't landed. ecoLens treats `null` as "skip" (don't substitute 0).

### Range constraints

| Field | Range |
| :--- | :--- |
| `power_mw`, `demand_mw` | 0–100,000 (NEM) / 0–5,000 (WEM) |
| `price_mwh` | -1,000 to 16,600 (NEM) / -1,000 to 1,000 (WEM) |
| `renewable_proportion` | 0–1 (or NULL) |
| `emissions_tonnes_co2e` | 0–1,000,000 (5-min NEM) / 0–50,000 (5-min WEM) |

### Consistency (per record)

- `renewable_proportion` is `null` when `gross_demand` is missing (per changelog) — do NOT treat as 0.
- `power_mw × (interval_seconds / 3600) ≈ energy_mwh` (±5% for cross-boundary)
- For the NEM aggregate: `sum(region.demand_mw) ≈ network.demand_mw` (±1%)

### Automated checks

JSON Schema 2020-12 + Great Expectations suite (`great_expectations_oe_suite.json`) + cross-validation diff against AEMO rows in `market_data.aemo_nem_dispatch_5min` (run hourly, alert on >2% diff in any region × fuel cell).

### Known caveats

- **License: CC BY-NC 4.0** on Community/Academic. ecoLens is commercial → **must be on Enterprise plan** for the data we use to be redistribution-safe. Encrypted-at-rest + Enterprise contract required.
- **API key signup is waitlisted** (per their GitHub README). New ecoLens deployments need a pre-arranged key, not a self-serve signup.
- **Renewable proportion null vs zero**: changelog v4.5.1 fixed spurious zeros; now returns `null` for unsettled intervals. Old code that defaulted to 0 will over-estimate the renewable share.
- **Synthetic rooftop backfill (Mar 2015 → Dec 2016)**: OpenElectricity fills a 16-month gap in rooftop solar with synthetic data. ecoLens tags these rows in `notes` so ML training can filter them.
- **WEM reform boundary (2023-10-01)**: OpenElectricity rebuilt the WEM series to match the post-reform WEMDE feed. Pre-2023-10 WEM data has different column semantics.
- **AU aggregate** (`network_code=AU`): NEM + WEM combined. Do not use for NEM-only or WEM-only analysis.

---

## 5. Versioning

| Version | Date | Notes |
| :--- | :--- | :--- |
| `1.0.0` | 2026-07-26 | Initial release. NEM + WEM. Cross-validation against AEMO rows. |
| `1.1.0` | Q3 2026 (planned) | Add APVI rooftop solar as a separate stream (currently embedded in NEM renewable_proportion) |
| `1.2.0` | Q4 2026 (planned) | Switch to facility-level hourly snapshots for ML training labels (more accurate than 5-min network aggregates) |

Major bumps on: required field added, type change, enum removed. Schema retained for 12 months after a major release.

---

## 6. Contact

- **Email**: `data@ecolens.app`
- **OpenElectricity support**: `support@openelectricity.org.au`
- **OpenElectricity platform**: <https://platform.openelectricity.org.au>
- **On-call**: PagerDuty `ecolens-data-pipeline`
- **Runbook**: <https://ecolens.app/runbooks/openelectricity-pipeline>
- **Status**: <https://status.ecolens.app>
- **Schema repo**: <https://github.com/ecolens/schemas/tree/main/market_data/openelectricity>

## 7. Citation

> ecoLens OpenElectricity Data Card v1.0, accessed [date]. Derived from
> OpenElectricity v4 API (<https://api.openelectricity.org.au/v4>) under
> Enterprise licence. Original data © OpenElectricity Pty Ltd / AEMO, used
> with permission. ecoLens processing layer licensed CC BY 4.0.
