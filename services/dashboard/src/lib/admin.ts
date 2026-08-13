/**
 * Admin data layer for ecoLens.
 *
 * In production this calls the admin-api (`http://localhost:8004`):
 *   fetch(`${ADMIN_API_URL}/v1/admin/models`)
 *   fetch(`${ADMIN_API_URL}/v1/admin/models/{name}/train`, { method: "POST" })
 *   fetch(`${ADMIN_API_URL}/v1/admin/jobs`)
 *   ...etc
 *
 * For the dashboard demo (no admin-api service attached yet) we
 * generate deterministic, realistic data with a seeded PRNG so
 * the page is reproducible across reloads and SSR/CSR matches.
 *
 * The shape matches the API response exactly — when the service
 * is deployed, replacing `generate*()` with a real `fetch()` call
 * is a one-line change per function.
 */

// ────────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────────
export type DataSource = {
  id: string;
  name: string;
  type: "api" | "csv" | "ftp" | "scraper";
  status: "healthy" | "degraded" | "down" | "unknown";
  last_run: string | null;
  last_run_status: "ok" | "partial" | "failed";
  last_run_rows: number;
  cadence: string;
  schedule: string;
  description: string;
  enabled: boolean;
};

export type JobKind = "train" | "fine_tune" | "evaluate" | "promote" | "ingest" | "backfill" | "refresh" | "archive";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type Job = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  submitted_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  params: Record<string, unknown>;
  log: string[];
  result: Record<string, unknown> | null;
  error: string | null;
  duration_seconds: number | null;
};

export type User = {
  username: string;
  email: string;
  name: string;
  role: "admin" | "analyst" | "viewer";
  last_active: string;
  mfa_enabled: boolean;
  status: "active" | "inactive";
};

export type SystemHealth = {
  status: "healthy" | "degraded" | "down";
  uptime_seconds: number;
  components: Record<string, {
    status: string;
    latency_ms?: number;
    pool_active?: number;
    pool_idle?: number;
    last_run?: string;
    last_duration_s?: number;
    current_model?: string;
    last_reload?: string;
    next_run?: string;
    queued_jobs?: number;
    collections?: number;
    keys?: number;
    experiments?: number;
  }>;
  disk: { used_gb: number; free_gb: number; total_gb: number; pct_used: number };
  memory: { used_mb: number; total_mb: number; pct_used: number };
  recent_errors: { ts: string; service: string; level: string; message: string }[];
};

