/**
 * Data-quality client for the ecoLens dashboard.
 *
 * **Cutover**: `fetchPublicDataQualitySummary()` -- the only one of
 * these four functions anything actually calls (Executive Dashboard's
 * "Data Quality Score"/"Open Risks" KPIs) -- now talks to
 * `services/ingestion`'s `GET /v1/data-quality/summary/public`
 * (`app/api/v1/data_quality/routes.py` there), not data-pipeline's.
 * Field-for-field identical response shape (ingestion's
 * `PublicDataQualitySummaryResponse` is a direct port). No auth
 * required, same reasoning as `lib/data-sources.ts`'s module docstring
 * — none of this response carries anything sensitive.
 *
 * `fetchPublicIssues`/`fetchPublicOutliers`/`fetchPublicSchemaReport`
 * below still point at data-pipeline — they back routes nothing in this
 * dashboard calls yet (see each function's own docstring: they exist
 * for whoever wires up the Data Quality & Anomalies page next, which
 * needs a page redesign first, not a swap-in). Not ported to ingestion
 * for the same reason they were never a priority on data-pipeline
 * either — no live consumer to migrate.
 */
import { DATA_PIPELINE_API_URL, INGESTION_API_URL } from "./env";

/** Shape of ingestion's `PublicDataQualitySummaryResponse`. */
export type PublicDataQualitySummary = {
  as_of: string;
  data_quality_score_pct: number | null;
  open_risks_high_plus: number;
};

/** Live call to `GET /v1/data-quality/summary/public` (ingestion) --
 * throws on any non-2xx or network failure so callers (e.g. the
 * Executive Dashboard KPIs) can fall back to a placeholder rather than
 * show a wrong number. */
export async function fetchPublicDataQualitySummary(): Promise<PublicDataQualitySummary> {
  const res = await fetch(`${INGESTION_API_URL}/data-quality/summary/public`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-quality/summary/public failed: ${res.status}`);
  }
  return res.json();
}

export type IssueSeverity = "critical" | "high" | "medium" | "low";
export type IssueCategory =
  | "completeness" | "validity" | "uniqueness" | "consistency" | "timeliness";
export type IssueStatus = "open" | "acknowledged" | "resolved" | "suppressed";

/** Shape of data-pipeline's `DataQualityIssue`. */
export type DataQualityIssue = {
  id: string;
  source_id: string;
  pipeline_id: string;
  severity: IssueSeverity;
  category: IssueCategory;
  title: string;
  description: string;
  first_seen_at: string;
  last_seen_at: string;
  occurrences: number;
  status: IssueStatus;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  suggested_action: string | null;
  auto_resolvable: boolean;
};

export type DataQualityIssuesList = {
  meta: { total: number; filtered: number };
  data: DataQualityIssue[];
  next_cursor: string | null;
  has_more: boolean;
};

export async function fetchPublicIssues(params?: {
  sourceId?: string;
  severity?: IssueSeverity;
  category?: IssueCategory;
  status?: IssueStatus;
  limit?: number;
}): Promise<DataQualityIssuesList> {
  const q = new URLSearchParams();
  if (params?.sourceId) q.set("source_id", params.sourceId);
  if (params?.severity) q.set("severity", params.severity);
  if (params?.category) q.set("category", params.category);
  if (params?.status) q.set("status", params.status);
  q.set("limit", String(params?.limit ?? 50));
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-quality/public/issues?${q}`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-quality/public/issues failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of data-pipeline's `DataQualityOutlier` -- a statistical
 * z-score reading, not a rule/ML-hybrid flag. */
export type DataQualityOutlier = {
  id: string;
  source_id: string;
  metric: string;
  value: number;
  expected_range: { low: number | null; high: number | null };
  z_score: number;
  observed_at: string;
  region: string | null;
  station_id: string | null;
  context: { rolling_median_24h: number | null; rolling_std_24h: number | null } | null;
  linked_issue_id: string | null;
};

export type DataQualityOutliersList = {
  meta: { total: number; as_of: string };
  data: DataQualityOutlier[];
};

export async function fetchPublicOutliers(params?: {
  sourceId?: string;
  metric?: string;
  zScoreMin?: number;
  limit?: number;
}): Promise<DataQualityOutliersList> {
  const q = new URLSearchParams();
  if (params?.sourceId) q.set("source_id", params.sourceId);
  if (params?.metric) q.set("metric", params.metric);
  if (params?.zScoreMin != null) q.set("z_score_min", String(params.zScoreMin));
  q.set("limit", String(params?.limit ?? 50));
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-quality/public/outliers?${q}`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-quality/public/outliers failed: ${res.status}`);
  }
  return res.json();
}

export type SchemaDrift = {
  source_id: string;
  table: string;
  severity: IssueSeverity;
  kind: "column_added" | "column_removed" | "type_changed" | "nullable_changed";
  column: string;
  old_type: string | null;
  new_type: string | null;
  first_seen_at: string;
  auto_adapted: boolean;
  action_required: boolean;
  downstream_impact: string | null;
};

export type SchemaReport = {
  as_of: string;
  drifts: SchemaDrift[];
  summary: { total_drifts_24h: number; auto_adapted: number; needs_action: number };
};

export async function fetchPublicSchemaReport(): Promise<SchemaReport> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-quality/public/schema`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-quality/public/schema failed: ${res.status}`);
  }
  return res.json();
}
