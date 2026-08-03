# ecoLens Data-Pipeline — Ingest Files Reference

> **File:** `task.md`
> **Purpose:** Single-page reference for the file-level structure of the
> ingestion layer. Answers "which file fetches and stores data?" and
> walks through the call chain.

---

## The 5 fetch-and-store files

All live in `services/data-pipeline/src/ecolens/pipeline/tasks/`:

| File | Source | Granularity | Region(s) | Lands in | Cron cadence |
|---|---|---|---|---|---|
| **`ingest_openelectricity.py`** | OpenElectricity SDK | 5-min (NEM) / 30-min (WEM) | NSW1, QLD1, VIC1, SA1, TAS1, WEM | `raw.openelectricity_mix` | every 5 min |
| **`ingest_aemo_nem.py`** | AEMO NEM dispatch | 5-min → 30-min resampled | NSW1, QLD1, VIC1, SA1, TAS1 | `raw.aemo_nem_dispatch` | every 15 min |
| **`ingest_aemo_wem.py`** | AEMO WEM (SWIS) | 30-min | WEM | `raw.aemo_wem_dispatch` | every 15 min |
| **`ingest_bom.py`** | Bureau of Meteorology | 30-min | 6 stations (one per region) | `raw.bom_observations` | every 30 min |
| **`ingest_holidays.py`** | AEMO calendar | annual snapshot | All 6 regions | `raw.aemo_holidays` | once a year |

Each file exports a `run(...)` coroutine. **That `run()` is the single entry point** that everything else calls.

---

## The 3-layer data flow

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 1:  pipeline/tasks/ingest_<source>.py   (5 files)           │
│    run()  ── fetch the data, return pandas.DataFrame               │
│           ──► @standard_run decorator                             │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 2:  pipeline/tasks/_common.py              (1 file)         │
│    @standard_run(source, table, s3_key_prefix) ── decorator       │
│      ├─ writes start row to meta._ingest_log                      │
│      ├─ wraps fetch in get_breaker(source).call(...)              │
│      └─ calls landing.land_and_load(df, table, …)                 │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 3:  pipeline/landing.py                    (1 file)         │
│    land_to_s3(key, body)             ── puts Parquet to MinIO     │
│    load_to_postgres(df, table, …)    ── asyncpg COPY FROM STDIN   │
│    land_and_load(df, table, …)       ── both in one call          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                  ┌───────────────────────────┐
                  │  s3://ecolens/raw/...     │  (Parquet landing)
                  │  raw.*  tables            │  (Postgres warehouse)
                  │  meta._ingest_log         │  (run audit)
                  └───────────────────────────┘
```

**Read it top-to-bottom:** each ingest task is 50–80 lines of source-specific fetch code. Everything else (S3, Postgres, logging, metrics, circuit breaker) is shared via the decorator in `_common.py` and the helper in `landing.py`.

---

## Layer 1 — the 5 ingest files in detail

### `ingest_openelectricity.py`

- **Imports:** `app.service.emissions.fetch_network_data`
- **Fetch strategy:** `openelectricity.OpenElectricity().get_network_data(...)` (the SDK)
- **Pivots long-form** (`ts, fuel_type, value`) → **wide-form** matching `raw.openelectricity_mix` columns
- **Fuel mapping:** OE uses `'coal'`, `'ccgt'`, `'solar_utility'`, etc.; we map to `coal_mw`, `gas_mw`, `solar_utility_mw` etc.
- **One region failing ≠ run fails:** the decorator records success if at least one region lands
- **Wrapped by `@standard_run("openelectricity", "openelectricity_mix", "raw/openelectricity")`**

### `ingest_aemo_nem.py`

- **Imports:** `httpx` (no clean async SDK for AEMO NEM)
- **Fetch strategy (3-tier fallback):**
  1. Live API call to AEMO NEMWeb → if it works, return parsed df
  2. Cached CSVs at `/data/raw/aemo/nem/{region}.csv` → read + filter to lookback
  3. Synthetic stub (deterministic per-region demand via `numpy.random.default_rng`) → only for dev
- **5 regions hard-coded** in the `REGIONS` tuple at the top
- **Wrapped by `@timed("aemo_nem")`** (just the timing histogram — does not use `standard_run` because of the 3-tier fallback)

### `ingest_aemo_wem.py`

- Same 3-tier fallback as NEM, but for the WEM data portal
- **Single region:** `'WEM'`
- Default values: ~2500 MW mean demand, 900 MW coal, 1100 MW gas
- **Wrapped by `@timed("aemo_wem")`**

### `ingest_bom.py`

- **Imports:** `httpx`, station IDs from `settings.bom_stations`
- **Fetch strategy (3-tier fallback, same as AEMO):**
  1. Live BoM JSON at `http://www.bom.gov.au/fwo/{station_id}/observations.json`
  2. Cached CSVs at `/data/raw/bom/*.csv`
  3. Synthetic stub with diurnal temperature patterns
