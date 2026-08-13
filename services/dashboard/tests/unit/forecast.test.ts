/**
 * Tests for src/lib/forecast.ts — region constants and the shared
 * `summarize`/`formatStepLabel` helpers used by the Forecast Explorer
 * page and `FanChart`. (The old deterministic mock generator this file
 * used to test was removed once /dashboard/forecast was wired to
 * forecast-api's real `GET /v1/forecast`.)
 */
import { describe, it, expect } from "vitest";

import { ALL_REGIONS, formatStepLabel, summarize, type Forecast } from "@/lib/forecast";

describe("constants", () => {
  it("ALL_REGIONS contains the 6 NEM regions + WEM", () => {
    expect(ALL_REGIONS).toEqual(["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]);
  });
});

function makeForecast(points: Forecast["points"]): Forecast {
  return {
    region: "NSW1",
    asOf: "2026-07-22T00:00:00Z",
    generatedAt: "2026-07-22T00:00:00Z",
    model: "ecolens_demand_lstm@production",
    modelVersion: 1,
    intervalMinutes: 30,
    source: "api",
    points,
  };
}

describe("summarize", () => {
  it("returns the peak and trough as actual min/max points", () => {
    const f = makeForecast([
      { ts: "2026-07-22T00:30:00Z", step: 1, p10: 90, p50: 100, p90: 110 },
      { ts: "2026-07-22T01:00:00Z", step: 2, p10: 180, p50: 200, p90: 220 },
      { ts: "2026-07-22T01:30:00Z", step: 3, p10: 45, p50: 50, p90: 55 },
    ]);
    const s = summarize(f);
    expect(s.peak.value).toBe(200);
    expect(s.trough.value).toBe(50);
  });

  it("mean is the arithmetic mean of P50s", () => {
    const f = makeForecast([
      { ts: "2026-07-22T00:30:00Z", step: 1, p10: 90, p50: 100, p90: 110 },
      { ts: "2026-07-22T01:00:00Z", step: 2, p10: 180, p50: 200, p90: 220 },
    ]);
    const s = summarize(f);
    expect(s.mean).toBe(150);
  });

  it("total energy is mean × hours (interval-aware)", () => {
    // 30-min interval, 2 steps => 1 hour total window
    const f = makeForecast([
      { ts: "2026-07-22T00:30:00Z", step: 1, p10: 90, p50: 100, p90: 110 },
      { ts: "2026-07-22T01:00:00Z", step: 2, p10: 180, p50: 200, p90: 220 },
    ]);
    const s = summarize(f);
    // sum(p50) * (intervalMinutes/60) = 300 * 0.5 = 150 MWh
    expect(s.total).toBe(150);
  });

  it("handles empty forecast gracefully", () => {
    const empty = makeForecast([]);
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
