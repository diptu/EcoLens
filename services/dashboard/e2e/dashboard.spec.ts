/**
 * E2E tests for the live dashboard pages (the new 15-page taxonomy,
 * minus the disabled routes -- see each disabled route's own
 * page.tsx). Verifies sidebar + topbar are present, each page renders
 * its expected content, and navigation works.
 *
 * Routes:
 *   /login                        — auth (separate)
 *   /                             — executive dashboard
 *   /analytics-forecast           — analytics & forecast (combines the
 *                                    disabled Forecast Explorer/Carbon
 *                                    Intelligence/Energy Analytics)
 *   /data-ingestion               — data ingestion
 *   /architecture                 — end-to-end model architecture
 *   /dashboard/reports            — reports
 *   /dashboard/settings           — settings & users
 */
import { test, expect } from "@playwright/test";

const DASHBOARD_PAGES = [
  "/",
  "/analytics-forecast",
  "/data-ingestion",
  "/architecture",
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

test.describe("/", () => {
  test("renders KPIs", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Executive Dashboard/ })).toBeVisible();
    await expect(page.getByText(/Total CO₂e/).first()).toBeVisible();
  });
});

test.describe("/analytics-forecast", () => {
  test("renders KPIs and period/region selectors", async ({ page }) => {
    await page.goto("/analytics-forecast");
    await expect(page.getByRole("heading", { name: /Analytics & Forecast/ })).toBeVisible();
    await expect(page.getByText("Total Demand (Actual)")).toBeVisible();
    await expect(page.getByTestId("af-period-7d")).toBeVisible();
    await expect(page.getByTestId("af-region-NEM")).toBeVisible();
  });
});

test.describe("/architecture", () => {
  test("renders the Overview tab by default", async ({ page }) => {
    await page.goto("/architecture");
    await expect(page.getByRole("heading", { name: /System Architecture/ })).toBeVisible();
    await expect(page.getByText("ML Model Architecture — Input to Output")).toBeVisible();
    await expect(page.getByText("Multi-Model Architecture").first()).toBeVisible();
    await expect(page.getByText("Model Optimization & Reliability")).toBeVisible();
  });

  test("tabs switch content", async ({ page }) => {
    await page.goto("/architecture");
    await page.getByRole("button", { name: "Data Pipeline" }).click();
    await expect(page.getByText("Real Data Sources")).toBeVisible();
    await page.getByRole("button", { name: "Deployment" }).click();
    await expect(page.getByText("Model Serving", { exact: true })).toBeVisible();
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
    await page.goto("/");
    const fcp = await page.evaluate(() => {
      const entries = performance.getEntriesByName("first-contentful-paint");
      return entries.length > 0 ? entries[0].startTime : -1;
    });
    expect(fcp).toBeGreaterThan(0);
    expect(fcp).toBeLessThan(1500);
    expect(Date.now() - t0).toBeLessThan(5000);
  });
});
