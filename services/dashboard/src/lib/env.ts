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
 * `/v1/healthz` healthcheck there).
 *
 * `WAREHOUSE_API_URL` added alongside the Pipeline Operations tab's
 * cutover off `data-pipeline` — `services/waerehouse` runs its own
 * FastAPI control plane on port 8004 (`docker-compose.yml`'s
 * `warehouse:` service).
 *
 * **Cutover (this change)**: `lib/ingestion.ts`'s pipeline-listing/run/
 * backfill functions now read from `INGESTION_API_URL`
 * (`GET /v1/ingestion/public/pipelines`, `POST /v1/data-sources/{id}/
 * run`, etc. — real, unauthenticated equivalents already existed in
 * `services/ingestion`, confirmed against its own source before
 * switching) and the dbt-build trigger now reads from
 * `WAREHOUSE_API_URL` (`POST /v1/dbt/build`, newly added there — dbt
 * always belonged to the warehouse service, not data-pipeline).
 * `DATA_PIPELINE_API_URL` is kept below and still used for everything
 * this pass didn't touch: ML training/model-registry routes (Model
 * Operations tab — training hasn't moved services, a separate,
 * deliberately out-of-scope migration) and the 3 ingestion-page
 * endpoints (`public/failed`/`public/retry-queue`/`public/scheduler`)
 * `services/ingestion` doesn't have equivalents for yet.
 */

export const IAM_API_URL =
  process.env.NEXT_PUBLIC_IAM_API_URL ?? "http://localhost:8000/api/v1";

export const FORECAST_API_URL =
  process.env.NEXT_PUBLIC_FORECAST_API_URL ?? "http://localhost:8002/v1";

export const DATA_PIPELINE_API_URL =
  process.env.NEXT_PUBLIC_DATA_PIPELINE_API_URL ?? "http://localhost:8001/v1";

export const INGESTION_API_URL =
  process.env.NEXT_PUBLIC_INGESTION_API_URL ?? "http://localhost:8003/v1";

export const WAREHOUSE_API_URL =
  process.env.NEXT_PUBLIC_WAREHOUSE_API_URL ?? "http://localhost:8004/v1";

/** IAM's health routes (`/`, `/db_health`) live at the app root, not
 * under `/api/v1` like every other IAM route this dashboard calls. */
export const IAM_BASE_URL = IAM_API_URL.replace(/\/api\/v1\/?$/, "");
