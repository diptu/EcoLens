/**
 * Tests for src/lib/emissions.ts — region/factor constants and the
 * shared formatting helpers used across the emissions-related pages.
 * (The old mock generators this file used to test were removed once
 * /dashboard/carbon was wired to forecast-api's real endpoints.)
 */
import { describe, it, expect } from "vitest";

import {
  ALL_EMISSION_REGIONS,
  EMISSION_FACTORS,
  formatEnergy,
  formatIntensity,
  formatTco2e,
} from "@/lib/emissions";

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