// ────────────────────────────────────────────────────────────────────
// Mulberry32 PRNG (matches the rest of the app)
// ────────────────────────────────────────────────────────────────────
function mulberry32(seed: number) {
  let s = seed >>> 0;
  return function next() {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function seedFor(...parts: (string | number)[]): number {
  let h = 0;
  const s = parts.join("|");
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h) || 1;
}

// ────────────────────────────────────────────────────────────────────
// Anomaly detection
// ────────────────────────────────────────────────────────────────────

/**
 * Severity classification for ingestion anomalies. Drives the colour
 * coding and the KPI cards on the admin/anomaly-detection page.
 */
export type AnomalySeverity = "high" | "medium" | "low";

/**
 * Method that flagged the record. "rule" = schema / range / freshness
 * check fired; "ml" = the residual-based forecaster disagreed by
 * >threshold; "hybrid" = both.
 */
export type AnomalyMethod = "rule" | "ml" | "hybrid";

/**
 * Lifecycle of a flagged anomaly. New records land in "new", admins
 * can "acknowledge" them, mark them "resolved" once remediated, or
 * "false_positive" if the ML flagged a genuine operational event.
 */
export type AnomalyStatus = "new" | "acknowledged" | "resolved" | "false_positive";

/**
 * Source that produced the anomalous record. Mirrors the 5 pipeline
 * sources so admins can drill down per upstream.
 */
export type AnomalySource =
  | "aemo_nem"
  | "aemo_wem"
  | "bom_observation"
  | "open_electricity"
  | "holiday";

/**
 * What kind of anomaly was detected. Maps to specific rule / ML
 * checks in the ingestion layer.
 */
export type AnomalyType =
  | "demand_spike"        // 5-min demand > 3σ above rolling 7-day mean
  | "demand_drop"         // 5-min demand < 3σ below rolling 7-day mean
  | "negative_price"      // price < -AUD 100/MWh (administered floor breach)
  | "stale_observation"   // same value reported for >2 consecutive intervals
  | "missing_interval"    // expected 5/30-min interval absent
  | "out_of_range"        // demand_mw or temperature outside physical limits
  | "interconnector_imbalance" // |imports - exports| > 200 MW
  | "schema_mismatch"     // upstream columns differ from v1.0 schema
  | "source_disagreement" // AEMO and OpenElectricity differ by >5%
  | "duplicate"           // exact (ts, region) duplicate within 1 hour
  | "future_ts"           // timestamp > now() + 5 min
  | "backdated_revision"; // settlement revision older than 7 days

export type Anomaly = {
  id: string;
  detected_at: string;
  ts: string;                       // interval start that was flagged
  region: AnomalySource extends never ? string : string;
  source: AnomalySource;
  type: AnomalyType;
  severity: AnomalySeverity;
  method: AnomalyMethod;
  score: number;                    // 0–1 (ML) or rule weight
  reason: string;
  observed_value: number | string | null;
  expected_value: number | string | null;
  unit: string;
  status: AnomalyStatus;
  assigned_to: string | null;
  notes: string | null;
};

const ANOMALY_TYPE_TEMPLATES: Array<{
  type: AnomalyType;
  severity: AnomalySeverity;
  method: AnomalyMethod;
  reason: (region: string, value: number) => string;
  unit: string;
  expected: (region: string) => number;
  observedRange: (region: string) => [number, number];
}> = [
  {
    type: "demand_spike",
    severity: "high",
    method: "hybrid",
    reason: (r, v) =>
      `Demand ${v.toFixed(0)} MW is 3.4σ above the 7-day rolling mean for ${r} (expected ~${(v * 0.78).toFixed(0)} MW). Both the rule-based range check and the LSTM residual model flagged this interval.`,
    unit: "MW",
    expected: (r) => (r === "WEM" ? 1900 : r === "NSW1" ? 8200 : 5800),
    observedRange: (r) => [12000, 16500],
  },
  {
    type: "demand_drop",
    severity: "medium",
    method: "ml",
    reason: (r, v) =>
      `Demand ${v.toFixed(0)} MW dropped unexpectedly for ${r}; the residual model predicted ${(v * 1.6).toFixed(0)} MW (±12%). Likely a sudden industrial load loss.`,
    unit: "MW",
    expected: (r) => (r === "WEM" ? 1900 : 8200),
    observedRange: (r) => [600, 1400],
  },
  {
    type: "negative_price",
    severity: "medium",
    method: "rule",
    reason: (r, v) =>
      `Price ${v.toFixed(2)} AUD/MWh is below the administered floor (-AUD 100/MWh) for ${r}. Excess rooftop solar + low demand.`,
    unit: "AUD/MWh",
    expected: () => 50,
    observedRange: () => [-273, -120],
  },
  {
    type: "stale_observation",
    severity: "low",
    method: "rule",
    reason: (r, v) =>
      `BoM station in ${r} reported the same value (${v}°C) for 4 consecutive 30-min slots. Likely a stuck sensor — flag for replacement.`,
    unit: "°C",
    expected: () => 18.5,
    observedRange: () => [18.4, 18.4],
  },
  {
    type: "missing_interval",
    severity: "high",
    method: "rule",
    reason: (r, v) =>
      `Expected 5-min interval absent for ${r} at the timestamp shown. The DuckDB staging table is missing row #${v}. Most likely an AEMO upstream outage.`,
    unit: "interval_id",
    expected: () => 0,
    observedRange: () => [1, 288],
  },
  {
    type: "out_of_range",
    severity: "high",
    method: "rule",
    reason: (r, v) =>
      `Value ${v} is outside the physical envelope for ${r}. Either a sensor fault or a unit-of-measure conversion error.`,
    unit: "MW",
    expected: () => 8000,
    observedRange: (r) => (r === "WEM" ? [9500, 12000] : [55000, 78000]),
  },
  {
    type: "interconnector_imbalance",
    severity: "medium",
    method: "rule",
    reason: (r, v) =>
      `Interconnector flows for ${r} differ from schedule by ${v.toFixed(0)} MW (>200 MW threshold). Possible constraint breach or SCADA lag.`,
    unit: "MW",
    expected: () => 0,
    observedRange: () => [240, 620],
  },
  {
    type: "schema_mismatch",
    severity: "high",
    method: "rule",
    reason: (r, v) =>
      `Upstream payload for ${r} contains column 'v${v.toFixed(0)}' not in the v1.0 schema. AEMO may have rolled a new dispatch table version.`,
    unit: "schema_col",
    expected: () => 0,
    observedRange: () => [37, 41],
  },
  {
    type: "source_disagreement",
    severity: "low",
    method: "hybrid",
    reason: (r, v) =>
      `AEMO and OpenElectricity differ by ${v.toFixed(1)}% on the demand reading for ${r}. Within the 5% tolerance but flagged for review.`,
    unit: "%",
    expected: () => 0,
    observedRange: () => [5.2, 7.8],
  },
  {
    type: "duplicate",
    severity: "medium",
    method: "rule",
    reason: (r, v) =>
      `Duplicate (ts, region) for ${r} — same row received ${v} times within 60s. Upstream re-publish or retry storm.`,
    unit: "count",
    expected: () => 1,
    observedRange: () => [3, 12],
  },
  {
    type: "future_ts",
    severity: "low",
    method: "rule",
    reason: (r, v) =>
      `Row from ${r} carries a timestamp ${v} minutes in the future. Clock-skew between AEMO servers and ecoLens.`,
    unit: "min",
    expected: () => 0,
    observedRange: () => [6, 18],
  },
  {
    type: "backdated_revision",
    severity: "low",
    method: "rule",
    reason: (r, v) =>
      `Settlement revision for ${r} is backdated by ${v} days — older than the 7-day re-revision window. The warehouse will not overwrite production values.`,
    unit: "days",
    expected: () => 0,
    observedRange: () => [8, 32],
  },
];

const ANOMALY_REGIONS = [
  "NEM",
  "NSW1",
  "QLD1",
  "VIC1",
  "SA1",
  "TAS1",
  "WEM",
] as const;
const ANOMALY_SOURCES: AnomalySource[] = [
  "aemo_nem",
  "aemo_wem",
  "bom_observation",
  "open_electricity",
  "holiday",
];
const ANOMALY_ASSIGNED = ["diptu", "diptu.app", "n.perera", "k.zhao", null];

/**
 * Deterministic PRNG (mulberry32) so the demo stays reproducible.
 */
function _anomRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Generate a deterministic list of recent anomalies.
 * 30 default; mix of severities, methods, statuses, and sources.
 */
export function generateAnomalies(limit: number = 30): Anomaly[] {
  const rng = _anomRng(2026_07_28);
  const now = new Date("2026-07-28T18:00:00Z").getTime();
  const out: Anomaly[] = [];
  for (let i = 0; i < limit; i++) {
    const tpl = ANOMALY_TYPE_TEMPLATES[i % ANOMALY_TYPE_TEMPLATES.length];
    const source =
      tpl.type === "stale_observation" || tpl.type === "out_of_range"
        ? "bom_observation"
        : tpl.type === "negative_price" || tpl.type === "interconnector_imbalance"
        ? "aemo_nem"
        : tpl.type === "missing_interval" || tpl.type === "schema_mismatch"
        ? i % 2 === 0
          ? "aemo_nem"
          : "aemo_wem"
        : ANOMALY_SOURCES[Math.floor(rng() * ANOMALY_SOURCES.length)];
    const region =
      source === "aemo_wem" || (source === "bom_observation" && i % 7 === 6)
        ? "WEM"
        : ANOMALY_REGIONS[Math.floor(rng() * (ANOMALY_REGIONS.length - 1))] || "NSW1";
    const [oLo, oHi] = tpl.observedRange(region);
    const observed = oLo + rng() * (oHi - oLo);
    const detected = now - Math.floor(rng() * 7 * 24 * 3600_000);
    const intervalTs = detected - Math.floor(rng() * 12 * 3600_000);
    const score =
      tpl.method === "rule"
        ? 0.6 + rng() * 0.2
        : tpl.method === "ml"
        ? 0.5 + rng() * 0.3
        : 0.85 + rng() * 0.13;
    // Status distribution: 50% new, 25% acknowledged, 15% resolved, 10% false_positive
    const r = rng();
    const status: AnomalyStatus =
      r < 0.5
        ? "new"
        : r < 0.75
        ? "acknowledged"
        : r < 0.9
        ? "resolved"
        : "false_positive";
    out.push({
      id: `anom-${(detected - intervalTs).toString(36)}-${i.toString(36)}`,
      detected_at: new Date(detected).toISOString(),
      ts: new Date(intervalTs).toISOString(),
      region,
      source,
      type: tpl.type,
      severity: tpl.severity,
      method: tpl.method,
      score: Math.round(score * 1000) / 1000,
      reason: tpl.reason(region, observed),
      observed_value:
        tpl.type === "missing_interval" || tpl.type === "duplicate" || tpl.type === "schema_mismatch"
          ? Math.round(observed)
          : Math.round(observed * 100) / 100,
      expected_value:
        tpl.type === "missing_interval" || tpl.type === "duplicate" || tpl.type === "schema_mismatch"
          ? tpl.expected(region)
          : Math.round(tpl.expected(region) * 100) / 100,
      unit: tpl.unit,
      status,
      assigned_to:
        status === "new" || status === "false_positive"
          ? null
          : ANOMALY_ASSIGNED[Math.floor(rng() * ANOMALY_ASSIGNED.length)] ?? null,
      notes: status === "false_positive" ? "Confirmed as a planned event (industrial maintenance)." : null,
    });
  }
  // Newest first
  out.sort((a, b) => (a.detected_at < b.detected_at ? 1 : -1));
  return out;
}

/**
 * Aggregate stats for the KPI cards on the anomaly-detection page.
 */
export type AnomalySummary = {
  total: number;
  new_count: number;
  acknowledged_count: number;
  resolved_count: number;
  false_positive_count: number;
  high_severity: number;
  medium_severity: number;
  low_severity: number;
  hybrid_count: number;
  rule_count: number;
  ml_count: number;
  avg_score: number;
  anomaly_rate_pct: number;       // anomalies / total ingestions, rough
  daily_counts: Array<{ date: string; count: number }>; // last 7 days
};

export function summarizeAnomalies(items: Anomaly[]): AnomalySummary {
  const counts = {
    new: 0,
    acknowledged: 0,
    resolved: 0,
    false_positive: 0,
  };
  const sev = { high: 0, medium: 0, low: 0 };
  const mth = { hybrid: 0, rule: 0, ml: 0 };
  let scoreSum = 0;
  for (const a of items) {
    counts[a.status]++;
    sev[a.severity]++;
    mth[a.method]++;
    scoreSum += a.score;
  }
  // Last 7 days count
  const days: Record<string, number> = {};
  const today = new Date("2026-07-28T00:00:00Z").getTime();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today - i * 86_400_000);
    days[d.toISOString().slice(0, 10)] = 0;
  }
  for (const a of items) {
    const day = a.detected_at.slice(0, 10);
    if (day in days) days[day]++;
  }
  return {
    total: items.length,
    new_count: counts.new,
    acknowledged_count: counts.acknowledged,
    resolved_count: counts.resolved,
    false_positive_count: counts.false_positive,
    high_severity: sev.high,
    medium_severity: sev.medium,
    low_severity: sev.low,
    hybrid_count: mth.hybrid,
    rule_count: mth.rule,
    ml_count: mth.ml,
    avg_score: items.length ? Math.round((scoreSum / items.length) * 1000) / 1000 : 0,
    // Synthetic but plausible: 1 anomaly per ~10,000 ingestions
    anomaly_rate_pct: 0.012,
    daily_counts: Object.entries(days).map(([date, count]) => ({ date, count })),
  };
}

