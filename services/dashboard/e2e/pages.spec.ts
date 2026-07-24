/**
 * E2E page content tests.
 * Verifies the inner pages render their expected content from the
 * static data layer.
 */
import { test, expect } from "@playwright/test";

test.describe("/product", () => {
  test("renders hero", async ({ page }) => {
    await page.goto("/product");
    await expect(page.getByRole("heading", { name: /All-in-one Carbon/i })).toBeVisible();
  });
  test("renders all 6 features", async ({ page }) => {
    await page.goto("/product");
    for (const title of [
      "Smart Data Ingestion",
      "AI-Powered Calculations",
      "Actionable Insights",
      "Goals & Tracking",
      "Reports & Compliance",
      "Reduce & Offset",
    ]) {
      await expect(page.getByText(title, { exact: true })).toBeVisible();
    }
  });
  test("renders 4 step flow", async ({ page }) => {
    await page.goto("/product");
    // Steps render as "1. Connect", "2. Measure", "3. Act", "4. Impact"
    for (const step of ["1. Connect", "2. Measure", "3. Act", "4. Impact"]) {
      await expect(page.getByRole("heading", { name: step, level: 3 })).toBeVisible();
    }
  });
});

test.describe("/resources", () => {
  test("renders hero", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByRole("heading", { name: /Knowledge Today/i })).toBeVisible();
  });
  test("renders all 6 categories", async ({ page }) => {
    await page.goto("/resources");
    for (const title of [
      "Guides & Playbooks",
      "Reports & Research",
      "Tools & Calculators",
      "Videos & Webinars",
      "Case Studies",
      "Policy & Standards",
    ]) {
      // Use heading role to avoid matching paragraph text
      await expect(page.getByRole("heading", { name: title, level: 3 })).toBeVisible();
    }
  });
  test("renders featured resources", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByRole("heading", { name: "Carbon Accounting 101" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "GHG Inventory Template" })).toBeVisible();
  });
  test("renders search input", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByPlaceholder("Search resources...")).toBeVisible();
  });
});

test.describe("/solutions", () => {
  test("renders hero", async ({ page }) => {
    await page.goto("/solutions");
    await expect(page.getByRole("heading", { name: /Smarter Solutions/i })).toBeVisible();
  });
  test("renders all 5 industries", async ({ page }) => {
    await page.goto("/solutions");
    for (const industry of [
      "Manufacturing",
      "Energy & Utilities",
      "Transportation & Logistics",
      "Construction & Real Estate",
      "Technology & SaaS",
    ]) {
      await expect(page.getByText(industry, { exact: true })).toBeVisible();
    }
  });
  test("renders 6 platform features", async ({ page }) => {
    await page.goto("/solutions");
    for (const feature of [
      "AI-Driven Insights",
      "Unified Data Hub",
      "Custom Workflows",
      "Enterprise Security",
      "Scalable Architecture",
      "Global Coverage",
    ]) {
      await expect(page.getByText(feature, { exact: true })).toBeVisible();
    }
  });
  test("renders stats", async ({ page }) => {
    await page.goto("/solutions");
    await expect(page.getByText(/Measured/i)).toBeVisible();
    await expect(page.getByText(/Average Reduction/i)).toBeVisible();
  });
  test("renders the industry 'don't see your industry?' bar", async ({ page }) => {
    await page.goto("/solutions");
    // Multiple elements contain this text; use first() to be lenient
    await expect(page.getByText(/Don't see your industry/i).first()).toBeVisible();
  });
});

test.describe("core web vitals (smoke)", () => {
  test("home page: FCP < 1.5s, CLS = 0", async ({ page }) => {
    await page.goto("/");
    const metrics = await page.evaluate(() => {
      return new Promise<{ fcp: number; cls: number }>((resolve) => {
        let fcp = 0;
        let cls = 0;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (entry.name === "first-contentful-paint") {
              fcp = entry.startTime;
            }
          }
        }).observe({ type: "paint", buffered: true });
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!(entry as PerformanceEntry & { hadRecentInput?: boolean }).hadRecentInput) {
              cls += (entry as PerformanceEntry & { value: number }).value;
            }
          }
        }).observe({ type: "layout-shift", buffered: true });
        setTimeout(() => resolve({ fcp, cls }), 500);
      });
    });
    expect(metrics.fcp).toBeGreaterThan(0);
    expect(metrics.fcp).toBeLessThan(1500);
    expect(metrics.cls).toBe(0);
  });
});
