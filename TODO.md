# TODO's

## Storage
[]store all asstets & art-effects on claudeflare R2

## Performance optimization:

- [] Prefetch Data Before Navigation: prefetch pages in the background. Ensure you are using framework-level prefetching.
-[] Stream inference updates or pipeline progress indicators back to Next.js progressively,


## FastAPI Backend: Payload Compression & Asynchronous Processing

-  []Gzip Compression Middleware: Enable built-in compression in FastAPI to drastically reduce JSON payload size for large time-series arrays.

## Response Caching & Edge Delivery

-[] FastAPI Response Caching: For heavy forecasting endpoints that only update after  5-minute cron/dbt pipeline runs, use fastapi-cache backed by Redis. This prevents FastAPI from recalculating or querying the database repeatedly for identical requests within that 5-minute window.

Cache-Control Headers: Set explicit cache headers (Cache-Control: public, s-maxage=300, stale-while-revalidate=60) on  FastAPI GET endpoints so that Vercel or CDN layers cache static historical carbon analytics closer to your users.


# Operational Tasks

## Model Operations — Fine-tune from the Model Operations tab

Companion docs (deeper / adjacent scope, not this plan's job):
- `todo-operational-tasks.md` — whole Operational Tasks page (pipelines, tasks, schedules)
- `todo-model-training.md` — multi-model research path (TimesFM / TFT / blend / pruning)

This section is specifically: **what happens when an operator clicks
"Fine-tune" on `/dashboard/operational-tasks` Model Operations**, what is
already real, what is broken/incomplete, and the multi-phase plan to make
that path production-honest end-to-end.

---

### Ground truth (verified against current code, 2026-08-04)

#### End-to-end path that already exists

```
[Operational Tasks UI]
  Model Ops card "Fine-tune" button  ──┐
  "Model Training & Tuning" form     ──┼──► lib/ingestion.triggerTraining()
                                       │      POST data-pipeline /v1/model/train
                                       │         body: { regions?, window_hours? }
                                       │         → publish_training_trigger.fn
                                       │         → RabbitMQ training-trigger queue
                                       │         ← 202 { queued_at, regions,
                                       │                 window_since/until, ... }
                                       │
[train-worker]  (data-pipeline, separate process / compose service)
  consume event ───────────────────────┘
  → INSERT meta._training_log (status=running)
  → ml.incremental.train_and_register_incremental
       · warm-start weights from Production, else Staging
       · train only on data since window_since
       · epochs/lr from Settings.incremental_train_* (not per-request)
       · register new MLflow version at stage=None (not Production)
  → UPDATE meta._training_log (success|failed + run_id + model_version)

[Dashboard completion signal]
  pollForNewModelVersion(sinceVersion)
    → GET forecast-api /v1/model/versions every 5s, up to 120s
    → stops when newest version id ≠ sinceVersion

[Serving path — separate, not part of fine-tune]
  forecast-api ModelRegistry only loads stage=Production
  hot-reloads on model_reload_interval_seconds
  promote is a separate call:
    POST forecast-api /v1/model/versions/{v}/promote { stage }
    (gated on test_mape when promoting to Production)
```

#### What is already real (do not re-build)

| Layer | Real artifact |
| :--- | :--- |
| UI — Model Ops table | Single row from `GET /v1/model` (`fetchModelInfo`) — not the old 5-model mock |
| UI — Fine-tune button | Calls real `triggerTraining()`; disables while queued/polling |
| UI — Training form | Regions + window hours only (matches real request schema) |
| UI — Models page Fine-tune tab | Same real path as Operational Tasks |
| data-pipeline | `POST /v1/model/train`, `GET /v1/model/training-runs` |
| data-pipeline | `training_worker` + `ml.incremental` warm-start fine-tune |
| data-pipeline | `meta._training_log` (migration `0021_training_log.sql`) |
| forecast-api | `GET /v1/model`, `GET /v1/model/versions`, `POST .../promote` |
| forecast-api | Production-only load + background hot-reload watch |
| Active Tasks | `model_training` rows mapped from real `training-runs` (other task types still mock) |
| Recent Training Runs | Real MLflow versions via `GET /v1/model/versions` |

#### Critical gaps (why "Fine-tune" does not yet mean "production got smarter")

1. **Register ≠ serve.** Fine-tune registers a new version at MLflow stage
   `None`. Serving only ever loads `Production`. Until someone promotes,
   forecasts are unchanged. The UI currently treats "new version appeared"
   as success and stops — it never prompts promote, never auto-promotes,
   and never refreshes the Model Ops "currently served" row for a stage
   change that hasn't happened.
2. **Completion signal is incomplete.** Polling only watches for a *new
   version id*. A failed fine-tune (empty window, no warm-start, worker
   crash, MLflow down) never registers a version, so the UI sits in
   "polling" until the 120s timeout then silently returns to idle with no
   error. Real failure lives in `meta._training_log` / DLQ and is ignored.
3. **Fake progress.** Active Tasks hardcodes `progress: 50` for running
   training rows. Nothing in the backend emits epoch-level progress to
   the dashboard.
4. **Recent Training Runs ≠ training attempts.** That card lists
   *registered MLflow versions*, so failed attempts, in-flight runs, and
   "queued but worker dead" never appear. Operators cannot tell *why*
   Fine-tune did nothing.
5. **Full retrain is still CLI-only.** Models page Train tab is disabled;
   Operational Tasks form is incremental-only. No warm-start exists until
   `ecolens-pipeline train` + promote has been run once — Fine-tune will
   hard-fail with a real `ValueError` in that bootstrap case.
6. **Ops prerequisites are invisible.** Fine-tune needs all of: RabbitMQ
   up, `train-worker` process running, MLflow reachable, warehouse data
   for the window, and a Production/Staging version to warm-start from.
   UI has no preflight / health banner for any of these.
7. **No in-flight guard.** Multiple clicks queue multiple events; worker
   serializes them. UI disables only *this browser tab's* button state.
8. **KPIs / schedules still mock** on this page for model-related numbers
   ("Next Retrain", etc.) — no real training scheduler is exposed.
9. **120s poll ceiling is optimistic.** Real incremental runs on non-toy
   windows can exceed 2 minutes; timeout leaves the job running server-side
   with the UI already idle.
10. **Stale companion docs.** `todo-operational-tasks.md` still says
    retrain/train endpoints "do not exist" — they do now. Treat *this*
    section as source of truth for Model Operations fine-tune; update
    that companion when convenient.

#### Non-negotiable design constraints (already enforced in code)

- **forecast-api never trains** — training stays in data-pipeline's
  `train-worker`. Dashboard must never call a forecast-api train route.
- **Never train inside an HTTP request** — `POST /train` only publishes;
  work is async. Do not "fix" this by running training in the API process.
- **Promotion is gated** — Production promote rejects worse `test_mape`.
  Any auto-promote path must respect (or deliberately extend) that gate.
- **Honesty over polish** — no fabricated multi-model roster, no fake
  progress bars, no success toast without a real backend signal.

---

### Phase 0 — Operator honesty (UI only, no new backend)

Goal: make the current real path *tell the truth* about what Fine-tune
does and does not do, before adding more machinery.

- [ ] Model Operations card copy: state explicitly that Fine-tune
      **registers a new candidate version** and does **not** swap
      Production by itself; link to `/dashboard/models` for promote.
- [ ] After a successful new-version poll, show a post-success panel:
      new version id + key metrics (`test_mape`, coverage if present) +
      primary CTA **"Promote to Production"** (calls existing
      `promoteModelVersion`) + secondary "View in registry".
- [ ] On promote success, re-fetch `fetchModelInfo()` so the Model Ops
      table reflects the new served version once forecast-api hot-reloads
      (or immediately shows the registry truth; note `loaded_at` may lag
      until the watch loop picks it up — surface that honestly).
- [ ] Prerequisites banner (best-effort, client-side): if
      `modelInfo.status === "not_loaded"` OR versions list is empty,
      disable Fine-tune and explain "run a full retrain + promote first
      (`ecolens-pipeline train`)" — matches `incremental.py`'s real
      `ValueError` precondition.
- [ ] Fix Models page Train-tab docstring/subtitle that still claims
      `POST /v1/model/train` "lands in Phase 2" — that endpoint exists
      and is *incremental*, not full retrain. Don't pretend the Train
      tab is wired.

**Acceptance:** an operator who only reads the Operational Tasks UI
understands: Fine-tune → new candidate; Promote → may serve; no warm-start
base → button disabled with reason.

---

### Phase 1 — Real completion loop (training-runs as source of truth)

Goal: stop using "new MLflow version appeared" as the only success
signal. Use `meta._training_log` for lifecycle; keep versions for
registry identity.

- [ ] Dashboard: after `triggerTraining()`, poll
      `fetchTrainingRuns()` (not only `pollForNewModelVersion`) until the
      newest row for this attempt is `success` or `failed`.
      Practical match key (no run id is returned by the trigger today):
      `started_at >= trigger.queued_at` + `triggered_by` in
      `{public, manual}` + `status` transition out of `running`/absent.
- [ ] On `failed`: surface `error_message` in the Model Ops card and the
      Training form (empty window, no warm-start, MLflow errors, etc.).
      Do **not** leave the UI in silent idle.
- [ ] On `success`: then fetch versions, highlight the new
      `model_version`, offer promote CTA (Phase 0).
- [ ] **Recent Training Runs** card: switch primary data source to
      `GET /v1/model/training-runs` (attempts: running/success/failed,
      window, regions, error). Keep a link to `/dashboard/models` for
      registered versions — don't conflate the two concepts in one list.
- [ ] Active Tasks `model_training` rows: drop fake `progress: 50`;
      either omit the progress bar for training or show indeterminate
      ("running…") until a real progress channel exists (Phase 4).
- [ ] Raise / make configurable the client poll timeout (default ≥ 10 min
      for fine-tune; 120s is too short for real windows). Cancel on
      unmount (already done) and on explicit "Dismiss".
- [ ] Optional small backend nicety (only if matching by timestamp proves
      flaky): return a `training_log_id` (or correlation id) from
      `POST /train` by inserting a `queued` row *at publish time*, then
      have the worker claim/update that row. Today the log row is only
      created when the worker *starts*, so a dead worker is invisible.

**Acceptance:** kill `train-worker`, click Fine-tune → UI eventually
shows a clear failure/timeout, not a quiet return to idle. Successful
run shows the training-log row *and* the new version.

---

### Phase 2 — Candidate staging + one-click promote from Operational Tasks

Goal: close the "registered but invisible to serving" gap with the
minimum safe automation.

- [ ] **Decision (record here before coding):** on successful fine-tune,
      should `log_and_register_run` / incremental path auto-transition the
      new version to **Staging** (not Production)? Recommended: **yes** —
      Staging is ungated, makes candidates discoverable in
      `get_warm_start`'s fallback order, and matches the Models page
      mental model. Production stays manual or gate-auto (Phase 3).
- [ ] If auto-Staging: implement in data-pipeline only
      (`mlops.registry.transition` after register when
      `training_type=incremental`), tag the run, unit-test it.
- [ ] Operational Tasks Model Ops: inline **Promote** on the latest
      non-Production candidate (reuse `promoteModelVersion`). Handle 409
      `worse_than_production` with the server message, not a generic error.
- [ ] After Production promote: poll `fetchModelInfo()` until
      `version` matches (or timeout + "registry updated; serving reload
      may take up to N seconds" using `model_reload_interval_seconds`
      if exposed, else a documented default).
- [ ] Models page and Operational Tasks must not diverge: shared helper
      for "trigger fine-tune → watch training-runs → optional promote"
      in `lib/` (today the two pages duplicate poll/trigger logic).

**Acceptance:** Fine-tune from Operational Tasks → new version in
Staging (if that decision is yes) → one click Promote → Model Ops table
shows the new Production version without leaving the page.

---

### Phase 3 — Full retrain from the same ops surface

Goal: bootstrap and periodic reset without SSH/`make train`. Fine-tune
depends on this existing at least once.

- [ ] Backend: `POST /v1/model/train` grows a mode (recommended):
      `{ "mode": "incremental" | "full", ... }` default `incremental`
      for backward compatibility. `full` publishes a distinct event
      (or same queue with `training_type=full`) that the worker routes to
      `train_and_register` instead of `train_and_register_incremental`.
      Do **not** run full retrain in the API process.
- [ ] Request fields for `full`: regions + optional history window
      (days) + optional hyperparams *only if* `TrainConfig` is extended
      to accept overrides; until then, only expose what the worker
      actually honors (regions), and keep epochs/hidden/etc. as
      Settings-driven — same honesty rule as the current Fine-tune form.
- [ ] Worker: branch on mode; log `training_type=full|incremental` on
      both MLflow tags and `meta._training_log` (may need a column or
      encode in `triggered_by` / new `training_type` column — prefer an
      explicit column if touching the migration).
- [ ] UI: Models page **Train** tab becomes the full-retrain form
      (enable submit). Operational Tasks keeps Fine-tune as the primary
      action; add a secondary "Full retrain…" link to Models Train tab
      rather than cramming two forms into one card.
- [ ] Prerequisites banner from Phase 0 flips: empty registry → offer
      Full retrain CTA instead of only a CLI hint.

**Acceptance:** empty registry → Full retrain from Models UI → version
registered → promote → Fine-tune on Operational Tasks works without CLI.

---

### Phase 4 — Reliability, preflight, and progress

Goal: make Fine-tune safe to click in a real multi-operator / flaky-deps
environment.

- [ ] **Preflight endpoint or composite client check** before enabling
      Fine-tune:
      - MLflow reachable (forecast-api versions list or a tiny
        data-pipeline health detail)
      - `train-worker` liveness (new signal needed — options: heartbeats
        in Redis, "last consumer ack" metric, or "no running row + queue
        depth" from RabbitMQ management). Pick one; document it.
      - Warm-start base exists (Production or Staging version)
      - Optional: recent warehouse data present for the requested window
        (cheap `COUNT` / max(ts) — only if cheap enough; otherwise skip)
- [ ] **In-flight guard:** if `training-runs` has `status=running`,
      disable Fine-tune globally (all tabs) with "training in progress
      since …". Optionally still allow queueing with an explicit
      "Queue another" confirm — default deny.
- [ ] **MLflow as a real compose service** (persistent backend + artifact
      store) — currently often a manual `mlflow server` on :5001 that
      dies on reboot; Fine-tune fails closed without it. Tracked also
      under storage/infra notes; blocks reliable demos.
- [ ] **Progress (optional, only if cheap):** worker logs epoch N/M to
      `meta._training_log` (JSONB `progress` column) or Redis key;
      dashboard polls it. If not built, keep indeterminate UI — never
      fake 50%.
- [ ] **DLQ visibility:** surface or link training-trigger DLQ depth
      (ops) so repeated failures aren't only in RabbitMQ UI.
- [ ] Streaming to the dashboard (related root TODO "Stream inference
      updates or pipeline progress"): SSE/WebSocket for training-run
      status would replace poll loops — nice-to-have after poll path is
      correct, not a prerequisite.

**Acceptance:** with worker down or MLflow down, Fine-tune is disabled
*or* fails fast with a specific reason within seconds. Concurrent double
submit does not surprise the operator.

---

### Phase 5 — Quality gates on the Fine-tune → Production path

Goal: automatic or semi-automatic promote only when the candidate is
actually better on fresh data — not only on training-time `test_mape`.

- [ ] Before offering "Promote" (or before auto-promote), run / display
      a **fresh evaluation** on a holdout window *after* the fine-tune
      training window (walk-forward piece from
      `todo-model-training.md` Phase 0 `evaluate.py` — build that harness
      once, reuse here).
- [ ] Extend promote gate options:
      - keep current `test_mape` comparison (already real)
      - add optional live-window MAPE / coverage check
      - configurable tolerance (allow tiny regressions for latency/size
        later; not needed until pruning)
- [ ] **Auto-promote policy** (explicit config, default off):
      `incremental_auto_promote=true` only if gate passes; otherwise
      leave Staging and notify Operational Tasks / logs.
- [ ] Catastrophic-forgetting / weight-drift metric vs last full retrain
      (see `todo-model-training.md` Phase 4) — log to MLflow; show on
      candidate row if above threshold ("recommend full retrain").
- [ ] Periodic **full retrain** schedule via Prefect (`training_due`
      already exists in `pipeline.flows` but is not a real deployment
      cadence for reset) — Operational Tasks "Scheduled Operations"
      gains one *real* model row only when this schedule exists; until
      then do not invent cron rows.

**Acceptance:** a deliberately overfit short-window fine-tune is
refused for Production (409 or UI block) with a readable reason; a
genuinely improved candidate can promote in one click or auto.

---

### Phase 6 — Page-level finish (Model Ops adjacency on Operational Tasks)

Once Phases 0–2 work, clean the rest of the page so Model Operations
isn't surrounded by fiction.

- [ ] KPIs: replace mock model KPIs with real ones —
      `fetchModelInfo()` (version/stage), running training count from
      `training-runs`, next *ingestion* run from scheduler (label
      honestly — not "Next Retrain" until Phase 5 schedule exists).
- [ ] Scheduled Operations: wire ingestion schedules only; add model
      fine-tune/full-retrain rows only when Prefect deployments are real.
- [ ] System Commands: keep only real actions (see
      `todo-operational-tasks.md`); drop vacuum/reindex fiction.
- [ ] Active Tasks: either (a) only real training + real ingestion runs,
      or (b) keep other types behind an explicit "illustrative" marker —
      no silent mixed fiction.
- [ ] Sync `todo-operational-tasks.md` Model Operations / Training
      sections with this file so the two docs stop contradicting each
      other.

**Acceptance:** Operational Tasks can be demoed without apologizing for
half the cards; every enabled button has a real backend effect.

---

### Suggested implementation order (if doing this now)

| Priority | Phase | Why |
| :--- | :--- | :--- |
| P0 | Phase 0 | Cheap, stops misleading operators immediately |
| P0 | Phase 1 | Without failure visibility, Fine-tune is undebuggable |
| P1 | Phase 2 | Completes the product promise: fine-tune can affect serving |
| P1 | Phase 3 | Unblocks empty-registry / bootstrap without CLI |
| P2 | Phase 4 | Needed before multi-user or flaky-infra use |
| P2 | Phase 5 | Needed before any auto-promote or "set and forget" |
| P3 | Phase 6 | Page polish once the model path is trustworthy |

### Out of scope here (tracked elsewhere)

- TimesFM / TFT / blend experts → `todo-model-training.md`
- Structured pruning + recovery fine-tune → same
- Cloudflare R2 artifact storage → Storage section above
- Gzip / Redis response cache for forecast payloads → Performance sections above


