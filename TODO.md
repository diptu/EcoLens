# TODO's

## Storage
[]store all asstets & art-effects, including model weights on claudeflare R2


# Storage & Cost Optimization — Neon free tier + local DuckDB archive

Goal: stay on Neon's free tier (512MB) **indefinitely** by keeping only a
rolling ~2-month hot window in Postgres, while a persistent local DuckDB
warehouse holds full history — **from 2025-08-01 (the real data start
date across all 5 sources) onward, growing forever after** — for anything
that needs it. Split model training accordingly: **initial/full training
and hyperparameter tuning read from local DuckDB** (unbounded history,
zero Neon cost); **online/incremental training keeps reading from Neon**
(it only ever needs a recent window anyway, so the 2-month cap never
affects it).

Companion docs: `todo-model-training.md` (what each architecture trains
on), the Model Operations section above (`ml/incremental.py`'s trigger
path — unaffected by this plan).

---

### Ground truth (verified against live code + live DB, 2026-08-05)

#### Current state

- Neon project size: **399MB / 512MB** (right after clearing a runaway
  duplicate-anomaly bug this session — see incident note below; was
  489MB before cleanup).
- Real history already spans **~1 full year** per raw source
  (`raw.aemo_nem_dispatch`: 2025-07-31 → today, 528K rows;
  `raw.openelectricity_mix`, `raw.aemo_wem_dispatch`, `raw.bom_observations`
  similar). That entire year fits in ~400MB — i.e. **a 60-day window is
  ~1/6 of that, roughly 65-70MB**, leaving generous headroom under the
  512MB cap even accounting for `meta.anomalies`/`meta._ingest_log`
  operational overhead. No compression tricks needed to make 60 days fit;
  they're a safety margin, not a requirement.
- **Decision: the local DuckDB archive's history starts at `2025-08-01`**
  (not "whatever's in Neon today", and not per-source min timestamp).
  This is a deliberate, slightly-rounded boundary: `aemo_nem_dispatch`
  (2025-07-31 14:05) and `openelectricity_mix` (2025-07-31 08:00) both
  have a partial day of real rows *before* 2025-08-01 that this boundary
  excludes — acceptable (well under a day, across only 2 of the 5
  sources), but call it out explicitly here rather than let Phase 1 drop
  it silently. `aemo_wem_dispatch`/`bom_observations` already start
  exactly at 2025-08-01 00:00, so the boundary is a no-op for those two.
- **5 raw tables are already TimescaleDB hypertables**, 7-day chunks
  (`migrations/0009_hypertables.sql`, `0012_reapply_hypertables_and_indexes.sql`):
  `raw.openelectricity_mix`, `raw.aemo_nem_dispatch`, `raw.aemo_wem_dispatch`,
  `raw.bom_observations`, `raw.aemo_holidays`. The migration was written
  assuming Neon *doesn't* support the `timescaledb` extension (with a
  graceful no-op fallback) — turns out it does on this project; hypertable
  chunks are real and live (`_timescaledb_internal._hyper_*_*_chunk`).
  This matters: **Timescale's `add_retention_policy` drops whole chunks**
  (cheap, no dead-tuple bloat), unlike the row-by-row `DELETE` this
  session had to run by hand today, which left the DB reporting "full"
  until autovacuum caught up.
- `raw_marts.fct_energy_demand` (dbt, `+materialized: table`, i.e. full
  rebuild every `dbt build`) is derived entirely from those 5 raw tables.
  It is **not itself a hypertable** — but because it's a full-refresh
  table, pruning the raw hypertables automatically shrinks it to match on
  the *next* dbt build. No separate mart-pruning logic needed.
- `analytics.fact_demand_30min` / `fact_generation_30min` (~72K rows,
  ~20MB combined): a **leftover schema from the pre-dbt medallion
  architecture** (`0001_init.sql`). Confirmed unreferenced by any dbt
  model or app code today (`0022_drop_unused_schemas.sql`'s own comment
  explicitly deferred this decision). Pure dead weight sitting in the
  512MB budget for nothing.
