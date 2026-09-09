/**
 * E2E tests for the EmissionsPreview widget on / (the Executive
 * Dashboard). The dedicated /dashboard/carbon page these tests used to
 * also cover is disabled now (see that route's own page.tsx) -- its
 * real functionality (period/region tabs, KPIs, methodology panel,
 * per-region table) was consolidated into /analytics-forecast, not
 * removed; that page has its own e2e coverage in dashboard.spec.ts.
 */
import { test, expect } from "@playwright/test";

test.describe("EmissionsPreview widget on /", () => {
  test("renders the preview with sparkline + KPIs + link to /analytics-forecast", async ({ page }) => {
    await page.goto("/");
    const preview = page.getByTestId("emissions-preview");
    await expect(preview).toBeVisible();
    await expect(preview.getByText("Total (Scope 2)")).toBeVisible();
    await expect(preview.getByText("Grid intensity")).toBeVisible();
    await expect(preview.locator("svg").first()).toBeVisible();
    const link = preview.getByRole("link", { name: /View details/ });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/analytics-forecast/");
  });
});
