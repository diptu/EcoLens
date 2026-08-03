/**
 * e2e tests for the Executive Dashboard:
 *  - All 4 charts (Demand Forecast, Emissions Snapshot, Emissions Trend, Emissions by Source)
 *    show details on hover
 *  - Donut slices highlight + show tooltip on hover
 *  - Sparkline / trend chart crosshair + tooltip on hover
 */
import { test, expect } from "@playwright/test";

import { loginAs } from "./_helpers/auth";

test.beforeEach(async ({ page }) => {
  await loginAs(page, "diptu");
  await page.goto("/dashboard/executive/");
  await expect(page.getByRole("heading", { name: "Executive Dashboard" })).toBeVisible();
});

test("executive page renders all chart sections", async ({ page }) => {
  await expect(page.getByText("Demand Forecast Preview")).toBeVisible();
  await expect(page.getByText("Emissions Snapshot")).toBeVisible();
  await expect(page.getByText("Emissions Trend")).toBeVisible();
  await expect(page.getByText("Emissions by Source")).toBeVisible();
});

test("forecast sparkline shows hover tooltip", async ({ page }) => {
  const chart = page.getByTestId("forecast-sparkline");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  // Use steps to ensure mousemove fires
  await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.3, { steps: 5 });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("forecast-sparkline-tooltip")).toBeVisible();
});

test("emissions sparkline shows hover tooltip", async ({ page }) => {
  const chart = page.getByTestId("emissions-sparkline");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.3, { steps: 5 });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("emissions-sparkline-tooltip")).toBeVisible();
});

test("emissions trend chart shows hover tooltip with P10-P90 band", async ({ page }) => {
  const chart = page.getByTestId("emissions-trend-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.4, { steps: 5 });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("emissions-trend-tooltip")).toBeVisible();
  // Tooltip should mention Actual and P10/P90
  const tooltip = page.getByTestId("emissions-trend-tooltip");
  await expect(tooltip).toContainText("Actual");
  await expect(tooltip).toContainText("P10");
  await expect(tooltip).toContainText("P90");
});

test("emissions by source donut shows hover tooltip", async ({ page }) => {
  // Hover over one of the legend items (which has onMouseEnter handler).
  // Use a partial match since the testid includes parens like "(Scope 2)".
  const gridItem = page.locator('[data-testid^="donut-legend-grid"]').first();
  await gridItem.scrollIntoViewIfNeeded();
  const box = await gridItem.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2, { steps: 5 });
  await page.waitForTimeout(500);
  // Tooltip should be visible with the slice data
  await expect(page.getByTestId("donut-tooltip")).toBeVisible();
  await expect(page.getByTestId("donut-tooltip")).toContainText("Grid Electricity");
});

test("executive page has View full forecast link", async ({ page }) => {
  const link = page.getByTestId("forecast-preview-link");
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "/dashboard/forecast/");
});

test("executive page has View details link to carbon", async ({ page }) => {
  const link = page.getByTestId("emissions-preview-link");
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "/dashboard/carbon/");
});

test("executive page shows 6 KPIs", async ({ page }) => {
  // The 6 KPI cards each have an uppercase label
  const kpiLabels = ["Total CO₂e (YTD)", "Carbon Intensity", "Renewable Share", "Avg Wholesale Price (YTD)", "Data Quality Score", "Open Risks"];
  for (const label of kpiLabels) {
    await expect(page.getByText(label).first()).toBeVisible();
  }
});
