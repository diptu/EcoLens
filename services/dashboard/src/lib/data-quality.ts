/**
 * data-pipeline client — currently just the one public, unauthenticated
 * endpoint that's safe to call from a browser.
 *
 * Every other route under services/data-pipeline's `/v1/data-quality/*`
 * requires a bearer token from that service's own separate auth domain
 * (`app/core/security.py` — HS256, self-issued via `POST /v1/auth/token`,
 * deliberately not the IAM session token this dashboard already holds).
 * Exposing that token to the browser would mean shipping a service
 * credential in client-side JS, so `GET /v1/data-quality/summary/public`
 * exists specifically as an unauthenticated projection of just two
 * aggregate numbers (see its own docstring in data-pipeline) — nothing
 * else from that service is safe to call from here without a real
 * backend-for-frontend proxy, which doesn't exist yet.
 *
 * Backs the Executive Dashboard's "Data Quality Score" and "Open Risks"
 * KPIs — the honestly-scoped replacement for the old fabricated
 * "Compliance Score"/"Open Risks" mock (no sustainability-regulatory
 * compliance or risk-register domain exists anywhere in this platform;
 * real ingestion/data-quality health is the closest honest substitute).
 */

import { DATA_PIPELINE_API_URL } from "./env";

/** Shape of data-pipeline's `PublicDataQualitySummaryResponse`. */
export type PublicDataQualitySummary = {
  as_of: string;
  data_quality_score_pct: number | null;
  open_risks_high_plus: number;
};

export async function fetchPublicDataQualitySummary(): Promise<PublicDataQualitySummary> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-quality/summary/public`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-quality/summary/public failed: ${res.status}`);
  }
  return res.json();
}
