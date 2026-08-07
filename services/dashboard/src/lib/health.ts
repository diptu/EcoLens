/**
 * Cross-service health client — the 4 real, differently-shaped health
 * endpoints this platform actually has:
 *
 *   - forecast-api:  GET /v1/readyz  -> { ready, database, redis, model }
 *   - data-pipeline: GET /v1/readyz  -> { status, components: [{name,healthy,detail}] }
 *   - ingestion:     GET /v1/readyz  -> { status, components: [{name,healthy,detail}] }
 *   - IAM:           GET /           -> { server, service, version }  (liveness only)
 *                    GET /db_health  -> { database: "healthy" } | 500 w/ error detail
 *
 * No single endpoint reports whole-platform health and there's no 5th
 * aggregator service — this file does the client-side multi-fetch +
 * normalization instead (confirmed cheaper than building one; see root
 * TODO.md's "Cross-service health aggregation" note). IAM's shape is
 * the odd one out (no unified readyz), so it's normalized here to the
 * same `ServiceHealth`/`ComponentHealth` shape the other three already
 * return natively.
 *
 * `ingestion` added 2026-08-07 (`services/ingestion/TODO.md`'s
 * "Frontend integration" section) — its `/v1/readyz` is real and
 * live-verified to return the exact same `{status, components}` shape
 * `data-pipeline`'s does (confirmed by reading `app/api/v1/health/
 * routes.py` directly: same three checks — Postgres, Redis, RabbitMQ —
 * just no MLflow check, since this service has no ML training
 * dependency). This closes a real gap: `services/ingestion`'s worker/
 * beat processes silently died twice in one session with zero visible
 * signal anywhere in this dashboard, because nothing here even knew
 * this service existed.
 *
 * `latencyMs` is a real single-sample round-trip time for *this*
 * check (measured client-side with `performance.now()`), not a
 * fabricated historical p95 — label it as such wherever it's shown.
 */

import {
  DATA_PIPELINE_API_URL,
  FORECAST_API_URL,
  IAM_BASE_URL,
  INGESTION_API_URL,
} from "./env";

export type ComponentHealth = {
  name: string;
  healthy: boolean;
  detail: string | null;
};

export type ServiceHealth = {
  service: "forecast-api" | "data-pipeline" | "ingestion" | "iam";
  /** Could we get any response at all (vs. a network-level failure). */
  reachable: boolean;
  /** Overall readiness; `null` when unreachable (not "unhealthy"). */
  ready: boolean | null;
  components: ComponentHealth[];
  /** Real round-trip time for this check, ms. `null` if unreachable. */
  latencyMs: number | null;
};

async function timedFetchJson(
  url: string,
): Promise<{ status: number; body: unknown; latencyMs: number } | null> {
  const start = performance.now();
  try {
    const res = await fetch(url);
    const latencyMs = Math.round(performance.now() - start);
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    return { status: res.status, body, latencyMs };
  } catch {
    return null;
  }
}

export async function fetchForecastApiHealth(): Promise<ServiceHealth> {
  const r = await timedFetchJson(`${FORECAST_API_URL}/readyz`);
  if (!r || r.body == null) {
    return { service: "forecast-api", reachable: false, ready: null, components: [], latencyMs: null };
  }
  const b = r.body as {
    ready?: boolean;
    database?: { ok?: boolean; detail?: string | null };
    redis?: { ok?: boolean; detail?: string | null };
    model?: { ok?: boolean; detail?: string | null };
  };
  return {
    service: "forecast-api",
    reachable: true,
    ready: Boolean(b.ready),
    components: [
      { name: "database", healthy: Boolean(b.database?.ok), detail: b.database?.detail ?? null },
      { name: "redis", healthy: Boolean(b.redis?.ok), detail: b.redis?.detail ?? null },
      { name: "model", healthy: Boolean(b.model?.ok), detail: b.model?.detail ?? null },
    ],
    latencyMs: r.latencyMs,
  };
}

export async function fetchDataPipelineHealth(): Promise<ServiceHealth> {
  const r = await timedFetchJson(`${DATA_PIPELINE_API_URL}/readyz`);
  if (!r || r.body == null) {
    return { service: "data-pipeline", reachable: false, ready: null, components: [], latencyMs: null };
  }
  const b = r.body as {
    status?: string;
    components?: { name: string; healthy: boolean; detail?: string | null }[];
  };
  return {
    service: "data-pipeline",
    reachable: true,
    ready: b.status === "ready",
    components: (b.components ?? []).map((c) => ({
      name: c.name,
      healthy: Boolean(c.healthy),
      detail: c.detail ?? null,
    })),
    latencyMs: r.latencyMs,
  };
}

/** Same response shape as `fetchDataPipelineHealth` — `services/
 * ingestion`'s `/v1/readyz` returns the identical `{status,
 * components}` shape (confirmed by reading its route directly, not
 * assumed from the URL alone). Kept as its own function rather than a
 * shared helper, matching this file's existing one-function-per-service
 * pattern (`fetchForecastApiHealth`/`fetchDataPipelineHealth` don't
 * share one either, despite `data-pipeline` and `forecast-api` both
 * being FastAPI services too). */
export async function fetchIngestionHealth(): Promise<ServiceHealth> {
  const r = await timedFetchJson(`${INGESTION_API_URL}/readyz`);
  if (!r || r.body == null) {
    return { service: "ingestion", reachable: false, ready: null, components: [], latencyMs: null };
  }
  const b = r.body as {
    status?: string;
    components?: { name: string; healthy: boolean; detail?: string | null }[];
  };
  return {
    service: "ingestion",
    reachable: true,
    ready: b.status === "ready",
    components: (b.components ?? []).map((c) => ({
      name: c.name,
      healthy: Boolean(c.healthy),
      detail: c.detail ?? null,
    })),
    latencyMs: r.latencyMs,
  };
}

export async function fetchIamHealth(): Promise<ServiceHealth> {
  const start = performance.now();
  const [root, db] = await Promise.all([
    timedFetchJson(`${IAM_BASE_URL}/`),
    timedFetchJson(`${IAM_BASE_URL}/db_health`),
  ]);
  const latencyMs = Math.round(performance.now() - start);
  if (!root || root.body == null) {
    return { service: "iam", reachable: false, ready: null, components: [], latencyMs: null };
  }
  const serverHealthy = root.status < 500;
  const dbBody = db?.body as { database?: string; detail?: { error?: string } } | null;
  const dbHealthy = db?.status === 200 && dbBody?.database === "healthy";
  const dbDetail = dbHealthy ? null : (dbBody?.detail?.error ?? "unreachable");
  return {
    service: "iam",
    reachable: true,
    ready: serverHealthy && dbHealthy,
    components: [
      { name: "server", healthy: serverHealthy, detail: null },
      { name: "database", healthy: dbHealthy, detail: dbDetail },
    ],
    latencyMs,
  };
}

export async function fetchAllServicesHealth(): Promise<ServiceHealth[]> {
  return Promise.all([
    fetchForecastApiHealth(),
    fetchDataPipelineHealth(),
    fetchIngestionHealth(),
    fetchIamHealth(),
  ]);
}
