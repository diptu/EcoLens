/**
 * E2E tests for the new /dashboard/forecast page and the
 * ForecastPreview widget on /dashboard/executive.
 */
import { test, expect } from "@playwright/test";

test.describe("/dashboard/forecast", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/forecast/");
  });

  test("renders the page with a fan chart, KPI row, and source badge", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Demand Forecast" })).toBeVisible();
    // Source badge
    await expect(page.getByTestId("forecast-source")).toBeVisible();
    await expect(page.getByTestId("forecast-source")).toContainText(/mock/i);
    // Region tabs
    for (const r of ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]) {
      await expect(page.getByTestId(`region-${r}`)).toBeVisible();
    }
    // Horizon tabs
    for (const h of [4, 48, 168]) {
      await expect(page.getByTestId(`horizon-${h}`)).toBeVisible();
    }
    // Fan chart SVG (scoped to the fan-chart container)
    const chart = page.getByTestId("fan-chart");
    await expect(chart).toBeVisible();
    await expect(chart.locator("svg")).toBeVisible();
  });

  test("switching region re-renders the chart and changes the model info", async ({ page }) => {
    // Default is NSW1
    const nswButton = page.getByTestId("region-NSW1");
    await expect(nswButton).toHaveAttribute("aria-selected", "true");

    // Switch to QLD1
    await page.getByTestId("region-QLD1").click();
    await expect(page.getByTestId("region-QLD1")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("region-NSW1")).toHaveAttribute("aria-selected", "false");

    // The endpoint snippet should now show QLD1
    await expect(page.getByText(/forecast\/QLD1/)).toBeVisible();
  });

  test("switching horizon re-renders the chart and updates the table count", async ({ page }) => {
    // Default horizon is 48
    await expect(page.getByTestId("horizon-48")).toHaveAttribute("aria-selected", "true");

    // Switch to 168
    await page.getByTestId("horizon-168").click();
    await expect(page.getByTestId("horizon-168")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(/next 168 steps/i)).toBeVisible();
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