// ────────────────────────────────────────────────────────────────────
// Data sources
// ────────────────────────────────────────────────────────────────────
export function generateDataSources(): DataSource[] {
  const now = new Date();
  const min = 60_000;
  const hour = 3_600_000;
  const day = 86_400_000;
  return [
    {
      id: "aemo-nem",
      name: "AEMO NEM dispatch + SCADA",
      type: "api",
      status: "healthy",
      last_run: new Date(now.getTime() - 4 * min).toISOString(),
      last_run_status: "ok",
      last_run_rows: 1_440,
      cadence: "5-min",
      schedule: "*/5 * * * *",
      description: "Real-time generation by fuel type for the 5 NEM regions.",
      enabled: true,
    },
    {
      id: "aemo-wem",
      name: "AEMO WEM market data",
      type: "api",
      status: "healthy",
      last_run: new Date(now.getTime() - 8 * min).toISOString(),
      last_run_status: "ok",
      last_run_rows: 144,
      cadence: "30-min",
      schedule: "*/30 * * * *",
      description: "WEM is a single region (no sub-regions); 30-min settlement.",
      enabled: true,
    },
    {
      id: "bom-live",
      name: "BoM weather observations",
      type: "api",
      status: "healthy",
      last_run: new Date(now.getTime() - 22 * min).toISOString(),
      last_run_status: "ok",
      last_run_rows: 144,
      cadence: "30-min",
      schedule: "*/30 * * * *",
      description: "6 stations × 24 obs/day = 144 docs/day.",
      enabled: true,
    },
    {
      id: "bom-historical",
      name: "BoM historical (Open-Meteo ERA5)",
      type: "api",
      status: "degraded",
      last_run: new Date(now.getTime() - 7 * hour).toISOString(),
      last_run_status: "partial",
      last_run_rows: 52_560,
      cadence: "manual",
      schedule: "manual",
      description: "Used for backfill >2y when BoM CDS is too expensive.",
      enabled: true,
    },
    {
      id: "holidays",
      name: "Australian public holidays",
      type: "scraper",
      status: "healthy",
      last_run: new Date(now.getTime() - 2 * hour).toISOString(),
      last_run_status: "ok",
      last_run_rows: 120,
      cadence: "yearly",
      schedule: "0 0 1 1 *",
      description: "State-specific public holidays per NEM region.",
      enabled: true,
    },
    {
      id: "openelectricity",
      name: "OpenElectricity (OpenNEM)",
      type: "api",
      status: "healthy",
      last_run: new Date(now.getTime() - 6 * hour).toISOString(),
      last_run_status: "ok",
      last_run_rows: 175_200,
      cadence: "weekly",
      schedule: "0 0 * * 0",
      description: "Pre-built NEM historical aggregates. Backfill source.",
      enabled: false,
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Jobs (with simulated progress)
// ────────────────────────────────────────────────────────────────────
export function generateJobs(limit: number = 12): Job[] {
  const rand = mulberry32(seedFor("jobs", new Date().toISOString().slice(0, 10)));
  const now = new Date();
  const hour = 3_600_000;
  const min = 60_000;
  const pick = <T,>(arr: T[]) => arr[Math.floor(rand() * arr.length)];

  const templates: Array<Omit<Job, "id" | "created_at" | "started_at" | "finished_at" | "duration_seconds" | "progress" | "log">> = [
    {
      kind: "train",
      status: "succeeded",
      submitted_by: "diptu",
      params: { model_name: "ecolens_lstm_demand", training_window_days: 1095, epochs: 50, batch_size: 128, hidden_size: 128, num_layers: 2, dropout: 0.2, lookback_steps: 48 },
      result: { new_version: 7, stage: "Production", mape: 4.2 },
      error: null,
    },
    {
      kind: "fine_tune",
      status: "succeeded",
      submitted_by: "ci-pipeline",
      params: { model_name: "ecolens_lstm_demand", base_version: 6, window_days: 30, learning_rate: 0.0001, epochs: 5 },
      result: { new_version: 6, mape: 4.7 },
      error: null,
    },
    {
      kind: "backfill",
      status: "succeeded",
      submitted_by: "diptu",
      params: { source_id: "bom-historical", start_date: "2020-01-01", end_date: "2023-07-01" },
      result: { rows_fetched: 1_051_200, rows_loaded: 1_051_200, source_id: "bom-historical", dbt_triggered: true },
      error: null,
    },
    {
      kind: "ingest",
      status: "running",
      submitted_by: "diptu",
      params: { source_id: "aemo-nem" },
      result: null,
      error: null,
    },
    {
      kind: "evaluate",
      status: "queued",
      submitted_by: "n.perera",
      params: { model_name: "ecolens_lstm_demand", test_window_days: 30 },
      result: null,
      error: null,
    },
    {
      kind: "refresh",
      status: "succeeded",
      submitted_by: "ci-pipeline",
      params: { source_id: "aemo-wem" },
      result: { rows_fetched: 144, rows_loaded: 144, source_id: "aemo-wem" },
      error: null,
    },
    {
      kind: "train",
      status: "failed",
      submitted_by: "ci-pipeline",
      params: { model_name: "ecolens_lstm_demand", training_window_days: 365, epochs: 50 },
      result: null,
      error: "OOM on GPU worker (8 GB used by prior job); retry with batch_size=64",
    },
    {
      kind: "promote",
      status: "succeeded",
      submitted_by: "diptu",
      params: { model_name: "ecolens_lstm_demand", version: 7, stage: "Production" },
      result: { version: 7, stage: "Production" },
      error: null,
    },
    {
      kind: "fine_tune",
      status: "running",
      submitted_by: "ci-pipeline",
      params: { model_name: "ecolens_lstm_demand", base_version: 7, window_days: 7, learning_rate: 0.0001, epochs: 3 },
      result: null,
      error: null,
    },
    {
      kind: "ingest",
      status: "succeeded",
      submitted_by: "diptu",
      params: { source_id: "bom-live" },
      result: { rows_fetched: 144, rows_loaded: 144, source_id: "bom-live" },
      error: null,
    },
    {
      kind: "backfill",
      status: "queued",
      submitted_by: "diptu",
      params: { source_id: "aemo-nem", start_date: "2015-01-01", end_date: "2018-01-01" },
      result: null,
      error: null,
    },
    {
      kind: "train",
      status: "succeeded",
      submitted_by: "ci-pipeline",
      params: { model_name: "ecolens_lstm_demand", training_window_days: 1095 },
      result: { new_version: 6, stage: "Staging", mape: 4.7 },
      error: null,
    },
  ];

  return templates.slice(0, limit).map((t, i) => {
    const ageMin = Math.floor(rand() * 60 * 24 * 3); // up to 3 days old
    const startedMin = Math.min(ageMin, Math.max(1, ageMin - 15));
    const createdAt = new Date(now.getTime() - ageMin * min);
    const startedAt = t.status === "queued" ? null : new Date(createdAt.getTime() + 30_000);
    const finishedAt = (t.status === "succeeded" || t.status === "failed" || t.status === "cancelled")
      ? new Date(createdAt.getTime() + startedMin * min)
      : null;
    const id = `job-${(i + 1).toString().padStart(4, "0")}-${Math.floor(rand() * 1e6).toString(36)}`;
    const log: string[] = [];
    if (t.status !== "queued") {
      const steps = t.kind === "train" || t.kind === "fine_tune"
        ? ["Loading training set", "Building model", "Training epoch", "Validating", "Calibrating conformal bands", "Registering in MLflow"]
        : ["Connecting to source", "Fetching rows", "Validating", "Loading into MongoDB", "Triggering dbt run"];
      for (const step of steps) {
        log.push(`[${new Date(startedAt?.getTime() ?? createdAt.getTime()).toISOString().slice(11, 19)}] ${step}…`);
      }
      if (t.status === "failed" && t.error) {
        log.push(`[${new Date(finishedAt?.getTime() ?? now.getTime()).toISOString().slice(11, 19)}] ERROR: ${t.error}`);
      }
    }
    const progress = t.status === "succeeded" ? 1.0 : t.status === "failed" ? 1.0 : t.status === "running" ? 0.42 : 0;
    return {
      ...t,
      id,
      created_at: createdAt.toISOString(),
      started_at: startedAt?.toISOString() ?? null,
      finished_at: finishedAt?.toISOString() ?? null,
      progress,
      log,
      duration_seconds: finishedAt && startedAt ? Math.round((finishedAt.getTime() - startedAt.getTime()) / 1000) : null,
    };
  });
}

// ────────────────────────────────────────────────────────────────────
// Users (must match the auth MOCK_USERS + a few extra)
// ────────────────────────────────────────────────────────────────────
export function generateAdminUsers(): User[] {
  return [
    { username: "diptu",        email: "diptu@ecolens.com",     name: "Diptu",          role: "admin",   last_active: new Date().toISOString(), mfa_enabled: true,  status: "active" },
    { username: "diptu.app",    email: "diptu@ecolens.app",     name: "Diptu (admin)",  role: "admin",   last_active: new Date(Date.now() - 1 * 3_600_000).toISOString(), mfa_enabled: false, status: "active" },
    { username: "demo",         email: "demo@ecolens.app",      name: "Demo User",      role: "analyst", last_active: new Date(Date.now() - 2 * 86_400_000).toISOString(), mfa_enabled: false, status: "active" },
    { username: "n.perera",     email: "n.perera@ecolens.com",  name: "Nimal Perera",   role: "analyst", last_active: new Date(Date.now() - 4 * 3_600_000).toISOString(), mfa_enabled: true,  status: "active" },
    { username: "k.zhao",       email: "k.zhao@ecolens.com",    name: "Kelly Zhao",     role: "viewer",  last_active: new Date(Date.now() - 4 * 86_400_000).toISOString(), mfa_enabled: false, status: "active" },
    { username: "a.brennan",    email: "a.brennan@ecolens.com", name: "Aiden Brennan",  role: "analyst", last_active: new Date(Date.now() - 6 * 3_600_000).toISOString(), mfa_enabled: true,  status: "active" },
    { username: "m.singh",      email: "m.singh@ecolens.com",   name: "Maya Singh",     role: "viewer",  last_active: new Date(Date.now() - 5 * 86_400_000).toISOString(), mfa_enabled: false, status: "inactive" },
  ];
}

// ────────────────────────────────────────────────────────────────────
// System health
// ────────────────────────────────────────────────────────────────────
export function generateSystemHealth(): SystemHealth {
  return {
    status: "healthy",
    uptime_seconds: 864_000,
    components: {
      postgres:        { status: "healthy", latency_ms: 4.2,  pool_active: 3, pool_idle: 5 },
      mongodb:         { status: "healthy", latency_ms: 6.8,  collections: 6 },
      redis:           { status: "healthy", latency_ms: 1.1,  keys: 142 },
      mlflow:          { status: "healthy", latency_ms: 22.0, experiments: 4 },
      dbt:             { status: "healthy", last_run: new Date(Date.now() - 1.2 * 3_600_000).toISOString(), last_duration_s: 42 },
      model_loader:    { status: "healthy", current_model: "ecolens_lstm_demand v7", last_reload: new Date(Date.now() - 2 * 86_400_000).toISOString() },
      scheduler:       { status: "healthy", next_run: new Date(Date.now() + 12 * 3_600_000).toISOString(), queued_jobs: 2 },
    },
    disk: { used_gb: 18, free_gb: 32, total_gb: 50, pct_used: 36 },
    memory: { used_mb: 612, total_mb: 2048, pct_used: 30 },
    recent_errors: [
      { ts: new Date(Date.now() - 4 * 3_600_000).toISOString(), service: "warehouse-api", level: "WARN",  message: "OpenElectricity API rate limit reached; backoff 60s" },
      { ts: new Date(Date.now() - 13 * 3_600_000).toISOString(), service: "forecast-api",  level: "ERROR", message: "MLflow model load returned 503; fell back to local fallback model" },
      { ts: new Date(Date.now() - 32 * 3_600_000).toISOString(), service: "data-pipeline", level: "INFO",  message: "dbt build completed in 38s; 1,440 rows inserted" },
    ],
  };
}

// ────────────────────────────────────────────────────────────────────
// Re-exports
// ────────────────────────────────────────────────────────────────────
