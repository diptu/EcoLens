/**
 * Tests for src/lib/emissions.ts — the mock emissions layer
 * that backs the /dashboard/emissions page.
 */
import { describe, it, expect } from "vitest";

import {
  ALL_EMISSION_REGIONS,
  EMISSION_FACTORS,
  formatEnergy,
  formatIntensity,
  formatTco2e,
  generateMockEmissionForecast,
  generateMockEmissionsTimeseries,
  generateMockFuelBreakdown,
  generateMockNationalEmissions,
  generateMockRegionEmissions,
  summarizeEmissions,
} from "@/lib/emissions";

const NOW = "2026-07-22T12:00:00Z";
const SINCE_24H = "2026-07-21T12:00:00Z";
const SINCE_7D = "2026-07-15T12:00:00Z";

describe("constants", () => {
  it("ALL_EMISSION_REGIONS contains 6 NEM regions + WEM", () => {
    expect(ALL_EMISSION_REGIONS).toHaveLength(6);
    expect(ALL_EMISSION_REGIONS).toContain("WEM");
  });

  it("EMISSION_FACTORS has the expected keys", () => {
    expect(EMISSION_FACTORS).toHaveProperty("coal_black_mw");
    expect(EMISSION_FACTORS).toHaveProperty("coal_brown_mw");
    expect(EMISSION_FACTORS).toHaveProperty("wind_mw");
    expect(EMISSION_FACTORS).toHaveProperty("hydro_mw");
  });

  it("brown coal > black coal > gas CCGT > wind", () => {
    expect(EMISSION_FACTORS.coal_brown_mw).toBeGreaterThan(EMISSION_FACTORS.coal_black_mw);
    expect(EMISSION_FACTORS.coal_black_mw).toBeGreaterThan(EMISSION_FACTORS.gas_ccgt_mw);
    expect(EMISSION_FACTORS.gas_ccgt_mw).toBeGreaterThan(EMISSION_FACTORS.wind_mw);
  });
});

describe("formatTco2e", () => {
  it("formats kg, t, kt, Gt correctly", () => {
    expect(formatTco2e(500)).toBe("500 kg");
    expect(formatTco2e(2_500)).toBe("2.5 t");
    expect(formatTco2e(150_000)).toBe("150.0 t");
    expect(formatTco2e(2_000_000)).toBe("2.00 kt");
    expect(formatTco2e(1_500_000_000)).toBe("1.50 Gt");
  });

  it("returns em-dash for null/undefined", () => {
    expect(formatTco2e(null)).toBe("—");
    expect(formatTco2e(undefined)).toBe("—");
  });
});

describe("formatIntensity", () => {
  it("rounds to whole kg/MWh", () => {
    expect(formatIntensity(700.4)).toBe("700 kg/MWh");
    expect(formatIntensity(0)).toBe("0 kg/MWh");
  });
  it("handles null", () => {
    expect(formatIntensity(null)).toBe("—");
  });
});

describe("formatEnergy", () => {
  it("formats MWh, GWh, TWh", () => {
    expect(formatEnergy(500)).toBe("500 MWh");
    expect(formatEnergy(1500)).toBe("1.5 GWh");
    expect(formatEnergy(5_000_000)).toBe("5.00 TWh");
  });
});

describe("generateMockRegionEmissions", () => {
  it("returns the requested scope2 value for the period", () => {
    const r = generateMockRegionEmissions("NSW1", SINCE_24H, NOW, "scope2");
    expect(r.region).toBe("NSW1");
    expect(r.scope).toBe("scope2");
    expect(r.scope2_kgco2e).toBeGreaterThan(0);
    expect(r.intensity_kgco2e_per_mwh).toBeGreaterThan(0);
  });

  it("returns scope1 only when scope is scope1 or all", () => {
    const s2 = generateMockRegionEmissions("VIC1", SINCE_24H, NOW, "scope2");
    expect(s2.scope1_kgco2e).toBeNull();

    const s1 = generateMockRegionEmissions("VIC1", SINCE_24H, NOW, "scope1");
    expect(s1.scope1_kgco2e).toBeGreaterThan(0);
    expect(s1.scope2_kgco2e).toBeNull();

    const both = generateMockRegionEmissions("VIC1", SINCE_24H, NOW, "all");
    expect(both.scope1_kgco2e).toBeGreaterThan(0);
    expect(both.scope2_kgco2e).toBeGreaterThan(0);
  });

  it("is deterministic for the same inputs", () => {
    const a = generateMockRegionEmissions("QLD1", SINCE_7D, NOW, "scope2");
    const b = generateMockRegionEmissions("QLD1", SINCE_7D, NOW, "scope2");
    expect(a.scope2_kgco2e).toBe(b.scope2_kgco2e);
    expect(a.energy_mwh).toBe(b.energy_mwh);
  });

  it("scales with the period length", () => {
    const oneHour = generateMockRegionEmissions("NSW1", NOW, "2026-07-22T13:00:00Z", "scope2");
    const oneDay  = generateMockRegionEmissions("NSW1", NOW, "2026-07-23T12:00:00Z", "scope2");
    expect(oneDay.scope2_kgco2e!).toBeGreaterThan(oneHour.scope2_kgco2e! * 10);
  });
});

