/**
 * Service-health client for the Operations Dashboard
 * (`app/(dashboard)/dashboard/operations/page.tsx`).
 *
 * `fetchAllServicesHealth()` calls each backend service's own
 * `GET /v1/readyz` and normalizes their differently-shaped responses
 * into one `ServiceHealth[]`:
 *   - forecast-api: `{ ready, database, redis, model }`
 *     (`app/schemas/health/response.py`)
 *   - data-pipeline: `{ status, components: [{name, healthy, detail}] }`
 *     (`app/schemas/health/response.py`)
 *
 * IAM is deliberately NOT checked here -- `services/iam` was scaffolded
 * then deleted (commit `a0d36b0`, "removed unnecessary for V1") and
 * doesn't exist as a running service. `env.ts`'s `IAM_API_URL` still
 * defaults to `http://localhost:8000/api/v1`, but that port is actually
 * bound to forecast-api in `docker-compose.yml` -- probing it under an
 * "IAM" label would misattribute forecast-api's own health as IAM's.
 * Add the IAM leg back here once/if that service returns for real.
 */
import { DATA_PIPELINE_API_URL, FORECAST_API_URL } from "./env";

export type ServiceHealthComponent = {
  name: string;
  healthy: boolean;
  detail?: string | null;
};

export type ServiceHealth = {
  service: string;
  reachable: boolean;
  ready: boolean;
  latencyMs: number | null;
  components: ServiceHealthComponent[];
};

type ForecastApiReadyResponse = {
  ready: boolean;
  database: { ok: boolean; detail: string | null };
  redis: { ok: boolean; detail: string | null };
  model: { ok: boolean; detail: string | null };
};

type DataPipelineReadyResponse = {
  status: "ready" | "not_ready";
  components: { name: string; healthy: boolean; detail: string | null }[];
};

async function checkForecastApi(): Promise<ServiceHealth> {
  const started = Date.now();
  try {
    const res = await fetch(`${FORECAST_API_URL}/readyz`);
    const body: ForecastApiReadyResponse = await res.json();
    return {
      service: "forecast-api",
      reachable: true,
      ready: body.ready,
      latencyMs: Date.now() - started,
      components: [
        { name: "database", healthy: body.database.ok, detail: body.database.detail },
        { name: "redis", healthy: body.redis.ok, detail: body.redis.detail },
        { name: "model", healthy: body.model.ok, detail: body.model.detail },
      ],
    };
  } catch {
    return { service: "forecast-api", reachable: false, ready: false, latencyMs: null, components: [] };
  }
}

async function checkDataPipeline(): Promise<ServiceHealth> {
  const started = Date.now();
  try {
    const res = await fetch(`${DATA_PIPELINE_API_URL}/readyz`);
    const body: DataPipelineReadyResponse = await res.json();
    return {
      service: "data-pipeline",
      reachable: true,
      ready: body.status === "ready",
      latencyMs: Date.now() - started,
      components: body.components.map((c) => ({ name: c.name, healthy: c.healthy, detail: c.detail })),
    };
  } catch {
    return { service: "data-pipeline", reachable: false, ready: false, latencyMs: null, components: [] };
  }
}

/** Checks every backend service's `/v1/readyz` in parallel. Never
 * throws -- an unreachable service shows up as `reachable: false`
 * rather than failing the whole call, so one down service doesn't blank
 * out the others. */
export async function fetchAllServicesHealth(): Promise<ServiceHealth[]> {
  return Promise.all([checkForecastApi(), checkDataPipeline()]);
}
