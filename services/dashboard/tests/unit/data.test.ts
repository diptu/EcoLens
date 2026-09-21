/**
 * Unit tests for the static data layer.
 * Confirms the data shape and minimum content is what each page expects.
 */
import { describe, it, expect } from "vitest";
import {
  DATA_VERSION,
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
