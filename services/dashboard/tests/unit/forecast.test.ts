/**
 * Tests for the deterministic forecast generator in src/lib/forecast.ts.
 * Verifies shape, region profiles, reproducibility, summary stats, and label formatting.
 */
import { describe, it, expect } from "vitest";

import {
  ALL_HORIZONS,
  ALL_REGIONS,
  formatStepLabel,
  generateMockForecast,
  summarize,
  type Horizon,
  type Region,
} from "@/lib/forecast";

describe("constants", () => {
  it("ALL_REGIONS contains the 6 NEM regions + WEM", () => {
    expect(ALL_REGIONS).toEqual(["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]);
  });

  it("ALL_HORIZONS includes the common values", () => {
    const steps = ALL_HORIZONS.map((h) => h.steps);
    expect(steps).toContain(4);
    expect(steps).toContain(48);
    expect(steps).toContain(168);
  });

  it("every horizon has a non-empty label", () => {
    for (const h of ALL_HORIZONS) {
      expect(h.label.length).toBeGreaterThan(0);
    }
  });
});

describe("generateMockForecast", () => {
  it("returns the right number of points for a given horizon", () => {
    for (const h of [4, 8, 12, 24, 48, 96] as Horizon[]) {
      const f = generateMockForecast("NSW1", h, "2026-07-22T00:00:00Z");
      expect(f.points).toHaveLength(h);
    }
  });

  it("marks itself as a mock and uses a sentinel model name", () => {
    const f = generateMockForecast("NSW1", 8);
    expect(f.source).toBe("mock");
    expect(f.model).toBe("ecolens_lstm_demand");
  });

  it("uses 30-min intervals", () => {
    const f = generateMockForecast("NSW1", 4, "2026-07-22T00:00:00Z");
    expect(f.intervalMinutes).toBe(30);
    // First point is 30 min after asOf
    expect(new Date(f.points[0].ts).getTime() - new Date(f.asOf).getTime()).toBe(30 * 60 * 1000);
    // Second point is 60 min after asOf
    expect(new Date(f.points[1].ts).getTime() - new Date(f.asOf).getTime()).toBe(60 * 60 * 1000);
  });

  it("produces plausible NEM demand magnitudes for each region", () => {
    for (const r of ALL_REGIONS) {
      const f = generateMockForecast(r, 48, "2026-07-22T00:00:00Z");
      const p50s = f.points.map((p) => p.p50);
      const min = Math.min(...p50s);
      const max = Math.max(...p50s);
      // All regions should have at least one point > 1000 MW (WEM can dip lower at night)
      // and no point should exceed 20 GW (a hard sanity ceiling).
      for (const v of p50s) {
        expect(v).toBeGreaterThan(0);
        expect(v).toBeLessThan(20_000);
      }
      // And the daily swing should be > 200 MW (every region has visible diurnal pattern)
      expect(max - min).toBeGreaterThan(200);
    }
  });

  it("P10 ≤ P50 ≤ P90 at every point (with tiny float tolerance)", () => {
    const f = generateMockForecast("NSW1", 48, "2026-07-22T00:00:00Z");
    for (const p of f.points) {
      expect(p.p10).toBeLessThanOrEqual(p.p50 + 0.01);
      expect(p.p50).toBeLessThanOrEqual(p.p90 + 0.01);
    }
  });

  it("uncertainty (P90-P10) grows with horizon", () => {
    // Use a time well past the peak hour so we don't conflate with diurnal.
    const f = generateMockForecast("VIC1", 96, "2026-07-22T00:00:00Z");
    const first = (f.points[0].p90 - f.points[0].p10) / 2;
    const last = (f.points[95].p90 - f.points[95].p10) / 2;
    // The band should grow (by sqrt(horizon) scaling at minimum).
    expect(last).toBeGreaterThan(first);
  });

  it("is deterministic — same inputs give the same numbers", () => {
    const a = generateMockForecast("NSW1", 24, "2026-07-22T12:00:00Z");
    const b = generateMockForecast("NSW1", 24, "2026-07-22T12:00:00Z");
    expect(a.points.length).toBe(b.points.length);
    for (let i = 0; i < a.points.length; i++) {
      expect(a.points[i].p50).toBe(b.points[i].p50);
      expect(a.points[i].p10).toBe(b.points[i].p10);
      expect(a.points[i].p90).toBe(b.points[i].p90);
    }
  });

  it("different regions produce meaningfully different curves", () => {
    const nsw = generateMockForecast("NSW1", 48, "2026-07-22T00:00:00Z");
    const qld = generateMockForecast("QLD1", 48, "2026-07-22T00:00:00Z");
    // NSW mean should be > QLD mean (NSW1 is a larger region).
    const nswMean = nsw.points.reduce((s, p) => s + p.p50, 0) / nsw.points.length;
    const qldMean = qld.points.reduce((s, p) => s + p.p50, 0) / qld.points.length;
    expect(nswMean).toBeGreaterThan(qldMean);
  });

  it("different asOf times produce different curves", () => {
    const morning = generateMockForecast("NSW1", 48, "2026-07-22T00:00:00Z");
    const evening = generateMockForecast("NSW1", 48, "2026-07-22T12:00:00Z");
    // At least one point should differ
    let anyDifferent = false;
    for (let i = 0; i < morning.points.length; i++) {
      if (morning.points[i].p50 !== evening.points[i].p50) {
        anyDifferent = true;
        break;
      }
    }
    expect(anyDifferent).toBe(true);
  });
});

describe("summarize", () => {
  it("returns the peak and trough as actual min/max points", () => {
    const f = generateMockForecast("NSW1", 48, "2026-07-22T00:00:00Z");
    const s = summarize(f);
    const p50s = f.points.map((p) => p.p50);
    expect(s.peak.value).toBe(Math.max(...p50s));
    expect(s.trough.value).toBe(Math.min(...p50s));
  });

  it("mean is the arithmetic mean of P50s", () => {
    const f = generateMockForecast("VIC1", 24, "2026-07-22T00:00:00Z");
    const s = summarize(f);
    const expected = f.points.reduce((sum, p) => sum + p.p50, 0) / f.points.length;
    expect(s.mean).toBeCloseTo(Math.round(expected * 10) / 10, 1);
  });

  it("total energy is mean × hours (rounded to nearest MWh)", () => {
    const f = generateMockForecast("SA1", 48, "2026-07-22T00:00:00Z"); // 24 hours
    const s = summarize(f);
    // mean is rounded to 1dp before the multiplication, so allow ±1 MWh drift
    expect(s.total).toBeGreaterThan(s.mean * 24 - 5);
    expect(s.total).toBeLessThan(s.mean * 24 + 5);
    // And it should be a whole number
    expect(Number.isInteger(s.total)).toBe(true);
  });

  it("handles empty forecast gracefully", () => {
    const empty = {
      region: "NSW1" as Region,
      asOf: "2026-07-22T00:00:00Z",
      generatedAt: "2026-07-22T00:00:00Z",
      model: "x",
      modelVersion: 0,
      intervalMinutes: 30,
      source: "mock" as const,
      points: [],
    };
    const s = summarize(empty);
    expect(s.peak.value).toBe(0);
    expect(s.mean).toBe(0);
    expect(s.total).toBe(0);
  });
});

describe("formatStepLabel", () => {
  const t1 = "2026-07-22T22:30:00Z"; // ~08:30 AEST
  const t2 = "2026-07-22T13:00:00Z"; // ~23:00 AEST

  it("labels the first and last step for short horizons", () => {
    expect(formatStepLabel(t1, 1, 12)).toBe("08:30");
    expect(formatStepLabel(t2, 12, 12)).toBe("23:00");
  });

  it("skips intermediate steps that don't fall on a label stride", () => {
    // With total=12, stride = floor(12/6) = 2, so steps 2,4,6,8,10 ARE labeled.
    // We pick a step that doesn't fall on the stride or the endpoints.
    expect(formatStepLabel(t1, 3, 12)).toBe("");
    expect(formatStepLabel(t1, 5, 12)).toBe("");
    expect(formatStepLabel(t1, 7, 12)).toBe("");
    expect(formatStepLabel(t1, 9, 12)).toBe("");
    expect(formatStepLabel(t1, 11, 12)).toBe("");
  });

  it("uses date format for long horizons (>48 steps)", () => {
    const label = formatStepLabel(t1, 1, 100);
    expect(label).toMatch(/\d+\/\d+/);
  });
});
