# Holiday data — binary feature flag for the LSTM, marking demand-shifting days (industrial off, retail patterns, school holiday correlation).
# Data Card: `ecolens-holiday-data-v1`

> Short-form spec for the Australian public holidays dataset. Schema locked
> to JSON Schema 2020-12 (`holiday_data.schema.json`, 23 fields).

---

## 1. Overview

| Field | Value |
| :--- | :--- |
| **Dataset** | `ecolens-holiday-data-v1` v1.0.0 (2026-07-26) |
| **Source** | `data.gov.au` (federal) + 8 state/territory gazettes + Fair Work Ombudsman |
| **Storage** | PostgreSQL 16, database `ecolens`, schema `calendar`, table `au_public_holidays` (declarative partitioning by `date` year, sub-partitioned by `region`). Nightly Parquet export to S3. |
| **License** | CC BY 4.0 (ecoLens processing). Upstream state gazettes are public-domain. |
| **Refresh** | Annual (state gazettes published in Jan) + ad-hoc for one-offs (e.g. Coronation). Daily 03:00 AEST fallback fetch. |
| **Retention** | 5 years hot (current + 2 prior + 2 ahead); longer history in S3 cold tier |
| **Schema reference** | `OBSERVATION_OUTPUT_COLUMNS` pattern in `ecolens_holiday_fetcher.py:200-260` |

**Purpose in ecoLens:** (1) **Feature flag** for the LSTM — demand on public holidays is structurally different (industrial load off, retail spike, school holidays correlate). (2) **Calendar-day observability** — demand spikes/dips around holiday boundaries are easy to explain with a single join. (3) **Compliance / HR** — which day are staff off in which state/region.
**Out of scope:** individual employment contracts, school terms, school holidays (separate dataset), international holidays.

---

## 2. Schema (23 fields, primary key `(date, region)`)

### 2.1 Identity (required)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `date` | `DATE` | no | Official / legislated date (`YYYY-MM-DD`) |
| `region` | `VARCHAR(4)` | no | `NEM` \| `NSW1` \| `QLD1` \| `VIC1` \| `SA1` \| `TAS1` \| `WEM` |
| `state` | `VARCHAR(3)` | no | `NSW` \| `VIC` \| `QLD` \| `SA` \| `WA` \| `TAS` \| `ACT` \| `NT` \| `NAT` |
| `holiday_name` | `VARCHAR(100)` | no | Official name as legislated (e.g. `Melbourne Cup Day`) |
| `holiday_type` | `VARCHAR(16)` | no | `national` \| `state` \| `regional` \| `bank` \| `half_day` \| `restricted` |
| `is_business_day` | `BOOLEAN` | no | Always `false` for public holidays by definition |
| `is_observed` | `BOOLEAN` | no | `true` if `date` is the *rolled* (observed) date |
| `schema_version` | `VARCHAR(10)` | no | `1.0` (semver, e.g. `1.0.0`) |

