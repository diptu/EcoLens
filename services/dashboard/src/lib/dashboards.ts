/**
 * src/lib/dashboards.ts — Data layer for the 14 dashboard pages.
 *
 * All data is deterministic (seeded PRNGs or static) so the same
 * input always produces the same output across page loads and tests.
 *
 * Sections:
 *   - Executive Dashboard   (KPIs, initiatives, scope breakdown)
 *   - Operations Dashboard  (KPIs, pipelines, services)
 *   - Data Sources          (sources, categories)
 *   - Data Ingestion        (pipelines, runs, failed jobs)
 *   - Data Quality          (checks, schema)
 *   - Warehouse             (tables, dbt runs)
 *   - AI / Recommendations
 *   - ML Models             (registry, training, deployments)
 *   - MLflow                (experiments, runs)
 *   - Compliance, Audit, Users, Settings
 */

// ────────────────────────────────────────────────────────────────────
// Re-exports from admin-dashboard.ts (existing)
// ────────────────────────────────────────────────────────────────────

import {
  getAdminKpis,
  getEmissionsTrend,
  getEmissionsByScope,
  getGenerationMix,
  getCarbonIntensityForecast,
  getIngestionStatus,
  getRecentReports,
  getRecentAlerts,
  getRecentUsers,
  getUpcomingDeadlines,
  getComplianceItems,
  getPipelineOps,
  getModelOps,
  getActiveTasks,
  getTrainingConfigOptions,
  getRecentTrainingRuns,
  getScheduledOps,
  getSystemCommands,
  getOperationalKpis,
} from "./admin-dashboard";

export {
  getAdminKpis,
  getEmissionsTrend,
  getEmissionsByScope,
  getGenerationMix,
  getCarbonIntensityForecast,
  getIngestionStatus,
  getRecentReports,
  getRecentAlerts,
  getRecentUsers,
  getUpcomingDeadlines,
  getComplianceItems,
  getPipelineOps,
  getModelOps,
  getActiveTasks,
  getTrainingConfigOptions,
  getRecentTrainingRuns,
  getScheduledOps,
  getSystemCommands,
  getOperationalKpis,
};

// ────────────────────────────────────────────────────────────────────
// Executive Dashboard
// ────────────────────────────────────────────────────────────────────

export interface ExecutiveKpi {
  label: string;
  value: string;
  delta_pct: number;
  trend: "up" | "down" | "flat";
  good_when: "up" | "down";
  unit?: string;
}

export function getExecutiveKpis(): ExecutiveKpi[] {
  return [
    { label: "Total CO₂e (YTD)", value: "12,840",  unit: "tCO₂e", delta_pct: -4.2,  trend: "down", good_when: "down" },
    { label: "Carbon Intensity",  value: "612",    unit: "g/kWh", delta_pct: -2.8,  trend: "down", good_when: "down" },
    { label: "Renewable Share",   value: "38.6",   unit: "%",     delta_pct:  6.1,  trend: "up",   good_when: "up"   },
    { label: "Cost Savings",      value: "$1.42M", unit: "YTD",   delta_pct: 11.3,  trend: "up",   good_when: "up"   },
    { label: "Compliance Score",  value: "92",     unit: "/100",  delta_pct:  1.4,  trend: "up",   good_when: "up"   },
    { label: "Open Risks",        value: "3",      unit: "high",  delta_pct: -25.0, trend: "down", good_when: "down" },
  ];
}

export interface ExecutiveInitiative {
  id: string;
  name: string;
  status: "on-track" | "at-risk" | "blocked" | "completed";
  progress_pct: number;
  due: string;
  owner: string;
  impact: string;
}

export function getExecutiveInitiatives(): ExecutiveInitiative[] {
  return [
    { id: "i-1", name: "Net-Zero Roadmap 2030",     status: "on-track",  progress_pct: 68, due: "Q4 2026", owner: "CSO",          impact: "-45% scope 1+2 by 2030" },
    { id: "i-2", name: "Solar PPA — 200 MW",        status: "at-risk",   progress_pct: 42, due: "Q2 2026", owner: "Procurement",  impact: "12k tCO₂e/yr avoided" },
    { id: "i-3", name: "Scope 3 Supplier Disclosure",status: "blocked",  progress_pct: 18, due: "Q3 2026", owner: "Sustainability", impact: "Regulatory (CSRD)" },
    { id: "i-4", name: "EV Fleet Transition",        status: "on-track", progress_pct: 81, due: "Q1 2026", owner: "Facilities",   impact: "-1.8k tCO₂e/yr" },
    { id: "i-5", name: "LED Retrofit — All Sites",   status: "completed",progress_pct: 100, due: "Done",  owner: "Facilities",   impact: "-320 tCO₂e/yr" },
  ];
}

