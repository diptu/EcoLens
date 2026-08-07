/**
 * Backend base URLs — the single place these are defined.
 *
 * Every other lib file imports from here instead of declaring its own
 * copy. Before this file existed, `auth.ts`, `dashboards.ts`,
 * `emissions.ts`, `health.ts`, `data-quality.ts`, and `ingestion.ts` each
 * had their own hardcoded fallback for the same env var — they'd drifted
 * out of sync (IAM's fallback was wrong in some, forecast-api's in
 * others), which is exactly the kind of bug a single source of truth
 * avoids. Update `.env.local` to change the actual dev URLs (that's the
 * normal, code-free way to do it); only touch the fallbacks below if
 * the *default* itself needs to change (e.g. a new teammate's default
 * port layout).
 *
 * Values below match `.env.local`'s own documented canonical port map
 * (from `make dev`'s printed service list): iam 8000, data-pipeline
 * 8001, forecast-api 8002.
 *
 * `INGESTION_API_URL` added 2026-08-07 — `services/ingestion` (the
 * Celery-based rewrite of `data-pipeline`'s ingestion half,
 * `services/ingestion/TODO.md`) runs its own FastAPI app on port 8003
 * (`docker-compose.yml`'s `ingestion:` service, confirmed real
 * `/v1/healthz` healthcheck there) but had no entry here at all until
 * now — this dashboard had zero way to reach it, which is exactly why
 * nothing here noticed when its worker/beat processes silently died
 * (see `TODO.md`'s "Frontend integration" section). Additive only:
 * still reads exclusively from `DATA_PIPELINE_API_URL` for every actual
 * data-serving page — this just makes the service reachable for health
 * monitoring, not a cutover.
 */

export const IAM_API_URL =
  process.env.NEXT_PUBLIC_IAM_API_URL ?? "http://localhost:8000/api/v1";

export const FORECAST_API_URL =
  process.env.NEXT_PUBLIC_FORECAST_API_URL ?? "http://localhost:8002/v1";

export const DATA_PIPELINE_API_URL =
  process.env.NEXT_PUBLIC_DATA_PIPELINE_API_URL ?? "http://localhost:8001/v1";

export const INGESTION_API_URL =
  process.env.NEXT_PUBLIC_INGESTION_API_URL ?? "http://localhost:8003/v1";

/** IAM's health routes (`/`, `/db_health`) live at the app root, not
 * under `/api/v1` like every other IAM route this dashboard calls. */
export const IAM_BASE_URL = IAM_API_URL.replace(/\/api\/v1\/?$/, "");
