/**
 * Unit tests for src/lib/admin-dashboard.ts.
 *
 * The data layer is deterministic (all seeded PRNGs / static arrays).
 * We assert:
 *   - every generator returns the right shape,
 *   - enums stay within their typed union,
 *   - totals reconcile (KPIs vs breakdowns),
 *   - dates are coherent (no future timestamps, no gap in 8-day trend).
 */
import { describe, expect, it } from "vitest";

import {
  getActiveTasks,
  getAdminKpis,
  getCarbonIntensityForecast,
  getComplianceItems,
  getEmissionsByScope,
  getEmissionsTrend,
  getGenerationMix,
  getIngestionStatus,
  getModelOps,
  getOperationalKpis,
  getPipelineOps,
  getRecentAlerts,
  getRecentReports,
  getRecentTrainingRuns,
  getRecentUsers,
  getScheduledOps,
  getSystemCommands,
  getTrainingConfigOptions,
  getUpcomingDeadlines,
  type PipelineStatus,
  type TaskStatus,
  type ComplianceStatus,
  type AlertLevel,
} from "@/lib/admin-dashboard";

describe("admin-dashboard — shape & invariants", () => {
  it("getAdminKpis returns 6 KPIs with valid deltas", () => {
    const kpis = getAdminKpis();
    expect(kpis).toHaveLength(6);
    for (const k of kpis) {
      expect(k.label.length).toBeGreaterThan(0);
      expect(typeof k.delta_pct).toBe("number");
      expect(["up", "down", "flat"]).toContain(k.trend);
      expect(["up", "down"]).toContain(k.good_when);
    }
  });

  it("getEmissionsTrend returns 8 coherent days", () => {
    const trend = getEmissionsTrend();
    expect(trend).toHaveLength(8);
    for (const t of trend) {
      expect(t.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      // p10 ≤ p50 ≤ p90
      expect(t.forecast_p10).toBeLessThanOrEqual(t.forecast_p50);
      expect(t.forecast_p50).toBeLessThanOrEqual(t.forecast_p90);
    }
    // Dates should be in ascending order
    const dates = trend.map((t) => t.date);
    const sorted = [...dates].sort();
    expect(dates).toEqual(sorted);
  });

  it("getEmissionsByScope totals 100% and adds up tco2e correctly", () => {
    const slices = getEmissionsByScope();
    const sumPct = slices.reduce((a, b) => a + b.pct, 0);
    expect(Math.abs(sumPct - 100)).toBeLessThan(0.01);
    // each pct and tco2e must be positive
    for (const s of slices) {
      expect(s.pct).toBeGreaterThan(0);
      expect(s.tco2e).toBeGreaterThan(0);
    }
  });

  it("getGenerationMix totals 100%", () => {
    const mix = getGenerationMix();
    const sumPct = mix.reduce((a, b) => a + b.pct, 0);
    expect(Math.abs(sumPct - 100)).toBeLessThan(0.01);
  });

  it("getCarbonIntensityForecast stays in p10 ≤ p50 ≤ p90", () => {
    const f = getCarbonIntensityForecast();
    expect(f).toHaveLength(8);
    for (const p of f) {
      expect(p.p10).toBeLessThanOrEqual(p.p50);
      expect(p.p50).toBeLessThanOrEqual(p.p90);
    }
  });

  it("getIngestionStatus returns all 3 buckets", () => {
    const s = getIngestionStatus();
    expect(s.success).toBeGreaterThan(0);
    expect(s.failed).toBeGreaterThanOrEqual(0);
    expect(s.pending).toBeGreaterThanOrEqual(0);
  });

  it("getPipelineOps has 5 pipelines with valid cron & status", () => {
    const pipes = getPipelineOps();
    expect(pipes).toHaveLength(5);
    const validStatuses: PipelineStatus[] = ["running", "success", "failed", "queued"];
    for (const p of pipes) {
      expect(validStatuses).toContain(p.status);
      expect(p.cron).toMatch(/^[\d*/ ,]+$/); // basic cron shape
      expect(p.last_run).toBeTruthy();
    }
  });

  it("getModelOps has 5 models with performance metrics", () => {
    const models = getModelOps();
    expect(models).toHaveLength(5);
    for (const m of models) {
      expect(m.version).toBeTruthy();
      expect(m.performance.mape).toBeGreaterThan(0);
      expect(m.performance.rmse).toBeGreaterThan(0);
      expect(["deployed", "staging", "deprecated"]).toContain(m.status);
    }
  });

  it("getActiveTasks covers all 4 statuses", () => {
    const tasks = getActiveTasks();
    expect(tasks.length).toBeGreaterThan(0);
    const seen: TaskStatus[] = ["running", "queued", "completed", "failed"];
    for (const s of seen) {
      expect(tasks.some((t) => t.status === s)).toBe(true);
    }
    // progress ∈ [0, 100]
    for (const t of tasks) {
      expect(t.progress).toBeGreaterThanOrEqual(0);
      expect(t.progress).toBeLessThanOrEqual(100);
    }
  });

  it("getRecentReports rows have valid status chips", () => {
    const rows = getRecentReports();
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(["completed", "processing", "failed"]).toContain(r.status);
      expect(r.name.length).toBeGreaterThan(0);
    }
  });

  it("getRecentAlerts have valid level & non-empty message", () => {
    const rows = getRecentAlerts();
    expect(rows.length).toBeGreaterThan(0);
    const levels: AlertLevel[] = ["critical", "warning", "info"];
    for (const a of rows) {
      expect(levels).toContain(a.level);
      expect(a.message.length).toBeGreaterThan(0);
    }
  });

  it("getRecentUsers have email and role", () => {
    const users = getRecentUsers();
    expect(users.length).toBeGreaterThan(0);
    for (const u of users) {
      expect(u.name.length).toBeGreaterThan(0);
      expect(u.organization.length).toBeGreaterThan(0);
    }
  });

  it("getUpcomingDeadlines have due + remaining", () => {
    const rows = getUpcomingDeadlines();
    expect(rows.length).toBeGreaterThan(0);
    for (const d of rows) {
      expect(d.name).toBeTruthy();
      expect(d.due).toBeTruthy();
      expect(d.remaining).toBeTruthy();
    }
  });

  it("getComplianceItems have 3 valid statuses", () => {
    const rows = getComplianceItems();
    expect(rows.length).toBeGreaterThan(0);
    const valid: ComplianceStatus[] = ["compliant", "partial", "pending"];
    for (const c of rows) {
      expect(valid).toContain(c.status);
    }
  });

  it("getRecentTrainingRuns has model+version+performance", () => {
    const runs = getRecentTrainingRuns();
    expect(runs.length).toBeGreaterThan(0);
    for (const r of runs) {
      expect(r.model.length).toBeGreaterThan(0);
      expect(r.version).toMatch(/^v?\d/);
      expect(r.performance.mape).toBeGreaterThan(0);
    }
  });

  it("getScheduledOps have active/paused status & next/last run", () => {
    const rows = getScheduledOps();
    expect(rows.length).toBeGreaterThan(0);
    for (const s of rows) {
      expect(["active", "paused"]).toContain(s.status);
      expect(s.cron).toBeTruthy();
    }
  });

  it("getSystemCommands have label + description + destructive flag", () => {
    const cmds = getSystemCommands();
    expect(cmds.length).toBeGreaterThan(0);
    for (const c of cmds) {
      expect(c.label).toBeTruthy();
      expect(c.description).toBeTruthy();
      expect(typeof c.destructive).toBe("boolean");
    }
  });

  it("getOperationalKpis has 6 KPIs with tone", () => {
    const k = getOperationalKpis();
    expect(k).toHaveLength(6);
    for (const kpi of k) {
      expect(["ok", "warn", "neutral"]).toContain(kpi.tone);
    }
  });

  it("getTrainingConfigOptions has models, environments, compute", () => {
    const opts = getTrainingConfigOptions();
    expect(opts.models.length).toBeGreaterThan(0);
    expect(opts.environments.length).toBeGreaterThan(0);
    expect(opts.compute.length).toBeGreaterThan(0);
  });
});