- **6 stations:** NSW1=066037, QLD1=040913, VIC1=086282, SA1=023034, TAS1=094029, WEM=009225
- **Wrapped by `@timed("bom")`**

### `ingest_holidays.py`

- **Annual snapshot**, not a time-series — only the `REGIONS` × holidays table
- Builds a `pandas.DataFrame` of (date, region, holiday_name, is_workday) in memory
- No HTTP call (the static list lives in the code as `_BASE_HOLIDAYS`)
- **Wrapped by `@timed("aemo_holidays")`**

---

## Layer 2 — the shared decorator

**File:** `pipeline/tasks/_common.py`

```python
def standard_run(source, table, s3_key_prefix):
    """Decorator factory: standardise the run-start / fetch / land+load / finish lifecycle."""
    def decorator(fetch_fn):
        @functools.wraps(fetch_fn)
        async def wrapper(*args, **kwargs):
            run_id = await _log_run_start(source, ...)      # meta._ingest_log row
            breaker = get_breaker(source)
            try:
                df = await breaker.call(fetch_fn, ...)      # circuit breaker
                async with get_session() as session:
                    s3_uri, rows = await land_and_load(
                        session, df, table, s3_key_prefix=s3_key_prefix)
                await _log_run_finish(run_id, status="success", rows_loaded=rows, ...)
                ingest_rows_total.labels(source=source).inc(len(df))
                latest_ingest_ts.labels(source=source).set(time.time())
                return rows
            except Exception as e:
                await _log_run_finish(run_id, status="failed", error_message=str(e), ...)
                ingest_failures_total.labels(source=source).inc()
                raise
        return wrapper
    return decorator
```

**Why the decorator:** every ingest does the same 4 things (start log → fetch → land+load → finish log). Writing that 4 times is 4× the code and 4× the bug surface. The decorator turns each task into a 30-line "how do I fetch this?" file.

**Why only some tasks use `standard_run`:** the AEMO and BoM tasks have 3-tier fetch fallbacks (live → cache → stub), so they use just `@timed(...)` (the metrics histogram) and handle the rest themselves. OpenElectricity always succeeds (or raises) cleanly, so it gets the full decorator.

---

## Layer 3 — the actual storage

**File:** `pipeline/landing.py`

| Function | What it does | Where the data goes |
|---|---|---|
| `land_to_s3(key, body, bucket=None)` | `boto3.put_object(...)` | `s3://ecolens/raw/{source}/run={uuid}/data.parquet` |
| `load_to_postgres(session, df, table, schema="raw")` | `asyncpg.copy_to_table(format="csv", null=r"\N")` | `{schema}.{table}` (e.g. `raw.bom_observations`) |
| `land_and_load(session, df, table, s3_key_prefix, …)` | both, in one call | both, in one transaction |
| `df_to_parquet_bytes(df)` | serialise to in-memory Parquet | (utility, used by `land_and_load`) |
| `s3_get_bytes(key, bucket)` | download a single object from S3 | (test helper) |
| `list_s3_keys(prefix, bucket)` | iterate objects under a prefix | (backfill helper) |
| `ping(session)` | `SELECT 1` health check | (readiness probe) |

**Why `COPY FROM STDIN` instead of `INSERT`:** 100× faster on bulk loads. asyncpg's `copy_to_table` is the standard pattern.

