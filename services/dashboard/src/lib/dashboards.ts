/**
 * src/lib/dashboards.ts — Data layer for the 14 dashboard pages.
 *
 * All data is deterministic (seeded PRNGs or static) so the same
 * input always produces the same output across page loads and tests.
 *
 * Sections:
 *   - Executive Dashboard   (KPIs, emissions by source)
 *   - Users, Settings, Integrations, Google Sheets export
 */

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
    { label: "Total CO₂e (MTD)", value: "—",  unit: "tCO₂e", delta_pct: null, trend: "flat", good_when: "down" },
    { label: "Carbon Intensity",  value: "—",    unit: "g/kWh", delta_pct: null, trend: "flat", good_when: "down" },
    { label: "Renewable Share",   value: "—",   unit: "%",     delta_pct: null, trend: "flat",   good_when: "up"   },
    { label: "Avg Wholesale Price (YTD)", value: "—", unit: "$/MWh",   delta_pct: null,  trend: "flat",   good_when: "down"   },
    { label: "Data Quality Score", value: "—",     unit: "%",  delta_pct: null,  trend: "flat",   good_when: "up"   },
    { label: "Open Risks",        value: "—",      unit: "high+",  delta_pct: null, trend: "flat", good_when: "down" },
  ];
}

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
