/**
 * Unit tests for the pricing data layer.
 * Validates the schema, plan counts, price consistency, and
 * compare-table integrity.
 */
import { describe, it, expect } from "vitest";
import {
  PRICING_PLANS,
  PRICING_COMPARE_ROWS,
  PRICING_INCLUDED,
  PRICING_ADDONS,
} from "@/lib/data";

describe("PRICING_PLANS", () => {
  it("has exactly 4 plans (Starter, Growth, Professional, Enterprise)", () => {
    expect(PRICING_PLANS).toHaveLength(4);
    const ids = PRICING_PLANS.map((p) => p.id);
    expect(ids).toEqual(["starter", "growth", "professional", "enterprise"]);
  });

  it("each plan has the required fields", () => {
    for (const plan of PRICING_PLANS) {
      expect(plan.id).toBeTruthy();
      expect(plan.name).toBeTruthy();
      expect(plan.description).toBeTruthy();
      expect(plan.icon).toBeTruthy();
      expect(plan.cta).toBeTruthy();
      expect(plan.cta.label).toBeTruthy();
      expect(plan.cta.href).toBeTruthy();
      expect(plan.features.length).toBeGreaterThanOrEqual(4);
      // price has both periods (even if null for enterprise)
      expect("monthly" in plan.price).toBe(true);
      expect("annually" in plan.price).toBe(true);
    }
  });

  it("annual price is always ≤ monthly price (encourages yearly)", () => {
    for (const plan of PRICING_PLANS) {
      if (plan.price.monthly !== null && plan.price.annually !== null) {
        expect(plan.price.annually).toBeLessThanOrEqual(plan.price.monthly);
      }
    }
  });

  it("annual price is ≥ 70% of monthly (max 30% discount)", () => {
    // The screenshot says "Save up to 20%". Be conservative.
    for (const plan of PRICING_PLANS) {
      if (plan.price.monthly !== null && plan.price.annually !== null) {
        const ratio = plan.price.annually / plan.price.monthly;
        expect(ratio).toBeGreaterThanOrEqual(0.7);
        expect(ratio).toBeLessThanOrEqual(1.0);
      }
    }
  });

  it("exactly one plan is highlighted (most popular)", () => {
    const highlighted = PRICING_PLANS.filter((p) => p.highlighted);
    expect(highlighted).toHaveLength(1);
    expect(highlighted[0].id).toBe("growth");
  });

  it("Enterprise plan has null prices + customLabel 'Custom'", () => {
    const ent = PRICING_PLANS.find((p) => p.id === "enterprise");
    expect(ent).toBeDefined();
    expect(ent!.price.monthly).toBeNull();
    expect(ent!.price.annually).toBeNull();
    expect(ent!.customLabel).toBe("Custom");
  });

  it("Enterprise CTA goes to sales (mailto or /contact)", () => {
    const ent = PRICING_PLANS.find((p) => p.id === "enterprise");
    expect(ent!.cta.href).toMatch(/^mailto:|\/contact/);
  });

  it("non-Enterprise plans have positive prices", () => {
    for (const plan of PRICING_PLANS) {
      if (plan.id === "enterprise") continue;
      expect(plan.price.monthly).toBeGreaterThan(0);
      expect(plan.price.annually).toBeGreaterThan(0);
    }
  });

  it("features are non-empty and unique within a plan", () => {
    for (const plan of PRICING_PLANS) {
      expect(plan.features.length).toBeGreaterThanOrEqual(4);
      expect(new Set(plan.features).size).toBe(plan.features.length);
    }
  });
});

describe("PRICING_COMPARE_ROWS", () => {
  it("has at least 5 comparison rows", () => {
    expect(PRICING_COMPARE_ROWS.length).toBeGreaterThanOrEqual(5);
  });

  it("every row has all 4 plan columns", () => {
    for (const row of PRICING_COMPARE_ROWS) {
      expect("starter" in row).toBe(true);
      expect("growth" in row).toBe(true);
      expect("professional" in row).toBe(true);
      expect("enterprise" in row).toBe(true);
    }
  });

  it("feature flags are monotonic (Starter ≤ Growth ≤ Professional ≤ Enterprise)", () => {
    // For boolean rows, a higher tier should never have fewer features
    for (const row of PRICING_COMPARE_ROWS) {
      if (typeof row.starter !== "boolean") continue;
      const s = row.starter, g = row.growth, p = row.professional, e = row.enterprise;
      if (s && !g) throw new Error(`Starter has ${row.row} but Growth doesn't`);
      if (g && !p) throw new Error(`Growth has ${row.row} but Professional doesn't`);
      if (p && !e) throw new Error(`Professional has ${row.row} but Enterprise doesn't`);
    }
  });

  it("row labels are non-empty and unique", () => {
    const labels = PRICING_COMPARE_ROWS.map((r) => r.row);
    for (const l of labels) expect(l).toBeTruthy();
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("PRICING_INCLUDED", () => {
  it("has 6 items", () => {
    expect(PRICING_INCLUDED).toHaveLength(6);
  });

  it("all items are non-empty strings", () => {
    for (const item of PRICING_INCLUDED) {
      expect(typeof item).toBe("string");
      expect(item.length).toBeGreaterThan(3);
    }
  });
});

describe("PRICING_ADDONS", () => {
  it("has 4 add-ons", () => {
    expect(PRICING_ADDONS).toHaveLength(4);
  });

  it("each add-on has a name and a price", () => {
    for (const a of PRICING_ADDONS) {
      expect(a.name).toBeTruthy();
      expect(a.price).toBeTruthy();
      expect(a.price).toMatch(/\$\d+/);
    }
  });
});
