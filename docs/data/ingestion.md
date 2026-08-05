# Ingestion Pipeline

How ecoLens pulls raw energy/weather data from external providers into
Postgres, what each source's real fetch behavior actually is, and the
APIs that trigger and observe it. Verified against the live code in
`services/data-pipeline/app/` on 2026-08-05 — not the older
`pipeline/tasks/task.md` (same directory), which describes a previous
architecture generation (S3/MinIO landing, a `src/ecolens` package
layout) this codebase has since moved past. Treat *this* file as source
of truth for the ingestion layer; `task.md`'s still-useful part is its
"6 common failure modes" recovery playbook, which is operationally still
roughly right even though its file paths/specifics are stale.

Companion docs: `overview.md` (product-level architecture pitch, also
somewhat aspirational/ahead of what's built in places — this file is the
grounded version for ingestion specifically), `TODO.md`'s Storage & Cost
Optimization section (what happens to this data after it lands),
`todo-model-training.md` (how the marts this pipeline feeds get used for
training).

---

## The 5 data sources

One row per `app.service.pipeline.tasks.registry.SOURCES` entry — the
single lookup both the API and CLI share. `registry key` is what you
pass to `POST /v1/data-sources/{id}/run`'s `{id}` (as `ds-{key}`) and to
`ecolens-pipeline ingest {key}`.

| Registry key | Source (`meta._ingest_log.source`) | Lands in | Regions | Auth | Documented cadence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `oe` | `openelectricity` | `raw.openelectricity_mix` | NSW1, QLD1, VIC1, SA1, TAS1 (NEM, per-region), WEM | API key (`OE_API_KEY`) | Every 5 min |
| `aemo-nem` | `aemo_nem` | `raw.aemo_nem_dispatch` | NSW1, QLD1, VIC1, SA1, TAS1 | None | Every 15 min |
| `aemo-wem` | `aemo_wem` | `raw.aemo_wem_dispatch` | WEM | None | Every 15 min |
| `bom` | `bom` | `raw.bom_observations` | One BoM station per region + WEM (6 total) | API key (optional; anonymous works, rate-limited) | Every 30 min |
| `holidays` | `aemo_holidays` | `raw.aemo_holidays` | All 6 | None | Once a year (Jan 2, 01:00 UTC) |

Cadences above come from `app/models/datasources.py`'s static catalog,
itself copied from the real `.github/workflows/ingest-*.yml` cron
strings (all UTC) — that's the production schedule. A local dev box's
crontab may instead run all 5 together on a coarser interval (e.g. every
15 min via a single `make ingest-all`-style script) — that's a
convenience, not the documented per-source cadence.

### What's actually real vs. fallback, per source

This is the part worth reading closely before assuming every source
behaves like the others — they don't.

**`oe` (OpenElectricity)** — the one source with no fallback tiers at
all. Every fetch (`lookback_minutes` *and* the `start`/`end` historical
path) is a real, live call through the official `openelectricity` SDK,
region-scoped (`network_region=`, one request per entry in `_NETWORKS`:
5 NEM regions + WEM), merged with a real emissions-intensity fetch
(`fetch_emissions`) to compute `intensity_kg_per_mwh`. If a region's
call fails, that region is skipped and logged (`oe.region_failed`) —
the run still succeeds if at least one region lands. Historical/backfill
fetches are day-chunked deliberately (the SDK's own `to_records()` is
O(n²) in point count — a multi-day, 6-region query is dramatically
slower than N single-day ones).

**`aemo-nem` / `aemo-wem`** — near-real-time fetches (`lookback_minutes`,
no `start`/`end`) go through a 3-tier fallback: **live API → cached
CSV → synthetic stub**. The "live" tier for *this* path
(`_try_live_api`) is a placeholder that never actually parses a
response — it always returns `None`, so in practice every near-real-time
NEM/WEM fetch falls through to the cached-CSV tier (`/data/raw/aemo/
{nem,wem}/`) or, if that directory is missing/empty, a small
deterministic synthetic stub (clearly not for production use). **The
historical path is different and genuinely real**: passing `start`/`end`
(what `POST .../backfill` and `pipeline.backfill` always do) routes to
`_fetch_historical_range`, verified live against AEMO's real public
Archive/data portal (NEMWeb's `Reports/ARCHIVE/DispatchIS_Reports/`
for NEM, `data.wa.aemo.com.au/public/market-data/wemde/` for WEM) — no
placeholder involved there.

