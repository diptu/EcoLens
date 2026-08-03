# GitHub Actions secrets for the scheduled ingest workflows

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
