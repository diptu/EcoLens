# Operational task todo list

Companion to the root `TODO.md`'s Rollout Phases plan, which only sketched this page in one line
each for "pipeline-ops" and "ML-ops" widgets. This is the detailed breakdown after reading every
real route this page could possibly call across both backend services
(`services/data-pipeline/app/api/v1/pipelines/routes.py`,
`services/data-pipeline/app/api/v1/dbt/routes.py`, every `services/forecast-api/app/api/v1/*/routes.py`)
and the current mock (`services/dashboard/src/lib/admin-dashboard.ts`, lines 330–480, backing
`src/app/(dashboard)/dashboard/operational-tasks/page.tsx`).

**Headline finding**: this page assumes three things that don't exist anywhere in this platform —
(1) a multi-model registry (real forecast-api serves exactly **one** model, not five), (2) a generic
task-queue/job-tracking abstraction with 0–100% progress (real backend only has ingestion *runs*,
which are binary-ish status, not a progress percentage), and (3) any way to *trigger* anything from
the browser — no pipeline run/pause/resume, no model retrain, no dbt rebuild, no system command has
an unauthenticated (or otherwise dashboard-reachable) write endpoint. Every write-capable route that
does exist (`POST /v1/ingestion/{id}/pause`, `POST /v1/ingestion/{id}/resume`,
`POST /v1/dbt/{subcommand}`) is gated behind that service's own JWT domain, which the dashboard has
no bridge to — the same standing gap root `TODO.md` already documents for data-pipeline. Net effect:
**read-only real data is very reusable (this page shares both backends with `/dashboard/operations`,
already fixed this session); every "action" button on this page has nothing real to call and must be
honestly disabled, not wired to a no-op.**

Feasibility at a glance:

| Section | Real backend? | Verdict |
|---|---|---|
| Pipeline Operations | Yes — fully | Wire directly, zero new backend |
| Model Operations | Partial (1 of 5 rows real) | Restructure to a single real model |
| Active Tasks | No generic task concept exists | Restructure around real ingestion runs |
| Model Training & Tuning | No | Replace with honest "not available" notice |
| Scheduled Operations | Partial (ingestion only) | Wire ingestion rows, drop model-training rows |
| Recent Training Runs | No (blocked on Phase 4 MLflow decision) | Leave honestly mock or drop |
| System Commands | 1 of 6 fully real, 1 auth-blocked-but-real | Keep 2, drop 4 |

##  Pipeline Operations — **DONE**

Real data already exists and is already wired into `/dashboard/operations` this session — this is
the same `PipelinesList` (`lib/ingestion.ts`'s `fetchPublicPipelines()`, hitting
`GET /v1/ingestion/public/pipelines`), just a different table layout. Genuinely the easiest section
on this page, which is why it's first.

- [x] Replaced `getPipelineOps()` (5 fictional sources: "ENTSO-E API", "Open-Meteo API", "EIA API",
      "Carbon Intensity API", "ICE API" — the exact same fictional-vendor problem the old Ingestion
      page mock had, now fixed there but not here) with `fetchPublicPipelines()`. Real inventory is
      6 pipelines (5 ingestion sources — OpenElectricity, AEMO NEM, AEMO WEM, BoM, AEMO Public
      Holidays — plus 1 dbt warehouse-transform pipeline), not 5. (A separate "audit table" was
      floated mid-implementation claiming Open-Meteo/Carbon Intensity API/Custom REST Site
      Meters/APVI were the real sources instead — checked directly against the current
      `services/data-pipeline/app/models/datasources.py` CATALOG, which still only defines the same
      5 sources above; confirmed with the user to proceed on the actual code, not that table.)
      Deleted `getPipelineOps()`/`PipelineOp`/`PipelineSource`/`PipelineSchedule`/`PipelineStatus`
      from `lib/admin-dashboard.ts` (confirmed zero other consumers first), its re-export from
      `lib/dashboards.ts`, and its dedicated test in `tests/unit/admin-dashboard.test.ts`.
