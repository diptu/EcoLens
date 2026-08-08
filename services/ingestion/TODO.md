# Remaining Ingestion Pipeline Todo's for frontend

## Operational task page todos

### Pipeline Operations

`dashboard/operational-tasks/page.tsx` — real vs. mock section
inventory as of 2026-08-08 (see that page's own module docstring for
the full history). The Pipeline Operations card itself (per-row
run/backfill/dbt-build trigger) and Model Operations/Training are real,
backed by ingestion + `services/waerehouse` + `services/forecast-api` —
nothing left to do there.

- [x] **Scheduled Operations** card — was `getScheduledOps()`
      (`lib/admin-dashboard.ts`), 5 hardcoded cron rows with 2025 dates.
      Now renders `fetchPublicPipelines()` (real per-pipeline
      `schedule.{cron,enabled}` + `last_run_at`/`next_run_at` from
      ingestion's `GET /v1/ingestion/public/pipelines` + waerehouse's
      `GET /v1/dbt/build/last`, composed together) via a rewritten
      `ScheduledTable` that takes `LivePipeline[]` directly instead of
      `ScheduledOp[]`. That fetch function already existed and was
      already field-compatible before this — it just had no caller on
      this page.

- [x] **Active Tasks** card, `type: "ingestion"` rows — was mock-only
      for every type except `model_training`. Now synthesizes real
      `ingestion`-typed `ActiveTask` rows from this page's own
      `pollLatestRun`/`pollBackfillSummary` state (`pipelineRows`) --
      extended `RowState` to carry `runId`/`startedAt`/`triggeredBy`
      off the real `PublicRun` those polls already receive, so a
      currently `queued`/`running`/`staged` pipeline now shows up here
      too, not just in the Pipeline Operations table.
      `type: "data_quality"`/`"feature_build"`/`"forecast"`/`"report"`/
      `"anomaly"` rows have no "task in flight" concept anywhere in any
      service yet and are out of ingestion's scope to fix alone — stay
      mock until/unless those systems get one.

- [x] **KPI row** — was `getOperationalKpis()`, all 6 numbers
      hardcoded. Now: "Ingestion Pipelines" derived from
      `fetchPublicPipelines()`'s fetched array (active/paused counts
      from `schedule.enabled`); "Last Ingestion" from the max
      `last_run_at` across that same array; "Active Tasks" reads
      `taskCounts` (the real Active Tasks data above) instead of a
      second source of truth; "Model Status" reads the already-fetched
      `modelInfo` (forecast-api). "Next Retrain" and "System Load" were
      left as explicit `"—"` placeholders with an honest sub-label
      rather than fabricated numbers — no fixed retrain cron exists
      (event-driven only, see `services/waerehouse/TODO.md`'s Pipeline
      Operations section) and no service exposes host-level metrics.

- [x] **System Commands** card, 2 of 6 buttons — was
      `getSystemCommands()`, all 6 buttons with no `onClick` at all.
      Now wired for real: "Refresh Materialized Views" calls
      `triggerDbtBuild()` (the same real endpoint the Pipeline
      Operations dbt row already uses); "System Diagnostics" calls
      `fetchAllServicesHealth()` and reports how many of the 5 services
      are unhealthy, if any. Both show a real running/success/error
      state on the card itself instead of a decorative always-enabled
      button.
      The other 4 stay explicitly disabled (grayed out, tooltip
      explaining why) rather than wired to something fake:
      - **"Rebuild Features"** — investigated and deliberately NOT
        wired to `services/ingestion/scripts/select_features.py`.
        That script reads a *local* `data/training/master.duckdb` and
        explicitly refuses to build one from cloud (R2) credentials on
        demand if it's missing (its own module docstring) — it's a
        local dev/data-science artifact, not something a running
        production container has or should build synchronously behind
        a dashboard button. Would need real scoping (build the master
        table from R2 first? cache the result where? how long can this
        realistically run behind an HTTP request?) before it's a real
        endpoint, not a quick wire-up.
      - **"Clear Cache"** — Redis backs real circuit-breaker/backfill-
        lock state in this service; flushing it isn't obviously safe
        (could un-stick a circuit breaker mid-incident, or drop an
        in-flight backfill's lock) and no scoped-down "safe subset to
        clear" has been defined.
      - **"Vacuum Database"** — a real, genuine Postgres admin
        operation against the live warehouse (`services/waerehouse`'s
        job, not ingestion's) — destructive-adjacent enough (resource
        contention on a live DB, not data loss) to need an explicit
        go-ahead and admin gating, not a dashboard button wired
        speculatively.
      - **"Reindex Search"** — no search-index concept (Elasticsearch
        or otherwise) exists anywhere in this codebase. Nothing to map
        this onto at all.
