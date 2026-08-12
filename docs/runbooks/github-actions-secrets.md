# GitHub Actions secrets for the scheduled workflows

## Ingest workflows

`.github/workflows/ingest-{openelectricity,aemo,bom,holidays}.yml` run on a
`schedule` trigger (plus `workflow_dispatch` for manual runs) and need these
repo secrets configured (**Settings → Secrets and variables → Actions**)
before they'll do anything but fail fast with a clear `missing secrets`
error. None are optional — every workflow needs all of them.

| Secret | Example | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?sslmode=require` | Same DSN as this repo's local `.env`. `Settings.database_url_env` reads it directly. |
| `REDIS_URL` | `rediss://default:xxx@my-redis.upstash.io:6380` | **Must be a real, externally-reachable Redis** — see "Why not localhost" below. |
| `S3_ENDPOINT_URL` | `https://<account>.r2.cloudflarestorage.com` | Or a real MinIO/S3 endpoint. Not `http://localhost:9000` — same reason as Redis. |
| `S3_BUCKET` | `ecolens` | |
| `S3_ACCESS_KEY` | | |
| `S3_SECRET_KEY` | | |
| `OE_API_KEY` | | Only `ingest-openelectricity.yml` uses this. Free registration at OpenElectricity. Without it, every region's fetch fails gracefully (0 rows landed, not a crash) — see `ingest_openelectricity.run()`'s per-region `try/except`. |

## Warehouse monitoring workflow

`.github/workflows/warehouse-monitor.yml` runs `ecolens-warehouse dbt
source freshness` + `check-size` hourly — read-only checks only (see the
workflow's own header comment for why `prune`/`export-and-prune` are
deliberately *not* on a schedule). Needs just one secret:

| Secret | Example | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?sslmode=require` | Same secret as the ingest workflows above — reused, not a second copy. `dbt`'s own `POSTGRES_HOST`/`PORT`/`USER`/`PASSWORD`/`DB` are derived from this automatically (`Settings.dbt_postgres_env`), no separate dbt-specific secrets needed. |

## Deploy workflows (Railway: ingestion, forecast-api, warehouse)

`.github/workflows/deploy-{ingestion,forecast,waerehouse}-service.yml`
each redeploy their own service's real Railway services (`deploy-
ingestion-service.yml`: `ingestion-api`/`ingestion-worker`/`ingestion-
beat`; `deploy-forecast-service.yml`: `forecast-api`/`forecast-train-
worker`; `deploy-waerehouse-service.yml`: `warehouse-api`/`warehouse-
consumer` — each set is that service's own real process-role topology,
see each workflow's own header comment) on every push to `main` that
touches that service's own source or Dockerfile, plus manual
`workflow_dispatch`. All 3 workflows share **one** secret:

| Secret | Example | Notes |
| --- | --- | --- |
| `RAILWAY_TOKEN` | | A Railway **project** token (Railway dashboard -> project -> Settings -> Tokens), not an account/personal token -- scopes across every service in that project, so this one secret covers all 3 workflows/6 services, not a separate copy per service or per workflow. Every Railway service referenced must already exist in that project with its own start-command override and that service's full `.env.example` env-var set already configured directly in Railway -- these workflows only trigger a redeploy, they never create a service or set its variables. |

## Deploy workflow (Vercel: dashboard)

`.github/workflows/deploy-dashboard-service.yml` builds `services/
dashboard`'s real static export (`next build`, `output: "export"`) and
deploys the prebuilt `out/` directory to Vercel on every push to `main`
that touches `services/dashboard/**`, plus manual `workflow_dispatch`.
Needs 3 secrets (Vercel dashboard -> project -> Settings -> General for
the org/project IDs; Account Settings -> Tokens for the token):

| Secret | Example | Notes |
| --- | --- | --- |
| `VERCEL_TOKEN` | | Personal or team access token. |
| `VERCEL_ORG_ID` | | From the linked Vercel project's `Settings -> General` (or the `.vercel/project.json` created by a local `vercel link`). |
| `VERCEL_PROJECT_ID` | | Same source as `VERCEL_ORG_ID` above. |

Backend API base URLs (`NEXT_PUBLIC_INGESTION_API_URL`/`_WAREHOUSE_API_URL`/
`_FORECAST_API_URL`) are real Vercel **Project** env vars (Production
environment), set directly in the Vercel dashboard, not as a GitHub
secret — `vercel pull` in this workflow fetches them automatically
before the build step.

## Deploy workflow (self-hosted: observability)

`.github/workflows/deploy-obsirvility-service.yml` ships `services/
observility`'s compose/config files to a real host over SSH and runs
`docker compose up -d` there — a different shape from the 3 Railway
workflows above since this is a real stateful multi-container stack, not
a single-process service (see the workflow's own header comment for
why). Needs 3 secrets:

| Secret | Example | Notes |
| --- | --- | --- |
| `OBSERVABILITY_SSH_HOST` | `203.0.113.7` or a real hostname | The target VM/host already running (or about to run) this stack. |
| `OBSERVABILITY_SSH_USER` | `deploy` | Must be able to run `docker compose` on that host (in the `docker` group or via passwordless sudo). |
| `OBSERVABILITY_SSH_KEY` | | Private key matching a public key already in that user's `~/.ssh/authorized_keys` on the host — generate a dedicated deploy keypair, don't reuse a personal one. |

This workflow deliberately never touches the host's own `.env` (real
`GRAFANA_ADMIN_PASSWORD`/`ALERTMANAGER_WEBHOOK_URL`/retention config,
`services/observility/.env.example`'s own "copy to `.env` before `docker
compose up`" instructions) — that's real one-time manual setup on the
host itself, same "this workflow only redeploys, it never provisions
secrets" boundary the 4 workflows above keep too.

## Why not `localhost`

A GitHub-hosted runner is a fresh VM for every single run — there's no
persistent `services:`-container Redis or MinIO you could point these at
that would actually help, because:

- **`CircuitBreaker` (ECO-D07) needs Redis to persist across runs** to
  mean anything. If Redis resets every run, the breaker never actually
  protects a flaky upstream — it starts `closed` every 5/15/30 minutes
  regardless of how many times the last run failed.
- **`land_to_s3` needs a bucket that persists** — it's the audit trail /
  replay source `task.md`'s recovery playbook depends on (mode 4:
  "Partial failure: S3 succeeded, Postgres failed").

Cheapest real options: Upstash (Redis, free tier) and Cloudflare R2 or a
real S3 bucket (S3-compatible, cheap egress).

## Reliability note

GitHub's `schedule` trigger is not a real-time scheduler — it's queued,
and short intervals (`*/5 * * * *` — OpenElectricity's cadence) are the
most contended slot on their infrastructure and can run late under load.
This is a reasonable **free interim** scheduler while there's no VPS yet
(`TODO.md`'s `ECO-D59` plans a real crontab on one eventually), not a
guarantee of exact cadence. If a source's data starts arriving
consistently late, that's expected GitHub Actions behavior, not a bug
here.

## The 60-day auto-disable trap

GitHub automatically disables a workflow's `schedule` trigger if the
*repository* has had no commits for 60 days. If ingestion silently stops
and `git log` shows a stale repo, this is almost certainly why — a commit
(even a trivial one) re-enables it, or re-enable manually under **Actions
→ [workflow name] → ⋯ → Enable workflow**.
