/**
 * E2E tests for /dashboard/forecast (wired to forecast-api's real
 * GET /v1/forecast + GET /v1/model) and the inline forecast preview
 * widget on /dashboard/executive.
 */
import { test, expect } from "@playwright/test";

test.describe("/dashboard/forecast", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/forecast/");
  });

  test("renders the page with a fan chart and KPI row", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Demand Forecast" })).toBeVisible();
    // Region tabs (NEM aggregate + 6 NEM/WEM regions) -- no Horizon tabs
    // anymore, since the real /v1/forecast endpoint always returns the
    // model's own fixed native horizon, not an arbitrary requested one.
    for (const r of ["NEM", "NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]) {
      await expect(page.getByTestId(`region-${r}`)).toBeVisible();
    }
    // Fan chart SVG (scoped to the fan-chart container)
    const chart = page.getByTestId("fan-chart");
    await expect(chart).toBeVisible();
    await expect(chart.locator("svg")).toBeVisible();
  });

  test("switching region re-renders the chart and endpoint snippet", async ({ page }) => {
    // Default is NEM
    const nemButton = page.getByTestId("region-NEM");
    await expect(nemButton).toHaveAttribute("aria-selected", "true");

    // Switch to QLD1
    await page.getByTestId("region-QLD1").click();
    await expect(page.getByTestId("region-QLD1")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("region-NEM")).toHaveAttribute("aria-selected", "false");

    // The endpoint snippet should now show the QLD1 query param
    await expect(page.getByText(/forecast\?region=QLD1/)).toBeVisible();
  });

  test("5 KPI cards are visible (peak, trough, mean, total, uncertainty)", async ({ page }) => {
    for (const label of ["Peak demand", "Trough", "Mean", "Total energy", "Uncertainty"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
  });

  test("forecast table toggles open and closed", async ({ page }) => {
    const toggle = page.getByRole("button", { name: /forecast table/i });
    await toggle.click();
    const table = page.getByTestId("forecast-table");
    await expect(table).toBeVisible();
    // Table has a P50 column header
    await expect(page.getByRole("columnheader", { name: "P50" })).toBeVisible();
  });

  test("'View full forecast' link is NOT here (we're already on it)", async ({ page }) => {
    await expect(page.getByRole("link", { name: /View full forecast/ })).toHaveCount(0);
  });
});

test.describe("ForecastPreview widget on /dashboard/executive", () => {
  test("renders the preview with sparkline + KPIs + link to /dashboard/forecast", async ({ page }) => {
    await page.goto("/dashboard/executive/");
    const preview = page.getByTestId("forecast-preview");
    await expect(preview).toBeVisible();
    await expect(preview.getByText("Current (P50)")).toBeVisible();
    await expect(preview.getByText("Peak in next 4h")).toBeVisible();
    // SVG sparkline
    await expect(preview.locator("svg").first()).toBeVisible();
    // Link to the full forecast page
    const link = preview.getByRole("link", { name: /View full forecast/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/forecast/");
  });
});

test.describe("Sidebar nav includes Forecast", () => {
  test("sidebar has a 'Forecast Explorer' link to /dashboard/forecast", async ({ page, viewport }) => {
    // Sidebar is a drawer on mobile; only assert on desktop-sized viewports.
    test.skip(viewport && viewport.width < 1024, "Sidebar is a drawer on mobile");
    await page.goto("/dashboard/forecast/");
    const link = page.getByRole("link", { name: /Forecast/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/forecast/");
  });
});
