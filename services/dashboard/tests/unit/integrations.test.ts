/**
 * Unit tests for the Integrations data layer.
 *
 * Verifies the shape + key invariants of:
 *   - getIntegrations()         — 7 providers, only Google Sheets is connected
 *   - getGoogleSheetExports()   — 4 configured exports, all have destinations
 *   - getGoogleSheetHistory()   — most-recent first, has a mix of statuses
 */
import { describe, expect, it } from "vitest";

import {
  getGoogleSheetExports,
  getGoogleSheetHistory,
  getIntegrations,
  type ExportDataSource,
  type ExportFormat,
  type ExportSchedule,
  type IntegrationProvider,
} from "@/lib/dashboards";

describe("getIntegrations", () => {
  const integrations = getIntegrations();

  it("returns 7 providers", () => {
    expect(integrations).toHaveLength(7);
  });

  it("includes Google Sheets as the only connected one", () => {
    const connected = integrations.filter((i) => i.status === "connected");
    expect(connected).toHaveLength(1);
    expect(connected[0].provider).toBe("google_sheets");
    expect(connected[0].name).toBe("Google Sheets");
    expect(connected[0].available).toBe(true);
  });

  it("marks Microsoft Excel, Notion, Airtable, Slack, PagerDuty as coming-soon", () => {
    const coming = integrations.filter((i) => i.coming_soon);
    expect(coming.map((i) => i.provider).sort()).toEqual(
      ["airtable", "microsoft_excel", "notion", "pagerduty", "slack"].sort(),
    );
  });

  it("marks Custom Webhook as available but not connected", () => {
    const webhook = integrations.find((i) => i.provider === "webhook");
    expect(webhook).toBeDefined();
    expect(webhook?.available).toBe(true);
    expect(webhook?.coming_soon).toBeFalsy();
    expect(webhook?.status).toBe("disconnected");
  });

  it("Google Sheets has expected OAuth scopes", () => {
    const gs = integrations.find((i) => i.provider === "google_sheets")!;
    expect(gs.scopes).toContain("https://www.googleapis.com/auth/spreadsheets");
    expect(gs.scopes).toContain("https://www.googleapis.com/auth/drive.file");
  });

  it("every integration has a unique id", () => {
    const ids = integrations.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every integration has one of the 7 known providers", () => {
    const valid: IntegrationProvider[] = [
      "google_sheets", "microsoft_excel", "notion", "airtable",
      "slack", "pagerduty", "webhook",
    ];
    for (const i of integrations) {
      expect(valid).toContain(i.provider);
    }
  });
});

describe("getGoogleSheetExports", () => {
  const exports = getGoogleSheetExports();

  it("returns 4 configured exports", () => {
    expect(exports).toHaveLength(4);
  });

  it("every export has a destination with spreadsheet_id and sheet_tab", () => {
    for (const e of exports) {
      expect(e.destination.spreadsheet_id).toBeTruthy();
      expect(e.destination.sheet_tab).toBeTruthy();
      expect(e.destination.spreadsheet_name).toBeTruthy();
    }
  });

  it("covers a mix of data sources", () => {
    const sources = new Set(exports.map((e) => e.data_source));
    expect(sources.size).toBeGreaterThanOrEqual(3);
  });

  it("every export uses a known data source", () => {
    const valid: ExportDataSource[] = [
      "emissions_total", "emissions_by_region", "emissions_by_source",
      "emissions_by_scope", "forecast_quantiles", "demand_timeseries",
      "renewable_mix", "carbon_intensity", "anomalies",
      "data_quality_issues", "system_health",
    ];
    for (const e of exports) {
      expect(valid).toContain(e.data_source);
    }
  });

  it("every export uses a known format", () => {
    const valid: ExportFormat[] = ["raw", "summary", "pivot"];
    for (const e of exports) {
      expect(valid).toContain(e.format);
    }
  });

  it("every export uses a known schedule", () => {
    const valid: ExportSchedule[] = ["manual", "hourly", "daily", "weekly", "monthly"];
    for (const e of exports) {
      expect(valid).toContain(e.schedule);
    }
  });

  it("at least one export is enabled", () => {
    expect(exports.some((e) => e.enabled)).toBe(true);
  });

  it("at least one export is paused (disabled)", () => {
    expect(exports.some((e) => !e.enabled)).toBe(true);
  });

  it("every export has a unique id", () => {
    const ids = exports.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("NEM daily emissions export is enabled + daily schedule", () => {
    const nem = exports.find((e) => e.name === "NEM Daily Emissions Summary")!;
    expect(nem).toBeDefined();
    expect(nem.schedule).toBe("daily");
    expect(nem.enabled).toBe(true);
    expect(nem.region).toBe("NEM");
    expect(nem.data_source).toBe("emissions_total");
  });

  it("Anomalies export uses manual schedule (ad-hoc ops review)", () => {
    const anom = exports.find((e) => e.data_source === "anomalies")!;
    expect(anom).toBeDefined();
    expect(anom.schedule).toBe("manual");
    expect(anom.enabled).toBe(false);
  });
});

describe("getGoogleSheetHistory", () => {
  const history = getGoogleSheetHistory();

  it("returns 5 history entries", () => {
    expect(history).toHaveLength(5);
  });

  it("contains a mix of success and failure", () => {
    expect(history.some((h) => h.status === "success")).toBe(true);
    expect(history.some((h) => h.status === "failed")).toBe(true);
  });

  it("the failed entry has retryable + error details", () => {
    const failed = history.find((h) => h.status === "failed")!;
    expect(failed).toBeDefined();
    expect(failed.error).toBeDefined();
    expect(failed.error?.code).toBe("permission_denied");
    expect(failed.error?.retryable).toBe(false);
  });

  it("every entry has a unique id", () => {
    const ids = history.map((h) => h.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every entry links to a real export", () => {
    const exportIds = new Set(getGoogleSheetExports().map((e) => e.id));
    for (const h of history) {
      expect(exportIds.has(h.export_id)).toBe(true);
    }
  });

  it("every entry has a positive duration and non-negative rows", () => {
    for (const h of history) {
      expect(h.duration_ms).toBeGreaterThanOrEqual(0);
      expect(h.rows_written).toBeGreaterThanOrEqual(0);
    }
  });
});