- [x] **Columns**: `Pipeline Name` → `p.name`. `Source` → `formatSource(p.source_id)`.
      `Schedule`/`Cron` → `p.schedule.cron` + `p.schedule.timezone`, with "paused" shown instead of a
      cron string when `p.schedule.enabled` is false. `Last Run` → `formatRelativeTime(p.last_run_at)`.
      `Status` → `derivePipelineHealth(p)` — `PipelineStatusChip` rebuilt around its real
      success/failed/paused/idle vocabulary (not the mock's running/success/failed/queued; there's no
      real "running" signal at this endpoint's granularity, so that state no longer exists in the UI).
- [x] **Actions column — disabled, not wired.** No trigger-now endpoint exists at all (confirmed: the
      pipelines router only has GET routes plus
      `POST /{id}/pause`/`POST /{id}/resume` — no "run now"). Pause/resume exist but are gated by
      data-pipeline's own JWT, which the dashboard doesn't hold. Kept 2 of the original 3 action
      icons (Run now — disabled, tooltip explains why; Info — now a real link into
      `/dashboard/ingestion/`) and dropped "More", which never had a menu behind it in the mock
      either — matches how Settings' "Invite User" button was already left inert this session rather
      than either faked or deleted.
- [x] "Trigger Ingestion" button (top-right of the card) — disabled with a tooltip; no backend call
      is possible.
- [x] "View all pipelines" — now a real link to `/dashboard/ingestion/` (already has the full real
      pipelines table) instead of expanding in place.

**Verification**: `tsc --noEmit` clean, 236 dashboard unit tests pass (237→236: only the deleted
`getPipelineOps` test was removed). Live screenshot against the dev server confirms the honest
"Couldn't load pipelines (Failed to fetch) — is data-pipeline running?" fallback renders correctly
(this environment's data-pipeline instance errors on this specific endpoint — a pre-existing,
already-documented environment gap from earlier this session, not a code defect) and the disabled
"Trigger Ingestion" button is visually dimmed, unlike the still-enabled (still-mock) "Retrain Model"
button next to it.

## Model Operations

> **Superseded for fine-tune work.** The single-model table, Fine-tune button,
> `POST /v1/model/train`, training-runs log, and version/promote APIs are now
> real. The multi-phase plan for finishing Fine-tune end-to-end (completion
> loop, promote CTA, full retrain, preflight, quality gates) lives in root
> **`TODO.md` → `# Operational Tasks` → `## Model Operations — Fine-tune
> from the Model Operations tab`**. Do not implement from the outdated
> checklist below; it is kept only as historical context for what the mock
> looked like before Phase 0–2 landed.

**Historical note (pre-wiring):** The mock (`getModelOps()`) listed 5 different
models. **There is still exactly one real model** — whatever forecast-api's
`ModelRegistry` has loaded from MLflow Production (a DemandLSTM).
`generation-mix` / `emissions` remain SQL aggregations, not ML.

### Done since this doc was written

- [x] Single-row Model Ops table from `fetchModelInfo()` (`GET /v1/model`)
- [x] Metrics rendered generically from `modelInfo.metrics`
- [x] Stage chip from real MLflow stage / not-loaded
- [x] "Fine-tune" wired to `triggerTraining()` → `POST /v1/model/train`
- [x] "View model registry" → `/dashboard/models/`
- [x] Model Training & Tuning form (regions + window hours only)
- [x] Recent versions via `GET /v1/model/versions`
- [x] Active Tasks `model_training` rows from `GET /v1/model/training-runs`

### Still open

Track in root `TODO.md` Model Operations phases 0–6 (promote CTA, poll
training-runs for failure, full retrain UI, preflight, quality gates, page
KPI cleanup).

## Active Tasks

**No generic task/job abstraction exists in this platform at any layer** — confirmed: data-pipeline
tracks ingestion *runs* (status: success/failed/running/staged/sync_failed/queued/partial; no 0–100
progress field), and nothing tracks "model_training"/"data_quality"/"feature_build" as a
schedulable, progress-bearing unit anywhere. The mock's `TaskType` union (ingestion / model_training
/ data_quality / feature_build) and its `progress: number` field are both invented wholesale.

**Design decision needed before implementing** (flagging, not deciding): the closest real analogue
is `fetchPublicRuns()` (`GET /v1/ingestion/public/runs`, already built for the Ingestion page's Runs
tab) — real `id`/`pipeline_id`/`status`/`trigger`/`started_at`/`finished_at`/`duration_ms`. Two
honest paths forward:
  1. **Recommended**: rename the tab "Recent Ingestion Runs" and wire it to `fetchPublicRuns()`
     directly, dropping the multi-type `TaskType` concept entirely (only ingestion is real) and the
     `progress` percentage (no real endpoint reports partial completion — check how the Ingestion
     page's own Runs tab already displays a `running`/`staged` row without a progress bar, and match
     that pattern for consistency rather than re-solving it here).
  2. Leave the tab explicitly labeled illustrative/mock (same treatment as the Ingestion page's
     "Builder" tab) if product wants to keep the generic "any kind of task" framing for a future
     real task-queue system that doesn't exist yet — but then the tab needs a visible "illustrative"
     marker, not silence, per this session's standing rule against unlabeled fabrication.
