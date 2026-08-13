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

---

# Deployment: dockerize + deploy standalone on Railway (2026-08-12)

Overall target topology: `ingestion`, `services/waerehouse`, and
`services/forecast-api` each deployed as their own independent Railway
project/service group (not one combined deploy), `services/dashboard` on
Vercel. This section is ingestion's own slice of that split — the other
two services need their own equivalent plan, not written here.

## Current real state (verified by inspection, not assumed)

- **Already dockerized.** `infra/docker/ingestion.Dockerfile` exists,
  builds, and is already a real multi-stage image (`builder` with
  `uv sync --frozen` → slim `runtime` copy, no `uv`/apt caches shipped).
  `ENTRYPOINT ["ecolens-ingestion"]` + `CMD ["serve"]`, so the exact same
  image already serves all three real process roles docker-compose runs
  today (`ingestion` = `serve`, `ingestion-worker` = `worker --loglevel=
  info`, `ingestion-beat` = `beat --loglevel=info`) purely via a command
  override. **There is no "dockerize" task left to do** — the real work
  below is entirely deployment configuration, not image-building.
- **Config is already env-var-driven** (`app/core/config.py`,
  pydantic-settings) — no hardcoded `postgres`/`redis`/`rabbitmq` Docker
  Compose service-name assumptions anywhere in this service's own code.
  Good Railway fit already, confirmed, not aspirational.
- **The cross-machine handoff problem is already solved.**
  `docs/runbooks/independent-service-deployment.md` (existing, real,
  read in full for this plan) documents that `services/ingestion`
  writes staged rows to R2 *and* local DuckDB on every run, and both
  downstream consumers (`services/waerehouse`'s `landed_events`,
  `services/data-pipeline`'s legacy `warehouse_sync`) already fall back
  to downloading the run's snapshot from object storage
  (`read_run_with_fallback`) when the shared local file isn't there.
  **This means Railway needs zero shared Volume between `ingestion` and
  `warehouse`** — real Cloudflare R2 credentials on both sides is the
  actual requirement, not a Docker named volume, and that requirement
  already exists in code today.
- **Health endpoint already exists**: `GET /v1/healthz` (no dependency
  checks by design, per that route's own docstring — just proves the
  process is up), maps directly onto Railway's own per-service HTTP
  healthcheck config.
- **CI already builds real images for 3 of 4 backend services, not
  ingestion yet.** `.github/workflows/docker.yml` builds+pushes
  `data-pipeline`/`forecast-api`/`warehouse` to GHCR on every push to
  `main`/version tags (PRs build-only, no push) — its own comment says
  plainly `ingestion` "isn't in this matrix yet either... this workflow
  builds the images that actually exist and were in scope." Confirmed
  by reading the file — this is a real, small, mechanical gap, not a
  design decision anyone made on purpose.
- **`.github/workflows/deploy-ingestion-service.yml` implemented**
  (2026-08-13) — the real Railway deploy trigger for this service's own
  3-service Option A topology (`ingestion-api`/`ingestion-worker`/
  `ingestion-beat`), matching this section's own plan. The sibling
  `deploy-{forecast,waerehouse,dashboard,obsirvility}-service.yml` stubs
  are also implemented now (Railway/Vercel/SSH respectively, whichever
  fit each service) — see each workflow's own header comment and
  `docs/runbooks/github-actions-secrets.md` for the real secrets each
  needs.

## Real gaps found during this audit (not yet fixed, need a decision or a fix)

- [ ] **`meta.*` schema origin is genuinely unknown.** Searched this
      service, `services/waerehouse/app/migrations/*.sql` (owns
      `raw`/`marts`, confirmed by reading all 10 files), and
      `infra/docker/postgres/init/` (referenced by root
      `docker-compose.yml` as Postgres's init-script mount, but the
      directory is empty on disk) for whatever creates `meta._ingest_log`
      / `meta.anomalies` / `meta.data_sources` / `meta._training_log` /
      `meta._dbt_build_log`. Found nothing — no Alembic anywhere in the
      repo, no raw-SQL migration, no `Base.metadata.create_all()` call in
      any service's startup path. One real clue:
      `services/waerehouse/app/loaders/ingest_log.py`'s own docstring
      claims "services/ingestion's own migrations create it" — but no
      migrations directory exists in `services/ingestion` today. Either
      that comment is stale (pointing at something that got deleted
      during the extraction-from-data-pipeline split) or the real DDL
      was applied by hand once, directly against the shared dev Postgres,
      and never captured anywhere durable. **This blocks a real Railway
      deploy concretely**: a fresh Railway Postgres plugin starts
      completely empty, and `meta._ingest_log` not existing yet fails
      this service's very first ingest run (`standard_run` writes to it
      unconditionally). Needs a real answer before Phase 1 below, not a
      guess — either locate the actual source (ask whoever ran the
      original local setup) or reverse-engineer the DDL from
      `\d meta._ingest_log` etc. against the current live dev database
      and check a real migration file in.