**Why Parquet to S3 at all (not just Postgres):** the S3 copy is your **audit trail**. If Postgres has a row but S3 doesn't, someone ran a manual `INSERT`. If S3 has the Parquet, you can replay the data into Postgres anytime (use `s3_get_bytes` + `load_to_postgres`).

---

## Trigger files (do not fetch, but start the run)

| File | Role | How it calls the ingest |
|---|---|---|
| `api/routers/ingest.py` | `POST /v1/ingest/{source}` | `await run(lookback_minutes=body.lookback_minutes)` |
| `cli.py` | `ecolens-pipeline ingest {source}` | `asyncio.run(run())` |
| `api/routers/ingest.py` | `GET /v1/ingest/runs` | reads `meta._ingest_log` (no fetch) |

Both surfaces call the **exact same** `run()` function. There is one code path from "trigger" to "row in Postgres".

---

## End-to-end call trace (one BoM ingest)

```
14:30:00  cron fires `*/30 * * * *  ... ecolens-pipeline ingest bom`
14:30:00  └─► docker exec into data-pipeline container
14:30:00      └─► cli.py: asyncio.run(ingest_bom.run())
14:30:00          └─► ingest_bom.py: @timed("bom") wraps run()
14:30:00              └─► run() body: try httpx → fall back to cached CSV → fall back to stub
14:30:01              └─► returns pd.DataFrame (288 rows, 6 stations × 48 half-hours)
14:30:01          └─► @timed exits, Histogram.observe(1.234)
14:30:01      └─► cli.py: process exits with code 0
14:30:01  cron logs exit 0 → next run in 30 minutes

Meanwhile, inside the same call, _common.py's standard_run did:
14:30:00.100  INSERT INTO meta._ingest_log (id=…, source='bom', status='running', …)
14:30:00.500  asyncio.to_thread(land_to_s3(...))  → s3://ecolens/raw/bom/run=abc123/data.parquet
14:30:00.900  asyncpg.copy_to_table('raw.bom_observations', …)  → 288 rows
14:30:00.950  UPDATE meta._ingest_log SET status='success', rows_loaded=288 WHERE id=…
```

---

## 🔥 Failure Modes & Recovery

Cron is fragile. AEMO goes down. Postgres runs out of disk. Docker restarts mid-ingest. **This section is the playbook for when things break.**

### Quick triage — is the pipeline healthy right now?

```bash
# 1. When did each source last succeed?
PGPASSWORD=ecolens psql -h localhost -U ecolens -d ecolens -c "
  SELECT source,
         max(finished_at) AS last_success,
         extract(epoch FROM now() - max(finished_at))::int AS seconds_ago
  FROM meta._ingest_log
  WHERE status = 'success'
  GROUP BY source
  ORDER BY last_success DESC NULLS LAST;
"

# 2. What's currently failing?
PGPASSWORD=ecolens psql -h localhost -U ecolens -d ecolens -c "
  SELECT source, started_at, status, error_message
  FROM meta._ingest_log
  WHERE status != 'success'
    AND started_at > now() - interval '6 hours'
  ORDER BY started_at DESC
  LIMIT 20;
"

# 3. Are any circuit breakers open?
for k in $(redis-cli KEYS 'ecolens:circuit_breaker:*'); do
  echo "$k → $(redis-cli GET $k)"
done

# 4. The one-call health check
curl -s http://localhost:8001/v1/readyz | jq
curl -s http://localhost:8001/v1/ops/status | jq '.last_ingest_per_source'
```

A healthy stack shows every source's `last_success` within the last cron interval (≤30 min for BoM, ≤5 min for OE, etc.). Anything older than 2× the interval is a problem.

---

### The 6 common failure modes

#### 1. Cron didn't fire (host crashed, scheduler died)

**Symptom:** `last_success` for some source is much older than its cron interval. No `meta._ingest_log` rows in the gap.

**Cause:** host reboot, `cron` daemon not running, `systemd` unit failed.

**Fix:**
```bash
# Did cron actually run? Check the host's cron log
ssh app@diptuverse.com 'journalctl -u cron --since "2 hours ago" | tail -30'

# Force a catch-up: re-run each source manually with a wide lookback
for src in oe aemo-nem aemo-wem bom; do
    docker compose exec -T data-pipeline ecolens-pipeline ingest $src
done

# OR use the API (no docker exec needed)
for src in oe aemo-nem aemo-wem bom; do
    curl -s -X POST "http://localhost:8001/v1/ingest/$src" | jq -c .
done
```

