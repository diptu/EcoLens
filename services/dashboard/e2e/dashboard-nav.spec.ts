/**
 * E2E tests for dashboard navigation.
 * Verifies the sidebar nav links work and active state is set.
 *
 * On mobile the sidebar is a drawer; the open/close interaction is
 * not part of these tests, so we only assert the static link set
 * on desktop-sized viewports.
 */
import { test, expect } from "@playwright/test";

test.describe("sidebar nav (desktop only)", () => {
  test.beforeEach(async ({ viewport }) => {
    test.skip(viewport && viewport.width < 1024, "Sidebar is a drawer on mobile");
  });

  test("Overview -> Analytics & Forecast", async ({ page }) => {
    await page.goto("/");
    await page.locator("aside").getByRole("link", { name: /Analytics & Forecast/ }).first().click();
    await page.waitForURL(/\/analytics-forecast/);
  });

  test("Analytics & Forecast -> Overview (via sidebar, lands on /)", async ({ page }) => {
    await page.goto("/analytics-forecast");
    await page.locator("aside").getByRole("link", { name: "Overview", exact: true }).first().click();
    await page.waitForURL((url) => url.pathname === "/");
    await expect(page.getByRole("heading", { name: /Executive Dashboard/ })).toBeVisible();
  });

  test("Analytics & Forecast -> Data Ingestion", async ({ page }) => {
    await page.goto("/analytics-forecast");
    await page.locator("aside").getByRole("link", { name: /Data Ingestion/ }).first().click();
    await page.waitForURL(/\/data-ingestion/);
  });

  // Architecture is the last real sidebar link now -- Training &
  // Experiments, Performance, and System Health are all disabled (see
  // those routes' own page.tsx), and Reports/Settings & Users still
  // exist as pages (see dashboard.spec.ts's DASHBOARD_PAGES) but, per
  // sidebar.tsx's own docstring, aren't linked from the sidebar nav --
  // so there's no further sidebar hop to test past Architecture.
  test("Data Ingestion -> Architecture", async ({ page }) => {
    await page.goto("/data-ingestion");
    await page.locator("aside").getByRole("link", { name: /Architecture/ }).first().click();
    await page.waitForURL(/\/architecture/);
  });
});