- [ ] Pick one of the two paths above before writing code.
- [ ] If path 1: `TaskStatusChip`'s 4-state map (running/queued/completed/failed) roughly matches
      `RunStatus`'s real values close enough to reuse with a small remap (`staged`→queued-ish,
      `partial`→its own state, `sync_failed`→failed) — decide the exact mapping during implementation,
      don't silently drop statuses the real data can actually return.
- [ ] The status-count tabs ("All (n) / Running (n) / Queued (n) / Completed (n) / Failed (n)") stay
      structurally the same either way, just recomputed from real run statuses instead of the mock
      array.
- [ ] **KPI row tie-in**: "Active Tasks" KPI → if path 1 is chosen, becomes a real running/staged
      count from `scheduler.queue_depth` (exactly what Operations' "Pending Jobs" KPI already uses)
      rather than a task-queue size that doesn't exist.

## Model Training & Tuning

**No real backend capability exists for this at all** — no train-trigger endpoint, no
hyperparameter-tuning endpoint, anywhere in forecast-api or data-pipeline (confirmed: every route in
both services was read directly from source, not inferred from either service's own possibly-stale
`TODO.md`). The "Select Model" dropdown's 4 options are the same fictional multi-model roster as
Model Operations above; "Training Data Range", "Environment", "Compute Resource", "Experiment Name"
have no corresponding config surface on any real endpoint either.

- [ ] **Do not wire this form to anything** — there is nothing to wire it to. Replace the entire
      card with an honest "not available yet" notice (matching the Ingestion page's "Builder" tab
      precedent: state plainly that training/tuning triggers aren't built, rather than leaving an
      interactive-looking form whose Submit button does nothing when clicked). This is a product/UX
      call on how much of the form's visual design to keep vs. how prominently to disclose
      unavailability — flagging for a decision, not prescribing the exact layout.
- [ ] If keeping any part of the form as a preview of a future feature, at minimum disable the
      "Start Training" button and replace the model dropdown's options with the single real model
      name from `fetchModelInfo()`, not the 4 fictional ones.

## Scheduled Operations

Partially real: ingestion pipelines already carry a real cron schedule
(`LivePipeline.schedule.cron`/`.timezone`/`.enabled`) and the scheduler endpoint's `upcoming_runs`
gives real next-run timestamps — same data Pipeline Operations (above) and Operations' page already
use. Model-training schedule rows ("Daily Model Retraining", "Weekly Model Evaluation") have **no
real backing** — no training scheduler/cron exists anywhere (same gap as Model Training & Tuning /
Recent Training Runs).

- [ ] Replace `getScheduledOps()`'s 5 rows with real ones derived from `fetchPublicPipelines()` +
      `fetchPublicScheduler()` (both already built, zero new backend): one row per pipeline with
      `Schedule Name` = pipeline name, `Cron Expression` = `schedule.cron` (+ `schedule.timezone`),
      `Next Run` = matching entry in `scheduler.upcoming_runs` by `pipeline_id` (falls back to "—"
      if the pipeline is paused/disabled, since disabled pipelines are excluded from `upcoming_runs`
      — confirmed by reading `get_scheduler_status`'s `continue` when `not enabled`), `Last Run` =
      `schedule.last_run_at` (i.e. `last_run_at` on the pipeline), `Status` = `enabled ? "active" :
      "paused"`.
- [ ] **Drop the model-training schedule rows entirely** rather than leaving them mock — there is
      nothing real to attach them to, and keeping fictional cron rows next to real ingestion ones in
      the same table would make the fake ones look equally credible.
- [ ] `Task Type` column becomes redundant once every row is ingestion — consider dropping the column
      rather than keeping a single-value column around.
- [ ] Actions column (Info/Edit/More) — same as Pipeline Operations, no real edit-schedule endpoint
      exists; disable with tooltip, don't wire.
- [ ] **KPI row tie-in**: "Next Retrain" KPI — **no real backing** (no training scheduler exists;
      same gap this section documents). Replace with "Next Scheduled Run" sourced from
      `scheduler.upcoming_runs[0]` (real) — same fix Operations' page already made for its identical
      KPI. Word the label/sub carefully so it reads as the next *ingestion* run, not a training run,
      given this page's heavy model-training framing elsewhere — avoid recreating the exact kind of
      misleading adjacency the mock already has.

## Recent Training Runs

**Blocked on the same Phase 4 MLflow decision root `TODO.md` already flags** (`## MLflow / training
history` section): no endpoint anywhere proxies MLflow's run history, and forecast-api's `GET
/v1/model` is a thin current-snapshot, not a list of past runs. The mock's 5 rows (v2.3.1 down to
v2.0.0, each with independent MAPE/RMSE) have zero backing.

- [ ] Don't implement anything here until the Phase 4 MLflow decision is made (proxy MLflow's
      tracking API / link out to the real MLflow UI / leave explicitly-labeled mock) — same 3 options
      root `TODO.md` already lists for Model Registry and Training & Experiments. This section is the
      same underlying gap, not a new one.
