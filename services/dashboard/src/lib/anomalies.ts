/**
 * Real `meta.anomalies` client -- `GET /v1/anomalies`,
 * `GET /v1/anomalies/summary`, `PATCH /v1/anomalies/{id}`
 * (`services/ingestion`, added 2026-08-08, root TODO.md's "make every
 * page fully functional with real data"). Replaces `lib/admin.ts`'s
 * fully-fabricated `generateAnomalies()`/`summarizeAnomalies()` on the
 * dashboard's anomaly-detection page -- that page's mutation handlers
 * (acknowledge/resolve/false-positive) used to be local-state-only;
 * `updateAnomalyStatus` below is a real `PATCH`, not a client-side
 * simulation.
 *
 * `severity`/`method` are server-derived, not separately tracked
 * columns -- see `services/ingestion/app/schemas/anomalies/response.py`'s
 * own docstring for exactly how (real, already-established thresholds/
 * score-presence rules, not invented in this client).
 *
 * `method: "rule"` is legacy-only, 2026-08-12 on -- the backend's
 * rule-based signal (out-of-range bounds, missing-value flagging) was
 * retired that date (real, live-observed reason: it accounted for the
 * overwhelming majority of flagged rows, structurally expected rather
 * than anomalous -- see `pipeline/anomaly.py`'s own docstring). A row
 * detected going forward that only clears the statistical (z-score)
 * signal is `"statistical"` instead of the old, cruder `"rule"` catch-all.
 */

import { INGESTION_API_URL } from "./env";

export type AnomalySeverity = "high" | "medium" | "low";
export type AnomalyMethod = "rule" | "statistical" | "ml" | "hybrid";
export type AnomalyStatus = "new" | "acknowledged" | "resolved" | "false_positive";

export type Anomaly = {
  id: string;
  detected_at: string;
  ts: string | null;
  region: string | null;
  source: string;
  table_name: string;
  reason: string;
  severity: AnomalySeverity;
  method: AnomalyMethod;
  score: number;
  metric: string | null;
  observed_value: number | null;
  z_score: number | null;
  expected_low: number | null;
  expected_high: number | null;
  status: AnomalyStatus;
  status_updated_at: string | null;
};

export type AnomalyListResponse = {
  meta: { total: number; limit: number; offset: number };
  data: Anomaly[];
};

export type AnomalySummary = {
  total: number;
  avg_score: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  by_method: Record<string, number>;
  by_reason_kind: Record<string, number>;
  daily_counts: { date: string; count: number }[];
  /** Real `max(detected_at)` across all of `meta.anomalies` -- when the
   * detector last actually flagged something, not a synthetic "job
   * last ran" timestamp (this detector runs inline with every ingest,
   * not as its own separate scheduled job). `null` if nothing has ever
   * been flagged. */
  latest_detected_at: string | null;
};

export type AnomalyTimeseriesPoint = {
  ts: string;
  value: number | null;
  is_anomalous: boolean;
  anomaly_score: number | null;
  severity: AnomalySeverity | null;
  expected_low: number | null;
  expected_high: number | null;
};

export type AnomalyTimeseriesResponse = {
  region: string;
  metric: string;
  start: string;
  end: string;
  total_points: number;
  anomalous_points: number;
  points: AnomalyTimeseriesPoint[];
};

export type AnomalyListFilters = {
  severity?: AnomalySeverity;
  method?: AnomalyMethod;
  status?: AnomalyStatus;
  source?: string;
  search?: string;
  limit?: number;
  offset?: number;
};

export async function fetchAnomalies(filters: AnomalyListFilters = {}): Promise<AnomalyListResponse> {
  const params = new URLSearchParams();
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.method) params.set("method", filters.method);
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.search) params.set("search", filters.search);
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));

  const res = await fetch(`${INGESTION_API_URL}/anomalies?${params}`);
  if (!res.ok) {
    throw new Error(`GET /v1/anomalies failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAnomalySummary(): Promise<AnomalySummary> {
  const res = await fetch(`${INGESTION_API_URL}/anomalies/summary`);
  if (!res.ok) {
    throw new Error(`GET /v1/anomalies/summary failed: ${res.status}`);
  }
  return res.json();
}

export type AnomalyTimeseriesFilters = {
  region: string;
  metric?: "demand_mw" | "price_mwh";
  start?: string;
  end?: string;
};

export async function fetchAnomalyTimeseries(
  filters: AnomalyTimeseriesFilters,
): Promise<AnomalyTimeseriesResponse> {
  const params = new URLSearchParams({ region: filters.region });
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);

  const res = await fetch(`${INGESTION_API_URL}/anomalies/timeseries?${params}`);
  if (!res.ok) {
    throw new Error(`GET /v1/anomalies/timeseries failed: ${res.status}`);
  }
  return res.json();
}

export async function updateAnomalyStatus(id: string, status: AnomalyStatus): Promise<Anomaly> {
  const res = await fetch(`${INGESTION_API_URL}/anomalies/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error?.message ?? `PATCH /v1/anomalies/${id} failed: ${res.status}`);
  }
  return res.json();
}
