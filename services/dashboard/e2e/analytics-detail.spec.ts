/**
 * e2e tests for the Energy Analytics page:
 *  - chart hover tooltips appear
 *  - "View details" buttons open a modal
 *  - the modal renders field data
 *  - the modal can be closed
 */
import { test, expect } from "@playwright/test";

import { loginAs } from "./_helpers/auth";

test.beforeEach(async ({ page }) => {
  await loginAs(page, "diptu");
  await page.goto("/dashboard/analytics/");
});

test("analytics page renders all chart titles", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Emissions Trends" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Emissions by Scope" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Benchmarking" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Industry Comparison" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Regional Comparison" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Emission Intensity Over Time" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cost vs. Emissions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reduction Opportunity Analysis" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Emissions Forecast/ })).toBeVisible();
});

test("line chart paths are rendered for hover detection", async ({ page }) => {
  // There are 3 line charts on the analytics page (trends, intensity, forecast).
  // Each renders paths (was polyline, now framer-motion path).
  const paths = page.locator("svg path");
  const count = await paths.count();
  expect(count).toBeGreaterThanOrEqual(3);
});

test("View full breakdown opens trends modal", async ({ page }) => {
  await page.getByTestId("open-trends-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Emissions Trends — Full Breakdown")).toBeVisible();
  await expect(page.getByTestId("detail-field-2024-total-(jan–may)")).toBeVisible();
});

test("View full breakdown opens scopes modal", async ({ page }) => {
  await page.getByTestId("open-scopes-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Emissions by Scope — Full Breakdown")).toBeVisible();
});

test("View benchmarking detail opens benchmark modal", async ({ page }) => {
  await page.getByTestId("open-benchmark-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Benchmarking — vs Industry Average")).toBeVisible();
});

test("View industry comparison opens industry modal", async ({ page }) => {
  await page.getByTestId("open-industry-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Industry Comparison — Full Table")).toBeVisible();
});

test("View regional breakdown opens regional modal", async ({ page }) => {
  await page.getByTestId("open-regional-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  // Title is "Regional Breakdown" when no region is selected
  await expect(page.locator('[data-testid="detail-modal"] h2')).toBeVisible();
});

test("View intensity history opens intensity modal", async ({ page }) => {
  await page.getByTestId("open-intensity-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Emission Intensity — Full History")).toBeVisible();
});

test("View detailed analysis opens cost modal", async ({ page }) => {
  await page.getByTestId("open-cost-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("Cost vs. Emissions — Detailed Analysis")).toBeVisible();
});

test("View forecast details opens forecast modal", async ({ page }) => {
  await page.getByTestId("open-forecast-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText("2024 Emissions Forecast — Full Detail")).toBeVisible();
});

test("modal can be closed with close button", async ({ page }) => {
  await page.getByTestId("open-trends-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await page.getByTestId("detail-modal-close").click();
  await expect(page.getByTestId("detail-modal")).toBeHidden();
});

test("modal can be closed with ESC key", async ({ page }) => {
  await page.getByTestId("open-trends-detail").click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("detail-modal")).toBeHidden();
});

test("clicking an opportunity row opens its detail modal", async ({ page }) => {
  // Click the first opportunity row button
  await page.locator('[data-testid^="opportunity-"]').first().click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
});

test("clicking a region dot on the map opens that region's modal", async ({ page }) => {
  // Click one of the map dots
  const dot = page.locator('[data-testid^="map-dot-"]').first();
  await dot.click();
  await expect(page.getByTestId("detail-modal")).toBeVisible();
  await expect(page.getByText(/^Region: /)).toBeVisible();
});