- `ml.ml_features_demand_v1` (orphaned table, no dbt model/pipeline code
  owns it, `ml/data.py`'s own comment): a full year, 103,734 rows, but
  **66% imputed/synthetic** (`data_quality_status='imputed'`). Already a
  documented fallback data source (`load_ml_features_v1_training_data`),
  not something to build the new archive on top of.
- **Training data sources today (before this plan), all Postgres, no
  DuckDB training path exists at all:**
  - `ml/train.py:725` (`train_and_register`, full LSTM retrain) —
    `load_training_data(db, regions, since=since)`
  - `ml/train_tft.py:373` (full TFT retrain) — same
  - `ml/tune.py:101,250` (`tune_optuna`) — same
  - `ml/incremental.py:191` (`train_and_register_incremental`, the
    online/warm-start path, `incremental_train_window_hours` default
    **24h**) — same call, but always `since=<recent window>`, so it's
    naturally unaffected by a 60-day Neon retention window.
- **DuckDB today is transient staging only** (`pipeline/duckdb_staging.py`):
  one `.duckdb` file per ingest run, deleted once `warehouse_sync` loads
  it into Postgres. It is explicitly *not* a durable archive.
- **Incident this session, still relevant to sizing/safety:** an
  `openelectricity` bug (`_pivot_long_to_wide` sourcing `demand_mw`/
  `price_mwh` from a `fuel_type` that never appears in the SDK's `POWER`
  metric response — fixed in `anomaly.py` by dropping those columns from
  its scan list) caused every OE run to flag ~100% of its batch as
  anomalous, filling `meta.anomalies` with 108,864 duplicate rows/110MB
  across 63 retried runs and pushing Neon over its limit — which then
  wedged every in-flight run in `status='running'` forever (the write
  that would finalize it also failed with `DiskFullError`). Cleaned up
  this session (108,864 rows deleted, 13 stuck runs marked `failed`).
  Separately: **645 orphaned `.duckdb` staging files (330MB)** sit in
  `services/data-pipeline/data/staging/` right now — real fetched data
  (mostly `bom_observations`) that a different bug (`Event loop is
  closed` on the RabbitMQ publish, 701 occurrences) left un-synced and
  un-deleted. Both should feed into Phase 1's backfill below rather than
  being discarded.
- **Unresolved, blocks Phase 2's "keep DuckDB continuously current" until
  fixed:** the machine's crontab (`*/15 * * * *`) actually drives
  ingestion against `/Users/macbook/Project/personal/EcoLens` — a
  **separate, stale clone** of this same repo (6 commits behind, and on
  an entirely different `ecolens.*` package layout, not this repo's
  `app.*`). The `Event loop is closed` bug lives over there, in code this
  plan hasn't touched. Needs its own decision (point the crontab at this
  repo, or treat that clone as intentionally separate) before Phase 2 can
  be trusted to run unattended.

#### Non-negotiable design constraints

- **Never delete from Neon before it's durably archived elsewhere.** The
  one-time historical backfill (Phase 1) must complete and be verified
  *before* any retention policy goes live (Phase 3) — otherwise pruning
  destroys the only copy of anything older than 60 days.
- **Prefer hypertable + `add_retention_policy` over manual `DELETE`**
  wherever the table has a time column — chunk-drop is instant and
  doesn't leave dead tuples needing a manual `VACUUM` (today's incident,
  the hard way).
- **Online/incremental training never changes source.** It stays on
  Neon/`load_training_data` — this plan does not touch
  `ml/incremental.py`'s data path at all, only the full-retrain/tune
  call sites.
- **Every training run logs which storage tier it trained from** (MLflow
  param, matching the existing `data_source` pattern already used for
  `ml_features_v1` vs mart) — so a model version is always auditable
  back to its actual data source.

---

### Phase 1 — One-time historical backfill into local DuckDB (safety net)

Goal: get a verified, full-history copy of everything currently in Neon
onto local disk *before* anything is ever deleted from Postgres.

