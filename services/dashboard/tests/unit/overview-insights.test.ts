/**
 * Tests for src/lib/overview.ts and src/lib/insights.ts.
 */
import { describe, it, expect } from "vitest";

import {
  generateGoals,
  generateOverviewAlerts,
  generateOverviewKpis,
  generateOverviewTrend,
  generateRegionStats,
} from "@/lib/overview";

import {
  generateAnomalies,
  generateForecastVsActual,
  generateInsightKpis,
  generateInsightTrend,
  generateOpportunities,
  generatePeerBenchmarks,
  generateRecommendations,
} from "@/lib/insights";

describe("overview: KPIs", () => {
  it("returns 5 KPIs with required fields", () => {
    const k = generateOverviewKpis();
    expect(k).toHaveLength(5);
    for (const item of k) {
      expect(item.id).toBeTruthy();
      expect(item.label).toBeTruthy();
      expect(item.value).toBeTruthy();
    }
  });
  it("is deterministic", () => {
    expect(generateOverviewKpis()[0].value).toBe(generateOverviewKpis()[0].value);
  });
});

describe("overview: trend", () => {
  it("returns 12 months of data by default", () => {
    const t = generateOverviewTrend(12);
    expect(t.labels).toHaveLength(12);
    expect(t.demand_gwh).toHaveLength(12);
    expect(t.emissions_kt).toHaveLength(12);
    expect(t.renewable_pct).toHaveLength(12);
  });
  it("demand and emissions are positive", () => {
    const t = generateOverviewTrend(6);
    for (const v of t.demand_gwh) expect(v).toBeGreaterThan(0);
    for (const v of t.emissions_kt) expect(v).toBeGreaterThan(0);
  });
});

describe("overview: regions", () => {
  it("returns 6 regions + a NEM total row", () => {
    const r = generateRegionStats("30d");
    expect(r).toHaveLength(7);
    const nem = r.find((x) => x.region === "NEM");
    expect(nem).toBeDefined();
  });
  it("every region row has the required fields", () => {
    const r = generateRegionStats("7d");
    for (const region of r) {
      expect(region.energy_mwh).toBeGreaterThan(0);
      expect(region.emissions_tco2e).toBeGreaterThan(0);
      expect(region.intensity_kg_per_mwh).toBeGreaterThan(0);
      expect(["ok", "warning", "alert"]).toContain(region.status);
    }
  });
});

describe("overview: alerts", () => {
  it("returns up to 6 alerts", () => {
    const a = generateOverviewAlerts(6);
    expect(a.length).toBeLessThanOrEqual(6);
    for (const alert of a) {
      expect(["info", "warning", "alert"]).toContain(alert.severity);
      expect(alert.title).toBeTruthy();
      expect(alert.body).toBeTruthy();
    }
  });
  it("TS1 has renewable-related positive anomaly", () => {
    const a = generateOverviewAlerts(6);
    const tasAlert = a.find((x) => x.region === "TAS1");
    expect(tasAlert).toBeDefined();
  });
});

describe("overview: goals", () => {
  it("returns 4 goals with progress and status", () => {
    const g = generateGoals();
    expect(g).toHaveLength(4);
    for (const goal of g) {
      expect(goal.progressPct).toBeGreaterThanOrEqual(0);
      expect(goal.progressPct).toBeLessThanOrEqual(200);
      expect(["on-track", "behind", "ahead", "achieved"]).toContain(goal.status);
    }
  });
});

describe("insights: KPIs", () => {
  it("returns 4 KPIs with proper trend direction", () => {
    const k = generateInsightKpis();
    expect(k).toHaveLength(4);
    const emissions = k.find((x) => x.id === "emissions");
    expect(emissions?.invertTrend).toBe(true);
  });
});

describe("insights: trend", () => {
  it("returns 12 months of current + prior year", () => {
    const t = generateInsightTrend(12);
    expect(t.current).toHaveLength(12);
    expect(t.prior).toHaveLength(12);
    expect(t.current_indexed[0]).toBe(100);
    expect(t.prior_indexed[0]).toBe(100);
  });
});

describe("insights: anomalies", () => {
  it("returns requested count of anomalies with valid sigma + metric", () => {
    const a = generateAnomalies(5);
    expect(a).toHaveLength(5);
    for (const anomaly of a) {
      expect(["demand", "emissions", "intensity", "renewable", "price"]).toContain(anomaly.metric);
      expect(anomaly.expected).toBeGreaterThan(0);
      expect(typeof anomaly.sigma).toBe("number");
    }
  });
  it("is deterministic", () => {
    const a = generateAnomalies(5);
    const b = generateAnomalies(5);
    expect(a[0].id).toBe(b[0].id);
    expect(a[0].ts).toBe(b[0].ts);
  });
});

describe("insights: opportunities", () => {
  it("returns opportunities sorted by ROI when requested", () => {
    const o = generateOpportunities();
    expect(o.length).toBeGreaterThan(0);
    for (const opp of o) {
      expect(opp.roi_5yr_pct).toBeGreaterThan(0);
      expect(opp.reduction_tco2e).toBeGreaterThan(0);
      expect(["Low", "Medium", "High"]).toContain(opp.effort);
      expect(["High", "Medium", "Low"]).toContain(opp.priority);
    }
  });
});

describe("insights: forecast vs actual", () => {
  it("returns 6 regions with MAPE and band coverage", () => {
    const f = generateForecastVsActual();
    expect(f).toHaveLength(6);
    for (const row of f) {
      expect(row.mape).toBeGreaterThan(0);
      expect(row.band_coverage).toBeGreaterThan(0);
      expect(row.band_coverage).toBeLessThanOrEqual(1);
      expect(["great", "ok", "needs-work"]).toContain(row.status);
    }
  });
});

describe("insights: peer benchmarks", () => {
  it("returns 3 benchmarks with consistent units", () => {
    const b = generatePeerBenchmarks();
    expect(b).toHaveLength(3);
    for (const bench of b) {
      expect(bench.ours).toBeGreaterThan(0);
      expect(bench.industry).toBeGreaterThan(0);
      expect(["top", "above-average", "average", "below-average"]).toContain(bench.rank);
    }
  });
});

describe("insights: recommendations", () => {
  it("returns up to 3 recommendations", () => {
    const r = generateRecommendations(3);
    expect(r).toHaveLength(3);
    for (const rec of r) {
      expect(rec.impact_tco2e).toBeGreaterThan(0);
      expect(["reduce", "switch", "report", "investigate"]).toContain(rec.category);
      expect(["now", "this-week", "this-month", "this-quarter"]).toContain(rec.urgency);
    }
  });
});
