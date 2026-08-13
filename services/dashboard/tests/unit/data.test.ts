/**
 * Unit tests for the static data layer.
 * Confirms the data shape and minimum content is what each page expects.
 */
import { describe, it, expect } from "vitest";
import {
  DATA_VERSION,
  INDUSTRIES,
  PLATFORM_FEATURES,
  SOLUTIONS_STATS,
  PRODUCT_FEATURES,
  PRODUCT_STEPS,
  PRODUCT_PILL_FEATURES,
  CATEGORIES,
  FEATURED_RESOURCES,
  TOOLS,
  RESOURCE_STATS,
  POPULAR_TAGS,
} from "@/lib/data";

describe("static data", () => {
  it("has a version string", () => {
    expect(DATA_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });

  describe("solutions data", () => {
    it("INDUSTRIES has 5 entries with required fields", () => {
      expect(INDUSTRIES).toHaveLength(5);
      INDUSTRIES.forEach((i) => {
        expect(i.title).toBeTruthy();
        expect(i.image).toMatch(/^\/images\//);
        expect(i.alt).toBeTruthy();
        expect(i.href).toMatch(/^\/solutions\//);
        expect(i.body).toBeTruthy();
        expect(i.metrics).toBeDefined();
      });
    });

    it("PLATFORM_FEATURES has 6 entries", () => {
      expect(PLATFORM_FEATURES).toHaveLength(6);
      PLATFORM_FEATURES.forEach((f) => {
        expect(f.title).toBeTruthy();
        expect(f.body).toBeTruthy();
        expect(f.icon).toBeTruthy();
      });
    });

    it("SOLUTIONS_STATS has 4 entries with valid numeric values", () => {
      expect(SOLUTIONS_STATS).toHaveLength(4);
      SOLUTIONS_STATS.forEach((s) => {
        expect(typeof s.value).toBe("number");
        expect(s.suffix).toBeTruthy();
        expect(s.label).toBeTruthy();
      });
    });
  });

  describe("product data", () => {
    it("PRODUCT_FEATURES has 6 entries with bullets and visual key", () => {
      expect(PRODUCT_FEATURES).toHaveLength(6);
      PRODUCT_FEATURES.forEach((f) => {
        expect(f.bullets).toBeDefined();
        expect(f.bullets.length).toBeGreaterThanOrEqual(3);
        expect(f.visual).toBeTruthy();
      });
    });

    it("PRODUCT_STEPS has exactly 4 numbered steps", () => {
      expect(PRODUCT_STEPS).toHaveLength(4);
      const numbers = PRODUCT_STEPS.map((s) => s.number);
      expect(numbers).toEqual([1, 2, 3, 4]);
    });

    it("PRODUCT_PILL_FEATURES has 3 entries", () => {
      expect(PRODUCT_PILL_FEATURES).toHaveLength(3);
    });
  });

  describe("resources data", () => {
    it("CATEGORIES has 6 entries with resourceCount", () => {
      expect(CATEGORIES).toHaveLength(6);
      CATEGORIES.forEach((c) => {
        expect(c.title).toBeTruthy();
        expect(c.body).toBeTruthy();
        expect(c.resourceCount).toBeGreaterThan(0);
        expect(c.href).toMatch(/^\/resources\//);
      });
    });

    it("FEATURED_RESOURCES has 5 entries with images", () => {
      expect(FEATURED_RESOURCES).toHaveLength(5);
      FEATURED_RESOURCES.forEach((r) => {
        expect(r.type).toBeTruthy();
        expect(r.title).toBeTruthy();
        expect(r.image).toMatch(/^\/images\//);
        expect(r.alt).toBeTruthy();
      });
    });

    it("TOOLS has 4 entries", () => {
      expect(TOOLS).toHaveLength(4);
    });

    it("RESOURCE_STATS has 4 entries with valid numeric values", () => {
      expect(RESOURCE_STATS).toHaveLength(4);
      RESOURCE_STATS.forEach((s) => {
        expect(typeof s.value).toBe("number");
      });
    });

    it("POPULAR_TAGS has at least 3 tags", () => {
      expect(POPULAR_TAGS.length).toBeGreaterThanOrEqual(3);
    });
  });
});