// Aliases for executive page
export const getExecutiveTrend = getEmissionsTrend;
export const getExecutiveScope = getEmissionsByScope;

// ────────────────────────────────────────────────────────────────────
// Emissions by Source (where the emissions come from)
// ────────────────────────────────────────────────────────────────────

export interface SourceSlice {
  name: string;
  pct: number;
  tco2e: number;
  color: string;
}

export function getEmissionsBySource(): SourceSlice[] {
  return [
    { name: "Grid Electricity (Scope 2)", pct: 58.4, tco2e: 73_220, color: "#34d399" },
    { name: "Natural Gas (Scope 1)",      pct: 21.6, tco2e: 27_060, color: "#fbbf24" },
    { name: "Diesel (Scope 1)",           pct:  8.2, tco2e: 10_280, color: "#94a3b8" },
    { name: "Refrigerants (Scope 1)",     pct:  4.1, tco2e:  5_140, color: "#a78bfa" },
    { name: "Supply Chain (Scope 3)",     pct:  5.0, tco2e:  6_280, color: "#22d3ee" },
    { name: "Travel (Scope 3)",           pct:  2.7, tco2e:  3_360, color: "#f472b6" },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Operations Dashboard
// ────────────────────────────────────────────────────────────────────

export function getOpsKpis() {
  return [
    { label: "Active Pipelines",  value: "12",  sub: "5 running" },
    { label: "Pending Jobs",      value: "23",  sub: "1 retry"   },
    { label: "Last Ingestion",    value: "2m",  sub: "AEMO NEM"  },
    { label: "Model Status",      value: "OK",  sub: "v7 prod"   },
    { label: "Next Retrain",      value: "11d", sub: "Apr 9"     },
    { label: "System Load",       value: "62%", sub: "8/16 cores"},
  ];
}

export function getOpsPipelines() {
  return [
    { id: "op-1", name: "AEMO NEM 5-min",   status: "running",  last_run: "2 min ago",  records_today: 8_640,  health: "healthy"  },
    { id: "op-2", name: "BoM Observations", status: "success",  last_run: "12 min ago", records_today: 4_320,  health: "healthy"  },
    { id: "op-3", name: "Carbon Intensity", status: "success",  last_run: "28 min ago", records_today: 1_440,  health: "healthy"  },
    { id: "op-4", name: "Fuel Mix",         status: "queued",   last_run: "1h ago",     records_today: 720,    health: "healthy"  },
    { id: "op-5", name: "Distributed PV",   status: "failed",   last_run: "3h ago",     records_today: 0,      health: "degraded" },
    { id: "op-6", name: "WEM Dispatch",     status: "success",  last_run: "5 min ago",  records_today: 1_280,  health: "healthy"  },
  ];
}

export function getOpsServices() {
  return [
    { name: "Forecast API",  status: "healthy",  uptime: "99.97%", latency_p95: "82ms"  },
    { name: "Emissions API", status: "healthy",  uptime: "99.99%", latency_p95: "54ms"  },
    { name: "Warehouse API", status: "healthy",  uptime: "99.92%", latency_p95: "120ms" },
    { name: "Admin API",     status: "degraded", uptime: "98.10%", latency_p95: "210ms" },
    { name: "PostgreSQL",    status: "healthy",  uptime: "100%",   latency_p95: "12ms"  },
    { name: "MongoDB",       status: "healthy",  uptime: "100%",   latency_p95: "8ms"   },
    { name: "MLflow",        status: "healthy",  uptime: "99.95%", latency_p95: "44ms"  },
    { name: "Redis",         status: "healthy",  uptime: "100%",   latency_p95: "2ms"   },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Data Sources
// ────────────────────────────────────────────────────────────────────

export type SourceHealth = "healthy" | "degraded" | "down" | "unknown";
export type DataSourceCategory = "grid" | "weather" | "carbon" | "fuel" | "custom";

export interface DataSource {
  id: string;
  name: string;
  category: DataSourceCategory;
  vendor: string;
  region: string;
  cadence: string;
  cron: string;
  description: string;
  enabled: boolean;
  last_sync: string;
  last_status: "success" | "failed" | "partial" | "queued";
  records_today: number;
  health: SourceHealth;
  api_endpoint: string;
}

export function getDataSources(): DataSource[] {
  return [
    { id: "ds-aemo-nem",   name: "AEMO NEM",            category: "grid",    vendor: "AEMO",            region: "AU NEM", cadence: "Every 5 min",   cron: "*/5 * * * *",   description: "5-min dispatch + SCADA for the 5 NEM regions",                              enabled: true,  last_sync: "2 min ago",  last_status: "success", records_today: 8_640,  health: "healthy",  api_endpoint: "https://nemweb.com.au/..." },
    { id: "ds-aemo-wem",   name: "AEMO WEM",            category: "grid",    vendor: "AEMO WA",         region: "AU WEM", cadence: "Every 30 min",  cron: "*/30 * * * *",  description: "30-min market data for WA (single region)",                                  enabled: true,  last_sync: "12 min ago", last_status: "success", records_today: 48,     health: "healthy",  api_endpoint: "data.wa.aemo.com.au"      },
    { id: "ds-entsoe",     name: "ENTSO-E",             category: "grid",    vendor: "ENTSO-E",         region: "EU",     cadence: "Hourly",        cron: "0 * * * *",     description: "European grid transparency (load + generation + prices)",                  enabled: true,  last_sync: "1 hr ago",   last_status: "success", records_today: 24,     health: "healthy",  api_endpoint: "transparency.entsoe.eu"  },
    { id: "ds-open-meteo", name: "Open-Meteo",          category: "weather", vendor: "Open-Meteo",      region: "Global", cadence: "Hourly",        cron: "0 * * * *",     description: "Free global weather forecast (no API key required)",                        enabled: true,  last_sync: "15 min ago", last_status: "success", records_today: 4_320,  health: "healthy",  api_endpoint: "api.open-meteo.com"      },
    { id: "ds-bom",        name: "BoM Observations",    category: "weather", vendor: "BoM",             region: "AU",     cadence: "Every 30 min",  cron: "*/30 * * * *",  description: "6 NEM/WEM weather stations via BoM v1 API",                                 enabled: true,  last_sync: "22 min ago", last_status: "success", records_today: 1_440,  health: "healthy",  api_endpoint: "api.weather.bom.gov.au"  },
    { id: "ds-carbon",     name: "Carbon Intensity API",category: "carbon", vendor: "Electricity Maps",region: "Global", cadence: "Hourly",        cron: "0 * * * *",     description: "Carbon intensity (gCO₂/kWh) per region",                                     enabled: true,  last_sync: "30 min ago", last_status: "success", records_today: 24,     health: "healthy",  api_endpoint: "api.electricitymaps.com" },
    { id: "ds-fuel-ice",   name: "ICE Fuel Prices",     category: "fuel",    vendor: "ICE",             region: "Global", cadence: "Every 2 hours", cron: "0 */2 * * *",   description: "Gas + coal + oil benchmark prices",                                          enabled: false, last_sync: "1 hr ago",   last_status: "failed",  records_today: 0,      health: "degraded", api_endpoint: "theice.com/..."          },
    { id: "ds-eia",        name: "EIA Open Data",       category: "grid",    vendor: "EIA",             region: "US",     cadence: "Hourly",        cron: "0 * * * *",     description: "US EIA generation + demand + price (US benchmark)",                         enabled: true,  last_sync: "1 hr ago",   last_status: "success", records_today: 24,     health: "healthy",  api_endpoint: "api.eia.gov"             },
    { id: "ds-custom-1",   name: "Custom REST — Site Meters", category: "custom", vendor: "Internal", region: "AU NEM", cadence: "Every 5 min",   cron: "*/5 * * * *",   description: "Customer's internal site-meter telemetry (REST/JSON)",                       enabled: true,  last_sync: "3 min ago",  last_status: "success", records_today: 12_000, health: "healthy",  api_endpoint: "https://internal/meters" },
  ];
}

export function getSourceCategories() {
  return [
    { id: "grid",    label: "Grid Operators", count: 4 },
    { id: "weather", label: "Weather",        count: 2 },
    { id: "carbon",  label: "Carbon",         count: 1 },
    { id: "fuel",    label: "Fuel Markets",   count: 1 },
    { id: "custom",  label: "Custom REST",    count: 1 },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Data Ingestion Pipelines
// ────────────────────────────────────────────────────────────────────

export type PipelineState = "running" | "success" | "failed" | "queued" | "paused";

export interface Pipeline {
  id: string;
  name: string;
  source: string;
  schedule: string;
  cron: string;
  last_run: string;
  duration: string;
  records: number;
  state: PipelineState;
  triggered_by: string;
}

export function getPipelines(): Pipeline[] {
  return [
    { id: "pl-1", name: "Grid Operations Data", source: "ENTSO-E API",          schedule: "Every 5 min",   cron: "*/5 * * * *",  last_run: "2 min ago",  duration: "4.2s", records:    288, state: "running", triggered_by: "Cron"  },
    { id: "pl-2", name: "Weather Data",         source: "Open-Meteo API",      schedule: "Every 15 min",  cron: "*/15 * * * *", last_run: "12 min ago", duration: "8.1s", records:  1_440, state: "success", triggered_by: "Cron"  },
    { id: "pl-3", name: "Generation Mix",       source: "EIA API",             schedule: "Every hour",    cron: "0 */1 * * *",  last_run: "28 min ago", duration: "12.0s",records:     48, state: "success", triggered_by: "Cron"  },
    { id: "pl-4", name: "Carbon Intensity",     source: "Carbon Intensity API",schedule: "Every hour",    cron: "0 */1 * * *",  last_run: "31 min ago", duration: "9.7s", records:     24, state: "success", triggered_by: "Cron"  },
    { id: "pl-5", name: "Fuel Prices",          source: "ICE API",             schedule: "Every 2 hours", cron: "0 */2 * * *",  last_run: "1 hr ago",   duration: "—",     records:      0, state: "failed",  triggered_by: "Cron"  },
    { id: "pl-6", name: "WEM Dispatch",         source: "AEMO WEM",            schedule: "Every 30 min",  cron: "*/30 * * * *", last_run: "5 min ago",  duration: "3.4s", records:     16, state: "success", triggered_by: "Cron"  },
    { id: "pl-7", name: "Distributed PV",       source: "APVI",                schedule: "Daily 06:00",   cron: "0 6 * * *",    last_run: "3 hr ago",   duration: "—",     records:      0, state: "failed",  triggered_by: "Cron"  },
    { id: "pl-8", name: "Site Meters",          source: "Custom REST",         schedule: "Every 5 min",   cron: "*/5 * * * *",  last_run: "3 min ago",  duration: "2.1s", records:    120, state: "success", triggered_by: "Cron"  },
  ];
}

export interface PipelineRun {
  id: string;
  pipeline_id: string;
  started_at: string;
  duration: string;
  records: number;
  state: PipelineState;
  triggered_by: string;
}

export function getPipelineRuns(limit = 12): PipelineRun[] {
  const states: PipelineState[] = ["success", "success", "success", "failed", "success", "success"];
  const trigs = ["Cron", "Cron", "Admin", "Cron", "Cron", "API"];
  const out: PipelineRun[] = [];
  for (let i = 0; i < limit; i++) {
    const state = states[i % states.length];
    out.push({
      id: `run-${1000 + i}`,
      pipeline_id: `pl-${(i % 8) + 1}`,
      started_at: `${(i + 1) * 5} min ago`,
      duration: `${(2 + (i % 4) * 1.3).toFixed(1)}s`,
      records: ((i * 137) % 1500),
      state,
      triggered_by: trigs[i % trigs.length],
    });
  }
  return out;
}

export interface FailedJob {
  id: string;
  pipeline: string;
  error_code: string;
  error_message: string;
  occurred_at: string;
  retryable: boolean;
}

export function getFailedJobs(): FailedJob[] {
  return [
    { id: "fj-1", pipeline: "Fuel Prices",    error_code: "HTTP 503", error_message: "Service Unavailable from upstream ICE API", occurred_at: "1 hr ago",  retryable: true  },
    { id: "fj-2", pipeline: "Distributed PV", error_code: "TIMEOUT",  error_message: "No response within 30s",                  occurred_at: "3 hr ago",  retryable: true  },
    { id: "fj-3", pipeline: "Site Meters",    error_code: "AUTH 401", error_message: "Token expired",                           occurred_at: "1 day ago", retryable: false },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Data Quality
// ────────────────────────────────────────────────────────────────────

export interface QualityCheck {
  id: string;
  name: string;
  rule: string;
  severity: "low" | "medium" | "high" | "critical";
  pass_rate: number;
  failing_records: number;
  last_evaluated: string;
}

export function getQualityChecks(): QualityCheck[] {
  return [
    { id: "q-1", name: "Demand ≥ 0",            rule: "ts.demand_mw >= 0",          severity: "critical", pass_rate: 99.98, failing_records:  18, last_evaluated: "5 min ago" },
    { id: "q-2", name: "Region in NEM",         rule: "ts.region IN ('NSW1',...)",  severity: "high",     pass_rate: 100,   failing_records:   0, last_evaluated: "5 min ago" },
    { id: "q-3", name: "ts not in future",      rule: "ts.ts <= now()",             severity: "critical", pass_rate: 99.95, failing_records:  48, last_evaluated: "5 min ago" },
    { id: "q-4", name: "Unique (ts, region)",   rule: "COUNT(DISTINCT) == COUNT()", severity: "high",     pass_rate: 100,   failing_records:   0, last_evaluated: "5 min ago" },
    { id: "q-5", name: "Renewable ≤ 100",       rule: "renewable_pct <= 100",       severity: "medium",   pass_rate: 100,   failing_records:   0, last_evaluated: "5 min ago" },
    { id: "q-6", name: "Temperature -40..60",   rule: "temp_c BETWEEN -40 AND 60",  severity: "low",      pass_rate: 99.99, failing_records:   2, last_evaluated: "5 min ago" },
    { id: "q-7", name: "No NULL prices",        rule: "price IS NOT NULL",          severity: "high",     pass_rate: 99.91, failing_records: 102, last_evaluated: "5 min ago" },
    { id: "q-8", name: "Interconnector balance",rule: "ABS(flow) <= 1500",          severity: "medium",   pass_rate: 99.85, failing_records:  18, last_evaluated: "5 min ago" },
  ];
}

export interface SchemaField {
  name: string;
  type: string;
  nullable: boolean;
  description: string;
}

export function getSchemaFields(): SchemaField[] {
  return [
    { name: "ts",            type: "TIMESTAMPTZ", nullable: false, description: "Interval end timestamp" },
    { name: "region",        type: "TEXT",        nullable: false, description: "NEM region (NSW1, QLD1, ...)" },
    { name: "demand_mw",     type: "NUMERIC",     nullable: false, description: "Total demand (MW)" },
    { name: "price",         type: "NUMERIC",     nullable: true,  description: "Spot price ($/MWh)" },
    { name: "renewable_pct", type: "NUMERIC",     nullable: true,  description: "Renewable share %" },
    { name: "intensity",     type: "NUMERIC",     nullable: true,  description: "Carbon intensity g/kWh" },
  ];
}

// ────────────────────────────────────────────────────────────────────
// ML & Feature Store & MLflow
// ────────────────────────────────────────────────────────────────────

export type ModelStage = "production" | "staging" | "archived" | "experiment";

export interface MLModel {
  id: string;
  name: string;
  version: string;
  type: "LSTM" | "XGBoost" | "Transformer" | "RandomForest" | "Linear";
  stage: ModelStage;
  framework: "PyTorch" | "scikit-learn" | "XGBoost" | "JAX";
  trained_at: string;
  performance: { mape?: number; rmse?: number; mae?: number; r2?: number };
  features: number;
  training_duration: string;
}

export function getMLModels(): MLModel[] {
  return [
    { id: "m-1", name: "Demand Forecast LSTM",  version: "v8",  type: "LSTM",         stage: "production", framework: "PyTorch",      trained_at: "May 12, 2026", performance: { mape: 2.34, rmse: 184.2, mae: 142.1, r2: 0.954 }, features: 42, training_duration: "12m" },
    { id: "m-2", name: "Demand Forecast LSTM",  version: "v8c", type: "LSTM",         stage: "staging",    framework: "PyTorch",      trained_at: "May 18, 2026", performance: { mape: 2.18, rmse: 178.1, mae: 138.0, r2: 0.961 }, features: 48, training_duration: "14m" },
    { id: "m-3", name: "Carbon Intensity XGB",  version: "v3",  type: "XGBoost",      stage: "production", framework: "XGBoost",      trained_at: "Apr 28, 2026", performance: { rmse: 41.2, mae: 32.1, r2: 0.882 },                        features: 18, training_duration: "8m"  },
    { id: "m-4", name: "Renewable Share Transformer", version: "v2", type: "Transformer", stage: "staging", framework: "PyTorch",    trained_at: "May 14, 2026", performance: { mape: 4.12, rmse: 88.4, r2: 0.901 },                        features: 36, training_duration: "32m" },
    { id: "m-5", name: "Price Forecast RF",     version: "v1",  type: "RandomForest", stage: "archived",   framework: "scikit-learn", trained_at: "Feb 12, 2026", performance: { mape: 5.18, rmse: 42.1 },                                           features: 22, training_duration: "2m"  },
  ];
}

export interface TrainingJob {
  id: string;
  model: string;
  type: "train" | "fine-tune" | "hparam-search";
  started_at: string;
  duration: string;
  state: "running" | "finished" | "failed" | "queued";
  progress_pct: number;
  experiment: string;
}

export function getTrainingJobs(limit = 8): TrainingJob[] {
  return [
    { id: "tj-1", model: "Demand Forecast LSTM",     type: "hparam-search", started_at: "yesterday",  duration: "4h 12m", state: "finished", progress_pct: 100, experiment: "lstm_demand_v8_hptune" },
    { id: "tj-2", model: "Carbon Intensity XGB",     type: "fine-tune",     started_at: "2 days ago", duration: "8m 22s",  state: "finished", progress_pct: 100, experiment: "carbon_intensity_xgb" },
    { id: "tj-3", model: "Demand Forecast LSTM",     type: "train",         started_at: "May 12",     duration: "12m",     state: "finished", progress_pct: 100, experiment: "lstm_demand_v8" },
    { id: "tj-4", model: "Renewable Share Transformer", type: "train",     started_at: "May 14",     duration: "32m",     state: "finished", progress_pct: 100, experiment: "renewable_xformer_v2" },
    { id: "tj-5", model: "Demand Forecast LSTM",     type: "train",         started_at: "now",        duration: "—",        state: "running",  progress_pct:  42, experiment: "lstm_demand_v9" },
  ];
}

export interface DeploymentRecord {
  id: string;
  model: string;
  version: string;
  environment: "production" | "staging" | "canary";
  deployed_at: string;
  replicas: number;
  cpu_pct: number;
  latency_p95_ms: number;
  traffic_pct: number;
}

export function getDeployments(): DeploymentRecord[] {
  return [
    { id: "dep-1", model: "Demand Forecast LSTM",      version: "v8",  environment: "production", deployed_at: "May 12, 2026", replicas: 3, cpu_pct: 42, latency_p95_ms:  82, traffic_pct: 100 },
    { id: "dep-2", model: "Demand Forecast LSTM",      version: "v8c", environment: "canary",     deployed_at: "May 18, 2026", replicas: 1, cpu_pct: 12, latency_p95_ms:  78, traffic_pct:   5 },
    { id: "dep-3", model: "Carbon Intensity XGB",      version: "v3",  environment: "production", deployed_at: "Apr 28, 2026", replicas: 2, cpu_pct: 18, latency_p95_ms:  22, traffic_pct: 100 },
    { id: "dep-4", model: "Renewable Share Transformer", version: "v2", environment: "staging",   deployed_at: "May 14, 2026", replicas: 1, cpu_pct: 24, latency_p95_ms: 142, traffic_pct:   0 },
  ];
}

export interface FeatureGroup {
  id: string;
  name: string;
  entity: string;
  features: number;
  last_materialized: string;
  owner: string;
}

export function getFeatureGroups(): FeatureGroup[] {
  return [
    { id: "fg-1", name: "demand_lag_24h",     entity: "region",  features: 18, last_materialized: "5 min ago",  owner: "ML Team" },
    { id: "fg-2", name: "weather_features",   entity: "station", features: 24, last_materialized: "30 min ago", owner: "ML Team" },
    { id: "fg-3", name: "calendar_features",  entity: "date",    features: 12, last_materialized: "1 day ago",  owner: "ML Team" },
    { id: "fg-4", name: "price_features",     entity: "region",  features: 32, last_materialized: "5 min ago",  owner: "Trading" },
    { id: "fg-5", name: "renewable_features", entity: "region",  features: 16, last_materialized: "30 min ago", owner: "ML Team" },
  ];
}

export interface MlflowExperiment {
  id: string;
  name: string;
  runs: number;
  best_metric: string;
  best_value: number;
  owner: string;
}

export function getMlflowExperiments(): MlflowExperiment[] {
  return [
    { id: "exp-1", name: "lstm_demand_v8",        runs: 24, best_metric: "MAPE", best_value: 2.34, owner: "diptu" },
    { id: "exp-2", name: "lstm_demand_v8_hptune", runs: 48, best_metric: "MAPE", best_value: 2.18, owner: "diptu" },
    { id: "exp-3", name: "rf_baseline",           runs:  6, best_metric: "MAPE", best_value: 3.42, owner: "demo"  },
    { id: "exp-4", name: "carbon_intensity_xgb",  runs: 12, best_metric: "RMSE", best_value: 41.2, owner: "diptu" },
  ];
}

export interface MlflowRun {
  id: string;
  experiment: string;
  status: "running" | "finished" | "failed" | "killed";
  started: string;
  duration: string;
  metrics: Record<string, number>;
}

export function getMlflowRuns(limit = 8): MlflowRun[] {
  return [
    { id: "run-a1b2", experiment: "lstm_demand_v8",        status: "finished", started: "2 hr ago",  duration: "12m", metrics: { mape: 2.34, rmse: 184.2 } },
    { id: "run-c3d4", experiment: "lstm_demand_v8_hptune", status: "finished", started: "yesterday", duration: "4h",  metrics: { mape: 2.18, rmse: 178.1 } },
    { id: "run-e5f6", experiment: "carbon_intensity_xgb",  status: "finished", started: "1 day ago", duration: "8m",  metrics: { rmse: 41.2 } },
    { id: "run-g7h8", experiment: "rf_baseline",           status: "finished", started: "3 day ago", duration: "2m",  metrics: { mape: 3.42 } },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Users, Settings, Orgs, API Keys
// ────────────────────────────────────────────────────────────────────

export type UserRole = "admin" | "analyst" | "viewer" | "owner";

export interface UserAccount {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  org: string;
  status: "active" | "invited" | "suspended";
  last_active: string;
  mfa_enabled: boolean;
}

export function getUsers(): UserAccount[] {
  return [
    { id: "u-1", email: "diptu@ecolens.com", name: "Diptu",        role: "admin",   org: "Acme Energy", status: "active",  last_active: "now",       mfa_enabled: true  },
    { id: "u-2", email: "diptu@ecolens.app", name: "Diptu (app)",  role: "admin",   org: "Acme Energy", status: "active",  last_active: "2 hr ago",  mfa_enabled: true  },
    { id: "u-3", email: "demo@ecolens.app",  name: "Demo User",    role: "analyst", org: "Acme Energy", status: "active",  last_active: "1 day ago", mfa_enabled: false },
    { id: "u-4", email: "kelly@acme.com",    name: "Kelly Zhao",   role: "analyst", org: "Acme Energy", status: "active",  last_active: "3 hr ago",  mfa_enabled: true  },
    { id: "u-5", email: "nimal@acme.com",    name: "Nimal Perera", role: "analyst", org: "Acme Energy", status: "active",  last_active: "yesterday", mfa_enabled: false },
    { id: "u-6", email: "raj@acme.com",      name: "Raj Patel",    role: "viewer",  org: "Acme Energy", status: "active",  last_active: "1 wk ago",  mfa_enabled: false },
    { id: "u-7", email: "li@acme.com",       name: "Li Zhang",     role: "viewer",  org: "Acme Energy", status: "invited", last_active: "—",         mfa_enabled: false },
  ];
}

export function getOrganizations() {
  return [
    { id: "org-1", name: "Acme Energy",     industry: "Energy",     region: "AU NEM", members: 142, emissions_tco2e: 125_430, plan: "Enterprise", created_at: "2024-08-12" },
    { id: "org-2", name: "Northwind Power", industry: "Generation", region: "AU NEM", members:  48, emissions_tco2e:  62_180, plan: "Pro",        created_at: "2025-01-04" },
    { id: "org-3", name: "Contoso Solar",   industry: "Solar",      region: "AU NEM", members:  18, emissions_tco2e:   4_220, plan: "Starter",    created_at: "2025-09-18" },
    { id: "org-4", name: "Watt Utilities",  industry: "Utility",    region: "AU WEM", members:  62, emissions_tco2e:  28_440, plan: "Pro",        created_at: "2024-11-22" },
  ];
}

export function getAPIKeys() {
  return [
    { id: "k-1", name: "Production",   prefix: "eco_live_3a2b…", created_at: "2024-09-12", last_used: "2 min ago",  scopes: ["read:*", "write:forecast"], created_by: "diptu@ecolens.com" },
    { id: "k-2", name: "Staging",      prefix: "eco_test_91c4…", created_at: "2025-02-04", last_used: "1 day ago",  scopes: ["read:*"],                    created_by: "diptu@ecolens.app" },
    { id: "k-3", name: "Data Science", prefix: "eco_ds_f0e7…",   created_at: "2025-08-22", last_used: "3 hr ago",   scopes: ["read:data", "read:ml"],      created_by: "kelly@acme.com"    },
  ];
}

export function getServiceAccounts() {
  return [
    { id: "sa-1", name: "dbt-runner", client_id: "sa-dbt-001", purpose: "Trigger dbt models from cron", created_at: "2024-08-12", enabled: true  },
    { id: "sa-2", name: "mlflow",     client_id: "sa-mlf-002", purpose: "MLflow tracking",              created_at: "2024-08-15", enabled: true  },
    { id: "sa-3", name: "airbyte",    client_id: "sa-air-003", purpose: "Airbyte connector",             created_at: "2025-01-10", enabled: true  },
  ];
}

export interface SettingField {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "boolean" | "secret";
  value: string | number | boolean;
  options?: string[];
  category: "general" | "branding" | "security" | "env" | "secrets" | "storage" | "backup" | "flags";
}

export function getSettings(): SettingField[] {
  return [
    { key: "site_name",         label: "Site Name",         type: "text",    value: "ecoLens",                                category: "general"   },
    { key: "primary_color",     label: "Primary Color",     type: "text",    value: "#10b981",                                category: "branding"  },
    { key: "logo_url",          label: "Logo URL",          type: "text",    value: "/images/logo.svg",                       category: "branding"  },
    { key: "require_mfa",       label: "Require MFA",       type: "boolean", value: true,                                    category: "security"  },
    { key: "session_ttl_hours", label: "Session TTL (h)",   type: "number",  value: 8,                                       category: "security"  },
    { key: "env_mode",          label: "Environment",       type: "select",  value: "production", options: ["development", "staging", "production"], category: "env" },
    { key: "db_url",            label: "Database URL",      type: "secret",  value: "postgresql://ecolens:****@db:5432/eco",  category: "secrets"   },
    { key: "mlflow_uri",        label: "MLflow Tracking",   type: "text",    value: "http://mlflow:5000",                    category: "env"       },
    { key: "storage_backend",   label: "Storage Backend",   type: "select",  value: "postgresql", options: ["postgresql", "s3", "gcs"], category: "storage" },
    { key: "auto_backup",       label: "Auto-backup",       type: "boolean", value: true,                                    category: "backup"    },
    { key: "beta_ai_recs",      label: "Beta: AI Recs",     type: "boolean", value: false,                                   category: "flags"     },
    { key: "new_forecast_ui",   label: "New Forecast UI",   type: "boolean", value: true,                                    category: "flags"     },
  ];
}
