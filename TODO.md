# TODO's

## Status across services/{ingestion,waerehouse,observility,dashboard} — 2026-08-06

Ran a pass to close out every remaining tractable item in these four
areas. Summary (see each service's own `TODO.md`/this file's per-page
sections below for the full detail):

- **`services/ingestion`** — verified against the actual current code
  and a full test run (354 passed/5 skipped): its own `TODO.md` shows
  every phase already done (Celery scheduling, hybrid ML anomaly
  detection, R2 storage, retention) by work outside this session — spot-
  checked several `[x]` claims against real files/tests before trusting
  them, all confirmed real. What's left is explicitly non-code: an R2
  bucket lifecycle policy (a live cloud-console change, not application
  code) and Phases 4-6 (shadow verification/cutover/decommission — need
  live deployment time and an operator's go-ahead, not more code).
  Nothing added this pass.
- **`services/waerehouse`** — same finding, same verification (71
  passed/1 skipped): every phase (1-5) plus a full "Prod-Grade
  Hardening Pass" already marked done, confirmed real. What's left is
  explicitly deferred (security/auth hardening, flipping the
  legacy-consumer cutover flag, applying one migration against the real
  NeonDB) — all operator decisions or live-environment steps, not code.
  Nothing added this pass.
- **`services/observility`** — closed the "recommended next step" from
  its own prior pass: added `ecolens_build_info{service,version}` to
  all 4 business services (the info-metric Prometheus pattern, sourced
  from each service's real `__version__`, not a scrape-config label
  that would drift). See its own `TODO.md` for the remaining gaps
  (generic HTTP-layer metrics, OTel instrumentation, RabbitMQ
  queue-depth, structured-log identity) — all real, all documented,
  none closed this pass beyond the metric above.
- **Dashboard** — closed §2 (Operations), §3 (Data Sources), §4
  (Ingestion Pipeline) below in full; §5 (Data Quality) backend-side
  only (new public endpoints + client functions), page rewrite
  deliberately deferred — a real data-shape mismatch, not a shortcut,
  see that section. Everything else below (§8 Analytics, §9/§10 hparam
  training, §12 Operational Tasks aggregates, §13 System Health, §15
  Reports, §16 Settings) needs net-new backend features (new database
  columns, new aggregation logic, OAuth, PDF rendering) that go beyond
  "wire up what already exists" — each section states exactly what
  would need to be built, not attempted here.

## Frontend — API endpoints required to complete each dashboard page

Audited 2026-08-06 against the actual current code (`services/dashboard`,
`services/forecast-api`, `services/data-pipeline`, `services/ingestion`) —
not the aspirational docs. Legend:

- `[x]` — real endpoint exists **and** is already wired into the page.
- `[~]` — real endpoint exists on a backend service but the dashboard
  doesn't call it yet (missing/broken lib wrapper, or just never wired).
- `[ ]` — no endpoint exists anywhere; needs to be built from scratch.

Page order matches the sidebar nav (`src/components/dashboard/sidebar.tsx`)
grouping: Dashboards → Data Platform → Insights → ML Platform → Operations →
About, plus two pages reachable but not in the sidebar (`carbon/methodology`,
`reports`, `settings`).

### 0. Build-breaking — fixed 2026-08-06

Two pages imported lib modules that didn't exist in the repo, breaking
`next build`/`tsc`. Both now fixed:

- [x] `src/app/(dashboard)/dashboard/executive/page.tsx:26` imports
      `fetchPublicDataQualitySummary` from `@/lib/data-quality` — created,
      wraps `GET /v1/data-quality/summary/public` (data-pipeline,
      `api/v1/data_quality/routes.py:56`, unauthenticated, returns
      `data_quality_score_pct` + `open_risks_high_plus`).
- [x] `src/app/(dashboard)/dashboard/operations/page.tsx:25` imports
      `fetchAllServicesHealth`/`ServiceHealth` from `@/lib/health` —
      created, aggregates `GET /v1/readyz` from forecast-api (8002) and
      data-pipeline (8001) in parallel, normalizing their two different
      response shapes. IAM leg deliberately omitted — `services/iam` was
      scaffolded then deleted (commit `a0d36b0`) and doesn't exist as a
      running service; its default port (8000) is actually bound to
      forecast-api in `docker-compose.yml`, so probing it under an "IAM"
      label would have misattributed forecast-api's health as IAM's. Add
      it back if/when IAM returns for real.

Also note: `services/ingestion` (port 8003) is a full, running, tested
FastAPI service the dashboard never talks to (`env.ts` has no
`NEXT_PUBLIC_INGESTION_API_URL`) — it duplicates most of data-pipeline's
data-sources/ingest routes but fully unauthenticated. Decide whether it's
the eventual replacement for data-pipeline's ingestion routes or dead
weight before building new frontend code against either.

---

### 1. Executive (`/dashboard/executive`)

Mostly real; broken by the missing-lib bug above.

- [x] `GET /v1/emissions/ytd` (forecast-api) — "Total CO₂e (YTD)" KPI
- [x] `GET /v1/emissions/current` (forecast-api) — "Carbon Intensity" KPI
- [x] `GET /v1/demand/summary` (forecast-api) — "Renewable Share" +
      "Avg Wholesale Price (YTD)" KPIs
- [x] `GET /v1/generation-mix` (forecast-api) — emissions-by-source donut
- [x] `GET /v1/emissions/timeseries?bucket=day&days=8` (forecast-api) —
      trend chart
- [x] `GET /v1/emissions/timeseries?bucket=hour&days=1` (forecast-api) —
      emissions snapshot card
- [x] `GET /v1/forecast?region=NEM` (forecast-api) — forecast preview card
- [~] `GET /v1/data-quality/summary/public` (data-pipeline) — "Data
      Quality Score" + "Open Risks" KPIs. Endpoint exists; wire it up per
      §0.

### 2. Operations (`/dashboard/operations`) — mostly closed 2026-08-06

- [x] `GET /v1/model` (forecast-api) — loaded model card
- [x] `GET /v1/readyz` (forecast-api, port 8002) — via `lib/health.ts`
- [x] `GET /v1/readyz` (data-pipeline, port 8001) — via `lib/health.ts`
- [ ] IAM `GET /` + `GET /db_health` — still not wired; only needed if
      IAM comes back as a real service (currently doesn't exist)
- [x] Pipeline inventory now renders `GET /v1/data-sources/public`
      (real per-source health/schedule, `lib/data-sources.ts`) instead
      of the static `PIPELINE_CATALOG` — the public mirror endpoint
      needed for this (§3 below) didn't exist when this row was first
      written; it does now.

### 3. Data Sources (`/dashboard/data-sources`) — closed 2026-08-06

Was 100% fictional catalog with every action faked. **Real gap found
while implementing**: `GET /v1/data-sources` requires `analyst`/`admin`
auth (`require_roles(*ROLES)`) — the dashboard has no way to hold a
bearer token for data-pipeline's separate auth domain (no IAM service
exists), so this wasn't actually a pure rewiring job as originally
scoped. Fixed by adding `GET /v1/data-sources/public`
(`datasources/routes.py`, unauthenticated mirror, same established
pattern as `/ingestion/public/pipelines` — verified `DataSourceOut`
carries nothing sensitive, `auth.type` is a bare enum never a
credential value) — 4 new backend tests, `ruff`/tests clean.

- [x] `GET /v1/data-sources/public` — new, replaces
      `getDataSources()`/`getSourceCategories()` wholesale
      (`lib/data-sources.ts`).
- [x] `POST /v1/data-sources/{id}/run` — real, reused from `ingestion.ts`.
- [x] `POST /v1/data-sources/{id}/backfill` — real, reused from
      `ingestion.ts` (fixed 7-day trailing window; no date-range picker
      UI on this page).
- [ ] `PATCH /v1/data-sources/{id}` (admin) — still not real. Same auth
      problem as the list endpoint, but this one **is** genuinely
      privileged (schedule/enabled edits), so no public mirror was
      added — the page shows Edit/Enable-Disable as disabled controls
      with an explanatory tooltip instead of faking a mutation that
      never reaches the backend (matches `models/page.tsx`'s Train tab
      convention).
- [ ] `GET /v1/data-sources/{id}/history` — still not shown on this page;
      would need the same public-mirror treatment first (not added,
      out of scope for this pass — nothing on the page needs it yet).

### 4. Ingestion Pipeline (`/dashboard/ingestion`) — closed 2026-08-06

- [x] `POST /v1/data-sources/{id}/run` (data-pipeline) — "Run now" /
      "Trigger All"
- [x] `GET /v1/ingestion/public/runs` (data-pipeline) — "Runs" tab
- [x] `GET /v1/ingestion/public/failed` — "Failed Jobs" tab now real
      (`lib/ingestion.ts`'s `fetchPublicFailedRuns`).
- [x] `GET /v1/ingestion/public/retry-queue` — "Retry Queue" tab now
      real (`fetchPublicRetryQueue`).
- [x] `GET /v1/ingestion/public/scheduler` — "Scheduler" tab now real
      (`fetchPublicScheduler`; upcoming/recent runs + worker/queue
      status).
- [x] KPI row — removed the 4 numbers with no backing query
      (`Running`/`Records (24h)`/`Avg duration`/`Success rate`, pure
      fabrication) rather than leave them fake; `Failed (24h)` and
      `Retry Queue` size are now real, sourced from the two tabs above.
- [ ] "Builder" tab — still explicitly out of scope ("not exposing a
      real builder in this prototype"); no endpoint, not planned.

### 5. Data Quality & Anomalies (`/dashboard/data-quality`) — endpoints closed, page rewrite NOT done (2026-08-06)

100% mock (`generateAnomalies()`/`summarizeAnomalies()` in `admin.ts`).
Backend-side auth gap fixed (same problem as §3): `/issues`/`/outliers`/
`/schema` all required `analyst`/`admin` auth. Added
`GET /v1/data-quality/public/{issues,outliers,schema}` mirroring the
same established public-endpoint pattern — 8 new backend tests
(`test_data_quality_router.py`), `ruff`/mypy clean. Frontend client
functions added (`lib/data-quality.ts`: `fetchPublicIssues`,
`fetchPublicOutliers`, `fetchPublicSchemaReport`).

**Page itself deliberately NOT rewired this pass** — a real mismatch,
not a time-budget cut corner: this page's `Anomaly` type (`lib/admin.ts`)
has `severity`/`method: "rule"|"ml"|"hybrid"`/a single 0-1 ML-confidence
`score`/12 specific `AnomalyType` values (`demand_spike`,
`interconnector_imbalance`, etc.). The real backend's
`DataQualityIssue.category` (`completeness`/`validity`/`uniqueness`/
`consistency`/`timeliness`) and `DataQualityOutlier` (a z-score +
expected-range reading, no ML-confidence concept, no rule/ML/hybrid
distinction) are a genuinely different taxonomy — not a relabeling of
the same fields. Force-fitting real data into this page's existing
shape would misrepresent it (inventing a "method" the backend doesn't
have); doing it honestly means redesigning the page around what the
real data actually looks like, which is a design task, not a wiring
pass. Left as real, tested, ready-to-use endpoints for whoever picks up
that redesign.

- [x] `GET /v1/data-quality/public/outliers` — new, real statistical
      z-score rows.
- [x] `GET /v1/data-quality/public/issues` — new, real open DQ issues.
- [x] `GET /v1/data-quality/public/schema` — new, real schema drift
      report.
- [ ] `POST /v1/data-quality/recheck/{source}` (admin) — still
      authenticated only, no public mirror added (same reasoning as
      `PATCH /v1/data-sources/{id}` in §3 — this one mutates/triggers
      real work, genuinely privileged).
- [ ] Page rewrite around the real `issues`/`outliers`/`schema` shapes —
      not done, see above.
- [ ] `POST .../acknowledge`, `POST .../resolve`,
      `POST .../false-positive` (per-anomaly-row mutations) — **still
      do not exist anywhere in any service.** Needs new backend work (a
      mutable status column + 3 endpoints) regardless of the page
      redesign above.

### 6. Forecast Explorer (`/dashboard/forecast`)

Fully real already.

- [x] `GET /v1/forecast?region=` (forecast-api) — DemandLSTM inference
- [x] `GET /v1/model` (forecast-api) — sidebar model-info card

### 7. Carbon Intelligence (`/dashboard/carbon`)

Fully real already.

- [x] `GET /v1/emissions/timeseries` (forecast-api)
- [x] `GET /v1/generation-mix` (forecast-api) — NEM-wide + once per region
- [x] `GET /v1/emissions/forecast` (forecast-api)

### 7a. Carbon Methodology (`/dashboard/carbon/methodology`)

Reference content is intentionally static/curated (calculation chain,
citations) — that's correct as-is, not a gap. One real gap:

- [ ] `GET /v1/emissions/trace?region=&limit=` (forecast-api) — **does
      not exist anywhere.** Page has a `TraceMockup` placeholder component
      explicitly waiting on this. Needs new backend work: a per-interval
      trace of the emissions calculation chain (raw generation mix →
      per-fuel weighting → intensity) for a given region/period.

### 8. Energy Analytics (`/dashboard/analytics`)

100% static (`data.ts`'s `ANALYTICS_*` consts) plus inline hardcoded
arrays in the page itself (`RegionalMap`'s `dots`, `CostVsEmissionsChart`'s
`bubbles`). No endpoint anywhere covers any of this page's content.

- [ ] Emissions trend/scope timeseries by business unit or category —
      no such breakdown exists in any service (forecast-api's timeseries
      is region/fuel only, not "scope 1/2/3" or "by department").
- [ ] Industry/peer benchmarking data — no endpoint, no data source for
      this exists in the platform at all.
- [ ] Regional emissions breakdown for the map view — closest real data
      is `GET /v1/generation-mix?region=` (forecast-api) called per
      region, which the Carbon page already does; Analytics' map could
      reuse that instead of the hardcoded `dots` array, but the map's
      visual (lat/lng dots) vs. the API's region-code shape still needs
      a translation layer.
- [ ] Cost-vs-emissions bubble chart — needs wholesale price
      (`GET /v1/demand/summary` has `avg_price` but not per-bubble
      granularity) cross-referenced with emissions; no endpoint produces
      this pairing today.
- [ ] Opportunity/ROI recommendations — no endpoint, no modeling exists
      for this anywhere in the platform.

### 9. Model Registry (`/dashboard/models`)

Fully real already.

- [x] `GET /v1/model/versions?model_name=` (forecast-api)
- [x] `POST /v1/model/versions/{version}/promote` (forecast-api)
- [x] `DELETE /v1/model/versions/{version}` (forecast-api)
- [x] `POST /v1/model/train` (data-pipeline) — Fine-tune tab
- [ ] "Train" tab submit is intentionally disabled — no dedicated
      `POST /v1/model/train`-with-hyperparameters endpoint exists yet
      (current `/v1/model/train` just publishes a bare training-trigger
      event, no hyperparameter payload support). Needs backend work if
      the Train tab is to become real.

### 10. Training & Experiments (`/dashboard/training`)

100% mock — every tab (Training Jobs, Hyperparameter Tuning, Experiments,
Feature Store, Deployments) reads from `dashboards.ts`/`admin-dashboard.ts`
hardcoded generators. This is the page `performance/page.tsx`'s own code
comments explicitly call out as the anti-pattern to avoid. No MLflow
experiments/runs listing, feature-store listing, or deployment-status
endpoint exists in any service.

- [~] `GET /v1/model/versions` (forecast-api) — could replace
      `getMLModels()`'s 5 fake versions; already used by `models` and
      `performance` pages, just never adopted here.
- [~] `GET /v1/model/training-runs` (data-pipeline) — could replace
      `getTrainingJobs()`/`getRecentTrainingRuns()`'s fake job/run rows;
      same story, already real and used elsewhere.
- [ ] MLflow experiments/runs listing (`getMlflowExperiments()`/
      `getMlflowRuns()`) — no endpoint anywhere exposes MLflow experiment
      metadata beyond the single loaded model's own version history.
- [ ] Feature-store listing (`getFeatureGroups()`) — no endpoint.
- [ ] Deployment status (`getDeployments()`) — no endpoint.
- [ ] Hyperparameter-search trigger + history (`Hparam Search History`
      table, "Start Tuning" button) — no endpoint, and `/v1/model/train`
      doesn't accept a hyperparameter payload today (same gap as
      Model Registry's Train tab above — likely the same backend work
      would serve both).

### 11. Performance (`/dashboard/performance`)

Best-documented page in the codebase re: real vs. illustrative — keep
following its own convention (`IllustrativeBadge`) rather than fabricating
data for the items below.

- [x] `GET /v1/model/versions?model_name=` (forecast-api)
- [x] `GET /v1/model/versions/{version}/loss-curve?model_name=` (forecast-api)
- [x] `GET /v1/model/training-runs?limit=20` (data-pipeline)
- [ ] Online-learning "batches processed" / cumulative-drift tracking —
      not tracked anywhere in the pipeline.
- [ ] Concept-drift (PSI) values — `mlops/drift.py` has a real, tested PSI
      detector but zero callers; needs an endpoint wrapping it plus
      somewhere to persist/schedule its runs before this can be real.
- [ ] Model health score — no scoring formula exists anywhere; needs to
      be designed before an endpoint makes sense.
- [ ] Retraining decision guide thresholds — no retraining policy is
      wired to real alerts yet.
- [ ] Alert conditions beyond coverage/MAPE (which already use real
      values) — PSI and "Error plateau" have no metric to source from
      until the drift-tracking gap above is closed.

### 12. Operational Tasks (`/dashboard/operational-tasks`)

Most explicitly self-documented mixed page in the codebase (see its own
module docstring). Pipeline operations are real; 6 of 7 sections are
still mock.

- [x] `POST /v1/data-sources/{id}/run`, `POST .../backfill`,
      `GET .../backfill/status` (data-pipeline) — pipeline row actions
- [x] `POST /v1/ingestion/dbt-warehouse/build` (data-pipeline)
- [x] `POST /v1/model/train`, `GET /v1/model/training-runs` (data-pipeline)
- [x] `GET /v1/model`, `GET /v1/model/versions` (forecast-api)
- [ ] KPI row (`getOperationalKpis()`) — entirely hardcoded ("Active
      Tasks: 8", "System Load: 28%", etc.); no aggregation endpoint exists
      for any of these 6 numbers.
- [ ] Active Tasks list — only `model_training` rows are real (from
      `GET /v1/model/training-runs`); the other 6 task types
      (`ingestion`, `data_quality`, `feature_build`, `forecast`, `report`,
      `anomaly`) have no "task in flight" concept anywhere in the backend.
- [ ] Scheduled Operations (`getScheduledOps()`) — 5 hardcoded cron rows;
      closest real data is `GET /v1/ingestion/public/scheduler`
      (data-pipeline, exists, not wired here) but it's scoped to
      ingestion only, not the broader ops calendar this section implies.
- [ ] System Commands (`getSystemCommands()`) — "Rebuild Features",
      "Clear Cache", "Vacuum Database", etc. have no backend endpoints;
      each would need its own admin-gated route.

### 13. System Health (`/dashboard/system-health`)

100% static (`generateSystemHealth()` in `admin.ts`) — fixed uptime,
fabricated per-component latencies, fixed disk/memory numbers.

- [ ] Component-level health (postgres/mongodb/redis/mlflow/dbt/
      model_loader/scheduler status + latency) — no endpoint anywhere
      reports per-component detail; closest existing pieces are the
      coarser `GET /v1/readyz` on forecast-api and data-pipeline (overall
      pass/fail, not per-component latency).
- [ ] Disk/memory usage — not exposed by any endpoint.
- [ ] Recent-errors log — not exposed by any endpoint; `meta._ingest_log`/
      `meta._training_log`/`meta._dbt_build_log` exist as real tables
      queried elsewhere (`training-runs`, `dbt/runs` endpoints) but
      nothing aggregates cross-service error events into one feed.

### 14. Architecture (`/dashboard/architecture`)

Pure documentation/explainer page — no data, no KPIs, nothing to wire.
No endpoints needed.

### 15. Reports (not in sidebar, reachable at `/dashboard/reports`)

100% static seed data + `localStorage`-only persistence. No backend at
all — not even a stub.

- [ ] Report generation (real PDF/Excel/CSV rendering) — no endpoint.
- [ ] Reports-list / reports-history endpoint — no endpoint; currently
      `localStorage` under the browser's own `ecolens:reports:saved` key.
- [ ] Report download/preview endpoint — no endpoint.

### 16. Settings (not in sidebar, reachable at `/dashboard/settings`)

100% static across every tab; every button is a no-op with no `onClick`
mutation handler.

- [ ] User/role management (Roles tab) — no endpoint.
- [ ] API key CRUD (`getAPIKeys()`) — no endpoint.
- [ ] Service-account CRUD (`getServiceAccounts()`) — no endpoint.
- [ ] Settings persistence (`getSettings()`, 12 config fields incl. a fake
      `db_url`) — no endpoint.
- [ ] Google OAuth + Sheets export pipeline (trigger, schedule, history) —
      `getIntegrations()` shows Google Sheets as "connected" with a fake
      account, but there is no actual OAuth flow anywhere. The 6 other
      integrations (Excel, Notion, Airtable, Slack, PagerDuty, Webhook)
      are explicitly `coming_soon` placeholders, not a near-term gap.

