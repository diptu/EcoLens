/**
 * E2E tests for the new /dashboard/carbon/methodology page.
 */
import { test, expect } from "@playwright/test";

test.describe("/dashboard/carbon/methodology", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard/carbon/methodology/");
  });

  test("renders with title, 6-step calculation chain, 3 worked examples, factors table, sources", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /How emissions are calculated/i })).toBeVisible();
    await expect(page.getByTestId("methodology-source")).toBeVisible();

    // 6-step chain
    const chain = page.getByTestId("calculation-chain");
    await expect(chain).toBeVisible();
    for (let i = 1; i <= 6; i++) {
      await expect(page.getByTestId(`chain-step-${i}`)).toBeVisible();
    }

    // 3 worked example tabs
    for (const ex of ["ex-scope2-basic", "ex-scope1-mix", "ex-whatif-100"]) {
      await expect(page.getByTestId(`example-${ex}`)).toBeVisible();
    }

    // Factors table
    await expect(page.getByTestId("factors-table")).toBeVisible();
    // Each factor has a row
    for (const factor of ["coal_black_mw", "coal_brown_mw", "wind_mw", "nem_grid_avg"]) {
      await expect(page.getByTestId(`factor-row-${factor}`)).toBeVisible();
    }

    // Sources grid
    await expect(page.getByTestId("sources-grid")).toBeVisible();
    for (const source of ["aemo-nem", "bom-weather", "ipcc-ar5"]) {
      await expect(page.getByTestId(`source-${source}`)).toBeVisible();
    }
  });

  test("switching worked example updates the detail view", async ({ page }) => {
    // Default is ex-scope2-basic
    await expect(page.getByTestId("example-ex-scope2-basic")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("example-ex-scope2-basic-detail")).toBeVisible();

    // Switch to ex-scope1-mix
    await page.getByTestId("example-ex-scope1-mix").click();
    await expect(page.getByTestId("example-ex-scope1-mix")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("example-ex-scope1-mix-detail")).toBeVisible();
  });

  test("trace mockup shows after clicking 'Run trace'", async ({ page }) => {
    const trace = page.getByTestId("trace-result");
    await expect(trace).toHaveCount(0);
    await page.getByTestId("run-trace").click();
    await expect(trace).toBeVisible();
  });

  test("region selector picks all 6 regions + WEM", async ({ page }) => {
    const select = page.getByTestId("trace-region");
    for (const r of ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"]) {
      await expect(select.locator(`option[value="${r}"]`)).toHaveCount(1);
    }
  });
});

test.describe("/dashboard/carbon links to methodology", () => {
  test("carbon page has a 'How is this calculated?' link in the header", async ({ page }) => {
    await page.goto("/dashboard/carbon/");
    const link = page.getByTestId("carbon-methodology-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/carbon/methodology/");
  });

  test("clicking the link navigates to the methodology page", async ({ page }) => {
    await page.goto("/dashboard/carbon/");
    await page.getByTestId("carbon-methodology-link").click();
    await page.waitForURL(/\/dashboard\/carbon\/methodology\//);
    await expect(page.getByRole("heading", { name: /How emissions are calculated/i })).toBeVisible();
  });
});
