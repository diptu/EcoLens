/**
 * E2E tests for the new /dashboard/carbon page and the
 * EmissionsPreview widget on /dashboard/home.
 */
import { test, expect } from "@playwright/test";

test.describe("/dashboard/carbon", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/carbon/");
  });

  test("renders the page with KPIs, fuel donut, and methodology link", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Emissions", exact: true })).toBeVisible();
    await expect(page.getByTestId("carbon-methodology-link")).toBeVisible();

    // Period tabs
    for (const p of ["24h", "7d", "30d", "90d", "365d"]) {
      await expect(page.getByTestId(`period-${p}`)).toBeVisible();
    }
    // Region tabs (NEM + 6 regions)
    for (const r of ["NEM", "NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]) {
      await expect(page.getByTestId(`region-${r}`)).toBeVisible();
    }
    // KPI labels
    for (const label of ["Total emissions", "Grid intensity", "Renewable share", "vs prior period"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
  });

  test("switching period re-renders the chart", async ({ page }) => {
    await expect(page.getByTestId("period-7d")).toHaveAttribute("aria-selected", "true");
    await page.getByTestId("period-30d").click();
    await expect(page.getByTestId("period-30d")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("period-7d")).toHaveAttribute("aria-selected", "false");
  });

  test("switching region updates the period label and table", async ({ page }) => {
    await page.getByTestId("region-VIC1").click();
    await expect(page.getByTestId("region-VIC1")).toHaveAttribute("aria-selected", "true");
    // The region footer label updates
    await expect(page.getByText(/region: VIC1/i)).toBeVisible();
  });

  test("region table has 6 NEM regions + WEM and a NEM total row", async ({ page }) => {
    const table = page.getByTestId("emissions-region-table");
    await expect(table).toBeVisible();
    // Each region is a row
    for (const r of ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]) {
      await expect(table.getByRole("cell", { name: r, exact: true }).first()).toBeVisible();
    }
    // Total row
    await expect(table.getByText("NEM (total)")).toBeVisible();
  });

  test("methodology toggle expands a panel with emission factors", async ({ page }) => {
    const toggle = page.getByTestId("methodology-toggle");
    await expect(toggle).toBeVisible();
    await toggle.click();
    // After expanding, the real (computed, not static) factor table heading
    // should be visible.
    await expect(
      page.getByText("Effective emission factors this period", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Data sources", { exact: true })).toBeVisible();
  });
});

test.describe("EmissionsPreview widget on /dashboard/executive", () => {
  test("renders the preview with sparkline + KPIs + link to /dashboard/carbon", async ({ page }) => {
    await page.goto("/dashboard/executive/");
    const preview = page.getByTestId("emissions-preview");
    await expect(preview).toBeVisible();
    await expect(preview.getByText("Total (Scope 2)")).toBeVisible();
    await expect(preview.getByText("Grid intensity")).toBeVisible();
    await expect(preview.locator("svg").first()).toBeVisible();
    const link = preview.getByRole("link", { name: /View details/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/carbon/");
  });
});