**`bom`** — the live tier (`_try_live_api`) is genuinely real: a live
`httpx` call per station to `bom.gov.au/fwo/{station_id}/
observations.json`. Falls back to cached CSV, then a synthetic stub with
a diurnal temperature pattern, same shape as AEMO's fallback chain. BoM's
own public API only exposes a rolling ~72h window with no date-range
query — so the historical/backfill path (`start`/`end`) doesn't reuse
`_try_live_api` at all; it sources real historical weather from
Open-Meteo's ERA5 reanalysis archive instead (verified live before this
was wired in).

**`holidays`** — not a time-series ingest. A once-a-year, in-memory
build of a `(region, date, holiday_name, is_workday)` table from a
static list in code (`_BASE_HOLIDAYS`), no HTTP call at all.

### Circuit breaker

Every source's fetch runs through a Redis-backed circuit breaker
(`app/db/redis.get_breaker(source)`, state in `app/service/pipeline/
circuit_breaker.py`) — state lives in Redis, not process memory, so a
breaker tripped by one process (an API worker, a cron-triggered CLI
call) is honoured by every other process. Real defaults
(`Settings.circuit_breaker_failure_threshold`/`_reset_timeout`):
**5 consecutive failures** opens it; after **60 seconds** it goes
`half_open` (one trial call — success closes it, failure reopens it).
`POST /v1/data-sources/{id}/run`'s `force: true` bypasses the breaker
entirely for that one call (still doesn't count as a breaker
success/failure either way).

---

## Pipeline architecture — from `run()` to a Postgres row

Every ingest task exports one `async def run(...) -> pd.DataFrame`
coroutine (fetch logic only — the shared plumbing below is not
duplicated per-source). `run_source(key, triggered_by=...)`
(`registry.py`) is the one call site both the API and CLI go through; it
applies `_common.standard_run` to whichever task's `run()` the registry
key resolves to, at call time:

```
POST /v1/data-sources/{id}/run           ecolens-pipeline ingest {key}
  │  (background_tasks.add_task)           │  (asyncio.run)
  └──────────────┬──────────────────────────┘
                 ▼
      registry.run_source(key, triggered_by=...)
                 │
                 ▼
┌───────────────────────────────────────────────────────────────────┐
│ _common.standard_run(source, table)(entry.run)                    │
│                                                                     │
│  1. INSERT meta._ingest_log (status='running')                    │
│  2. breaker.call(fetch_fn, ...)   -- circuit-breaker-wrapped fetch │
│       (bypassed if force=true)                                    │
│  3. anomaly.detect_anomalies(df, source)                          │
│       -- flags rows, never drops them; INSERTs into meta.anomalies│
│  4. duckdb_staging.stage_dataframe(df, table, run_id)             │
│       -- one .duckdb file per run, table always named "landed"    │
│  5. rabbitmq.publish_landed_event({run_id, source, table,         │
│       duckdb_path, rows})   -- durable, persistent-delivery queue │
│  6. UPDATE meta._ingest_log (status='staged', rows_landed=N)      │
│     -- NOT terminal yet; finished_at stays NULL                   │
└───────────────────────────────────────────────────────────────────┘
                 │
                 │  (async, decoupled — a separate long-running consumer)
                 ▼
┌───────────────────────────────────────────────────────────────────┐
│ warehouse_sync.sync_landed_event(payload)                         │
│   (pipeline.warehouse_sync, the RabbitMQ consumer)                │
│                                                                     │
│  1. duckdb_staging.read_staged(duckdb_path)  -- read the DataFrame │
│  2. landing.load_to_postgres(df, table, schema="raw")             │
│       -- asyncpg COPY into a temp table, then                     │
│          INSERT ... ON CONFLICT DO NOTHING into raw.{table}       │
│  3. On success: UPDATE meta._ingest_log (status='success',        │
│       rows_loaded=N, finished_at=now())                           │
│       + duckdb_staging.delete_staged(duckdb_path)                 │
│  4. On failure: UPDATE meta._ingest_log (status='sync_failed')    │
│       -- the .duckdb file is deliberately LEFT on disk as the      │
│          recovery/replay artifact; message is nacked, not acked   │
└───────────────────────────────────────────────────────────────────┘
                 │
                 ▼
        raw.{openelectricity_mix,aemo_nem_dispatch,aemo_wem_dispatch,
             bom_observations,aemo_holidays}   (Postgres, Neon)
                 │
                 ▼           dbt build (separate trigger — pipeline
        raw_marts.fct_energy_demand      flows / manual / dbt-build API)
```