- [x] **`serve` doesn't read Railway's `$PORT`.** Fixed 2026-08-12:
      `app/cli.py`'s `serve` now resolves the port as explicit `--port` >
      `PORT` env var (Railway/Heroku-style convention, previously never
      read at all) > `Settings.api_port` (8003, unchanged default for
      local/Compose use).

## Dockerfile hardening (done, 2026-08-12)

Real prod-grade gaps found and fixed in `infra/docker/ingestion.Dockerfile`
— verified against an actual local `docker build` + `docker run` this
pass, not just read-and-assumed:

- [x] **Repo-root `.dockerignore` added** (new file, shared by every
      `infra/docker/*.Dockerfile` — all use `context: .`). Real, measured
      problem it fixes: with no `.dockerignore` at all, this service's
      own `COPY services/ingestion .` step was baking a stale,
      git-tracked 10MB `data/staging/landed.duckdb` + 13MB
      `data/training/master.duckdb` (real local dev-seed data, not
      anything a fresh prod container should start pre-loaded with)
      directly into the image. Confirmed fixed: a real build afterward
      shows `data/staging/` and `data/training/` present but empty of
      those files, `data/staging/models/**/*.joblib` (the anomaly
      pipeline's real, small, actually-loaded-at-runtime artifacts)
      correctly still included.
- [x] **Non-root runtime user.** Fixed UID/GID (10001), `--chown` on the
      `COPY --from=builder` and on `data/staging` (the one directory the
      app actually writes to at runtime). Verified: `docker run --entrypoint
      id` reports `uid=10001(app) gid=10001(app)`, not root.
- [x] **`tini` as real PID 1**, wrapping `ecolens-ingestion` rather than
      execing it directly — matters most for the `worker` role, whose
      Celery prefork pool forks real OS child processes per task (PID-1
      zombie-reaping/signal-forwarding responsibilities have no default
      handler without an init process). Verified by inspecting
      `/proc/1/comm`/`/proc/*/status` inside a running container:
      `tini` is PID 1, `ecolens-ingestion` is its direct child (not PID 1
      itself), for all three subcommands (`serve`/`worker`/`beat`).
- [x] **`PYTHONUNBUFFERED=1`/`PYTHONDONTWRITEBYTECODE=1`** — real-time
      log visibility (no stdout buffering delay in a container/log-
      aggregation context) and no `.pyc` writes into what may become a
      read-only or ephemeral filesystem.
- [x] **End-to-end verified, not just built**: real `docker build`
      (907MB final image, multi-stage already kept build-only layers —
      `uv`/apt caches/dependency-resolution intermediates — out of the
      shipped result), then `docker run` of all three subcommands.
      `serve` confirmed listening on `0.0.0.0:8003` and returning a real
      `{"status":"ok"}` from `/v1/healthz` (checked via an in-container
      request — the host-side port mapping hit an unrelated local Docker
      Desktop networking quirk, not a defect in the image itself).
      `worker`/`beat` both start cleanly under the new non-root/`tini`
      setup with no permission or invocation errors (no real RabbitMQ
      available in this ad-hoc test, so Celery's own quiet broker-
      connection-retry loop is expected, not a failure).
- [ ] **RabbitMQ has no first-party Railway plugin.** Unlike
      Postgres/Redis (both real, first-party Railway database plugins),
      RabbitMQ needs either an external managed instance (CloudAMQP —
      has a real free tier, simplest option, recommended for a first
      cut) or self-hosting RabbitMQ as its own Railway service from a
      community template (real persistent Volume + real ops burden this
      service doesn't currently need to own). This is a real, load-
      bearing dependency, not optional: `celery_app.py`'s broker
      (`_settings.rabbitmq_url`) and `db.rabbitmq.publish_landed_event`'s
      cross-service landed-event notification to `warehouse` are **the
      same URL/instance** today — whichever RabbitMQ this service points
      at, `warehouse`'s deploy must point at the identical instance, or
      the landed-event handoff silently never reaches it.

## Architecture decision: keep Celery worker+beat, or go Railway-native cron?

Two real options, not obviously one-sided — recommending A for the first
real deploy, with B flagged as a genuine follow-up once this service has
been live on Railway for a while.

**Option A — mirror docker-compose 1:1 (recommended for the first cut).**
Three Railway services, same image, same repo, differing only by start
command:
- `ingestion-api` — start command `ecolens-ingestion serve` (or blank,
  since that's already the image's default `CMD`)
- `ingestion-worker` — start command `ecolens-ingestion worker
  --loglevel=info`; safe to run >1 replica (Celery workers just compete
  for the same queue, no coordination needed)
- `ingestion-beat` — start command `ecolens-ingestion beat --loglevel=
  info`; **must stay at exactly 1 replica, always** — this is the sole
  scheduler, same constraint `docker-compose.yml`'s own comment on this
  service already documents. Never enable Railway autoscaling here.

Use the *full* command (`ecolens-ingestion worker ...`, not just
`worker ...`) as each Railway start-command override rather than relying
on the image's `ENTRYPOINT` being preserved and the override only
replacing `CMD` — that's standard `docker run`/Compose `command:`
semantics, but Railway's own start-command override behavior should be
verified against a real trial deploy before trusting it silently, since
it isn't confirmed here one way or the other. The fully-qualified form
works correctly regardless of which semantic Railway actually implements.

**Option B — Railway-native, fewer always-on processes.** Drop the
`ingestion-worker`/`ingestion-beat` pair entirely; replace the 30-minute
ingest cadence with a Railway Cron Job (a first-class Railway deploy type
that runs the built image fresh on a schedule, bills only for actual run
duration) invoking the ingest CLI directly instead of going through
Celery at all. RabbitMQ is *still* required either way (for
`publish_landed_event`'s real cross-service handoff to `warehouse`), but
stops being this service's own internal task broker too — a smaller
real footprint. Real, unresolved question this option needs answered
first: `app/cli.py`'s `ingest` group is per-source
(`ingest {oe,aemo-nem,aemo-wem,bom,holidays}`) — need to confirm whether
there's a real "all sources, one call" CLI path equivalent to
`ingest_all_sources_task`'s `celery.group` fan-out (parallel, one slow
source doesn't block the others) before treating this as a drop-in
replacement; if there isn't one, either add it or accept 5 separate
Railway Cron Jobs (one per source) instead of one. Not chosen for the
first cut because it's a real behavior change (loses whatever Celery-
level retry/visibility the worker provides today) layered on top of an
already-multi-part migration — do this once Option A is live and boring,
not simultaneously with it.

## Phased checklist

### Phase 0 — resolve the real blockers above

- [ ] Find or reconstruct the real `meta.*` schema DDL and check it into
      a real migration file (in whichever service should own it —
      probably `services/waerehouse`, since it already owns `raw`/
      `marts`'s migrations) before touching Railway at all. Deploying
      against a schema that doesn't exist yet fails loudly on the very
      first write, not silently — but better to know now.
- [ ] Fix `serve` to honor `PORT` when Railway sets it (see gap above).
- [ ] Decide CloudAMQP vs. self-hosted RabbitMQ-on-Railway (see gap
      above) — this choice also constrains `warehouse`'s own deploy
      plan, so make it once, here, and reuse it there.

### Phase 1 — provision the real managed dependencies

- [ ] Railway Postgres plugin (or point at an existing external Postgres
      if this is meant to share the same database `warehouse`/
      `forecast-api` use — confirm which before provisioning a second,
      empty one by accident).
- [ ] Railway Redis plugin (circuit-breaker state + backfill lock only —
      no persistence requirements beyond what Railway's own default
      gives it).
- [ ] RabbitMQ per the Phase 0 decision — same instance `warehouse`'s
      own deploy will need to be pointed at.
- [ ] Real Cloudflare R2 bucket + API token
      (`CLOUDFLARESTORAGE_ACCOUNT_ID`/`_S3_API`/`_ACCESS_KEY_ID`/
      `_SECRET_ACCESS_KEY`) — **required, not optional**, once ingestion
      and warehouse are on different machines (the runbook's own
      language). Same account/bucket `warehouse`'s deploy must read from.

### Phase 2 — CI image build (small, mechanical, mirrors existing pattern)

- [ ] Add `ingestion` to `.github/workflows/docker.yml`'s build matrix
      (`image: ingestion`, `dockerfile: infra/docker/ingestion.Dockerfile`)
      — copy the existing `data-pipeline`/`forecast-api`/`warehouse`
      entries' shape exactly, including the `pull_request.paths` trigger
      list (`services/ingestion/**` isn't in there yet either). This
      gets ingestion a real, tested-on-every-PR, versioned GHCR image
      (`ghcr.io/<repo>/ingestion:<tag>`) for Railway to deploy from,
      rather than having Railway build directly from the Dockerfile on
      every deploy (works too, but skips the PR-time build check this
      workflow already gives the other 3 services for free).

### Phase 3 — Railway service topology

- [ ] Create the 3 services from Option A above (or revisit Option B
      once this phase is otherwise done and stable) in one Railway
      project, all pointed at the same GHCR image (or same repo +
      `infra/docker/ingestion.Dockerfile` if building directly instead).
- [ ] Set every required env var from `services/ingestion/.env.example`
      on all 3 services identically (`DATABASE_URL`, `REDIS_URL`,
      `RABBITMQ_URL`, the `CLOUDFLARESTORAGE_*` block) — Railway
      variables can be shared at the project level so this isn't 3x
      manual entry.
- [ ] Set `ingestion-api`'s healthcheck path to `/v1/healthz`.
- [ ] Confirm `ingestion-beat` is pinned to 1 replica, autoscaling off.
- [ ] `OE_API_KEY`/`BOM_API_KEY` — optional (both sources already work
      anonymously/rate-limited without them, confirmed live this session
      against the real BOM historical backfill), but worth setting for
      real production data completeness rather than leaving on the
      anonymous rate limit indefinitely.

### Phase 4 — cutover and verification

- [ ] Trigger one real `ingest` run per source manually
      (`POST /v1/data-sources/{id}/run` or `ecolens-ingestion ingest
      <key>` via `railway run`) against the deployed service before
      trusting the Celery Beat schedule — confirms Postgres/Redis/
      RabbitMQ/R2 all actually reach each other over the real network
      path, not just that the container boots.
- [ ] Confirm a real landed event reaches `warehouse`'s consumer once
      that service is *also* deployed (this is a two-sided check — can't
      fully verify from ingestion's side alone).
- [ ] Watch `ingestion-beat`'s logs for the first real scheduled tick (up
      to 30 minutes) rather than assuming the crontab fired correctly.
- [ ] **Competing-consumer trap** (the runbook's own section, real and
      still applicable): if `services/data-pipeline`'s legacy
      `warehouse-sync` consumer is ever ALSO left running against the
      same RabbitMQ queue as `services/waerehouse`'s consumer, they race
      for the same messages. Not a concern if `data-pipeline` is never
      deployed alongside this Railway topology — worth one explicit
      check that it isn't, since nothing enforces that automatically.

### Phase 5 — observability (real gap, not blocking)

- [ ] `otel_traces_enabled` defaults `False`; `otel_exporter_otlp_
      endpoint` defaults to a local-only collector URL that won't exist
      on Railway. Leave tracing off until a real OTel collector endpoint
      (Grafana Cloud, Honeycomb, or self-hosted) is actually provisioned
      — turning it on against a nonexistent endpoint just adds failed
      export noise, not real observability.
- [ ] `services/observility`'s Prometheus scrape targets are env-driven
      (`INGESTION_TARGET`, per the runbook) — point it at this service's
      real Railway URL once that stack itself has a home; out of scope
      for ingestion's own deploy.
