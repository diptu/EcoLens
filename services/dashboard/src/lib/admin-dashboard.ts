/**
 * Data layer for the new Admin Dashboard + Operational Tasks pages.
 *
 * The dashboard is a higher-level overview (orgs / users / emissions)
 * and Operational Tasks is a pipeline + model training control surface.
 *
 * Pure deterministic generators (no Date.now() in the hot path) so the
 * data is reproducible across SSR and CSR.
 */
import { generateAdminUsers, type User } from "@/lib/admin";

// ────────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────────

export type ComplianceStatus = "compliant" | "partial" | "pending";
export type AlertLevel = "critical" | "warning" | "info";
export type ReportStatus = "completed" | "processing" | "failed";
export type PipelineSource =
  | "ENTSO-E API"
  | "Open-Meteo API"
  | "EIA API"
  | "Carbon Intensity API"
  | "ICE API"
  | "EIA";
export type PipelineSchedule =
  | "*/5 * * * *"     // every 5 min
  | "*/15 * * * *"    // every 15 min
  | "*/30 * * * *"    // every 30 min
  | "0 */1 * * *"     // every hour
  | "0 */2 * * *"     // every 2 hours
  | "0 */6 * * *"     // every 6 hours
  | "0 2 * * *"       // 2 AM daily
  | "0 3 * * 0"       // 3 AM Sunday
  | "0 0 * * *"       // every day
  | "0 0 1 * *";      // every month
export type PipelineStatus = "running" | "success" | "failed" | "queued";
export type ComputeType = "CPU" | "GPU" | "TPU";
export type TaskType =
  | "ingestion"
  | "model_training"
  | "data_quality"
  | "feature_build"
  | "forecast"
  | "report"
  | "anomaly";
export type TaskStatus = "running" | "queued" | "completed" | "failed";

export interface AdminKpi {
  label: string;
  value: number | string;
  unit?: string;
  delta_pct: number;          // vs last 7 days
  trend: "up" | "down" | "flat";
  good_when: "up" | "down";   // which direction is "good"
  icon: string;               // lucide-react icon name
}

export interface EmissionsTrendPoint {
  date: string;                // YYYY-MM-DD
  actual: number;
  forecast_p10: number;
  forecast_p50: number;
  forecast_p90: number;
}

export interface ScopeSlice {
  name: string;                // "Scope 1", "Scope 2", "Scope 3"
  pct: number;
  tco2e: number;
  color: string;               // hex
}

export interface FuelSlice {
  name: string;
  pct: number;
  color: string;
}

export interface IngestionStatus {
  success: number;
  failed: number;
  pending: number;
}

export interface RecentReport {
  name: string;
  organization: string;
  generated_at: string;
  status: ReportStatus;
}

export interface RecentAlert {
  level: AlertLevel;
  message: string;
  ago: string;                 // human-readable
}

export interface RecentUser {
  name: string;
  organization: string;
  joined_at: string;
}

export interface UpcomingDeadline {
  name: string;
  due: string;
  remaining: string;           // e.g. "3 days left"
}

export interface ComplianceItem {
  framework: string;
  status: ComplianceStatus;
}

// ────────────────────────────────────────────────────────────────────
// Admin Dashboard: deterministic PRNG
// ────────────────────────────────────────────────────────────────────

function _seededRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ANCHOR_DATE = new Date("2026-05-19T12:00:00Z").getTime();

function _ago(days: number): string {
  return new Date(ANCHOR_DATE - days * 86_400_000).toISOString();
}

function _dateStr(days: number): string {
  return new Date(ANCHOR_DATE - days * 86_400_000).toISOString().slice(0, 10);
}

// ────────────────────────────────────────────────────────────────────
// Admin Dashboard KPIs
// ────────────────────────────────────────────────────────────────────

