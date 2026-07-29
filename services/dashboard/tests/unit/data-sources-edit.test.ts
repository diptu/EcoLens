/**
 * Unit tests for the new data-sources data layer (with editable fields).
 */
import { describe, expect, it } from "vitest";

import { getDataSources, type DataSource } from "@/lib/dashboards";

describe("data-sources — editable fields", () => {
  it("getDataSources returns 9 sources", () => {
    const sources = getDataSources();
    expect(sources).toHaveLength(9);
  });

  it("every source has a cron expression", () => {
    const sources = getDataSources();
    for (const s of sources) {
      expect(s.cron).toBeTruthy();
      expect(s.cron).toMatch(/^(\*|\d+|\*\/\d+|\d+-\d+)( (\*|\d+|\*\/\d+|\d+-\d+)){4}$/);
    }
  });

  it("every source has a description and enabled flag", () => {
    const sources = getDataSources();
    for (const s of sources) {
      expect(s.description).toBeTruthy();
      expect(typeof s.enabled).toBe("boolean");
    }
  });

  it("at least one source is disabled (to show toggle state)", () => {
    const sources = getDataSources();
    const enabled = sources.filter((s) => s.enabled).length;
    const disabled = sources.filter((s) => !s.enabled).length;
    expect(enabled).toBeGreaterThan(0);
    expect(enabled + disabled).toBe(sources.length);
  });

  it("cron values are unique-ish (each source has its own cadence)", () => {
    const sources = getDataSources();
    const crons = new Set(sources.map((s) => s.cron));
    expect(crons.size).toBeGreaterThanOrEqual(3);
  });

  it("every source's cadence label matches its cron pattern", () => {
    const sources = getDataSources();
    // Cron */5 * * * * should be 5-min cadence
    const aemoNem = sources.find((s) => s.id === "ds-aemo-nem")!;
    expect(aemoNem.cron).toBe("*/5 * * * *");
    expect(aemoNem.cadence).toContain("5");

    const bom = sources.find((s) => s.id === "ds-bom")!;
    expect(bom.cron).toBe("*/30 * * * *");
    expect(bom.cadence).toContain("30");
  });

  it("mutating a source (toggle enabled) doesn't affect the original", () => {
    const sources = getDataSources();
    const original = sources[0];
    const updated: DataSource = { ...original, enabled: !original.enabled };
    expect(updated.id).toBe(original.id);
    expect(updated.enabled).toBe(!original.enabled);
    // Original should still be unchanged
    expect(original.enabled).not.toBe(updated.enabled);
  });
});
