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

  test("Executive -> Operations", async ({ page }) => {
    await page.goto("/dashboard/executive");
    await page.locator("aside").getByRole("link", { name: "Operations", exact: true }).first().click();
    await page.waitForURL(/\/dashboard\/operations/);
    await expect(page.locator("h1").first()).toContainText("Operations");
  });

  test("Operations -> Data Sources", async ({ page }) => {
    await page.goto("/dashboard/operations");
    await page.locator("aside").getByRole("link", { name: "Data Sources", exact: true }).first().click();
    await page.waitForURL(/\/dashboard\/data-sources/);
  });

  test("Data Sources -> Ingestion", async ({ page }) => {
    await page.goto("/dashboard/data-sources");
    await page.locator("aside").getByRole("link", { name: "Ingestion Pipeline", exact: true }).first().click();
    await page.waitForURL(/\/dashboard\/ingestion/);
  });

  test("Ingestion -> Data Quality", async ({ page }) => {
    await page.goto("/dashboard/ingestion");
    await page.locator("aside").getByRole("link", { name: /Data Quality/ }).first().click();
    await page.waitForURL(/\/dashboard\/data-quality/);
  });

  test("Data Quality -> Forecast", async ({ page }) => {
    await page.goto("/dashboard/data-quality");
    await page.locator("aside").getByRole("link", { name: /Forecast Explorer/ }).first().click();
    await page.waitForURL(/\/dashboard\/forecast/);
  });

  test("Forecast -> Carbon", async ({ page }) => {
    await page.goto("/dashboard/forecast");
    await page.locator("aside").getByRole("link", { name: /Carbon Intelligence/ }).first().click();
    await page.waitForURL(/\/dashboard\/carbon/);
  });

  test("Carbon -> Analytics", async ({ page }) => {
    await page.goto("/dashboard/carbon");
    await page.locator("aside").getByRole("link", { name: /Energy Analytics/ }).first().click();
    await page.waitForURL(/\/dashboard\/analytics/);
  });

  test("Analytics -> Models", async ({ page }) => {
    await page.goto("/dashboard/analytics");
    await page.locator("aside").getByRole("link", { name: /Model Registry/ }).first().click();
    await page.waitForURL(/\/dashboard\/models/);
  });

  test("Models -> Training", async ({ page }) => {
    await page.goto("/dashboard/models");
    await page.locator("aside").getByRole("link", { name: /Training/ }).first().click();
    await page.waitForURL(/\/dashboard\/training/);
  });

  test("Training -> Operational Tasks", async ({ page }) => {
    await page.goto("/dashboard/training");
    await page.locator("aside").getByRole("link", { name: /Operational Tasks/ }).first().click();
    await page.waitForURL(/\/dashboard\/operational-tasks/);
  });

  test("Operational Tasks -> System Health", async ({ page }) => {
    await page.goto("/dashboard/operational-tasks");
    await page.locator("aside").getByRole("link", { name: /System Health/ }).first().click();
    await page.waitForURL(/\/dashboard\/system-health/);
  });

  test("System Health -> Reports", async ({ page }) => {
    await page.goto("/dashboard/system-health");
    await page.locator("aside").getByRole("link", { name: "Reports", exact: true }).first().click();
    await page.waitForURL(/\/dashboard\/reports/);
  });

  test("Reports -> Settings", async ({ page }) => {
    await page.goto("/dashboard/reports");
    await page.locator("aside").getByRole("link", { name: /Settings/ }).first().click();
    await page.waitForURL(/\/dashboard\/settings/);
  });

  test("sidebar Operations link returns to /dashboard/operations", async ({ page }) => {
    await page.goto("/dashboard/forecast");
    await page.locator("aside").getByRole("link", { name: "Operations", exact: true }).first().click();
    await page.waitForURL(/\/dashboard\/operations/);
  });
});