export function getAdminKpis(): AdminKpi[] {
  return [
    {
      label: "Organizations",
      value: 48,
      delta_pct: 12,
      trend: "up",
      good_when: "up",
      icon: "Building2",
    },
    {
      label: "Active Users",
      value: 326,
      delta_pct: 18,
      trend: "up",
      good_when: "up",
      icon: "Users",
    },
    {
      label: "Total CO\u2082e",
      unit: "t",
      value: 125_430,
      delta_pct: -8.4,
      trend: "down",
      good_when: "down",
      icon: "Cloud",
    },
    {
      label: "Carbon Intensity",
      unit: "gCO\u2082e/MWh",
      value: 386,
      delta_pct: -6.2,
      trend: "down",
      good_when: "down",
      icon: "Leaf",
    },
    {
      label: "Renewable Proportion",
      unit: "%",
      value: 57.6,
      delta_pct: 7.3,
      trend: "up",
      good_when: "up",
      icon: "Wind",
    },
    {
      label: "Active Recommendations",
      value: 23,
      delta_pct: 5,
      trend: "up",
      good_when: "up",
      icon: "Lightbulb",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Emissions trend (last 8 days)
// ────────────────────────────────────────────────────────────────────

export function getEmissionsTrend(): EmissionsTrendPoint[] {
  const rng = _seededRng(2026_05_19);
  const out: EmissionsTrendPoint[] = [];
  let base = 12_000;
  for (let i = 7; i >= 0; i--) {
    const actual = Math.round(base + (rng() - 0.4) * 5_000);
    const p10 = actual - Math.round(2_000 + rng() * 1_500);
    const p50 = actual + Math.round(rng() * 1_000 - 200);
    const p90 = actual + Math.round(3_000 + rng() * 1_500);
    out.push({
      date: _dateStr(i),
      actual,
      forecast_p10: p10,
      forecast_p50: p50,
      forecast_p90: p90,
    });
    base = actual;
  }
  return out;
}

// ────────────────────────────────────────────────────────────────────
// Emissions by Scope (donut) + Generation mix (donut)
// ────────────────────────────────────────────────────────────────────

export function getEmissionsByScope(): ScopeSlice[] {
  return [
    { name: "Scope 1", pct: 62.4, tco2e: 78_150, color: "#34d399" },
    { name: "Scope 2", pct: 24.6, tco2e: 30_850, color: "#22d3ee" },
    { name: "Scope 3", pct: 13.0, tco2e: 16_430, color: "#a78bfa" },
  ];
}

export function getGenerationMix(): FuelSlice[] {
  return [
    { name: "Coal",         pct: 41.2, color: "#64748b" },
    { name: "Natural Gas",  pct: 28.7, color: "#fbbf24" },
    { name: "Hydro",        pct: 12.6, color: "#38bdf8" },
    { name: "Wind",         pct: 8.3,  color: "#34d399" },
    { name: "Solar",        pct: 6.5,  color: "#fb923c" },
    { name: "Other",        pct: 2.7,  color: "#94a3b8" },
  ];
}

// Carbon intensity forecast in gCO2e/MWh derived from the same
// emissions trend curve so the two charts stay coherent.
export function getCarbonIntensityForecast(): Array<{ date: string; p10: number; p50: number; p90: number }> {
  const trend = getEmissionsTrend();
  return trend.map((t) => ({
    date: t.date,
    p10: Math.round(t.actual * 0.81),
    p50: Math.round(t.actual * 0.95),
    p90: Math.round(t.actual * 1.09),
  }));
}

// ────────────────────────────────────────────────────────────────────
// Ingestion status
// ────────────────────────────────────────────────────────────────────

export function getIngestionStatus(): IngestionStatus {
  return {
    success: 18_432,
    failed: 241,
    pending: 13,
  };
}

// ────────────────────────────────────────────────────────────────────
// Recent reports, alerts, users, deadlines
// ────────────────────────────────────────────────────────────────────

export function getRecentReports(): RecentReport[] {
  return [
    { name: "May 2025 Emissions Summary",     organization: "GreenGrid Inc.",  generated_at: "May 19, 2025", status: "completed" },
    { name: "Q2 Sustainability Report",        organization: "EcoPower Ltd.",   generated_at: "May 18, 2025", status: "completed" },
    { name: "Carbon Footprint Analysis",      organization: "Bright Energy",   generated_at: "May 18, 2025", status: "completed" },
    { name: "Scope 3 Assessment",              organization: "PowerHouse Co.",  generated_at: "May 17, 2025", status: "processing" },
    { name: "ESG Performance Report",          organization: "Grid Solutions",   generated_at: "May 17, 2025", status: "completed" },
  ];
}

export function getRecentAlerts(): RecentAlert[] {
  return [
    { level: "critical", message: "Ingestion pipeline failed for source: IESO",    ago: "5m ago"  },
    { level: "warning",  message: "High anomaly rate detected in demand data",      ago: "18m ago" },
    { level: "warning",  message: "Data quality score dropped below threshold",     ago: "32m ago" },
    { level: "info",     message: "Model retraining completed successfully",        ago: "1h ago"  },
    { level: "info",     message: "New data source connected: PJM",                  ago: "2h ago"  },
  ];
}

export function getRecentUsers(): RecentUser[] {
  return [
    { name: "Sarah Johnson",  organization: "GreenGrid Inc.", joined_at: "May 19, 2025" },
    { name: "Michael Chen",   organization: "EcoPower Ltd.",  joined_at: "May 18, 2025" },
    { name: "Priya Patel",    organization: "Bright Energy",  joined_at: "May 18, 2025" },
    { name: "Daniel Kim",     organization: "PowerHouse Co.", joined_at: "May 17, 2025" },
    { name: "James Wilson",   organization: "Grid Solutions", joined_at: "May 17, 2025" },
  ];
}

export function getUpcomingDeadlines(): UpcomingDeadline[] {
  return [
    { name: "Monthly Emissions Report",  due: "May 25, 2025", remaining: "3 days left"  },
    { name: "EU Taxonomy Disclosure",    due: "May 31, 2025", remaining: "9 days left"  },
    { name: "Quarterly Review",          due: "Jun 15, 2025", remaining: "24 days left" },
  ];
}

export function getComplianceItems(): ComplianceItem[] {
  return [
    { framework: "EU Taxonomy",  status: "compliant"  },
    { framework: "GHG Protocol", status: "compliant"  },
    { framework: "ISO 14064",    status: "compliant"  },
    { framework: "TCFD",         status: "partial"    },
    { framework: "CSRD",         status: "pending"    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Operational Tasks page
// ────────────────────────────────────────────────────────────────────

export interface PipelineOp {
  id: string;
  name: string;
  source: PipelineSource;
  schedule: string;        // human-readable
  cron: PipelineSchedule;
  last_run: string;        // human-readable
  status: PipelineStatus;
}

export function getPipelineOps(): PipelineOp[] {
  return [
    { id: "pipe-1", name: "Grid Operations Data", source: "ENTSO-E API",        schedule: "Every 5 minutes",  cron: "*/5 * * * *",   last_run: "5 min ago",      status: "running" },
    { id: "pipe-2", name: "Weather Data",          source: "Open-Meteo API",     schedule: "Every 15 minutes", cron: "*/15 * * * *",  last_run: "12 min ago",     status: "success" },
    { id: "pipe-3", name: "Generation Mix",        source: "EIA API",            schedule: "Every hour",       cron: "0 */1 * * *",   last_run: "28 min ago",     status: "success" },
    { id: "pipe-4", name: "Carbon Intensity",      source: "Carbon Intensity API", schedule: "Every hour",     cron: "0 */1 * * *",   last_run: "31 min ago",     status: "success" },
    { id: "pipe-5", name: "Fuel Prices",           source: "ICE API",            schedule: "Every 2 hours",     cron: "0 */2 * * *",   last_run: "1 hr ago",       status: "failed"  },
  ];
}

export interface ActiveTask {
  id: string;
  type: TaskType;
  target: string;
  triggered_by: string;
  started_at: string;
  status: TaskStatus;
  progress: number;       // 0-100
}

export function getActiveTasks(): ActiveTask[] {
  return [
    { id: "task_8f3a1c2d", type: "ingestion",      target: "Grid Operations Data",     triggered_by: "System", started_at: "May 19, 10:20 AM", status: "running",   progress: 65  },
    { id: "task_1a2b3c4d", type: "ingestion",      target: "Weather Data",              triggered_by: "System", started_at: "May 19, 10:18 AM", status: "running",   progress: 40  },
    { id: "task_5d6e7f8g", type: "model_training", target: "Demand Forecast LSTM",      triggered_by: "Admin",  started_at: "May 19, 10:15 AM", status: "running",   progress: 72  },
    { id: "task_9h8j7k6l", type: "data_quality",   target: "Grid Operations Data",     triggered_by: "System", started_at: "May 19, 10:10 AM", status: "completed", progress: 100 },
    { id: "task_2t3r4n5m", type: "feature_build",  target: "Demand Forecast",          triggered_by: "System", started_at: "May 19, 10:00 AM", status: "completed", progress: 100 },
    { id: "task_7p8q9r0s", type: "ingestion",      target: "Fuel Prices",              triggered_by: "System", started_at: "May 19, 09:00 AM", status: "failed",    progress: 0   },
    { id: "task_4k5l6m7n", type: "ingestion",      target: "Distributed PV",           triggered_by: "Admin",  started_at: "May 19, 10:25 AM", status: "queued",    progress: 0   },
    { id: "task_6w7x8y9z", type: "model_training", target: "Carbon Intensity Model",   triggered_by: "Cron",   started_at: "May 19, 10:22 AM", status: "queued",    progress: 0   },
  ];
}

export function getTrainingConfigOptions() {
  return {
    models: [
      "Demand Forecast LSTM",
      "Generation Mix Model",
      "Carbon Intensity Model",
      "Anomaly Detection Model",
    ],
    environments: ["Production", "Staging", "Development"],
    compute: ["CPU (16 cores)", "GPU (NVIDIA T4)", "GPU (NVIDIA A100)", "TPU v3"],
  };
}

export interface TrainingRun {
  model: string;
  version: string;
  trained_at: string;
  status: "completed" | "running" | "failed";
  performance: { mape: number; rmse: number };
}

export function getRecentTrainingRuns(): TrainingRun[] {
  return [
    { model: "Demand Forecast LSTM", version: "v2.3.1", trained_at: "May 17, 02:15 AM", status: "completed", performance: { mape: 2.81, rmse: 542.3 } },
    { model: "Demand Forecast LSTM", version: "v2.3.0", trained_at: "May 14, 01:45 AM", status: "completed", performance: { mape: 2.94, rmse: 588.7 } },
    { model: "Demand Forecast LSTM", version: "v2.2.0", trained_at: "May 11, 02:10 AM", status: "completed", performance: { mape: 3.12, rmse: 589.1 } },
    { model: "Demand Forecast LSTM", version: "v2.1.0", trained_at: "May 08, 01:30 AM", status: "completed", performance: { mape: 3.45, rmse: 625.4 } },
    { model: "Demand Forecast LSTM", version: "v2.0.0", trained_at: "May 05, 12:55 AM", status: "completed", performance: { mape: 3.78, rmse: 661.2 } },
  ];
}

export interface ScheduledOp {
  id: string;
  name: string;
  type: TaskType;
  cron: string;
  next_run: string;
  last_run: string;
  status: "active" | "paused";
}

export function getScheduledOps(): ScheduledOp[] {
  return [
    { id: "s1", name: "Ingestion: Grid Operations", type: "ingestion",      cron: "*/5* * * *", next_run: "May 19, 10:30 AM", last_run: "May 19, 10:25 AM", status: "active" },
    { id: "s2", name: "Ingestion: Weather Data",    type: "ingestion",      cron: "*/15* * * *", next_run: "May 19, 10:30 AM", last_run: "May 19, 10:15 AM", status: "active" },
    { id: "s3", name: "Daily Model Retraining",     type: "model_training", cron: "0 2 * * *",   next_run: "May 20, 02:00 AM", last_run: "May 19, 02:00 AM", status: "active" },
    { id: "s4", name: "Data Quality Check",         type: "data_quality",   cron: "0 */6 * * *", next_run: "May 19, 12:00 PM", last_run: "May 19, 06:00 AM", status: "active" },
    { id: "s5", name: "Weekly Model Evaluation",    type: "model_training", cron: "0 3 * * 0",   next_run: "May 25, 03:00 AM", last_run: "May 18, 03:00 AM", status: "active" },
  ];
}

export interface SystemCommand {
  id: string;
  label: string;
  description: string;
  icon: string;       // lucide name
  destructive: boolean;
}

export function getSystemCommands(): SystemCommand[] {
  return [
    { id: "c1", label: "Rebuild Features",         description: "Rebuild all features for forecasting models",     icon: "RefreshCw",  destructive: false },
    { id: "c2", label: "Refresh Materialized Views",description: "Refresh all dbt materialized views",                icon: "Layers",      destructive: false },
    { id: "c3", label: "Clear Cache",                description: "Clear application and API caches",                   icon: "Trash2",      destructive: true  },
    { id: "c4", label: "Reindex Search",             description: "Reindex search indices",                            icon: "Search",      destructive: false },
    { id: "c5", label: "Vacuum Database",            description: "Run VACUUM on PostgreSQL",                          icon: "Database",    destructive: false },
    { id: "c6", label: "System Diagnostics",         description: "Run full system health diagnostics",                icon: "Activity",    destructive: false },
  ];
}

export interface OperationalKpi {
  label: string;
  value: number | string;
  unit?: string;
  sub: string;
  icon: string;
  tone: "ok" | "warn" | "neutral";
}

export function getOperationalKpis(): OperationalKpi[] {
  return [
    { label: "Ingestion Pipelines", value: 5,           sub: "3 Running · 0 Failed",  icon: "Play",      tone: "ok"      },
    { label: "Active Tasks",        value: 8,           sub: "6 Running · 2 Queued",  icon: "ListTodo",  tone: "ok"      },
    { label: "Last Ingestion",      value: "5 min ago", sub: "May 19, 2025 10:25 AM", icon: "Database",  tone: "neutral" },
    { label: "Model Status",        value: "Healthy",   sub: "All models operational",icon: "Cpu",       tone: "ok"      },
    { label: "Next Retrain",        value: "in 2 days", sub: "May 21, 2025 02:00 AM", icon: "Calendar",  tone: "neutral" },
    { label: "System Load",         value: "28%",       sub: "Normal",                icon: "Activity",  tone: "ok"      },
  ];
}
