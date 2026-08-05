# Warehouse Pipeline

How raw, per-source rows land in Postgres and get transformed into the
analytics-ready marts forecast-api/the dashboard/model training actually
read — the event-driven Postgres load, the dbt transformation DAG, what
keeps the two in sync, and the APIs that trigger/observe both. Verified
against the live code in `services/data-pipeline/app/` and
`services/data-pipeline/dbt/ecolens/` on 2026-08-05.

Companion docs: `docs/data/ingestion.md` (everything upstream of this —
how rows get fetched and staged in DuckDB in the first place; this file
picks up from "a RabbitMQ event has been published"), `TODO.md`'s
Storage & Cost Optimization section (Neon retention policy + local
DuckDB archive plan for everything described here), `overview.md`
(product-level pitch, ahead of what's built in a few places).

---

## Two stages: sync, then transform

```
                (from docs/data/ingestion.md — a RabbitMQ event has
                 just been published, one .duckdb file staged)
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│ STAGE 1 — pipeline.warehouse_sync.sync_landed_event  (event-driven) │
│   consumes the landing queue, one message at a time                │
│                                                                      │
│   1. duckdb_staging.read_staged(duckdb_path)                       │
│   2. landing.load_to_postgres(df, table, schema="raw")             │
│        asyncpg COPY -> temp table -> INSERT ... ON CONFLICT        │
│        DO NOTHING into raw.{table}                                 │
│   3. success: meta._ingest_log -> 'success', delete the .duckdb    │
│      failure: meta._ingest_log -> 'sync_failed', .duckdb file kept │
│               on disk as the replay artifact, message nacked       │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              raw.openelectricity_mix, raw.aemo_nem_dispatch,
              raw.aemo_wem_dispatch, raw.bom_observations,
              raw.aemo_holidays        (TimescaleDB hypertables)
                              │
                              │  (NOT automatic per-row — a separate,
                              │   periodic/triggered `dbt build`)
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│ STAGE 2 — dbt build  (batch, triggered — never per-row)             │
│                                                                      │
│   staging (view)  →  intermediate (ephemeral)  →  marts (table)    │
│   raw_staging.stg_*     inlined into marts        raw_marts.fct_*/ │
│                                                    dim_*            │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        forecast-api reads, dashboard reads, ml/train.py trains on
```

**Why two decoupled stages instead of one pipeline**: Stage 1 (row
lands in `raw.*`) happens continuously, every few minutes, per source.
Stage 2 (`dbt build`, rebuilding every mart) is comparatively expensive
and doesn't need to run on every single row — it runs on its own
triggers (below), batching up however much `raw.*` changed since the
last build. Nothing downstream ever reads a "half-transformed" state:
marts are full-table rebuilds, not incrementally patched per Stage-1
event.

---

## Stage 1 — event-driven Postgres load

Covered in depth in `docs/data/ingestion.md`'s pipeline-architecture
section; the short version from the warehouse side: `pipeline.
warehouse_sync.sync_landed_event` is the RabbitMQ consumer
(`app.db.rabbitmq.consume_landed_events`, run via the `warehouse-sync`
docker-compose service / `ecolens-pipeline worker` CLI command) that
turns a staged DuckDB file into real rows in `raw.*`, via `asyncpg`'s
`COPY FROM STDIN` into a throwaway temp table, then `INSERT ... ON
CONFLICT DO NOTHING` into the real table — idempotent, so a redelivered
or retried message never double-counts rows. This is the only writer of
`raw.*`; nothing else in the codebase inserts into those tables directly.

### Schema note: `raw.*` is TimescaleDB hypertables

All 5 raw tables are TimescaleDB hypertables, 7-day chunks
(`migrations/0009_hypertables.sql`, reapplied in `0012_...sql` after a
later schema reconciliation): `raw.openelectricity_mix`,
`raw.aemo_nem_dispatch`, `raw.aemo_wem_dispatch`,
`raw.bom_observations`, `raw.aemo_holidays`. Both migrations are
written defensively (`CREATE EXTENSION IF NOT EXISTS timescaledb`,
no-op with a `NOTICE` if the extension isn't available at all) because
several managed Postgres providers don't offer it — but on this
project's actual Neon instance it *is* available, and the hypertable
conversion is real and live. This matters for retention: Timescale's
`add_retention_policy` drops whole chunks (cheap, instant, no dead-tuple
bloat), a materially better mechanism than a row-by-row `DELETE` for
keeping Postgres storage bounded — see `TODO.md`'s Storage & Cost
Optimization plan, which is exactly what this capability is for
(currently no retention policy is active yet; `raw.*` still holds full
history, ~1 year as of this doc).

---

## Stage 2 — dbt transformation DAG

Project: `services/data-pipeline/dbt/ecolens/`. Materialization
strategy is fixed per layer (`dbt_project.yml`):

| Layer | Materialization | Schema | Why |
| :--- | :--- | :--- | :--- |
| `staging` | `view` | `raw_staging` | Cheap, always fresh off `raw.*` — thin passthroughs, no transformation logic worth persisting |
| `intermediate` | `ephemeral` | (inlined) | Feature-engineering CTEs — inlined into whatever mart references them, never queried directly, never materialized on their own |
| `marts` | `table` | `raw_marts` | What forecast-api/the dashboard/`ml/data.py` actually read — a real table, not recomputed per query |

(dbt's `generate_schema_name` macro — no override in this project —
names a custom-schema model `<profile_schema>_<custom_schema>`;
`profiles.yml`'s profile schema is `raw`, so `staging`/`marts` land in
`raw_staging`/`raw_marts`, not bare `staging`/`marts`.)

### The DAG, one source per staging model

```
raw.openelectricity_mix ──► stg_openelectricity_mix ──┬─► int_mix_share ──► int_fuel_emissions ──┬─► int_carbon_intensity ──┬─► fct_emissions_5min
                                                        │                                          │                           └─► fct_carbon_intensity
                                                        │                                          └─► fct_generation_mix
                                                        └───────────────────────────────────────────────────────────────────────► int_demand_with_weather ──► fct_energy_demand
raw.aemo_nem_dispatch   ──► stg_aemo_nem_dispatch   ───────────────────────────────────────────────────────────────────────────► int_demand_with_weather
raw.aemo_wem_dispatch   ──► stg_aemo_wem_dispatch   ───────────────────────────────────────────────────────────────────────────► int_demand_with_weather
raw.bom_observations    ──► stg_bom_observations    ───────────────────────────────────────────────────────────────────────────► int_demand_with_weather
raw.aemo_holidays       ──► stg_aemo_holidays        (joined at ml/features.py's build_features time, not inside a mart)

seeds/emissions_factors.csv ──► dim_energy_mix
                             ──► int_fuel_emissions (joined by fuel_type)
```

| Model | Layer | What it is |
| :--- | :--- | :--- |
| `stg_openelectricity_mix` / `stg_aemo_nem_dispatch` / `stg_aemo_wem_dispatch` / `stg_bom_observations` / `stg_aemo_holidays` | staging | Thin `select *`-shaped passthrough over the matching `raw.*` table — one staging model per raw table, 1:1 |
| `int_mix_share` | intermediate | Unpivots `stg_openelectricity_mix`'s wide per-fuel MW columns into one row per `(ts, network_code, region, fuel_type)` + that fuel's share of total generation |
| `int_fuel_emissions` | intermediate | Per-fuel MW → MWh (interval-aware: 5-min for NEM, 30-min for WEM) × `seeds/emissions_factors.csv`'s intensity — the shared weighting math `int_carbon_intensity` and `fct_generation_mix` both read from one place |
| `int_carbon_intensity` | intermediate | Sums `int_fuel_emissions` back up to `(ts, network_code, region)`, computing ecoLens's own generation-weighted intensity (`live_mix_weighted`) alongside OpenElectricity's own reported figure (`live_provider`, kept genuinely independent for cross-checking — not sharing a denominator) |
| `int_demand_with_weather` | intermediate | The real feature-engineering model: unions NEM+WEM demand, **as-of** (not exact-timestamp) left-joins the latest weather and generation-mix reading per region (BoM/OpenElectricity report on independent cadences that don't line up with AEMO's 5-min dispatch — an exact-match join left ~83% of rows null, confirmed against real data), plus `lag_1d`/`lag_7d`/`roll_7d` demand features |
| `fct_energy_demand` | mart | `= int_demand_with_weather`, table-materialized. **This is what `ml/data.py`'s `load_training_data` and `ml/incremental.py` read** — the single source of training data for the LSTM/TFT models |
| `fct_generation_mix` | mart | Hourly generation + emissions by fuel type per region — backs `GET /v1/generation-mix` and the dashboard's "Emissions by Source" breakdown |
| `fct_carbon_intensity` | mart | Hourly, generation-weighted carbon intensity per region, pre-aggregated so `/v1/footprint` doesn't re-weight raw rows per request; carries both the `live_mix_weighted` and `live_provider` intensities from `int_carbon_intensity` |
| `fct_emissions_5min` | mart | Row-level carbon intensity + emissions, one row per `(ts, network_code, region)` at OpenElectricity's own reporting cadence (name is historical — WEM rows land here too, at WEM's real 30-min cadence, not literally every 5 minutes) |
| `dim_energy_mix` | mart | Fuel-type reference dimension — straight from `seeds/emissions_factors.csv`, with a renewable/fossil/storage classification |
| `dim_facility` | mart | Region/network dimension standing in for a true per-generator facility table — **honestly scoped**: none of the 5 ingestion sources report at individual-generator granularity, so this is one row per `(network_code, region)`, the finest real granularity actually available, not a fabricated per-power-station table |

`raw.aemo_holidays` has a staging model but isn't referenced by any
mart above — it's joined in later, at feature-build time
(`ml/features.py`'s `build_features` via `ml/data.py`'s
`load_holidays`), not inside the dbt DAG.

### `analytics.*` — a legacy schema, not part of this DAG

`analytics.fact_demand_30min`/`fact_generation_30min` (~72K rows,
~20MB) predate dbt entirely — leftover from an original raw → staging →
intermediate → analytics medallion layout (`migrations/0001_init.sql`).
Confirmed unreferenced by any dbt model or app code today. Not touched
by anything described in this file; `TODO.md`'s Storage & Cost
Optimization plan is where the decision to finally archive-and-drop it
lives.

---

## What actually triggers a `dbt build`

Nothing runs a build per ingested row. Four real trigger paths, three of
which share one global lock so builds never overlap each other:

| Trigger | `meta._dbt_build_log.trigger` value | Wait behavior | Where |
| :--- | :--- | :--- | :--- |
| Periodic background rebuild | `periodic_watch` | Fail-fast (`max_wait_seconds=0`) — if a build's already running, this tick just skips (logged at `info`, not an error; the in-flight build already covers this tick's freshness need) | `dbt_build_watch.watch_and_build`, a long-running `asyncio.Task` started in `main.py`'s lifespan, every `Settings.dbt_auto_build_interval_seconds` (default **300s / 5 min**) |
| After a backfill completes | `backfill_auto` | Long wait (default 1800s) — nothing user-facing is blocked on it | `datasources.actions.run_backfill_in_background`, after the whole date range has landed in `raw.*` (one build for the range, not per day — see `docs/data/ingestion.md`'s backfill section) |
| Manual "Run now" (dashboard) | `dashboard_manual` | Fail-fast (`max_wait_seconds=0`) — a real multi-day/backfill build in progress should 409, not hold the HTTP request open | `POST /v1/ingestion/dbt-warehouse/build` |
| Arbitrary admin CLI passthrough | `admin_api` (own log path, doesn't take the shared lock) | N/A — not serialized against the other three | `POST /v1/dbt/{subcommand}` |

**Why a global lock at all**: two `dbt build` invocations against the
same `--project-dir`/mart tables can race destructively — only one may
run at a time regardless of who triggered it (`pipeline.dbt_build.
run_dbt_build_locked`, Redis key `dbt:build:lock`, `nx=True` + a
1800s TTL as a dead-lock safety net).

**What's still not logged to `meta._dbt_build_log`** (honest gap, not
silently claimed as covered): the Prefect `dbt-build` task
(`pipeline.flows`, not currently a deployed schedule — see
`docs/data/ingestion.md`'s sibling notes on aspirational-vs-built) and
the bare `ecolens-pipeline dbt {build,run,test}` CLI commands both call
`dbt_runner.run_dbt` directly, outside any of the four paths above.

---

## APIs

### `POST /v1/ingestion/dbt-warehouse/build`

The one real, immediate way to fix "a backfill's raw rows never reached
`raw_marts.*`" without shelling into a CLI. **Deliberately open** (no
auth) and **fixed** — always `dbt build`, no subcommand choice, no
`extra_args` — unlike `/v1/dbt/{subcommand}` below, which is why it
doesn't inherit that route's admin gate: a fixed no-args build is a much
smaller attack surface than arbitrary CLI-args passthrough. Synchronous,
not backgrounded — a build here typically finishes in well under a
minute, so returning the real exit code directly is simpler than a
202+poll shape.

```jsonc
// 200 response (DbtRunResponse)
{ "subcommand": "build", "target": "prod", "exit_code": 0 }
```

`409 dbt_build_in_progress` if the global lock is already held by
another build.

### `POST /v1/dbt/{subcommand}`

`{subcommand}` is `build`, `run`, or `test`. **Admin-gated** (JWT,
`require_roles("admin")`) — this runs arbitrary dbt subcommands
(`extra_args` passthrough) against the warehouse, a materially bigger
surface than the fixed build endpoint above. Does *not* go through the
global build lock (that lock exists to serialize whole-`build` runs
against each other specifically; this route's `run`/`test`/arbitrary-args
use doesn't fit that shape) — logged directly to `meta._dbt_build_log`
instead (`trigger="admin_api"`).

```jsonc
// request body (DbtRunRequest, all optional)
{ "target": null, "extra_args": [] }
```

```jsonc
// 200 response (DbtRunResponse)
{ "subcommand": "build", "target": "prod", "exit_code": 0 }
```

`500 internal` if the dbt subprocess exits non-zero.

### `GET /v1/dbt/runs`

Open (read access isn't the privileged part — running arbitrary dbt
subcommands is). Real `meta._dbt_build_log` history, `limit` up to 200.

```jsonc
// 200 response (DbtBuildRunsListResponse)
{
  "data": [
    {
      "id": "...", "subcommand": "build", "target": "prod",
      "trigger": "periodic_watch", "triggered_by": "scheduler",
      "status": "success", "started_at": "...", "finished_at": "...",
      "exit_code": 0, "error": null
    }
  ]
}
```

### CLI equivalent

```bash
ecolens-pipeline dbt build [--target prod] [extra_args...]
ecolens-pipeline dbt run   [--target prod] [extra_args...]
ecolens-pipeline dbt test  [--target prod] [extra_args...]
```

Calls `dbt_runner.run_dbt` directly (same function every API path above
uses under the hood — subprocess `dbt <subcommand> --project-dir ...
--profiles-dir ... --target ...`) — but, per the gap noted above, does
**not** write to `meta._dbt_build_log`.

---

## Where to look next

- **A specific source's rows never reached `raw.*`** —
  `docs/data/ingestion.md`'s Stage-1-equivalent detail (staging,
  publish, sync) and `pipeline/tasks/task.md`'s failure-mode playbook
  (mode 4, "S3 succeeded, Postgres failed" — read "DuckDB" for "S3" in
  that doc's stale terminology, the recovery shape is the same).
- **A mart looks stale** — check `GET /v1/dbt/runs` for the last
  successful build and its trigger; if `periodic_watch` hasn't run
  recently, check `dbt_build_watch`'s background task is actually alive
  (`main.py`'s lifespan).
- **What happens to this warehouse's storage footprint over time** —
  `TODO.md`'s Storage & Cost Optimization section (Neon retention policy
  via the hypertables described above, plus the plan to archive
  `analytics.*`).
- **How `fct_energy_demand` gets used** — `todo-model-training.md`.
