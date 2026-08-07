/**
 * data-pipeline client — data-sources catalog domain.
 *
 * Talks to `GET /v1/data-sources/public`
 * (`services/data-pipeline/app/api/v1/datasources/routes.py`) — the
 * unauthenticated mirror of the admin-gated `GET /v1/data-sources`,
 * added specifically so this dashboard (which has no way to hold a
 * bearer token for data-pipeline's own separate auth domain, see that
 * route's own docstring) can show real source health/schedule/last-run
 * data instead of the fictional 9-source catalog `lib/dashboards.ts`'s
 * old `getDataSources()` mock used to render here.
 *
 * Read-only. `PATCH /v1/data-sources/{id}` (schedule edits,
 * enable/disable) requires `admin` role and stays out of scope here —
 * there's no real auth flow for this dashboard to hold that token, so
 * the page shows those controls as disabled rather than faking a
 * mutation that never reaches the backend (same "no silently fabricated
 * success" convention `models/page.tsx`'s Train tab already follows).
 * `POST .../run` and `.../backfill` ARE real here — both are
 * deliberately open routes, already used by `ingestion.ts`'s
 * `triggerIngestionRun`/`triggerBackfill`, reused directly rather than
 * duplicated.
 */
import { DATA_PIPELINE_API_URL } from "./env";

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

/** Live call to `GET /v1/data-sources/public`. No auth, no mock
 * fallback on failure -- an honest empty list beats silently
 * reintroducing the old fictional catalog (same policy as the Carbon
 * Intelligence / Ingestion Pipeline pages once they were wired to real
 * data). `limit=200` -- the real catalog is 5 sources today, well under
 * any pagination boundary, so a single request always gets everything. */
export async function fetchPublicDataSources(): Promise<DataSourcesList> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-sources/public?limit=200`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-sources/public failed: ${res.status}`);
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
