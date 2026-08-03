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
  /** `null` when there's no real prior-period comparison to show (the
   * KPI is backed by a live API call with no baseline computed yet) —
   * `KpiCard` hides the delta row entirely rather than render a
   * leftover mock number next to a real value. */
  delta_pct: number | null;
  trend: "up" | "down" | "flat";
  good_when: "up" | "down";
  unit?: string;
}

export function getExecutiveKpis(): ExecutiveKpi[] {
  return [
    { label: "Total CO₂e (YTD)", value: "—",  unit: "tCO₂e", delta_pct: null, trend: "flat", good_when: "down" },
    { label: "Carbon Intensity",  value: "—",    unit: "g/kWh", delta_pct: null, trend: "flat", good_when: "down" },
    { label: "Renewable Share",   value: "—",   unit: "%",     delta_pct: null, trend: "flat",   good_when: "up"   },
    { label: "Avg Wholesale Price (YTD)", value: "—", unit: "$/MWh",   delta_pct: null,  trend: "flat",   good_when: "down"   },
    { label: "Data Quality Score", value: "—",     unit: "%",  delta_pct: null,  trend: "flat",   good_when: "up"   },
    { label: "Open Risks",        value: "—",      unit: "high+",  delta_pct: null, trend: "flat", good_when: "down" },
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

// ───────────────────────────────────────────────────────────────────────
// Integrations — third-party data destinations (Google Sheets, Excel, etc.)
// ───────────────────────────────────────────────────────────────────────

export type IntegrationProvider =
  | "google_sheets"
  | "microsoft_excel"
  | "notion"
  | "airtable"
  | "slack"
  | "pagerduty"
  | "webhook";

export type IntegrationStatus = "connected" | "disconnected" | "expired" | "error";

export interface Integration {
  id: string;
  provider: IntegrationProvider;
  name: string;
  description: string;
  category: "spreadsheet" | "chat" | "incident" | "webhook" | "doc";
  status: IntegrationStatus;
  connected_account?: string;     // e.g. "alice@acme.com"
  connected_at?: string;          // ISO 8601
  scopes?: string[];              // OAuth scopes granted
  config_url?: string;            // external URL (e.g. Google Cloud Console)
  icon_color: string;             // tailwind accent for the card
  available: boolean;             // whether the integration is built/shipped
  coming_soon?: boolean;          // shown as "Coming soon"
  docs_url?: string;
}

/** All known integrations. Google Sheets is shipped; the rest are placeholders. */
export function getIntegrations(): Integration[] {
  return [
    {
      id: "int-google-sheets",
      provider: "google_sheets",
      name: "Google Sheets",
      description:
        "Export emissions, forecasts, and demand data to a Google Sheet — for sharing with stakeholders, custom analysis, or feeding into existing BI workflows.",
      category: "spreadsheet",
      status: "connected",
      connected_account: "diptu@ecolens.com",
      connected_at: "2026-07-20T10:30:00Z",
      scopes: [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
      ],
      config_url: "https://console.cloud.google.com/apis/credentials",
      icon_color: "emerald-200",
      available: true,
      docs_url: "/docs/integrations/google-sheets",
    },
    {
      id: "int-microsoft-excel",
      provider: "microsoft_excel",
      name: "Microsoft Excel Online",
      description:
        "Same as Google Sheets, but writes to an Excel workbook in OneDrive. Best for orgs on the Microsoft 365 stack.",
      category: "spreadsheet",
      status: "disconnected",
      icon_color: "cyan-300",
      available: false,
      coming_soon: true,
      docs_url: "/docs/integrations/microsoft-excel",
    },
    {
      id: "int-notion",
      provider: "notion",
      name: "Notion Database",
      description:
        "Append rows to a Notion database. Useful for sustainability OKR tracking and team-level reporting.",
      category: "doc",
      status: "disconnected",
      icon_color: "white",
      available: false,
      coming_soon: true,
    },
    {
      id: "int-airtable",
      provider: "airtable",
      name: "Airtable",
      description: "Push emissions and forecast data into an Airtable base.",
      category: "spreadsheet",
      status: "disconnected",
      icon_color: "amber-300",
      available: false,
      coming_soon: true,
    },
    {
      id: "int-slack",
      provider: "slack",
      name: "Slack",
      description:
        "Send alert messages to a Slack channel (anomalies, pipeline failures, low-accuracy forecasts).",
      category: "chat",
      status: "disconnected",
      icon_color: "purple-300",
      available: false,
      coming_soon: true,
    },
    {
      id: "int-pagerduty",
      provider: "pagerduty",
      name: "PagerDuty",
      description: "Page on-call engineers when a critical pipeline fails or accuracy drops below threshold.",
      category: "incident",
      status: "disconnected",
      icon_color: "rose-300",
      available: false,
      coming_soon: true,
    },
    {
      id: "int-webhook",
      provider: "webhook",
      name: "Custom Webhook",
      description:
        "POST any ecoLens payload to a URL you control. For custom dashboards, internal tools, or downstream automation.",
      category: "webhook",
      status: "disconnected",
      icon_color: "lime-100",
      available: true,
    },
  ];
}

// ───────────────────────────────────────────────────────────────────────
// Google Sheets export — configured exports + history
// ───────────────────────────────────────────────────────────────────────

export type ExportDataSource =
  | "emissions_total"
  | "emissions_by_region"
  | "emissions_by_source"
  | "emissions_by_scope"
  | "forecast_quantiles"
  | "demand_timeseries"
  | "renewable_mix"
  | "carbon_intensity"
  | "anomalies"
  | "data_quality_issues"
  | "system_health";

export type ExportFormat = "raw" | "summary" | "pivot";
export type ExportSchedule = "manual" | "hourly" | "daily" | "weekly" | "monthly";

export interface GoogleSheetExport {
  id: string;
  name: string;
  data_source: ExportDataSource;
  region: "NEM" | "WEM" | "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1" | "ALL";
  period: "24h" | "7d" | "30d" | "90d" | "ytd" | "custom";
  format: ExportFormat;
  destination: {
    spreadsheet_id: string;
    spreadsheet_name: string;
    sheet_tab: string;            // e.g. "Sheet1" or "raw"
    cell_range?: string;          // e.g. "A1" or "raw!A1:Z1000"
  };
  schedule: ExportSchedule;
  next_run_at?: string;
  last_run_at?: string;
  last_status?: "success" | "failed" | "running" | "queued";
  last_rows_written?: number;
  notify_on_failure: boolean;
  enabled: boolean;
  created_by: string;
  created_at: string;
}

export function getGoogleSheetExports(): GoogleSheetExport[] {
  return [
    {
      id: "exp-001",
      name: "NEM Daily Emissions Summary",
      data_source: "emissions_total",
      region: "NEM",
      period: "7d",
      format: "summary",
      destination: {
        spreadsheet_id: "1BxN3M_pQaVc...",
        spreadsheet_name: "Acme Sustainability KPIs 2026",
        sheet_tab: "Emissions",
        cell_range: "A1",
      },
      schedule: "daily",
      next_run_at: "2026-08-02T01:00:00Z",
      last_run_at: "2026-08-01T01:00:00Z",
      last_status: "success",
      last_rows_written: 168,
      notify_on_failure: true,
      enabled: true,
      created_by: "diptu@ecolens.com",
      created_at: "2026-07-20T10:35:00Z",
    },
    {
      id: "exp-002",
      name: "VIC1 Forecast — P10/P50/P90 (next 24h)",
      data_source: "forecast_quantiles",
      region: "VIC1",
      period: "24h",
      format: "raw",
      destination: {
        spreadsheet_id: "1BxN3M_pQaVc...",
        spreadsheet_name: "Acme Sustainability KPIs 2026",
        sheet_tab: "Forecast_VIC1",
        cell_range: "A1",
      },
      schedule: "hourly",
      next_run_at: "2026-08-01T20:00:00Z",
      last_run_at: "2026-08-01T19:00:00Z",
      last_status: "success",
      last_rows_written: 48,
      notify_on_failure: true,
      enabled: true,
      created_by: "diptu@ecolens.com",
      created_at: "2026-07-25T14:22:00Z",
    },
    {
      id: "exp-003",
      name: "Carbon Intensity — All regions (monthly)",
      data_source: "carbon_intensity",
      region: "ALL",
      period: "30d",
      format: "pivot",
      destination: {
        spreadsheet_id: "1BxN3M_pQaVc...",
        spreadsheet_name: "Acme Sustainability KPIs 2026",
        sheet_tab: "Intensity_Monthly",
        cell_range: "A1",
      },
      schedule: "weekly",
      next_run_at: "2026-08-03T00:00:00Z",
      last_run_at: "2026-07-27T00:00:00Z",
      last_status: "failed",
      last_rows_written: 0,
      notify_on_failure: true,
      enabled: true,
      created_by: "diptu@ecolens.app",
      created_at: "2026-07-15T09:00:00Z",
    },
    {
      id: "exp-004",
      name: "Anomalies (last 7d) — Ops review",
      data_source: "anomalies",
      region: "ALL",
      period: "7d",
      format: "raw",
      destination: {
        spreadsheet_id: "1CyO5L_qRbWd...",
        spreadsheet_name: "Ops Anomaly Tracker",
        sheet_tab: "Sheet1",
        cell_range: "A1",
      },
      schedule: "manual",
      last_run_at: "2026-07-30T11:15:00Z",
      last_status: "success",
      last_rows_written: 23,
      notify_on_failure: false,
      enabled: false,
      created_by: "diptu@ecolens.com",
      created_at: "2026-07-22T16:40:00Z",
    },
  ];
}

// ───────────────────────────────────────────────────────────────────────
// Export history (most-recent first)
// ───────────────────────────────────────────────────────────────────────

export interface ExportHistoryEntry {
  id: string;
  export_id: string;
  export_name: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  status: "success" | "failed" | "running" | "cancelled";
  rows_written: number;
  bytes_written: number;
  destination: string;          // human-readable
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  };
  trigger: "schedule" | "manual" | "retry";
}

export function getGoogleSheetHistory(): ExportHistoryEntry[] {
  return [
    {
      id: "hist-2026-08-01-19-00",
      export_id: "exp-002",
      export_name: "VIC1 Forecast — P10/P50/P90 (next 24h)",
      started_at: "2026-08-01T19:00:00Z",
      finished_at: "2026-08-01T19:00:01.342Z",
      duration_ms: 1342,
      status: "success",
      rows_written: 48,
      bytes_written: 5420,
      destination: "Acme Sustainability KPIs 2026 › Forecast_VIC1",
      trigger: "schedule",
    },
    {
      id: "hist-2026-08-01-01-00",
      export_id: "exp-001",
      export_name: "NEM Daily Emissions Summary",
      started_at: "2026-08-01T01:00:00Z",
      finished_at: "2026-08-01T01:00:08.221Z",
      duration_ms: 8221,
      status: "success",
      rows_written: 168,
      bytes_written: 18432,
      destination: "Acme Sustainability KPIs 2026 › Emissions",
      trigger: "schedule",
    },
    {
      id: "hist-2026-07-31-19-00",
      export_id: "exp-002",
      export_name: "VIC1 Forecast — P10/P50/P90 (next 24h)",
      started_at: "2026-07-31T19:00:00Z",
      finished_at: "2026-07-31T19:00:01.298Z",
      duration_ms: 1298,
      status: "success",
      rows_written: 48,
      bytes_written: 5420,
      destination: "Acme Sustainability KPIs 2026 › Forecast_VIC1",
      trigger: "schedule",
    },
    {
      id: "hist-2026-07-30-11-15",
      export_id: "exp-004",
      export_name: "Anomalies (last 7d) — Ops review",
      started_at: "2026-07-30T11:15:00Z",
      finished_at: "2026-07-30T11:15:00.872Z",
      duration_ms: 872,
      status: "success",
      rows_written: 23,
      bytes_written: 3120,
      destination: "Ops Anomaly Tracker › Sheet1",
      trigger: "manual",
    },
    {
      id: "hist-2026-07-27-00-00",
      export_id: "exp-003",
      export_name: "Carbon Intensity — All regions (monthly)",
      started_at: "2026-07-27T00:00:00Z",
      finished_at: "2026-07-27T00:00:02.143Z",
      duration_ms: 2143,
      status: "failed",
      rows_written: 0,
      bytes_written: 0,
      destination: "Acme Sustainability KPIs 2026 › Intensity_Monthly",
      error: {
        code: "permission_denied",
        message: "The Google account no longer has edit access to this sheet. Reconnect or pick a new sheet.",
        retryable: false,
      },
      trigger: "schedule",
    },
  ];
}