- [ ] New persistent DuckDB warehouse file (distinct from the transient
      per-run staging files), e.g.
      `services/data-pipeline/data/warehouse/ecolens.duckdb`, with tables
      mirroring `raw.*` (the 5 hypertables) at minimum; `raw_marts.
      fct_energy_demand` optionally, for a query-ready copy (it's fully
      derivable from `raw.*`, so not strictly required).
    - Add `services/data-pipeline/data/warehouse/` to `.gitignore`
      (matches `data/staging/`'s existing treatment).
- [ ] One-off export script (`scripts/export_neon_to_duckdb.py` or a
      `pipeline.warehouse_export` module): read each `raw.*` hypertable
      **`WHERE ts >= '2025-08-01'`** (the decided archive start date
      above) → write/append into the DuckDB file. Chunk the read (e.g. by
      week) rather than one giant query, given `aemo_nem_dispatch` alone
      is 528K rows.
- [ ] **Recover, don't discard, the 330MB of orphaned `.duckdb` staging
      files** found this session (`data/staging/*.duckdb`, mostly
      `bom_observations`) — load them into the same warehouse file before
      deleting them. This is real fetched data that never reached
      Postgres at all; skipping it means a real, avoidable gap in local
      history.
- [ ] Verification step before moving to Phase 2/3: row counts and
      `min(ts)`/`max(ts)` per source must match between Neon and the new
      DuckDB warehouse (modulo the recovered staging files, which should
      make DuckDB's count *higher*, never lower).

**Acceptance:** local DuckDB warehouse has a verified superset of
everything in Neon, including the orphaned staging backlog. Nothing
about this phase changes Neon at all yet.

---

### Phase 2 — Keep the local archive continuously current

Goal: once Phase 1 establishes the baseline, every *future* successful
ingest must land in DuckDB too — not just Postgres — so Neon retention
(Phase 3) is always safe to run.

- [ ] Extend `warehouse_sync.sync_landed_event` (or add a second,
      parallel consumer on the same landing queue) so a successful
      Postgres load also appends/upserts the same batch into the
      persistent DuckDB warehouse from Phase 1. Same idempotency
      expectation as the Postgres path (`ON CONFLICT DO NOTHING`
      equivalent — DuckDB upsert on the natural key).
    - Decide: append-in-`sync_landed_event` (simplest, couples the two
      writes) vs. a fully separate DuckDB-sync consumer reading the same
      RabbitMQ queue (more resilient — a DuckDB write failure can't ever
      block/fail the Postgres sync). **Recommended: separate consumer** —
      matches this codebase's existing "one bad thing shouldn't sink
      everything else" pattern used throughout the ingestion pipeline.
- [ ] **Blocked on, and should not be marked done until:** the stale-clone
      crontab issue above is resolved one way or another — otherwise
      "continuously current" is only true for whichever repo actually has
      cron pointed at it, and this plan's local DuckDB could silently
      drift stale again exactly like the Neon side did.
- [ ] Also fix (or confirm already-fixed-here) the `Event loop is closed`
      RabbitMQ-publish bug — Phase 2 depends on that publish path being
      reliable; today it's dropping ~65% of `bom` batches into orphaned
      staging files instead of ever reaching a consumer.

**Acceptance:** a fresh ingest run for any of the 5 sources shows up in
*both* Neon and the local DuckDB warehouse within the normal sync
latency, with no manual step.

---

### Phase 3 — Enforce the 2-month retention on Neon

Goal: cap Neon at a rolling ~60-day hot window, using chunk-drop
retention (not manual `DELETE`) everywhere possible.

- [ ] `add_retention_policy` on all 5 raw hypertables, `INTERVAL '60
      days'` (new migration, same idempotent/no-op-if-no-timescaledb
      pattern as `0009`/`0012`).
- [ ] Convert `meta.anomalies` (time column `detected_at`) and
      `meta._ingest_log` (time column `started_at`) to hypertables too,
      then `add_retention_policy` the same way — this replaces the manual
      `DELETE` this session had to run by hand (and its dead-tuple
      aftermath) with the same cheap chunk-drop mechanism as `raw.*`.
      Check both for constraints that would block `create_hypertable`
      (a UNIQUE/PK not including the time column) before writing the
      migration — `meta.anomalies.id` is a bare UUID PK, should be fine.
- [ ] `raw_marts.fct_energy_demand` needs no explicit retention — it
      self-truncates to match `raw.*` on the next full-refresh `dbt
      build` (already ground-truthed above). Confirm this is actually
      true post-migration (build once, check row count/date range
      shrank) rather than just trusting the reasoning.
- [ ] **Archive-then-drop `analytics.*`** (the pre-dbt orphan schema,
      ~20MB, 72K rows, confirmed unused by any code): export its rows into
      the Phase 1 DuckDB warehouse (a "why not, it's real historical
      data" copy, not because anything reads it), then `DROP SCHEMA
      analytics CASCADE` — finally closing the decision `0022`'s own
      comment explicitly deferred.
- [ ] Re-measure `pg_database_size` after retention is live and a few
      chunks have actually dropped, to confirm the ~65-70MB back-of-
      envelope estimate above holds in practice, not just in theory.

**Acceptance:** Neon settles at a size that's a small, stable fraction of
512MB going forward, with headroom, and no future manual DELETE/VACUUM
babysitting is required to keep it there.

---

### Phase 4 — Split the model-training data source

Goal: initial/full training and hyperparameter tuning stop depending on
Neon holding more than 60 days of history; online/incremental training is
untouched.

- [ ] New loader in `ml/data.py` (or a sibling `ml/data_duckdb.py`):
      `load_training_data_duckdb(con, regions, since=None)`, same
      `_TRAINING_COLUMNS` output contract as `load_training_data`, reading
      from the Phase 1/2 persistent DuckDB warehouse via the `duckdb`
      Python API instead of an `AsyncSession`.
- [ ] Switch these call sites to the new loader (all **full/initial**
      training and tuning — not incremental):
      - `ml/train.py:725` (`train_and_register`)
      - `ml/train_tft.py:373` (full TFT retrain)
      - `ml/tune.py:101,250` (`tune_optuna`)
- [ ] **Do not touch** `ml/incremental.py:191`
      (`train_and_register_incremental`) — stays on
      `load_training_data(db, ...)` against Neon, per this plan's whole
      premise: online training only ever needs a recent window, which a
      60-day Neon retention always satisfies.
- [ ] Log a `data_source` MLflow param (`"duckdb"` vs `"postgres_marts"`
      vs the existing `"ml_features_v1"`) on every run, matching the
      pattern `load_ml_features_v1_imputed_fraction`'s docstring already
      established — every model version stays auditable back to what it
      actually trained on.
- [ ] Update `todo-model-training.md`'s data-source notes to point at
      this split once implemented (it currently only discusses Postgres
      marts vs. `ml_features_v1`).

**Acceptance:** a full LSTM/TFT retrain or Optuna tuning run succeeds
using only the local DuckDB warehouse, with Neon's retention already
active and older than 60 days — i.e. full-history training keeps working
even though Postgres itself no longer has that history.

---

### Phase 5 — Guardrails so this doesn't silently regress

- [ ] Cheap periodic check on `pg_database_size(current_database())` vs.
      the 512MB cap — a dashboard KPI, a `make db-size` target, or a cron
      alert (any one is enough; this session's whole investigation started
      from there being zero visibility into this until the UI was already
      stuck).
- [ ] Same for the local DuckDB warehouse file size / disk headroom on
      the host, since it's now the durable copy of record for anything
      older than 60 days.
- [ ] Note in this file (or `todo-operational-tasks.md`) once the
      stale-clone crontab question is actually resolved, so it stops
      being an open unknown every time this area gets touched again.

---

### Sizing summary

| Tier | Contents | Retention | Approx. size |
| :--- | :--- | :--- | :--- |
| Neon Postgres (free) | `raw.*` (5 hypertables) + derived marts + `meta.anomalies`/`_ingest_log` | rolling 60 days, chunk-drop | ~65-70MB steady-state (vs. 512MB cap) |
| Local DuckDB | Full history since 2025-08-01, growing forever after | unbounded (local disk) | ~400MB+ today, grows ~1.1MB/day at current volume |

### Suggested implementation order

| Priority | Phase | Why |
| :--- | :--- | :--- |
| P0 | Phase 1 | Nothing else is safe until history is durably copied out of Neon |
| P0 | Phase 3 (blocked on Phase 1) | The actual cost-saving goal — do this as soon as the safety net exists |
| P1 | Phase 4 | Makes Phase 3 actually safe for training, not just for storage cost |
| P1 | Phase 2 | Needed for Phase 3 to stay safe *going forward*, not just for today's backfill |
| P2 | Phase 5 | Prevents a quiet repeat of this session's incident |

### Out of scope here (tracked elsewhere)

- Fixing the `Event loop is closed` RabbitMQ-publish bug itself → belongs
  wherever the actually-cron-driven code lives once the stale-clone
  question (Phase 2) is resolved; this plan only depends on it being
  fixed, doesn't own the fix.
- TimesFM / TFT / blend model architecture work → `todo-model-training.md`
- MLflow becoming a real persistent compose service → Model Operations
  Phase 4 above
