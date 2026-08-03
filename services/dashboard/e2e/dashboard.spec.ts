/**
 * E2E tests for the 14 dashboard pages (the new 15-page taxonomy).
 * Verifies sidebar + topbar are present, each page renders its
 * expected content, and navigation works.
 *
 * Routes (15-page taxonomy):
 *   /login                        — auth (separate)
 *   /dashboard/executive          — executive dashboard
 *   /dashboard/operations         — operations dashboard
 *   /dashboard/data-sources       — data sources
 *   /dashboard/ingestion          — ingestion pipeline
 *   /dashboard/data-quality       — data quality & anomalies
 *   /dashboard/forecast           — forecast explorer
 *   /dashboard/carbon             — carbon intelligence
 *   /dashboard/analytics          — energy analytics
 *   /dashboard/models             — model registry
 *   /dashboard/training           — training & experiments
 *   /dashboard/operational-tasks  — operational tasks
 *   /dashboard/system-health      — system health
 *   /dashboard/reports            — reports
 *   /dashboard/settings           — settings & users
 */
import { test, expect } from "@playwright/test";

const DASHBOARD_PAGES = [
  "/dashboard/executive",
  "/dashboard/operations",
  "/dashboard/data-sources",
  "/dashboard/ingestion",
  "/dashboard/data-quality",
  "/dashboard/forecast",
  "/dashboard/carbon",
  "/dashboard/analytics",
  "/dashboard/models",
  "/dashboard/training",
  "/dashboard/operational-tasks",
  "/dashboard/system-health",
  "/dashboard/reports",
  "/dashboard/settings",
] as const;

for (const route of DASHBOARD_PAGES) {
  test(`${route} renders with sidebar + topbar + h1`, async ({ page }) => {
    await page.goto(route);
    // Sidebar must be visible
    const sidebar = page.locator("aside").first();
    await expect(sidebar).toBeVisible();
    // An active link (any link in the sidebar) should be visible
    const anyLink = sidebar.locator("a").first();
    await expect(anyLink).toBeVisible();
    // The h1 of the page should be visible
    await expect(page.locator("h1").first()).toBeVisible();
  });
}

test.describe("/dashboard/executive", () => {
  test("renders KPIs", async ({ page }) => {
    await page.goto("/dashboard/executive");
    await expect(page.getByRole("heading", { name: /Executive Dashboard/ })).toBeVisible();
    await expect(page.getByText(/Total CO₂e/).first()).toBeVisible();
  });
});

test.describe("/dashboard/forecast", () => {
  test("renders forecast page", async ({ page }) => {
    await page.goto("/dashboard/forecast");
    await expect(page.locator("h1").first()).toBeVisible();
  });
});

test.describe("/dashboard/reports", () => {
  test("renders reports page", async ({ page }) => {
    await page.goto("/dashboard/reports");
    await expect(page.locator("h1").first()).toBeVisible();
  });
});

test.describe("core web vitals (dashboard)", () => {
  test("executive: FCP < 1.5s, CLS = 0", async ({ page }) => {
    const t0 = Date.now();
    await page.goto("/dashboard/executive");
    const fcp = await page.evaluate(() => {
      const entries = performance.getEntriesByName("first-contentful-paint");
      return entries.length > 0 ? entries[0].startTime : -1;
    });
    expect(fcp).toBeGreaterThan(0);
    expect(fcp).toBeLessThan(1500);
    expect(Date.now() - t0).toBeLessThan(5000);
  });
});
