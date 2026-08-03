/**
 * E2E tests for the Integrations tab on the Settings page.
 *
 * Covers:
 *   - Tab loads with Google Sheets card
 *   - Connection state (CONNECTED pill) is visible
 *   - Configured exports are listed
 *   - New export modal opens, has all expected fields, can be dismissed
 *   - Export history table is populated
 *   - Other integrations show "soon" placeholder
 */
import { test, expect } from "@playwright/test";

test.describe("Settings → Integrations", () => {
  test("Integrations tab loads with the Google Sheets card", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await expect(page.getByTestId("integration-google-sheets")).toBeVisible();
    await expect(page.getByText("CONNECTED").first()).toBeVisible();
    await expect(page.getByText("diptu@ecolens.com")).toBeVisible();
  });

  test("Granted OAuth scopes are shown", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await expect(page.getByText("spreadsheets", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("drive.file", { exact: false }).first()).toBeVisible();
  });

  test("Configured exports are listed", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    const list = page.getByTestId("export-list");
    await expect(list).toBeVisible();
    await expect(page.getByText("NEM Daily Emissions Summary")).toBeVisible();
    await expect(page.getByText(/VIC1 Forecast/)).toBeVisible();
    await expect(page.getByText(/Carbon Intensity/)).toBeVisible();
  });

  test("Each export shows source / region / format / schedule", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    const row = page.getByTestId("export-row-exp-001");
    await expect(row).toBeVisible();
    await expect(row).toContainText("emissions_total");
    await expect(row).toContainText("NEM");
    await expect(row).toContainText("summary");
    await expect(row).toContainText("daily");
  });

  test("New export button opens the modal with all fields", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await page.getByTestId("new-export-btn").click();

    const modal = page.getByTestId("new-export-modal");
    await expect(modal).toBeVisible();

    await expect(page.getByTestId("export-name")).toBeVisible();
    await expect(page.getByTestId("export-source")).toBeVisible();

    // Source dropdown has 11 options
    const sourceOptions = page.getByTestId("export-source").locator("option");
    await expect(sourceOptions).toHaveCount(11);

    // Close via X
    await modal.getByRole("button", { name: "Close" }).click();
    await expect(modal).not.toBeVisible();
  });

  test("Edit existing export pre-fills the modal", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await page.getByTestId("edit-export-exp-001").click();
    const modal = page.getByTestId("new-export-modal");
    await expect(modal).toBeVisible();
    await expect(modal.getByText("Edit export")).toBeVisible();
    await expect(page.getByTestId("export-name")).toHaveValue("NEM Daily Emissions Summary");
  });

  test("Export history is shown with success + failed rows", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    const history = page.getByTestId("export-history");
    await expect(history).toBeVisible();
    await expect(history.getByText("success", { exact: false }).first()).toBeVisible();
    await expect(history.getByText("failed", { exact: false }).first()).toBeVisible();
  });

  test("Failed history rows show a Retry button", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    const history = page.getByTestId("export-history");
    await expect(history.getByRole("button", { name: /Retry/ })).toBeVisible();
  });

  test("Other integrations (Slack, PagerDuty) show 'soon' badge", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await expect(page.getByTestId("integration-slack")).toBeVisible();
    await expect(page.getByTestId("integration-pagerduty")).toBeVisible();
    await expect(page.getByTestId("integration-slack")).toContainText("soon");
    await expect(page.getByTestId("integration-pagerduty")).toContainText("soon");
  });

  test("Run-now button is visible on each export", async ({ page }) => {
    await page.goto("/dashboard/settings");
    await page.getByRole("button", { name: "Integrations" }).click();

    await expect(page.getByTestId("run-export-exp-001")).toBeVisible();
    await expect(page.getByTestId("run-export-exp-002")).toBeVisible();
  });
});