describe("generateMockNationalEmissions", () => {
  it("aggregates all regions + WEM", () => {
    const nat = generateMockNationalEmissions(SINCE_7D, NOW, "scope2");
    expect(nat.regions).toHaveLength(6);
    expect(nat.total_scope2_kgco2e).toBeGreaterThan(0);
  });

  it("total = sum of regions", () => {
    const nat = generateMockNationalEmissions(SINCE_7D, NOW, "scope2");
    const sum = nat.regions.reduce((s, r) => s + (r.scope2_kgco2e ?? 0), 0);
    expect(Math.abs(nat.total_scope2_kgco2e - sum)).toBeLessThan(1);
  });
});

describe("generateMockFuelBreakdown", () => {
  it("returns a sorted breakdown that sums to ~100%", () => {
    const fb = generateMockFuelBreakdown("NSW1", SINCE_7D, NOW);
    expect(fb.by).toBe("fuel");
    expect(fb.items.length).toBeGreaterThan(0);
    // Sorted descending
    for (let i = 1; i < fb.items.length; i++) {
      expect(fb.items[i - 1].kgco2e).toBeGreaterThanOrEqual(fb.items[i].kgco2e);
    }
    const totalPct = fb.items.reduce((s, i) => s + i.percent, 0);
    expect(totalPct).toBeGreaterThan(98);
    expect(totalPct).toBeLessThan(102);
  });

  it("TAS1 is mostly hydro", () => {
    const fb = generateMockFuelBreakdown("TAS1", SINCE_7D, NOW);
    const hydro = fb.items.find((i) => i.fuel === "hydro");
    expect(hydro).toBeDefined();
    expect(hydro!.percent).toBeGreaterThan(50);
  });
});

describe("generateMockEmissionForecast", () => {
  it("returns 2 points per hour × horizon_hours", () => {
    const f = generateMockEmissionForecast("NSW1", 6);
    expect(f.points).toHaveLength(12);
  });

  it("total kg > 0 and t = kg / 1000", () => {
    const f = generateMockEmissionForecast("VIC1", 24);
    expect(f.total_kgco2e).toBeGreaterThan(0);
    expect(f.total_tco2e).toBeCloseTo(f.total_kgco2e / 1000, 0);
  });
});

describe("generateMockEmissionsTimeseries", () => {
  it("hour bucket yields the right number of points", () => {
    const ts = generateMockEmissionsTimeseries("NSW1", SINCE_24H, NOW, "hour");
    expect(ts.points).toHaveLength(24);
  });

  it("day bucket yields the right number of points", () => {
    const ts = generateMockEmissionsTimeseries("NSW1", SINCE_7D, NOW, "day");
    expect(ts.points).toHaveLength(7);
  });

  it("month bucket yields the right number of points", () => {
    const ts = generateMockEmissionsTimeseries("NSW1", "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z", "month");
    expect(ts.points).toHaveLength(12);
  });

  it("every point has positive emissions", () => {
    const ts = generateMockEmissionsTimeseries("QLD1", SINCE_7D, NOW, "day");
    for (const p of ts.points) {
      expect(p.kgco2e).toBeGreaterThan(0);
      expect(p.mwh).toBeGreaterThan(0);
    }
  });
});

describe("summarizeEmissions", () => {
  it("returns a non-empty summary with sane KPIs", () => {
    const nat = generateMockNationalEmissions(SINCE_7D, NOW, "scope2");
    const ts = generateMockEmissionsTimeseries("NSW1", SINCE_7D, NOW, "day");
    const s = summarizeEmissions(nat, ts);
    expect(s.period).toBeTruthy();
    expect(s.totalTco2e).toBeGreaterThan(0);
    expect(s.energyMWh).toBeGreaterThan(0);
    expect(s.peakHour.kgco2e).toBeGreaterThanOrEqual(s.troughHour.kgco2e);
    expect(s.renewablePct).toBeGreaterThanOrEqual(0);
    expect(s.renewablePct).toBeLessThanOrEqual(100);
  });
});
