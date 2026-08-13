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
  // Not `getByText("Emissions Trend")` -- pre-existing strict-mode
  // ambiguity (confirmed, unrelated to 2026-08-10's real-data change):
  // "Emissions Trend (compact)" below also contains that substring.
  await expect(page.getByTestId("emissions-trend-title")).toBeVisible();
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

test("emissions trend chart shows hover tooltip for real actual data", async ({ page }) => {
  const chart = page.getByTestId("emissions-trend-chart");
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  // Near the left edge -- always the earliest real actual history,
  // regardless of where the real forecast segment currently falls (its
  // own timestamps aren't guaranteed to be the chronologically-latest
  // points -- see RealEmissionsTrend's own disclosed forecast-lag
  // comment; real serving lag on 2026-08-10 put it ~18h behind live).
  await page.mouse.move(box!.x + box!.width * 0.03, box!.y + box!.height * 0.5, { steps: 5 });
  await page.waitForTimeout(300);
  const tooltip = page.getByTestId("emissions-trend-tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("Actual");
});

test("emissions trend chart shows real forecast P10-P90 band on hover", async ({ page }) => {
  // Hover the real forecast band's own rendered element directly --
  // robust regardless of where its real timestamps fall on the shared
  // time axis (unlike a fixed x-fraction of the whole chart).
  const band = page.getByTestId("emissions-trend-forecast-band").first();
  await band.scrollIntoViewIfNeeded();
  const box = await band.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2, { steps: 5 });
  await page.waitForTimeout(300);
  const tooltip = page.getByTestId("emissions-trend-tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("Forecast");
  await expect(tooltip).toContainText("P10");
  await expect(tooltip).toContainText("P90");
});

test("emissions by source donut shows hover tooltip", async ({ page }) => {
  // Hover over the first (largest) real fuel-type legend item -- which
  // one that is depends on live generation-mix data, so this locates by
  // position (first row) rather than a fixed fabricated name like the
  // old mock's "Grid Electricity (Scope 2)".
  const firstItem = page.locator('[data-testid^="donut-legend-"]').first();
  await firstItem.scrollIntoViewIfNeeded();
  const box = await firstItem.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2, { steps: 5 });
  await page.waitForTimeout(500);
  // Tooltip should be visible with real slice data (real unit, tCO₂e)
  const tooltip = page.getByTestId("donut-tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("tCO");
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
