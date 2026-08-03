# Raw ingestion schema

Source of truth for the `raw.*` tables landed by the 5 ingestion tasks
(ECO-D25–D29) and the `meta`/`ml` bookkeeping tables that sit alongside
them (ECO-D17, ECO-D18). Migrations `0002`–`0008` established the first
version of this schema; `0011`–`0012` reconciled it against what the
actual task implementations in `ecolens/pipeline/tasks/` produce (richer
per-fuel columns, a wide-form `openelectricity_mix`, and a richer
`meta._ingest_log`). If you change one, change the other.

## `raw.*` — one table per source

### `raw.openelectricity_mix` (ECO-D25)

Generation mix, **wide form**: one row per `(ts, network_code, region)`,
one column per fuel type. (An earlier version of this table was long-form
— one row per `ts`+`region`+`fuel_type` — but `ingest_openelectricity.py`
pivots OpenElectricity's long-form SDK output into our wide schema before
landing, via `_pivot_long_to_wide`.)

| Column | Type | Notes |
| --- | --- | --- |
| `ts` | `timestamptz` | Interval start |
| `network_code` | `text` | `NEM` or `WEM` |
| `region` | `text` | e.g. `NSW1`, `WEM` |
| `coal_mw` | `numeric` | |
| `gas_mw` | `numeric` | |
| `hydro_mw` | `numeric` | |
| `wind_mw` | `numeric` | |
| `solar_utility_mw` | `numeric` | |
| `solar_rooftop_mw` | `numeric` | |
| `battery_discharge_mw` | `numeric` | |
| `battery_charge_mw` | `numeric` | |
| `pumped_hydro_mw` | `numeric` | |
| `biomass_mw` | `numeric` | |
| `distillate_mw` | `numeric` | |
| `total_generation_mw` | `numeric` | Sum of the fuel columns above |
| `total_renewable_mw` | `numeric` | wind + solar (both) + hydro + biomass |
| `demand_mw` | `numeric` | From OE's `demand` series, if present |
| `price_mwh` | `numeric` | From OE's `price` series, if present |
| `intensity_kg_per_mwh` | `numeric` | Filled by a separate emissions fetch — `None` until then |
| `source` | `text` | `"openelectricity"` |
| `ingested_at` | `timestamptz` | Landing time, not dispatch time |
| `ingest_run_id` | `uuid` | |

PK: `(ts, network_code, region)`

### `raw.aemo_nem_dispatch` (ECO-D26)

5-minute NEM dispatch, per region (NSW1/QLD1/VIC1/SA1/TAS1), with
per-fuel generation.

| Column | Type | Notes |
| --- | --- | --- |
| `ts` | `timestamptz` | Dispatch interval |
| `region` | `text` | |
| `demand_mw` | `numeric` | |
| `price_mwh` | `numeric` | Regional reference price ($/MWh) |
| `coal_mw` | `numeric` | |
| `gas_mw` | `numeric` | |
| `hydro_mw` | `numeric` | |
| `wind_mw` | `numeric` | |
| `solar_utility_mw` | `numeric` | |
| `solar_rooftop_mw` | `numeric` | |
| `battery_mw` | `numeric` | |
| `net_import_mw` | `numeric` | Interconnector flow |
| `source` | `text` | `"aemo_nem"` |
| `ingested_at` | `timestamptz` | |
| `ingest_run_id` | `uuid` | |

PK: `(ts, region)`

### `raw.aemo_wem_dispatch` (ECO-D27)

30-minute WEM (SWIS) dispatch. Single region, but WEM's own fuel mix
(notably `diesel_mw`, no `net_import_mw` — WEM is islanded).

| Column | Type | Notes |
| --- | --- | --- |
| `ts` | `timestamptz` | |
| `region` | `text` | Always `WEM` |
| `demand_mw` | `numeric` | |
| `price_mwh` | `numeric` | |
| `coal_mw` | `numeric` | |
| `gas_mw` | `numeric` | |
| `diesel_mw` | `numeric` | |
| `wind_mw` | `numeric` | |
| `solar_utility_mw` | `numeric` | |
| `solar_rooftop_mw` | `numeric` | |
| `battery_mw` | `numeric` | |
| `biomass_mw` | `numeric` | |
| `total_generation_mw` | `numeric` | Sum of the fuel columns above |
| `source` | `text` | `"aemo_wem"` |
| `ingested_at` | `timestamptz` | |
| `ingest_run_id` | `uuid` | |

PK: `(ts, region)`

### `raw.bom_observations` (ECO-D28)

Weather observations, 6 stations (one per NEM region + WEM) — full BoM
observation fields, not just temperature.