### 2.2 Date logic (optional, derived)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `observed_date` | `DATE` | yes | Day-off if `date` falls on weekend. Equal to `date` when no rollover. ANZAC and Christmas do **not** roll over. |
| `day_of_week` | `VARCHAR(10)` | yes | `Monday`–`Sunday` |
| `is_weekend` | `BOOLEAN` | yes | `true` if `date` is Sat/Sun |
| `days_until` | `INTEGER` | yes | Days from today (UTC) until `date`. NULL for past dates. |
| `recurring` | `BOOLEAN` | yes | `false` for one-offs (Coronation, Mourning days) |
| `is_one_off_2023` | `BOOLEAN` | yes | Flag for known 2023+ one-offs (coronation, King's Birthday rename) |

### 2.3 Scope (optional)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `scope_detail` | `VARCHAR(500)` | yes | Geographic or industry restriction when `holiday_type` ∈ {`regional`, `restricted`} (e.g. *"Melbourne metropolitan LGAs gazetted under Public Holidays Act 1993 s.5"*) |
| `legislation_url` | `VARCHAR(1024)` | yes | State/territory legislation that establishes the holiday. For audit. |

### 2.4 Provenance & lineage (required)

| Column | Type | Null | Description |
| :--- | :--- | :--- | :--- |
| `source` | `VARCHAR(32)` | no | `data_gov_au` \| `nsw_public_holidays` \| `vic_public_holidays` \| `qld_public_holidays` \| `sa_public_holidays` \| `wa_public_holidays` \| `tas_public_holidays` \| `act_public_holidays` \| `nt_public_holidays` \| `fairwork_ombudsman` \| `cache` \| `synthetic` |
| `source_url` | `VARCHAR(1024)` | yes | Direct URL for audit |
| `ingest_run_id` | `UUID` | no | UUID v4 of the pipeline run |
| `fetched_at` | `TIMESTAMP(TZ)` | no | UTC when upstream row was pulled |
| `ingested_at` | `TIMESTAMP(TZ)` | yes | UTC when written to warehouse. NULL for pre-computed future rows. |
| `pipeline_version` | `VARCHAR(16)` | yes | Fetcher version, e.g. `0.3.0` |
| `notes` | `VARCHAR(500)` | yes | Free-text annotation |

### Holiday-type taxonomy

| Type | Count/year (per region) | Example |
| :--- | ---: | :--- |
| `national` | 6–8 | Christmas, ANZAC, Australia Day, New Year's |
| `state` | 1–4 | Labour Day, Queen's/King's Birthday |
| `regional` | 0–2 | Melbourne Cup Day (VIC only), Show Day (regional) |
| `bank` | varies | Bank-only holidays (e.g. Melbourne Cup in non-metro VIC) |
| `half_day` | rare | AFL Grand Final Friday (VIC, from 2pm) |
| `restricted` | rare | Easter Saturday in some states |

---

## 3. Source endpoints

| URL | Cadence | Coverage | Auth |
| :--- | :--- | :--- | :--- |
| `https://data.gov.au/data/api/3/action/package_show?id=public-holidays` | annual | all 8 states | none |
| `https://www.nsw.gov.au/business-industry/employment-conditions/public-holidays` | annual | NSW1 | none |
| `https://www.vic.gov.au/public-holidays-victoria` | annual | VIC1 | none |
| `https://www.qld.gov.au/recreation/travel/holidays/public-holidays` | annual | QLD1 | none |
| `https://www.sa.gov.au/topics/employment/public-holidays` | annual | SA1 | none |
| `https://www.wa.gov.au/service/employment/workplace-relations/public-holidays` | annual | WEM | none |
| `https://www.communities.tas.gov.au/csr/community-calendars/public-holidays` | annual | TAS1 | none |
| `https://www.cmtedd.act.gov.au/employment-framework/public-holidays` | annual | ACT (joins NSW1) | none |
| `https://nt.gov.au/employ/money-taxes-and-work/public-holidays` | annual | NT (out of NEM scope) | none |
| `https://www.fairwork.gov.au/employment-conditions/public-holidays` | quarterly | federal reference | none |

**Fallback**: if all 9 sources fail, the fetcher generates holidays algorithmically (Easter algorithm + fixed-date templates). The result is tagged `source='synthetic'` and never used as ground truth — only as a placeholder until the real gazette lands.

---

## 4. Data quality rules

### Null thresholds

| Column(s) | Threshold |
| :--- | :--- |
| `date`, `region`, `state`, `holiday_name`, `holiday_type`, `is_business_day`, `is_observed`, `schema_version`, `source`, `ingest_run_id`, `fetched_at` | **0%** |
| `scope_detail` (when `holiday_type=regional`) | **0%** |
| `legislation_url` | ≤ 5% (some legacy rows lack it) |
| `days_until` (for past dates) | **expected NULL** — not a quality issue |

### Freshness SLA

| Source | Max staleness |
| :--- | :--- |
| State gazette published | ≤ 24 h after publication |
| One-off additions (Coronation, Mourning) | ≤ 1 h after official announcement |
| Synthetic fallback | any time all 9 sources are down |

### Range / value constraints

| Field | Range |
| :--- | :--- |
| `date` | 2009-01-01 → 2030-12-31 (5 years either side) |
| `state` | `NSW` \| `VIC` \| `QLD` \| `SA` \| `WA` \| `TAS` \| `ACT` \| `NT` \| `NAT` |
| `holiday_type` | 6 enum values (see §2) |
| `day_of_week` | 7 enum values |
| `days_until` | -2000 to +2000 (sanity) |
| `is_business_day` | **always `false`** — drop record if `true` |

### Consistency (per record)

- `is_business_day == false` for all rows (it's a public holiday, by definition)
- If `is_observed == true` → `observed_date != date` and `is_weekend(observed_date) == false`
- If `date` is weekend and `is_observed == false` → must be a non-rolling holiday (ANZAC, Christmas) or a half-day
- If `recurring == false` → `is_one_off_2023` should be `true` for 2023+ rows
- ACT holidays should be linked to NSW1 region (ACT has no separate NEM region)

### Automated checks

JSON Schema 2020-12 + Great Expectations suite (`holiday_expectations.json`, 18 expectations) + dbt tests + PagerDuty if a state gazette is missing > 30 days past its annual publication date.

### Known caveats

- **"Queen's Birthday" → "King's Birthday"** since 8 Sep 2022. Pre-2022-09 rows say `Queen's Birthday`; post-2022-09 say `King's Birthday`. Don't hardcode the name in downstream code.
- **One-off holidays** (cause discontinuities in time series):
  - 22 Sep 2022: National Day of Mourning (Queen Elizabeth II)
  - 8 May 2023: Coronation of King Charles III
  - 27 Sep 2022: National Day of Mourning
- **Weekend rollover rules vary by state**: e.g. ANZAC and Christmas do **not** roll, but Australia Day does. Check state-specific rules.
- **Regional holidays are state-specific**: Melbourne Cup Day is `VIC1` only; Ekka is `QLD1` only. Don't apply VIC's regional holidays to NSW.
- **ACT joins NSW1**: ACT is in NSW's NEM region. When source=ACT, region is remapped to NSW1.
- **NT is out of NEM scope**: Northern Territory has no NEM region. Fetched for completeness but not joined to energy data.
- **Pre-2009 data may be missing**: the AEMO NEM public archive starts 2009-07-01, so pre-2009 holiday data is rarely used. Some states (QLD, TAS) only published public-domain gazettes from 2010+.

---

## 5. Versioning

| Version | Date | Notes |
| :--- | :--- | :--- |
| `1.0.0` | 2026-07-26 | Initial production release. 23 fields, JSON Schema 2020-12, 6 holiday types, 11 source enums. |
| `1.1.0` | Q4 2026 (planned) | Add `school_holiday_adjacent` boolean (true if the holiday is the first business day after school holidays end). |
| `1.2.0` | Q1 2027 (planned) | Add `substituted_half_day` for the half-day variants (e.g. AFL Grand Final Friday from 2pm). |

Major bumps on: required field added, type change, enum value removed. Schema retained for 12 months after a major release.

---

## 6. Contact

- **Email**: `data@ecolens.app`
- **On-call**: PagerDuty `ecolens-data-pipeline`
- **Runbook**: <https://ecolens.app/runbooks/holiday-pipeline>
- **Status**: <https://status.ecolens.app>
- **Schema repo**: <https://github.com/ecolens/schemas/tree/main/calendar/holiday_data>
- **Source code**: `ecolens_holiday_fetcher.py` (45 KB, 29 self-tests)

## 7. Citation

> ecoLens Holiday Data Card v1.0, accessed [date]. Derived from Australian
> state/territory public holiday gazettes (<https://data.gov.au>) under CC BY
> 4.0. ecoLens processing layer licensed CC BY 4.0.