**Why the DuckDB hop instead of loading straight into Postgres**: it
decouples ingestion from warehousing — a short-lived ingest process
doesn't wait on (or fail because of) the warehouse-sync consumer, and
vice versa. It's also the audit/replay artifact: if `sync_landed_event`
fails after staging, the `.duckdb` file survives so a fixed consumer run
can replay it without re-fetching from the upstream API. One `.duckdb`
file per ingest run (not one shared file) — DuckDB only allows a single
read-write connection to a file at a time, and per-run files sidestep
the ingest process and the consumer ever fighting over that lock (see
`pipeline/duckdb_staging.py`'s own docstring). This staging layer is
currently transient — files get deleted once synced; there's no
persistent, ever-growing local archive yet (that's `TODO.md`'s Storage &
Cost Optimization plan, Phase 1/2, not yet built).

**`meta._ingest_log.status` state machine**: `running` → `staged` →
(`success` or `sync_failed`), with `failed` reachable straight from
`running` if the fetch or staging step itself raises (never reaches
staging). `staged`/`running` both leave `finished_at` NULL — "still in
flight." A row stuck in `running` or `staged` well past its source's
normal duration is the signal an operator should look for; it means the
downstream step (staging, or the sync consumer) never completed, not
that the source is merely slow.

**Anomaly detection** (`pipeline/anomaly.py`) never drops or modifies
the fetched DataFrame — it flags rows into `meta.anomalies` alongside
the load. Two signals per configured numeric column (`_NUMERIC_COLUMNS`,
per-source), the worse of the two wins per row: a rule-based
plausible-range check (e.g. `demand_mw` outside `[0, 20000]`,
`price_mwh` outside `[-1000, 17500]`) or missing-value check, and a
per-batch z-score outlier check (`|z| > 3`, only computed when a column
has ≥5 non-null values in that batch). This is a lightweight, self-contained
per-batch check — no historical baseline query, no trained model — not
a claim of a production ML anomaly detector.

**Idempotency**: `raw.*` tables load via `INSERT ... ON CONFLICT DO
NOTHING` against each table's real primary key, so re-running an ingest
(a retry, an overlapping backfill day, a redelivered RabbitMQ message)
never double-counts rows. `meta._ingest_log` gets a new row per attempt
regardless — it's an audit log, not deduplicated.

### Legacy, still-present-but-unused-in-the-hot-path code

`pipeline/landing.py` still has real, tested S3/MinIO, Postgres-blob,
and MongoDB "landing" backends (`land_to_s3`, `land_to_postgres_blob`,
`land_to_mongodb_blob`, dispatched via `Settings.landing_backend`) —
this predates the DuckDB+RabbitMQ design above and is no longer called
by `standard_run`. `load_to_postgres` (the actual `COPY`-then-`INSERT`
loader) is *not* legacy — `warehouse_sync` calls it directly, just from
a different caller than before.

---

## APIs

All under `/v1/data-sources`, on **both** `data-pipeline` (the original)
and `services/ingestion` (ported, `services/ingestion/TODO.md` Phase 1)
— same shape, same `meta.data_sources`/`meta._ingest_log` tables (both
point at the same Postgres instance today), independently deployable.

On `data-pipeline`: `run`/`backfill`/`backfill/status` are deliberately
open — no auth/role gate — triggering an ingestion run isn't treated as
a privileged action in this platform's current scope; list/detail/
health/history/patch endpoints require a real role (`require_roles`).

On `services/ingestion`: **every endpoint is open, no auth required for
now** — the list/detail/health/history/patch endpoints were briefly
gated the same way (`app/core/security.py`, verification-only JWT bearer
auth — never issues tokens, only verifies ones `data-pipeline`'s
`POST /v1/auth/token` or IAM issued), then reverted per an explicit
decision the same day. That module still exists, real and tested, just
not wired into any route right now — re-enabling it later is a
`Depends(require_roles(...))` change, not a re-port.

| Method & path | Purpose | Notes |
| :--- | :--- | :--- |
| `GET /v1/data-sources` | List the catalog + live health/run stats | Filter by `category`/`enabled`/`health`/`search`; sort/paginate |
| `GET /v1/data-sources/{id}` | One source's full detail | |
| `PATCH /v1/data-sources/{id}` | Edit `schedule.cron`/`timezone`/`enabled`, `description`, `auth.type`, `metadata` | Admin-only; `If-Match` header for optimistic concurrency |
| `POST /v1/data-sources/{id}/run` | Trigger one immediate fetch | `202`, backgrounded; see below |
| `POST /v1/data-sources/{id}/backfill` | Trigger a date-range backfill | `202`, backgrounded; see below |
| `GET /v1/data-sources/{id}/backfill/status` | Is a backfill for this source still running (survives a page refresh) | Reads the same `backfill:lock:{id}` Redis key the trigger's 409 check uses |
| `GET /v1/data-sources/{id}/health` | Success rate (1h/24h/7d/30d), p50/p95/p99 duration, circuit breaker detail | |
| `GET /v1/data-sources/{id}/history` | Paginated run history | Filter by `status`/`from`/`to` |

`{id}` is the catalog id, e.g. `ds-oe`, `ds-aemo-nem`, `ds-aemo-wem`,
`ds-bom`, `ds-holidays` (`app/models/datasources.py`'s `CATALOG`) — not
the bare registry key.

### `POST /v1/data-sources/{id}/run`

```jsonc
// request body (RunRequest, all optional)
{ "force": false, "deduplicate": true }
```

`force: true` bypasses the circuit breaker for this one call (still
doesn't affect the breaker's own success/failure bookkeeping). An
`Idempotency-Key` header replays the same `202` response for a repeated
call instead of triggering twice. Responds `409 already_running` if
`meta._ingest_log` already has a `running`/`staged` row for this source.

```jsonc
// 202 response (RunTriggerResponse)
{
  "run_id": "run-...", "source_id": "ds-bom", "status": "queued",
  "queued_at": "...", "estimated_start_at": "...",
  "triggered_by": "public", "deduplicate": true, "force": false
}
```

### `POST /v1/data-sources/{id}/backfill`

```jsonc
// request body (BackfillRequest)
{
  "start": "2026-07-01T00:00:00Z", "end": "2026-07-31T00:00:00Z",
  "chunk": "P1D", "concurrency": 1, "deduplicate": true, "skip_dbt": false
}
```

Range capped at 90 days. `chunk` accepts `PT1H`/`P1D`/`P1W` but execution
is always day-granularity regardless — `total_chunks` in the response is
the real inclusive day count `pipeline.backfill.daterange` will process,
not derived from `chunk`'s duration (a chunk-duration division would
silently undercount by 1 whenever the range spans N full days). Responds
`409 backfill_in_progress` if one's already running for this source.

```jsonc
// 202 response (BackfillTriggerResponse)
{
  "backfill_id": "bf-...", "source_id": "ds-oe", "status": "queued",
  "start": "...", "end": "...", "chunk": "P1D", "concurrency": 1,
  "total_chunks": 31, "estimated_duration_seconds": 1860,
  "triggered_by": "public", "progress_url": "/v1/ingestion/runs?backfill_id=bf-..."
}
```

Backfill processes one `(source, day)` pair at a time, sequentially
(`pipeline.backfill.backfill_day` — see below), skipping any day that
already has a `success`/`staged` row in `meta._ingest_log` for that
source (idempotent re-runs). `holidays` is excluded from
`BACKFILLABLE_SOURCES` — it's an annual snapshot, not a per-day series.
Runs one `dbt build` after the whole range completes (unless
`skip_dbt: true`) so the new rows are reflected in `raw_marts.*`
afterward — not per day, which would race dozens of times.

### CLI equivalent

```bash
ecolens-pipeline ingest oe        [--lookback-minutes N] [--triggered-by manual]
ecolens-pipeline ingest aemo-nem  [--lookback-minutes N] [--triggered-by manual]
ecolens-pipeline ingest aemo-wem  [--lookback-minutes N] [--triggered-by manual]
ecolens-pipeline ingest bom       [--lookback-minutes N] [--triggered-by manual]
ecolens-pipeline ingest holidays  [--year YYYY]           [--triggered-by manual]
```

Same `run_source()` call the API uses underneath — one code path from
either trigger surface to a row in `meta._ingest_log`. There's also a
standalone backfill script, `scripts/backfill.py`, for the same
day-by-day catch-up outside the API (see `pipeline/tasks/task.md`'s
"failure mode 6" for its exact flags — that part of the doc is still
accurate even though the storage-layer specifics elsewhere in it aren't).

---

## Where to look next

- **A specific run failed or is stuck** — `pipeline/tasks/task.md`'s
  "🔥 Failure Modes & Recovery" section has the triage queries and
  recovery playbook; its diagnosis steps hold up even though its
  architecture description (S3 landing) predates the current DuckDB
  design above.
- **What happens to this data after it lands in `raw.*`** — dbt builds
  (`dbt/ecolens/models/`), then `TODO.md`'s Storage & Cost Optimization
  section for the Neon-retention/local-DuckDB-archive plan.
- **How the resulting marts feed model training** —
  `todo-model-training.md`.