**Data loss:** depends on the upstream's retention. AEMO keeps years; BoM free tier keeps 7 days; OE depends on the API. The wider your lookback when you catch up, the more you recover.

**Preventative:** add a Prometheus alert `time() - ecolens_latest_ingest_ts_seconds{source="oe"} > 900` (fired if OE hasn't run in 15 min). Plus a systemd watchdog that restarts `cron` if it dies.

---

#### 2. Ingest task raised an exception (AEMO down, network blip)

**Symptom:** `meta._ingest_log` has a row with `status='failed'` and a non-null `error_message`.

**Cause:** the `run()` coroutine raised. Common cases:
- `httpx.ConnectError` — upstream unreachable
- `asyncpg.PostgresError` — DB connection lost
- `boto3.exceptions.EndpointConnectionError` — MinIO down
- `KeyError` / `ValueError` — upstream changed its schema

**Fix:**
```bash
# Read the error message
psql -c "SELECT error_message FROM meta._ingest_log WHERE status='failed' ORDER BY started_at DESC LIMIT 1;"

# Once you've identified the cause:
#   (a) Transient (network, upstream blip): just wait — the circuit breaker will reset
#   (b) Persistent (upstream changed): patch the ingest task, redeploy, re-run
#   (c) Our bug: same — fix and re-run

# Manual re-run after the fix
curl -s -X POST http://localhost:8001/v1/ingest/oe | jq
# or
docker compose exec -T data-pipeline ecolens-pipeline ingest oe
```

**Data loss:** zero if the failure was inside `run()` (no rows were written). Partial if it was inside `land_and_load` — see mode 4.

**Preventative:** the **circuit breaker** trips after 3 consecutive failures. While open, `breaker.call()` raises `CircuitOpenError` immediately (no 30-second timeout per attempt). After 5 minutes it goes `half_open`; one success closes it.

---

#### 3. Circuit breaker is open (a flaky upstream)

**Symptom:** `meta._ingest_log` shows `circuit_breaker_state='open'`. The cron job runs every 5 minutes but every row is `status='failed'` with error `"Circuit 'aemo_nem' is open; reset in 287s"`.

**Cause:** the same source failed 3 times in a row, so the breaker opened to protect the upstream (and us).

**Fix:**
```bash
# Option A: wait 5 minutes — the breaker auto-resets
sleep 300

# Option B: clear the breaker manually if you've fixed the upstream
redis-cli DEL ecolens:circuit_breaker:aemo_nem
# Then trigger one ingest manually to confirm it works
curl -s -X POST http://localhost:8001/v1/ingest/aemo-nem | jq

# Option C: tune the breaker for a known-flaky upstream
#   In .env or settings:
CIRCUIT_BREAKER_FAILURE_THRESHOLD=10
CIRCUIT_BREAKER_RESET_TIMEOUT=900
```

**Data loss:** the runs during the open window are missed. The next successful run picks up where it left off *only if* you use a wide lookback (see mode 6).

---

#### 4. Partial failure: S3 succeeded, Postgres failed (or vice versa)

**Symptom:** S3 has a new `data.parquet` for `run=abc123` but `meta._ingest_log` says `status='failed'` with `rows_loaded=NULL`. OR: `status='success'`, `rows_loaded=288`, but a later query against `raw.bom_observations` is missing some rows.

**Cause:** the `land_and_load` call is **not transactional** between S3 and Postgres. If Postgres COPY fails after the S3 PUT, the S3 object is the audit trail; you can replay it.

**Fix (S3 ok, PG failed):**
```python
# In a Python shell inside the container:
from app.service.pipeline.landing import s3_get_bytes, load_to_postgres
from app.db.session import get_session
import pandas as pd
import asyncio

async def replay():
    body = s3_get_bytes("raw/bom/run=abc123/data.parquet")
    df = pd.read_parquet(__import__("io").BytesIO(body))
    async with get_session() as session:
        rows = await load_to_postgres(session, df, "bom_observations", schema="raw")
    print(f"replayed {rows} rows")
asyncio.run(replay())
```

**Fix (PG ok, log says failed):** mark the run as success manually:
```sql
UPDATE meta._ingest_log
SET status='success', finished_at=now(), rows_loaded=288
WHERE id='abc123'::uuid;
```

**Data loss:** zero if you replay. The S3 copy is your safety net.

**Preventative:** the design choice is "S3 first, then Postgres, then log" rather than "log first" — so the worst case is "rows in S3 + log says failed" (recoverable) rather than "log says success + no rows anywhere" (catastrophic, requires re-ingest).

---

#### 5. Postgres is down (out of disk, OOM, replica failover)

**Symptom:** all ingests fail with `asyncpg.PostgresConnectionError`. `curl localhost:8001/v1/readyz` returns 503 with `postgres: healthy=false`.

**Cause:** container crashed, disk full, master/replica failover.

**Fix:**
```bash
# 1. Check Postgres itself
docker compose ps postgres
docker compose logs postgres --tail=50

# 2. Free disk if needed
df -h /var/lib/docker
docker system prune -af    # WARNING: removes unused images/volumes

# 3. If Postgres is recoverable, the ingests will auto-retry on the next cron tick
#    (each task catches its own exceptions and the next run picks up)

# 4. If you need to backfill the gap, the backfill script handles it
python scripts/backfill.py --source aemo-nem --from 2026-07-19 --to 2026-07-19

# 5. If Postgres is gone for good and you have a backup:
docker compose stop data-pipeline
docker compose up -d postgres
psql < /var/backups/ecolens/postgres-2026-07-19.sql
docker compose start data-pipeline
```

**Data loss:** depends on the WAL retention. With a daily `pg_dump` to `/var/backups`, max loss is 24 hours. With continuous WAL archiving (set up later), max loss is ~5 min.

**Preventative:** `scripts/cleanup.sh` prunes TimescaleDB chunks older than 18 months to keep disk usage bounded. `scripts/backup-mlflow.sh` runs daily.

---

#### 6. "I missed an ingest" — backfill by date range

**Symptom:** you noticed that some date in the past has no data. The system has been running fine since but a specific day is missing.

**Fix:** use the backfill script. It's idempotent — it skips days that already have a successful run (reads `meta._ingest_log`).

```bash
# Catch up a specific day for all sources
python scripts/backfill.py --from 2026-07-19 --to 2026-07-19

# Catch up a week
python scripts/backfill.py --from 2026-07-13 --to 2026-07-19

# Catch up only the BoM source
python scripts/backfill.py --source bom --from 2026-07-13 --to 2026-07-19

# Catch up only NEM demand (use the lookback-minutes arg)
python scripts/backfill.py --source aemo-nem --from 2026-07-19 --to 2026-07-19 --lookback-minutes 1440
```

The script:
1. Reads `meta._ingest_log` for the date range
2. For each day that doesn't have a `status='success'` row, calls `run(lookback_minutes=1440)`
3. Re-runs the dbt build at the end (so the new rows are visible to downstream)

**Data loss:** zero — the upstream API has the historical data (for the sources with reasonable retention).

---

### The full recovery cheat sheet

| Symptom | First thing to check | Fix |
|---|---|---|
| `last_success` too old | `journalctl -u cron` | Re-run manually + add watchdog |
| `status='failed'` rows | `error_message` column | Fix the cause, then re-run |
| `circuit_breaker_state='open'` | `redis-cli GET ecolens:circuit_breaker:*` | Wait 5 min, or `DEL` it, or tune thresholds |
| S3 ok, PG empty | `psql SELECT count(*)` | Replay from S3 via `load_to_postgres` |
| PG ok, log says failed | `meta._ingest_log` row exists | `UPDATE` the row to `status='success'` |
| All sources down | Postgres + Redis + MinIO health | `curl /v1/readyz`, check each dep |
| Specific date missing | backfill script | `python scripts/backfill.py --from YYYY-MM-DD --to YYYY-MM-DD` |
| S3 bucket empty | S3 health | Re-run from upstream + check IAM |
| MLflow model lost | `backup-mlflow.sh` restore | `cp /var/backups/mlflow-*.db /mlflow/mlflow.db` |
| dbt build failed | `dbt build` output | Fix the broken model, `dbt run --select <model>` |

### Recovery order of operations (canonical playbook)

```bash
# 1. ASSESS (don't change anything yet)
curl -s localhost:8001/v1/ops/status | jq
PGPASSWORD=ecolens psql -c "SELECT source, max(finished_at), status, error_message FROM meta._ingest_log GROUP BY source, status, error_message ORDER BY max DESC;"

# 2. FIX the root cause (network, disk, upstream)

# 3. RESET any stuck state
redis-cli DEL ecolens:circuit_breaker:openelectricity   # if needed

# 4. REPLAY missing data
python scripts/backfill.py --from YYYY-MM-DD --to YYYY-MM-DD

# 5. REBUILD the warehouse so downstream sees the new data
docker compose exec -T data-pipeline ecolens-pipeline dbt build

# 6. VERIFY
curl -s 'localhost:8001/v1/ingest/runs?limit=5' | jq
PGPASSWORD=ecolens psql -c "SELECT count(*) FROM raw.bom_observations WHERE ts > now() - interval '1 hour';"

# 7. POST-MORTEM — write a note in docs/runbooks/incidents/YYYY-MM-DD.md
#    What broke? How long was it down? How much data lost? How long to recover?
#    This builds into the operational knowledge over time.
```

### Idempotency guarantees (the safety net under everything)

| Layer | What makes it idempotent |
|---|---|
| `meta._ingest_log` | One row per run; `id` is a UUID. Re-running creates a new row, doesn't update the old. |
| `raw.*` tables | Primary key `(region, ts)` — re-running a day overwrites the same rows via the COPY. |
| S3 | Keys are unique per run (`run={uuid}/data.parquet`). Re-running never collides. |
| MLflow | Each `train_one` creates a new run; registered versions are immutable. |
| dbt incremental | `unique_key=['region','ts']` — rebuilds only new rows since the last run. |

**Implication:** you can re-run any ingest any number of times safely. The system converges. **When in doubt, re-run.**

### Monitoring you should set up (TODO)

- [ ] Prometheus alert: `time() - ecolens_latest_ingest_ts_seconds > 2 * expected_interval` (fired if a source is late)
- [ ] Grafana panel: ingest success rate by source (last 24h)
- [ ] Grafana panel: circuit breaker states (gauges)
- [ ] Alertmanager → Slack/email on `status='failed'` rows in `meta._ingest_log`
- [ ] Daily `meta._ingest_log` summary to a Slack channel ("24 successful ingests, 0 failed, max latency 2.3s")
- [ ] Weekly backup verification (restore from `/var/backups/` to a test DB)

---

## Tasks to internalise this layer

If you want to deeply understand the ingest files, work through these:

- [ ] Open `pipeline/tasks/ingest_bom.py` and read it top-to-bottom. ~120 lines.
- [ ] Trace the call: `run()` → `standard_run` decorator → `_log_run_start` → `breaker.call` → `land_and_load` → `_log_run_finish`.
- [ ] Read `_common.py` and identify the 4 phases: start log, fetch, land+load, finish log.
- [ ] Read `landing.py` and understand why `copy_to_table` is faster than `executemany`.
- [ ] Compare `ingest_openelectricity.py` (uses `standard_run`) to `ingest_bom.py` (uses just `@timed`). Why?
- [ ] Run `meta._ingest_log` in psql after a few ingests: `SELECT source, status, rows_loaded, duration FROM meta._ingest_log ORDER BY started_at DESC LIMIT 10;`
- [ ] Trigger one ingest via the API: `curl -X POST localhost:8001/v1/ingest/bom`
- [ ] Trigger the same one via the CLI: `ecolens-pipeline ingest bom` — confirm both leave a row in `meta._ingest_log`.

---

## If you had to remember one thing

**Each of the 5 ingest files is the same shape:**
1. A `run()` coroutine
2. Decorated with `@timed(source)` (and possibly `@standard_run(...)` if it doesn't have a 3-tier fallback)
3. That returns a `pandas.DataFrame`
4. Whose columns match a `raw.*` table

The fetch logic is the only thing that changes. Storage, logging, metrics, and circuit-breaking are shared. That's the entire ingest layer in 5 files.
