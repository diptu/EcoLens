/**
 * Tests for src/lib/methodology.ts — the static methodology data.
 */
import { describe, it, expect } from "vitest";

import {
  CALCULATION_CHAIN,
  DATA_SOURCES,
  FACTORS_WITH_CITATIONS,
  WORKED_EXAMPLES,
} from "@/lib/methodology";

describe("CALCULATION_CHAIN", () => {
  it("has 6 steps", () => {
    expect(CALCULATION_CHAIN).toHaveLength(6);
  });

  it("steps are numbered 1..6 in order", () => {
    for (let i = 0; i < CALCULATION_CHAIN.length; i++) {
      expect(CALCULATION_CHAIN[i].step).toBe(i + 1);
    }
  });

  it("every step has all required fields", () => {
    for (const step of CALCULATION_CHAIN) {
      expect(step.name).toBeTruthy();
      expect(step.source).toBeTruthy();
      expect(step.output).toBeTruthy();
      expect(step.details).toBeTruthy();
      expect(["ingestion", "warehouse", "calculation", "presentation"]).toContain(step.layer);
      expect(step.typical_latency).toBeTruthy();
    }
  });

  it("has exactly one step per layer", () => {
    const layers = CALCULATION_CHAIN.map((s) => s.layer);
    expect(new Set(layers).size).toBe(4);
  });
});

describe("DATA_SOURCES", () => {
  it("has at least 5 sources", () => {
    expect(DATA_SOURCES.length).toBeGreaterThanOrEqual(5);
  });

  it("every source has id, name, type, license, url, fields, cadence, note", () => {
    for (const s of DATA_SOURCES) {
      expect(s.id).toBeTruthy();
      expect(s.name).toBeTruthy();
      expect(["primary", "secondary", "regulatory", "reference"]).toContain(s.type);
      expect(s.license).toBeTruthy();
      expect(s.url).toMatch(/^https?:\/\//);
      expect(s.fields.length).toBeGreaterThan(0);
      expect(s.cadence).toBeTruthy();
      expect(s.note).toBeTruthy();
    }
  });

  it("ids are unique", () => {
    const ids = DATA_SOURCES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("includes AEMO NEM as a primary source", () => {
    const aemo = DATA_SOURCES.find((s) => s.id === "aemo-nem");
    expect(aemo).toBeDefined();
    expect(aemo?.type).toBe("primary");
  });
});

describe("FACTORS_WITH_CITATIONS", () => {
  it("covers all fuels", () => {
    const required = [
      "coal_black_mw", "coal_brown_mw", "gas_ccgt_mw", "gas_ocgt_mw",
      "wind_mw", "solar_utility_mw", "solar_rooftop_mw", "battery_discharge_mw",
      "hydro_mw", "biomass_mw", "nem_grid_avg", "wem_grid_avg",
    ];
    for (const k of required) {
      expect(FACTORS_WITH_CITATIONS[k]).toBeDefined();
    }
  });

  it("every factor is positive and has a source", () => {
    for (const [key, factor] of Object.entries(FACTORS_WITH_CITATIONS)) {
      expect(factor.factor).toBeGreaterThan(0);
      expect(factor.source).toBeTruthy();
      expect(["direct", "lifecycle"]).toContain(factor.scope);
      expect(factor.notes).toBeTruthy();
    }
  });

  it("coal_brown > coal_black > gas > wind", () => {
    const f = FACTORS_WITH_CITATIONS;
    expect(f.coal_brown_mw.factor).toBeGreaterThan(f.coal_black_mw.factor);
    expect(f.coal_black_mw.factor).toBeGreaterThan(f.gas_ccgt_mw.factor);
    expect(f.gas_ccgt_mw.factor).toBeGreaterThan(f.wind_mw.factor);
  });

  it("every factor that has an IPCC source includes a URL", () => {
    for (const factor of Object.values(FACTORS_WITH_CITATIONS)) {
      if (factor.source.toLowerCase().includes("ipcc")) {
        expect(factor.url).toBeDefined();
        expect(factor.url).toMatch(/^https?:\/\//);
      }
    }
  });
});

describe("WORKED_EXAMPLES", () => {
  it("has at least 3 examples (one per scope)", () => {
    expect(WORKED_EXAMPLES.length).toBeGreaterThanOrEqual(3);
    const scopes = new Set(WORKED_EXAMPLES.map((e) => e.scope));
    expect(scopes.has("scope1")).toBe(true);
    expect(scopes.has("scope2")).toBe(true);
    expect(scopes.has("whatif")).toBe(true);
  });

  it("every example has title, description, region, inputs, steps, finalAnswer", () => {
    for (const ex of WORKED_EXAMPLES) {
      expect(ex.id).toBeTruthy();
      expect(ex.title).toBeTruthy();
      expect(ex.description).toBeTruthy();
      expect(ex.inputs.length).toBeGreaterThan(0);
      expect(ex.steps.length).toBeGreaterThan(0);
      expect(ex.finalAnswer).toBeTruthy();
    }
  });

  it("examples have unique ids", () => {
    const ids = WORKED_EXAMPLES.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every step in every example has math + result strings", () => {
    for (const ex of WORKED_EXAMPLES) {
      for (const step of ex.steps) {
        expect(step.math).toBeTruthy();
        expect(step.result).toBeTruthy();
      }
    }
  });
});
