# Remaining Warehouse Pipeline Todo's for frontend

## Operational task page todos

### Pipeline Operations

`dashboard/operational-tasks/page.tsx` — the dbt-warehouse-build row in
the Pipeline Operations card is real (`POST /v1/dbt/build`, `GET
/v1/dbt/build/last`, `services/waerehouse`'s own Postgres-native
concurrent-build lock). `POST /v1/dbt/build` also has a second real
caller on the same page now: the System Commands card's "Refresh
Materialized Views" button (`services/ingestion/TODO.md`'s System
Commands item) — same endpoint, just a second UI entry point, no
warehouse-side change for that.

- [x] **`GET /v1/dbt/build/runs`** (list, paginated) — added.
      `app/api/v1/dbt/routes.py`'s `list_dbt_build_runs_endpoint`,
      backed by a new `app/schemas/dbt/response.py`'s
      `DbtBuildRunsListResponse` — same shape/field names data-pipeline's
      identical (now-removed) `GET /v1/dbt/runs` used, open (no auth),
      reads `meta._dbt_build_log`, `?limit=` query param, newest first.
      `GET /v1/dbt/build/last` stays too, as a thin single-row
      convenience wrapper — not replaced. 4 new tests in
      `tests/test_dbt_routes.py::TestListDbtBuildRuns`.

- [x] **Live "is a build running right now" signal** — added.
      `lib/ingestion.ts`'s `pollLatestDbtBuild()` (same
      `pollLatestRun`-shaped polling loop ingestion's 5 sources already
      use, reading `GET /v1/dbt/build/runs?limit=1`) is now started for
      the dbt row in `dashboard/operational-tasks/page.tsx`'s rehydrate
      effect on mount — a build triggered from a *different* browser
      tab/session is now visible here too, not just self-triggered ones.
      Both "Run now" (Pipeline Operations row) and "Refresh Materialized
      Views" (System Commands, wired via a new `busy` prop on
      `CommandCard`) now read `pipelineRows["pipe-dbt-warehouse"]` for
      their disabled state, so either button disables proactively while
      a build observed via polling is in flight — self- or externally-
      triggered — not just reactively on a 409.

- [x] **Active Tasks card, dbt-build row** — closed. Added a real
      `"transform"` value to the dashboard's `TaskType` union
      (`lib/admin-dashboard.ts`) instead of the earlier mislabeling as
      `"ingestion"` — `pipelineActiveTasks` (renamed from
      `ingestionActiveTasks`, since it now covers both) tags the
      dbt-warehouse row's synthesized `ActiveTask` as `"transform"`.
      Combined with the live-polling item above, a build triggered by
      *any* session now surfaces here while `"running"`, not just a
      one-tick `"queued"` flash from a self-triggered click.

- [x] **KPI row / Scheduled Operations, dbt row's aggregate fields** —
      closed. `lib/ingestion.ts`'s `fetchPublicPipelines()` now computes
      real 24h `run_count_24h`/`success_rate_24h`/`p95_duration_ms_24h`
      for the dbt row from `GET /v1/dbt/build/runs`'s real history
      (same aggregate shape ingestion's own sources already get
      server-side), replacing the old single-build 0%/100% proxy and
      the honest `null`s for the other two fields.

- [x] **Scheduled Operations, dbt row's cron** — confirmed not a gap,
      unchanged: `schedule.cron: "manual"` is accurate (no scheduled
      dbt-build workflow exists in `.github/workflows/` — `warehouse-
      monitor.yml`'s hourly cron only runs read-only freshness/size/
      mart-history checks). This card renders real per-pipeline data
      now, so this row's honest `"manual"` cron is visible on the page.

Nothing left open in this section as of 2026-08-08.