| Column | Type | Notes |
| --- | --- | --- |
| `ts` | `timestamptz` | |
| `station_id` | `text` | BoM station code (`Settings.bom_stations`) |
| `region` | `text` | Station → region mapping |
| `temp_c` | `numeric` | |
| `apparent_temp_c` | `numeric` | "Feels like" |
| `dew_point_c` | `numeric` | |
| `humidity_pct` | `numeric` | |
| `wind_speed_kmh` | `numeric` | |
| `wind_direction_deg` | `numeric` | |
| `wind_gust_kmh` | `numeric` | |
| `pressure_hpa` | `numeric` | Mean sea level pressure |
| `rain_since_9am_mm` | `numeric` | |
| `cloud_oktas` | `numeric` | 0-8 sky cover |
| `source` | `text` | `"bom"` |
| `ingested_at` | `timestamptz` | |
| `ingest_run_id` | `uuid` | |

PK: `(ts, station_id)`

### `raw.aemo_holidays` (ECO-D29)

Annual public-holiday calendar snapshot, per region.

| Column | Type | Notes |
| --- | --- | --- |
| `date` | `date` | (Not `holiday_date` — matches the task's own column name.) |
| `region` | `text` | |
| `holiday_name` | `text` | |
| `is_workday` | `boolean` | Always `false` today — reserved for substitute-holiday handling |
| `source` | `text` | `"aemo_holidays"` |
| `ingested_at` | `timestamptz` | |
| `ingest_run_id` | `uuid` | |

PK: `(region, date)`

## `meta.*` — operational bookkeeping (ECO-D17)

- **`meta._ingest_log`** — one row per ingestion run, written by
  `ecolens.pipeline.tasks._common.standard_run`: `id` (PK), `source`,
  `status` (`running`/`success`/`failed`), `triggered_by` (e.g. `manual`,
  `cron`, `github-actions`), `window_start`/`window_end` (free-text —
  whatever the caller passed, not necessarily parseable timestamps),
  `hostname` (which process ran it — `Settings.hostname`), `started_at`,
  `finished_at`, `rows_landed` (rows the fetch returned before loading),
  `rows_loaded` (rows actually COPYed into Postgres), `error_message`,
  `circuit_breaker_state` (the breaker's state at the end of the run).
- **`meta.circuit_breaker_state`** — Postgres mirror of the Redis-backed
  `CircuitBreaker` state (ECO-D07): `name` (PK), `state`, `failures`,
  `opened_at`, `updated_at`. Redis stays the source of truth for the
  actual open/closed decision; this table exists for durability/auditing
  across Redis restarts, not for the breaker to read from directly. (Not
  yet written to by any task — `_common.py` records breaker state onto
  `meta._ingest_log` per-run instead; nothing currently upserts this
  table.)
- **`meta.cron_run_log`** — one row per cron tick (ECO-D59): `id` (PK),
  `job_name`, `started_at`, `finished_at`, `exit_code`, `output`.
- **`meta._promotion_log`** — one row per promotion decision (ECO-D41):
  `id` (PK), `model_name`, `promoted`, `candidate_version`,
  `candidate_mape`, `production_mape`, `reason`, `created_at`. Shape
  mirrors the `PromotionResponse` API schema (ECO-D14).

## `ml.*` — training/evaluation bookkeeping (ECO-D18)

- **`ml.forecast_runs`** — one row per forecast served (ECO-D44):
  `id` (PK), `model_name`, `model_version`, `region`, `generated_at`,
  `horizon`, `interval`.
- **`ml.eval_reports`** — one row per evaluation run (ECO-D39):
  `id` (PK), `model_name`, `model_version`, `evaluated_at`, `window_days`,
  `mape`, `rmse`, `mae`, `p90_coverage`.
- **`ml.drift_reports`** — one row per drift check (ECO-D42): `id` (PK),
  `model_name`, `checked_at`, `psi`, `ks_statistic`, `drifted`, `report_url`.

## Hypertables & indexes (ECO-D19, ECO-D20, reapplied by 0012)

All 5 `raw.*` tables become TimescaleDB hypertables (7-day chunks) where
the extension is available — see `migrations/0012_reapply_hypertables_and_indexes.sql`,
which no-ops with a `NOTICE` on Postgres instances without `timescaledb`.
In practice this repo's own database (Neon) *does* support it — confirmed
when the migrations were first applied. Each `raw.*` table also gets a
`(region, ts DESC)` index (`(region, date DESC)` for `aemo_holidays`);
`ml.eval_reports` and `ml.drift_reports` get `(model_name, <timestamp> DESC)`
indexes for "latest N per model" queries.
