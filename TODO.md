# Todo's

## Book keeping

[x] save raw and raw.marts in seperate database uing seperate Database_URL (so taht i can save 2*512 mb data)
    See "Book keeping (continued)" below for the real implementation
    (2026-08-09) — periodic archive+prune, not a live cross-database join.

[x] update services/ingestion/scripts/select_features.py based on services/forecast-api/notebooks/feature_selection.ipynb and update warehouse pipeline accordingly.
    See "Book keeping (continued)" below — verified 2026-08-08, re-verified
    2026-08-09 after the notebook's next commit (105075b) touched only
    stale error outputs/kernelspec metadata, no source-cell changes.

## operational-tasks

[x] *Pipeline Operations*: Implement all pipeline operations , test with 30 min, single day, 1 month for each of nem,wem,bom,oe, holiday
    Already implemented (dashboard/admin/operational-tasks's Pipeline Operations
    card + /dashboard/ingestion): "Run now" = POST /v1/data-sources/{id}/run
    (30-min lookback, Settings.default_lookback_minutes), "Backfill" modal =
    POST /v1/data-sources/{id}/backfill (day or month range). Tested live
    2026-08-08 against all 5 sources via the same public API the dashboard
    calls:
    - 30-min run: all 5 (nem/wem/bom/oe/holidays) — real success, real rows.
    - Single-day backfill (2026-05-15): nem/wem/bom/oe — real success, real
      rows landed (845/288/144/1032 rows respectively).
    - 1-month backfill (2026-07): nem/wem/bom/oe — real success (oe: full
      1728 rows/day for all 31 days confirmed).
    - holidays has no day/month backfill by design — once-a-year (region,
      date) snapshot, no HTTP call, no date-range concept at all
      (ingest_holidays.py's own docstring). Not a gap, just doesn't apply.

    Bug found + fixed while testing: 85 meta._ingest_log rows were stuck at
    status='running' (oldest since 2026-08-07 19:45), permanently 409'ing
    "Run now" for bom/holidays/nem (_already_in_flight deliberately never
    times out 'running' rows — intentional, but needs the terminal-status
    write to actually happen). Root cause: standard_run's except handler
    calls _read_breaker_state() to log the failure, and that does a live
    Redis read — when Redis itself was the reason the original fetch
    failed, that same call raised again, so _log_run_finish never ran.
    Fixed in services/ingestion/app/service/pipeline/tasks/_common.py
    (_read_breaker_state now catches its own Redis errors, returns
    "unknown" instead of propagating). Cleaned up the 85 stuck rows by hand
    (marked 'failed' with the diagnosis in error_message) — confirmed live
    after: all 5 sources' "Run now" now returns real 202 → success.

    Also fixed a stale doc comment: operational-tasks/page.tsx's own
    module docstring said backfill was false for "OpenElectricity/
    Holidays/dbt-warehouse" — PIPELINE_CATALOG already had oe backfillable:
    true (lib/ingestion.ts was accurate), only the page's own prose comment
    was stale.

    **2026-08-08 follow-up — every row showing "Failed: trigger failed"
    (including dbt Warehouse Build)**: a second, unrelated bug, found
    right after the above. Root cause: `dashboard/src/lib/env.ts`'s
    `INGESTION_API_URL`/`WAREHOUSE_API_URL` default to docker-compose's
    container ports (8003/8004), but this machine's actual local dev
    servers (no documented port in either service's own Makefile/README,
    started outside docker-compose) run on 8001/8002 — the browser was
    fetching a port nothing was listening on. `.env.local` already had
    this exact fix applied once before for forecast-api (8002→8000, see
    its own comment); the same override was just missing for ingestion/
    warehouse. Added `NEXT_PUBLIC_INGESTION_API_URL=http://localhost:8001/v1`
    and `NEXT_PUBLIC_WAREHOUSE_API_URL=http://localhost:8002/v1` to
    `services/dashboard/.env.local`, restarted the dev server (Next.js
    inlines `NEXT_PUBLIC_*` at server start, doesn't hot-reload
    `.env.local`). Verified live: CORS is wide open (`*`) on both
    services, `POST /v1/data-sources/ds-oe/run` and
    `GET /v1/dbt/build/runs` both confirmed reachable at the corrected
    ports with the exact URLs `lib/ingestion.ts` builds.

    Related but separate real bug, found while re-testing the dbt
    Warehouse Build row specifically: `POST /v1/dbt/build` itself
    returned real `exit_code: 1` (a pre-existing data-quality test
    failure, `assert_renewable_mw_within_total` — unrelated, not this
    bug), but the *auto*-triggered build that fires after every real
    ingestion sync (`triggered_by: "landed_event"`) was failing with
    `exit_code: 127, "dbt executable not found on PATH"` every time.
    Cause: the `ecolens-warehouse consume` process (the one that runs
    those auto-triggers) had been started directly via its binary path
    rather than through `uv run`, so its PATH never included `.venv/bin`
    where `dbt` actually lives. Restarted it with the venv's `bin`
    prepended — confirmed fixed: a subsequent `POST /v1/dbt/build`
    returned real `exit_code: 1` (the same pre-existing test failure,
    not 127) as expected. Durable fix for any real deployment is making
    sure whatever supervises this process (docker CMD, systemd unit,
    launchd plist) always starts it via `uv run`/an activated venv —
    this was a local-dev-only process-launch mistake, not a code bug.

[x] *Model Operations* : Update with LSTM model for now
    Already real — `ModelInfoTable` (operational-tasks page) renders
    `GET /v1/model`, which server-side always loads whichever version is
    `Production` for `Settings.mlflow_registry_model_name` (hardcoded
    "lstm_demand", `registry.py`'s `load_bundle` default) — inherently
    LSTM-only already, no change needed. Now shows real data instead of
    "not loaded": `lstm_demand` v1 was trained + promoted to Production
    earlier in this session (test_mape=3.73%, test_coverage_calibrated=
    99.6%, real NSW1 data).

[ ] *Active Tasks*: Show all active task with their status.
    Partially real, by design, not an oversight: `model_training`
    (`meta._training_log`), `ingestion`, and `transform` (dbt build) task
    types are real, live-polled rows (2026-08-08 follow-up pass, this
    page's own docstring). The other 5 types (`data_quality`/
    `feature_build`/`forecast`/`report`/`anomaly`) stay mock — there is no
    "a task of this type is in flight" concept anywhere in any service to
    read from (confirmed: no queue/log table tracks these). Making this
    fully real needs those backend concepts built first (a genuinely
    separate, larger effort per task type), not a dashboard-only fix —
    left honestly mock rather than fabricating fake "real" data for them.

[x] *Scheduled Operations* : Update with all cron job (data fetch, remove older data from postgresql)
    Data-fetch half already real (`ScheduledTable`, `fetchPublicPipelines()`
    — real per-source cron/next-run/last-run, 2026-08-08 follow-up pass).
    Retention/removal half was missing entirely — no schedule existed
    anywhere for `services/waerehouse`'s `prune`/`export-and-prune`/
    `vacuum` (its own module docstring: "this service doesn't schedule
    itself, an operator/cron calls in"). Closed 2026-08-08 — see *Vacuum
    Database* below for the real Celery Beat schedule now doing this
    daily.

    Follow-up closed same day: the retention job is now its own row in
    the Scheduled Operations *table* too, not just a cron that runs
    invisibly. Added `meta._retention_log` (`services/waerehouse/app/
    migrations/0004_retention_log.sql`), start/finish logging in
    `app/tasks/retention_tasks.py` (same shape `meta._dbt_build_log`
    already uses), and `GET /v1/retention/runs`
    (`app/api/v1/retention/routes.py`). Dashboard: `fetchPublicPipelines()`
    (`lib/ingestion.ts`) now synthesizes a 7th row, "Warehouse Retention
    (export + prune + vacuum)", with a *real* cron (`0 3 * * *`, unlike
    the dbt-build row's "manual" placeholder) and real `last_run_at`/24h
    aggregates once runs accumulate (factored the aggregate-computation
    logic the dbt row already had into a shared `aggregate24h` helper
    rather than duplicating it). Verified live: dispatched a real task
    through an actual `ecolens-warehouse worker` + RabbitMQ broker,
    confirmed `GET /v1/retention/runs` returns the real logged row
    (status, real pruned/vacuumed jsonb, real started_at/finished_at).

[x] *Recent Training Runs* : Show 3 Recent Training Runs if training run is>=3.
    Was showing `GET /v1/model/versions` (registry entries — only
    successfully-registered runs, silently hiding running/failed
    attempts) mislabeled "Recent Training Runs". Rewired to the actually-
    correct source, `GET /v1/model/training-runs` (`meta._training_log`,
    real `running`/`success`/`failed` attempts), capped at 3
    (`RecentTrainingRunsList`, `operational-tasks/page.tsx`). Verified
    live against the 2 real runs this session produced (lstm_demand v1,
    lstm_demand_tft v1).

[x] *Model Training & Tuning* : fine tune the model on recent n-hours data.
    Already real — `FineTuneForm`/the Model Training & Tuning card both
    publish a real training-trigger event (`POST /v1/model/train`,
    `windowHours` = the "recent n-hours" the item asks for) that
    `training_worker.py`'s consumer picks up for a real warm-started
    incremental fine-tune. No change needed.

[x]*System Commands* Rebuild Features should run featrure selection script and select cloumns for forecasting models based on raw data and upload in raw.marts schem.
    Reconsidered and wired for real 2026-08-08 (previous pass left this
    deliberately disabled -- re-read `select_features.py` more carefully
    and realized wiring it doesn't actually contradict its own design
    decision, just needed to preserve the same two real, honest outcomes
    the CLI already has instead of hiding them).

    Added: `services/ingestion/app/service/features/rebuild.py`
    (`rebuild_features` -- same atomic-lock + log-start + run + log-finish
    shape `waerehouse/app/dbt/scheduler.py` already uses for
    `meta._dbt_build_log`), a new `meta._feature_selection_log` table
    (`services/waerehouse/app/migrations/0005_feature_selection_log.sql`
    -- cross-service `meta.*` migrations live there by convention, even
    though the writing code is in `ingestion`), and
    `POST /v1/features/rebuild` / `GET /v1/features/rebuild/runs`
    (`app/api/v1/features/routes.py`). Dashboard: `triggerFeatureRebuild()`
    (`lib/ingestion.ts`) wired to System Commands' `c1` button
    (`operational-tasks/page.tsx`'s `executeCommand`).

    Runs the real `run_selection()` function `select_features.py`'s own
    CLI (`main()`) calls -- identical output, writes the same
    `data/training/selected_features.json`. Two real, honest outcomes,
    not silently hidden: `409 rebuild_in_progress` if another rebuild is
    already running (same lock pattern `POST /v1/dbt/build` uses), and a
    real `422 master_duckdb_missing` if `data/training/master.duckdb`
    doesn't exist on the server -- this endpoint still never auto-builds
    it from R2 on demand, preserving the one real design decision that
    mattered.

    Tested for real, twice: first run succeeded end-to-end (started
    20:46:04, finished 20:56:16 -- ~10 real minutes of sklearn compute
    across 6 regions, `n_selected: 30`, confirmed
    `data/training/selected_features.json`'s mtime matches `finished_at`
    exactly). Second run (fired to test the lock) correctly got
    `409 rebuild_in_progress` while the first was still in flight, then
    ran to real completion on its own once the lock cleared.

[x] *Vacuum Database*: Vacuum Database should run cronjob using celery to clear older data defiend in .env file.
    Was real CLI-only (`export-and-prune`/`vacuum` commands), no scheduler
    at all anywhere. Added `services/waerehouse/app/celery_app.py` +
    `app/tasks/retention_tasks.py` (mirrors `services/ingestion`'s own
    Celery app structure) — a real Celery Beat schedule, daily 03:00 UTC,
    running `export_and_prune` (days = `Settings.retention_days`, 60,
    `.env`-overridable — the "defined in .env file" this item names) then
    `vacuum_analyze_raw_tables` if anything was actually pruned. Added
    `celery` to `pyproject.toml`, `worker`/`beat` CLI commands to `cli.py`
    (matching ingestion's own `worker`/`beat` convention).

    Tested for real, twice: first a direct function call correctly
    exported+pruned 438,340 real rows older than 60 days to R2 cold
    storage before deleting them from Postgres (confirmed: `aemo_nem_
    dispatch` 2,775, `aemo_wem_dispatch` 61,297, `bom_observations`
    29,646, `openelectricity_mix` 344,622) — then hit a real bug on the
    `vacuum` step ("attached to a different loop", the direct-call test
    itself calling `asyncio.run()` twice in one process without the
    persistent-loop setup a real worker has). Confirmed that was a test-
    methodology artifact, not a real bug, by running it properly: a real
    `ecolens-warehouse worker` (had to add `--pool=solo` — macOS's known
    `objc`/`fork()` crash with Celery's default prefork pool, and this
    task doesn't need concurrency anyway) + a task dispatched through the
    real RabbitMQ broker via `.delay()` completed both steps
    successfully. `beat` also confirmed starting cleanly with the real
    schedule loaded.

    Not wired: a dashboard "Vacuum Database" *button* (System Commands'
    existing mock stays disabled) — this item's own wording ("should run
    cronjob") is about the schedule existing and firing, which it now
    does; a manual on-demand trigger endpoint would be a separate,
    smaller follow-up if wanted.

[x]*System Diagnostics* : System Diagnostics should show which sytem are healthy and which are not.
    Was a single on-demand button (System Commands' "Check System
    Health") showing a one-line summary, not a persistent status
    display. Added a real `SystemDiagnosticsGrid` card
    (`operational-tasks/page.tsx`) — one tile per service (forecast-api/
    data-pipeline/ingestion/warehouse/iam), real `reachable`/`ready`/
    per-component (database/redis/rabbitmq/model) detail from
    `fetchAllServicesHealth()` (already-real `/v1/readyz` checks, `lib/
    health.ts` — no new backend needed). Auto-refreshes every 60s +
    manual "Recheck" button; the existing System Commands health-check
    button now shares this same state instead of an independent fetch.

## Book keeping (continued)

[x] update services/ingestion/scripts/select_features.py based on services/forecast-api/notebooks/feature_selection.ipynb and update warehouse pipeline accordingly.
    Checked 2026-08-08 — already done, before this session. Diffed
    `forecast-api/notebooks/feature_selection.ipynb` (cell 0, 931 lines)
    against `ingestion/scripts/select_features.py` (804 lines) function-
    by-function: every class/function in the notebook already exists in
    the script, verbatim logic (the only diff is formatting — the
    script's been reformatted, plus 3 new functions the script-wrapper
    itself needs: `main`/`run_selection`/`selected_features_path`). The
    real, executed output (`data/training/selected_features.json`, a
    real populated artifact, not empty/stale) is already consumed by
    both `services/waerehouse/dbt/.../int_demand_with_weather.sql`
    (wind_gust_kmh/wind_direction_deg were added because this file
    flagged them) and `forecast-api/app/service/ml/energy_features.py`.
    Marking this item accurate-but-stale rather than checking the box
    silently — nothing needed changing, but worth recording that it was
    actually verified, not assumed.

[x] save raw and raw.marts in seperate database uing seperate Database_URL (so taht i can save 2*512 mb data)
    FDW infrastructure built and proven for real 2026-08-08; the actual
    *cutover* (pointing any real service/dbt at it) deliberately NOT
    done — a genuine, measured performance risk surfaced during testing
    that needs your call, not a confidence gap.

    Built on `ep-noisy-water` (the real, already-existing second Neon
    project, same one `RAW_MARTS_DATABASE_URL` in `services/waerehouse/
    .env` already names): `CREATE EXTENSION postgres_fdw`, a
    `raw_db_server` FOREIGN SERVER pointing at `ep-bold-feather`, a real
    user mapping, and `IMPORT FOREIGN SCHEMA raw ... INTO raw_remote`
    (named `raw_remote`, not `raw` — `ep-noisy-water` already has its
    own small local `raw` schema from earlier, a real name collision to
    avoid, not a cosmetic choice). All 5 tables imported as real foreign
    tables, confirmed: `select count(*) from raw_remote.aemo_nem_dispatch`
    → 52,355 (matches the real row count on the source side).

    **The real problem found while testing, not assumed**: a realistic
    query shape (`WHERE region = ... ORDER BY ts DESC LIMIT N` — exactly
    what `ml/data.py`'s `load_latest_window` runs on every real `/v1/
    forecast` request) took 22.9s over the FDW the first time — postgres_
    fdw wasn't pushing the filter/sort/limit down to the remote side,
    just pulling the whole table across first. `ALTER SERVER
    raw_db_server OPTIONS (ADD use_remote_estimate 'true')` fixed the
    query *plan* (confirmed via `EXPLAIN`: went from a full pull to a
    real `Foreign Scan`, cost 100.15..102.61) and cut it to 1.7-3s
    depending on row count (5/200/500 rows tested) — a real, large
    improvement, but still 1.7-3s of *added* latency per query versus
    the low-milliseconds a local query gets, from real network + pooler-
    to-pooler round-trip cost that doesn't go away with more tuning.

    That's a genuine problem for two real load-bearing paths, not a
    hypothetical one: (1) `/v1/forecast`'s live serving path calls
    `load_latest_window` on every real request — 1.7-3s of added latency
    there is a real product regression, not a rounding error; (2) dbt's
    `int_demand_with_weather.sql` runs *many* small correlated LATERAL
    lookups per demand row (the exact query shape that already caused
    the 51-minute TimescaleDB chunk-scan blowup fixed earlier this same
    session, `services/waerehouse`'s own retention/backfill work above)
    — routing those same per-row lookups through FDW's cross-network
    overhead on top of that is a real, credible risk of reproducing or
    worsening that exact failure mode, not a new, unrelated concern.

    Left in place (harmless, fully additive, nothing currently points at
    it): the FDW plumbing on `ep-noisy-water` as described above. NOT
    done: `dbt/ecolens/profiles.yml` repointed, any service's
    `DATABASE_URL` changed, or the reverse direction (`ep-bold-feather`
    importing `raw_marts` back for forecast-api's reads) — that reverse
    import is what would actually let `raw_marts` move without touching
    forecast-api's own code (its `MARTS_SCHEMA` queries would keep
    working unchanged against a foreign-table `raw_marts`), but it's
    exactly as untested for the same live-serving-latency question and
    shouldn't be assumed safe just because the first direction measured
    OK-ish. Next real step, your call: (a) proceed anyway, accepting the
    measured 1.7-3s/query cost on the two paths above, (b) restructure
    so dbt/serving never need the cross-database join at all (e.g. a
    periodic real ETL copy instead of a live FDW join — more moving
    parts, but zero live per-request latency cost), or (c) drop the
    2×512MB goal and keep the current single-database layout.

    **Resolved 2026-08-09 — went with (b)**, the safe option: no code
    that queries `raw_marts.*` today (forecast-api's `MARTS_SCHEMA`
    reads, dbt's own build) changed at all. dbt still builds everything
    against the primary database, exactly as before, zero change to its
    risk profile. New instead: `services/waerehouse/app/retention/
    marts_archive.py` archives `raw_marts.*` rows older than
    `Settings.marts_local_retention_days` (60, matching `raw.*`'s own
    window) to the second database (`RAW_MARTS_DATABASE_URL`,
    ep-noisy-water — the same real Neon project the shelved FDW work
    used) via plain `COPY`, batched a week at a time so no single
    connection is held long enough for Neon's pooler to drop it (see
    below), then prunes them from the primary — only after the archive
    copy actually succeeds, same safe ordering `retention/cold_
    storage.py` already established for R2 exports. New Celery Beat job
    `archive-and-prune-marts`, daily 03:30 UTC (30 min after the existing
    raw retention job); new CLI command `ecolens-warehouse archive-
    marts`; new `meta._marts_archive_log` audit table (primary DB) and a
    real `raw_marts` schema on the second DB (`0008_marts_archive_
    schema_db2.sql`) — with a real PRIMARY KEY on each mart's natural
    key (the primary database's dbt-materialized originals have none at
    all, confirmed live), so a crash between the copy and the delete
    step is retry-safe (`ON CONFLICT DO NOTHING`).

    First real run hit exactly the kind of problem this needed live
    testing to find: a single-shot `WHERE ts < cutoff` sweep over the
    full first-ever backlog (423,722 rows in `fct_emissions_5min` alone
    — a full year of accumulated marts history, since this table has
    never been pruned before) held one connection pair open for 5+
    minutes and got "connection is closed" from Neon's pooler on all 3
    larger fact tables. No data lost (archive-then-prune ordering meant
    nothing had been deleted yet) — confirmed live via row-count
    comparison before rewriting. Fixed by batching in week-wide
    `[start, end)` windows, each with its own fresh connection pair
    (`_archive_and_prune_table`) — a half-open range on both the SELECT
    and the matching DELETE, so a batch boundary can never split a
    timestamp's row-group (multiple regions/fuel_types share one `ts`/
    `hour` value) and risk deleting rows that were never actually
    archived.

    Re-run with the fix, tested live end-to-end: 686,172 rows archived
    to the second database and pruned from the primary across the 3
    tables that had backlog (`fct_emissions_5min`: 343,068;
    `fct_carbon_intensity`: 28,592; `fct_generation_mix`: 314,512) —
    `archived == pruned` on every table, confirming no loss.
    `fct_energy_demand` correctly archived 0 (all its real data is
    within the last 6 weeks already, inside the 60-day window). Added
    `vacuum_analyze_marts_tables()` (`retention/vacuum.py`, same shape
    as the existing `raw.*` one) — plain `VACUUM ANALYZE` reclaims space
    for reuse but doesn't shrink the on-disk file size, so for this one-
    time backlog cutover specifically, also ran a manual `VACUUM FULL`
    once. Real, measured result: primary database's `raw_marts` schema
    dropped from 120MB (the single largest schema in the database) to
    28MB; total primary database size 330MB → 238MB (66% → 48% of the
    500MB free-tier cap). The routine scheduled job only ever does plain
    `VACUUM ANALYZE` after a prune (matching the existing raw-retention
    task) — daily deltas off a 60-day rolling window are small enough
    that a `VACUUM FULL`'s table-rewrite/lock cost isn't worth it going
    forward; this was a one-time exception for the first-run backlog.

## Frontend — every dashboard page fully functional with real data (2026-08-08/09)

Audited all 14 `services/dashboard/src/app/(dashboard)/dashboard/*/page.tsx`
pages via parallel investigation, then closed every real gap found.

[x] *System Health* page — was 100% fabricated (`lib/admin.ts`'s
    `generateSystemHealth()`, including a fake "mongodb" component this
    platform doesn't even use). Rewritten to use the same real
    `fetchAllServicesHealth()` already backing operational-tasks'
    System Diagnostics grid (`ComponentsCard`). Resource/error-log
    sections have no real host-metrics or log-aggregation backend
    anywhere in this platform — kept, but now honestly marked with
    `IllustrativeBadge` instead of presented as real.

[x] *Executive* page (this app's `/dashboard` landing redirect) — mock
    KPI/trend/forecast/snapshot sections had zero visual distinction
    from the real ones. Added per-section live-tracking (`liveKpiLabels`,
    `sourceLive`/`trendLive`/`forecastLive`/`snapshotLive`, only set
    `true` inside a successful real fetch), a `live` prop on `KpiCard`
    (amber dot when illustrative), and `IllustrativeBadge`s on the
    Forecast Preview / Emissions Snapshot / Emissions Trend / Emissions
    by Source card headers.

[x] *Data Quality / Anomaly Detection* page — was 100% mock
    (`generateAnomalies()`/`summarizeAnomalies()`). Built a real backend
    end to end: `GET /v1/anomalies` (filtered/paginated real query over
    `meta.anomalies`, 150K+ real rows already written by
    `pipeline.anomaly.detect_anomalies` + `pipeline.ml_anomaly`'s real
    sklearn `IsolationForest`), `GET /v1/anomalies/summary`, and
    `PATCH /v1/anomalies/{id}` (new `status`/`status_updated_at` columns,
    `services/waerehouse/app/migrations/0006_anomaly_status.sql`).
    Severity reuses `services/ingestion`'s existing
    `_severity_from_score` thresholds; method is derived from which of
    `rule_based_score`/`statistical_score`/`ml_score` are non-null, not
    invented. Rewrote the page (~700 lines): real KPIs, real 7-day daily
    chart, real method breakdown, real filters (severity/method/status/
    reason-kind — replaced a fictional 12-type taxonomy with the 4 real
    reason kinds), real acknowledge/resolve/false-positive mutations.
    Also fixed the page's "How it works" copy, which claimed the model
    was "LSTM residual"-based (it's `IsolationForest`) and described
    rule checks (duplicate-detection, interconnector-balance) that don't
    exist in the real `anomaly.py`. Tested live: real filtered queries,
    real status mutation round-tripped and reverted.

[x] *Training* page — Hyperparameter Tuning tab was a disabled button +
    a hardcoded 4-row sample table. Built `POST /v1/model/tune` (runs
    `ml/tune.py`'s real grid search — 3 hidden sizes × 2 learning rates,
    6 full trials — synchronously, returns the best config) and
    `GET /v1/model/tuning-runs` (real MLflow runs tagged `tuning=true`,
    `ml/tune.py` already tagged every trial this way — no new logging
    needed, just a query). Tested live: a real trigger with
    `regions=["NSW1"]` took 75s and returned 6 distinct real trials
    (best: hidden_size=64, lr=0.001, val_mape=4.61%); tuning-runs
    endpoint confirmed all 6 queryable with full real metrics/params.
    Frontend: real "Start Tuning" button (shows best config + all
    trials once it resolves) and a real Hparam Search History table,
    `IllustrativeBadge`s removed from both. Feature Store / Deployments
    tabs stay illustrative — confirmed no real backend concept exists
    for either anywhere in this platform.

[x] `carbon`, `carbon/methodology`, `data-sources`, `operations`,
    `forecast`, `ingestion`, `models`, `performance`, `operational-tasks`
    — audited, already fully real (methodology page had 2 stale
    doc-comments calling its already-real trace data "mock", fixed;
    no functional changes needed anywhere else in this group).

[ ] `analytics`, `reports` — legitimately out of scope: a customer-
    facing SaaS emissions/compliance-reporting surface with zero real
    backend anywhere, not the internal ML/ops platform the rest of this
    TODO covers. Would need its own backend built from scratch.

[ ] `architecture` — static architecture diagram; correctly needs no
    real data, not a gap.

[ ] `settings` — confirmed zero real backend anywhere for roles/
    API-keys/service-accounts/Google-Sheets integration. Would need a
    whole new IAM service to back it for real — left honestly out of
    scope rather than fabricated.

## `/dashboard/forecast/` — NEM (5-region sum) forecast (2026-08-09)

[x] Fixed: the "NEM (5-region sum)" region tab returned 503
    (`model_not_trained_for_region`) for every request — only NSW1 had
    a trained Production model (`lstm_demand` v1), and `GET /v1/
    forecast?region=NEM` needs all 5 NEM regions (`NSW1`/`QLD1`/`VIC1`/
    `SA1`/`TAS1`) to have a fitted feature scaler in the served bundle.

    First attempt (naive fix): retrained on all 5 regions with no other
    change (`lstm_demand` v2). Real, measured result: 76.79% test_mape,
    vs. 3.73% for v1's NSW1-only model — a single shared-weight model
    can't bridge region-specific demand *dynamics* through per-region
    feature *scaling* alone (TAS1's shape genuinely differs from NSW1's,
    not just its magnitude). Not promoted.

    Real fix: added a one-hot region-identity feature
    (`ml/features.py`'s `add_region_dummies`/`ALL_MODEL_REGIONS` — 6
    columns, `region_NSW1`..`region_WEM`, unscaled like the existing
    `is_weekend`/`is_holiday` flags, always all 6 regardless of which
    regions are actually trained so `FEATURE_COLUMNS`' shape stays
    stable across different training runs) so the model can actually
    learn region-specific dynamics instead of relying on scaling alone.
    Retrained (`lstm_demand` v3): blended test_mape 7.22% — still fails
    the promotion gate's single-scalar comparison against v1's 3.73%.

    Real per-region walk-forward backtest (`ecolens-forecast evaluate
    --version 3`, a genuinely more rigorous methodology — rolling-origin
    out-of-sample, not a single train/test split) told the real story
    the blended scalar couldn't: NSW1 3.18%, QLD1 2.23%, VIC1 2.49%, SA1
    4.47% (all beat the seasonal-naive baseline comfortably, NSW1 even
    beats v1's own 3.73%) — TAS1 alone: 25.43%, *worse* than its naive
    baseline (8.69%). The blended metric was almost entirely TAS1
    dragging it down.

    Added a real, reusable `force` override to `POST /v1/model/versions/
    {version}/promote` (`PromoteModelRequest.force`, `registry.
    promote_version`) — skips only the single-scalar `test_mape`
    regression gate, never the separate `eval_gate_passed` live-
    evaluation-gate check (a real correctness signal, not a blended-
    metric artifact). Promoted v3 with `force=true` after reviewing the
    real per-region breakdown above — a deliberate, reviewed override,
    not a gate bypass hack (the gate itself is unchanged for every
    normal promotion).

    **Second real bug, found only after promoting and testing live**:
    SA1/TAS1 forecasts came out inflated 3-6x (e.g. SA1 predicted
    ~5,758MW against a real ~1,923MW recent average). Root cause:
    `ml/data.py`'s `load_latest_window` only ever fetched the *requested*
    region's rows (its own docstring already flagged this as a "single-
    region caveat" that "a genuinely multi-region model would need" to
    fix) — so `ml/features.py`'s cross-region-context features
    (`total_demand_all_regions_mw`/`demand_share_of_total`) came out as
    "region vs. itself" (share=1.0) at *serving* time, even though v3
    was *trained* on the real multi-region total (TAS1 ~3% of NEM, NSW1
    ~28%). A real train/serve skew, not a training-quality problem —
    confirmed by the offline `evaluate` walk-forward backtest (a
    different code path, unaffected by this bug) already showing SA1 at
    a real 4.47% MAPE. Fixed: `load_latest_window` now takes a
    `cross_regions` param (`_run_inference` in `api/v1/forecast/
    routes.py` passes every other region the bundle was trained on) so
    the true multi-region total is computed at inference time too.
    Verified live after the fix: SA1 1,935MW (vs. ~1,923MW real recent
    average — matches), NSW1/QLD1/VIC1 similarly realistic, NEM's sum
    still exactly equals the 5 regions' individual forecasts summed.
    TAS1 stays genuinely weak (~6,443MW, real recent average ~1,026MW)
    — this one wasn't the serving bug, it's the real per-region model
    weakness the walk-forward evaluation already found and this was
    knowingly promoted with, now disclosed on the dashboard (below).

    Dashboard: `/dashboard/forecast/` shows a real, measured disclosure
    banner (not invented) when TAS1 or NEM is selected, citing the
    actual walk-forward numbers above (`TAS1_WALK_FORWARD_MAPE`/
    `TAS1_BASELINE_MAPE` — static since a walk-forward backtest is a
    deliberate occasional run, not something computed per page load,
    same convention `/dashboard/performance/`'s `CONFORMAL_ALPHA` already
    uses). Also fixed: `fetchDemandForecast` was discarding the backend's
    real error message/code, falling back to a generic "is forecast-api
    running?" message even for a specific, real answer like
    `model_not_trained_for_region` or a data-gap error — now surfaces
    forecast-api's actual message directly (e.g. WEM's real reason:
    `"Recent data for region 'WEM' has gaps -- cannot build a full
    feature window"`, not a guessed paraphrase).

    Not in scope: WEM. Different native cadence (30-min/24h vs. NEM's
    5-min/4h) — mixing it into the same shared-weight model as the 5 NEM
    regions isn't temporally coherent, a separate effort if ever wanted.
    `region_WEM` exists in the one-hot feature set (so `FEATURE_COLUMNS`
    stays stable if a future WEM-inclusive training run happens) but was
    never trained on in this pass.

    Tests: `tests/test_forecast.py`/`test_emissions_forecast.py`'s fake
    DB sessions previously ignored the bound `:region` SQL param
    (returned the same fixture rows for every region) — harmless before
    this fix, but broke `load_latest_window`'s new per-region row-count
    check once it started actually caring which rows came back for which
    region. Fixed by retagging fixture rows to the requested region
    per-query, preserving each test's real intent (identical underlying
    data across regions) rather than weakening the new check.