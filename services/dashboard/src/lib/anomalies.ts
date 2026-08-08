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
 */

import { INGESTION_API_URL } from "./env";

export type AnomalySeverity = "high" | "medium" | "low";
export type AnomalyMethod = "rule" | "ml" | "hybrid";
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
