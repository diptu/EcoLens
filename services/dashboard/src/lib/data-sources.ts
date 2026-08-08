/**
 * Data-sources catalog domain client.
 *
 * **Cutover**: talks to `services/ingestion`'s `GET /v1/data-sources`
 * (`app/api/v1/datasources/routes.py`) now, not data-pipeline's
 * `GET /v1/data-sources/public`. Field-for-field identical response
 * shape (confirmed by reading `app/schemas/datasources/entities.py`'s
 * `DataSourceOut` directly — id/name/category/description/url/license/
 * auth/schedule/health/last_run/regions/metadata/version/created_at/
 * updated_at, all present) — ingestion's version is a superset in
 * `meta` only (adds `healthy_count`/`degraded_count`/`failing_count`/
 * `paused_count`/`next_refresh_at`, all unused here, harmless). No
 * `/public` URL segment on ingestion's side because the whole router is
 * already deliberately open (no auth at all, see that route's own
 * docstring) — there's no separate admin-gated variant to mirror the
 * way data-pipeline had one.
 *
 * Read-only here. `PATCH /v1/data-sources/{id}` (schedule edits,
 * enable/disable) stays out of scope — there's no real auth flow for
 * this dashboard to hold a token for, so the page shows those controls
 * as disabled rather than faking a mutation that never reaches the
 * backend (same "no silently fabricated success" convention
 * `models/page.tsx`'s Train tab already follows) — true regardless of
 * which service owns the route, ingestion's PATCH is open too but this
 * dashboard still has no real edit flow built for it.
 * `POST .../run` and `.../backfill` ARE real here — both are
 * deliberately open routes, already used by `ingestion.ts`'s
 * `triggerIngestionRun`/`triggerBackfill`, reused directly rather than
 * duplicated.
 */
import { INGESTION_API_URL } from "./env";

export type DataSourceCategory = "grid" | "weather" | "carbon" | "fuel" | "custom";
export type DataSourceHealthStatus = "healthy" | "degraded" | "failing" | "paused";
export type CircuitBreakerState = "closed" | "open" | "half_open";
export type DataSourceRunStatus =
  | "success" | "failed" | "running" | "staged" | "sync_failed" | "queued" | "partial";
export type AuthType = "none" | "api_key" | "oauth2";

/** Shape of data-pipeline's `DataSourceOut`. `auth` only ever carries
 * `type` (a bare enum) -- never a credential value, confirmed against
 * `app/schemas/datasources/base.py`'s `AuthInfo`, which is exactly why
 * this whole shape is safe to expose on an unauthenticated route. */
export type DataSource = {
  id: string;
  name: string;
  category: DataSourceCategory;
  description: string;
  url: string;
  license: string;
  auth: { type: AuthType };
  schedule: {
    cron: string;
    cadence: string;
    timezone: string;
    enabled: boolean;
    next_run_at: string | null;
    last_run_at: string | null;
  };
  health: {
    status: DataSourceHealthStatus;
    success_rate_pct_24h: number | null;
    success_rate_pct_7d: number | null;
    p50_duration_ms: number | null;
    p95_duration_ms: number | null;
    p99_duration_ms: number | null;
    consecutive_failures: number;
    circuit_breaker: CircuitBreakerState;
    last_check_at: string;
  };
  last_run: {
    id: string;
    status: DataSourceRunStatus;
    started_at: string;
    finished_at: string | null;
    duration_ms: number | null;
    records_fetched: number | null;
    records_inserted: number | null;
    duplicates_skipped: number | null;
    anomalies_flagged: number | null;
    error: string | null;
  } | null;
  regions: string[];
  metadata: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
};

export type DataSourcesList = {
  meta: {
    total: number;
    enabled_count: number;
    disabled_count: number;
    as_of?: string;
  };
  data: DataSource[];
  next_cursor: string | null;
  has_more: boolean;
};

/** Live call to `GET /v1/data-sources` (ingestion). No auth, no mock
 * fallback on failure -- an honest empty list beats silently
 * reintroducing the old fictional catalog (same policy as the Carbon
 * Intelligence / Ingestion Pipeline pages once they were wired to real
 * data). `limit=200` -- the real catalog is 5 sources today, well under
 * any pagination boundary, so a single request always gets everything. */
export async function fetchPublicDataSources(): Promise<DataSourcesList> {
  const res = await fetch(`${INGESTION_API_URL}/data-sources?limit=200`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-sources failed: ${res.status}`);
  }
  return res.json();
}

export const DATA_SOURCE_CATEGORIES: { id: DataSourceCategory; label: string }[] = [
  { id: "grid", label: "Grid" },
  { id: "weather", label: "Weather" },
  { id: "carbon", label: "Carbon" },
  { id: "fuel", label: "Fuel" },
  { id: "custom", label: "Custom" },
];

/** Maps data-pipeline's 4-state health (includes "failing"/"paused") to
 * the 3-state dot this page already renders (+ "unknown" for the
 * zero-runs-yet case, e.g. `ds-bom` fresh off a migration) -- avoids
 * duplicating a 4th color/label everywhere a 3-state dot already works
 * fine. */
export function healthDotStatus(
  health: DataSourceHealthStatus,
): "healthy" | "degraded" | "down" | "unknown" {
  if (health === "healthy") return "healthy";
  if (health === "degraded") return "degraded";
  if (health === "failing") return "down";
  return "unknown"; // "paused"
}