- [ ] In the meantime, if this section must show *something*, the single real `modelInfo` row from
      Model Operations above could stand in as "current production version" (1 row, honestly
      labeled, not backfilled with 4 fake prior versions to fill out a list).

## System Commands

Six fabricated commands, checked individually against every real route in both backend services:

- [ ] **"Rebuild Features" — no real endpoint.** Feature engineering happens inline during forecast
      inference (`service/ml/features.py`), not as a standalone triggerable job. Drop, don't disable
      — there's no future real endpoint this is even a plausible placeholder for without new backend
      design work.
- [ ] **"Refresh Materialized Views" — real endpoint exists but is auth-blocked.** Maps to `POST
      /v1/dbt/{build,run,test}` (confirmed: `require_roles("admin")`, data-pipeline's own JWT domain,
      no public mirror). Keep the card but disable the Execute button with a tooltip explaining the
      auth gap — same "real but unreachable from here" treatment as Pipeline Operations'
      pause/resume, not a silent drop, since this one really would work if the auth-bridging decision
      root `TODO.md` flags ever gets made.
- [ ] **"Clear Cache" — no real endpoint.** (Redis caching exists internally in both forecast-api and
      data-pipeline for response caching, but nothing exposes a manual flush.) Drop.
- [ ] **"Reindex Search" — no real endpoint, and no search system exists at all.** The dashboard's
      topbar "Search anything…" box (visible on every page) has no backend behind it either — this
      command is fictional twice over. Drop.
- [ ] **"Vacuum Database" — no real endpoint.** Drop.
- [ ] **"System Diagnostics" — fully real, direct substitution available.** Wire to `lib/health.ts`'s
      `fetchAllServicesHealth()` (already built for Operations this session) — clicking "Execute"
      here can genuinely re-run the same 3-service health check and show real results, not a canned
      "diagnostics passed" message. The one System Command on this page that's a clean win.
- [ ] **KPI row tie-in**: "System Load" KPI → **no real backing** (no CPU/memory metrics endpoint
      exists anywhere). Replace with "Services Healthy" (n/3 from `fetchAllServicesHealth()`, already
      built for Operations — direct reuse, zero new code) rather than inventing a different
      substitute.
- [ ] Net result: this section shrinks from 6 cards to 2 (System Diagnostics, fully wired; Refresh
      Materialized Views, wired-but-disabled with an honest reason) unless product wants placeholder
      cards kept for the 4 dropped ones with an explicit "not available" label instead of removal —
      flagging as a call to make during implementation, not deciding here.

---

## Not part of this plan

- The Phase 4 MLflow decision (Model Training & Tuning, Recent Training Runs) — already an open,
  undecided item in root `TODO.md`; this page just has two more sections blocked on the same
  decision, not a new one to resolve here.
- The data-pipeline / forecast-api write-endpoint auth-bridging question (Pipeline Operations, Model
  Operations, Scheduled Operations, System Commands' "Refresh Materialized Views") — already flagged
  as a standing decision in root `TODO.md`'s "Ingestion pipeline public API" section (build a real
  backend-for-frontend proxy vs. keep everything read-only from the dashboard); every disabled
  action button on this page is downstream of that same undecided call, not a page-specific new
  blocker.
