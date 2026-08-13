/**
 * e2e tests for the new Report functionality in /dashboard/reports.
 *
 *  - "New Report" dropdown opens
 *  - Template selection opens the modal pre-filled
 *  - Custom report opens the modal in custom mode
 *  - Modal can be filled and submitted → new report appears in library
 *  - Preview modal opens with report details
 *  - Delete removes a report
 *  - Duplicate creates a copy
 *  - Toast notifications appear
 *  - localStorage persistence
 *  - Search and filter work
 */
import { test, expect } from "@playwright/test";

import { loginAs } from "./_helpers/auth";

test.beforeEach(async ({ page }) => {
  await loginAs(page, "diptu");
  // Clear any saved reports from prior runs
  await page.evaluate(() => localStorage.removeItem("ecolens:reports:saved"));
  await page.goto("/dashboard/reports/");
});

test("reports page renders with all sections", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Reports 📄" })).toBeVisible();
  await expect(page.getByText("Report Templates")).toBeVisible();
  await expect(page.getByText("Report Summary")).toBeVisible();
  await expect(page.getByText("Audit Trail")).toBeVisible();
  await expect(page.getByText("Reports Over Time")).toBeVisible();
  await expect(page.getByText("Popular Metrics in Reports")).toBeVisible();
});

test("New Report button opens dropdown", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  const dropdown = page.getByTestId("new-report-dropdown");
  await expect(dropdown).toBeVisible();
  // Should have template options
  await expect(page.getByTestId("new-report-template-ghg")).toBeVisible();
  await expect(page.getByTestId("new-report-custom")).toBeVisible();
});

test("clicking a template opens the new report modal", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-template-esg").click();
  const modal = page.getByTestId("new-report-modal");
  await expect(modal).toBeVisible();
  // Modal should be pre-filled with ESG
  const frameworkSelect = page.getByTestId("report-framework-select");
  await expect(frameworkSelect).toHaveValue("ESG Report");
  // And the name should be auto-suggested
  const nameInput = page.getByTestId("report-name-input");
  await expect(nameInput).toHaveValue(/ESG Report/);
});

test("custom report button opens modal in custom mode", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-custom").click();
  await expect(page.getByTestId("new-report-modal")).toBeVisible();
  await expect(page.getByTestId("report-name-input")).toHaveValue("Custom Report");
});

test("modal can be cancelled", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-custom").click();
  await expect(page.getByTestId("new-report-modal")).toBeVisible();
  await page.getByTestId("new-report-cancel").click();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("new-report-modal")).toBeHidden();
});

test("submitting a new report creates it in the library", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-template-ghg").click();
  await expect(page.getByTestId("new-report-modal")).toBeVisible();
  // Override the name
  await page.getByTestId("report-name-input").fill("Test Report E2E");
  // Submit
  await page.getByTestId("new-report-submit").click();
  await page.waitForTimeout(500);
  // Modal should be closed
  await expect(page.getByTestId("new-report-modal")).toBeHidden();
  // Toast should appear
  await expect(page.getByTestId("toast")).toBeVisible();
  // New report should be in the library (use the row's text, not the toast)
  const newRow = page.locator('[data-testid^="report-row-"]').filter({ hasText: "Test Report E2E" });
  await expect(newRow).toBeVisible();
});

test("submitting with empty name shows error toast", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-custom").click();
  await page.getByTestId("report-name-input").fill("");
  await page.getByTestId("new-report-submit").click();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("toast")).toContainText("Please enter a report name");
  // Modal should still be open
  await expect(page.getByTestId("new-report-modal")).toBeVisible();
});

test("preview button opens preview modal", async ({ page }) => {
  // Use the first seed report
  const firstReport = page.locator('[data-testid^="report-row-"]').first();
  const previewBtn = firstReport.locator('[data-testid^="preview-report-"]');
  await previewBtn.click();
  await expect(page.getByTestId("preview-modal")).toBeVisible();
  await expect(page.getByText("Report Preview")).toBeVisible();
  await expect(page.getByTestId("preview-download")).toBeVisible();
  // Close
  await page.getByTestId("preview-close").click();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("preview-modal")).toBeHidden();
});

test("download button shows toast", async ({ page }) => {
  const firstReport = page.locator('[data-testid^="report-row-"]').first();
  const downloadBtn = firstReport.locator('[data-testid^="download-report-"]');
  await downloadBtn.click();
  await page.waitForTimeout(200);
  await expect(page.getByTestId("toast")).toContainText(/Downloading/);
});

test("duplicate button creates a copy", async ({ page }) => {
  const firstReport = page.locator('[data-testid^="report-row-"]').first();
  const originalName = await firstReport.locator("p").first().textContent();
  const dupBtn = firstReport.locator('[data-testid^="duplicate-report-"]');
  await dupBtn.click();
  await page.waitForTimeout(300);
  // Look for a "Copy" version
  await expect(page.getByText(`${originalName} (Copy)`)).toBeVisible();
  await expect(page.getByTestId("toast")).toContainText("duplicated");
});

test("delete button removes the report", async ({ page }) => {
  // First create a report so we don't mess with seed data
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-template-ghg").click();
  await page.getByTestId("report-name-input").fill("Delete Me");
  await page.getByTestId("new-report-submit").click();
  await page.waitForTimeout(300);
  // Find that report and delete it
  const targetRow = page.locator('[data-testid^="report-row-"]').filter({ hasText: "Delete Me" });
  await targetRow.locator('[data-testid^="delete-report-"]').click();
  await page.waitForTimeout(300);
  await expect(page.getByText("Delete Me")).toBeHidden();
  await expect(page.getByTestId("toast")).toContainText("deleted");
});

test("search filters the report list", async ({ page }) => {
  await page.getByTestId("reports-search").fill("ESG");
  await page.waitForTimeout(200);
  // Only ESG reports should be visible
  const visibleRows = page.locator('[data-testid^="report-row-"]');
  const count = await visibleRows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const text = await visibleRows.nth(i).textContent();
    expect(text?.toLowerCase()).toContain("esg");
  }
});

test("framework filter narrows the list", async ({ page }) => {
  await page.getByTestId("reports-filter").selectOption("TCFD");
  await page.waitForTimeout(200);
  const visibleRows = page.locator('[data-testid^="report-row-"]');
  const count = await visibleRows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const text = await visibleRows.nth(i).textContent();
    expect(text).toContain("TCFD");
  }
});

test("new reports persist to localStorage", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-template-ghg").click();
  await page.getByTestId("report-name-input").fill("Persisted Report");
  await page.getByTestId("new-report-submit").click();
  await page.waitForTimeout(300);
  // Reload
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Persisted Report")).toBeVisible();
});

test("template cards open modal", async ({ page }) => {
  await page.getByTestId("template-card-cdp").click();
  await expect(page.getByTestId("new-report-modal")).toBeVisible();
  await expect(page.getByTestId("report-framework-select")).toHaveValue("CDP Report");
});

test("scope toggles work", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-custom").click();
  // Click Scope 2 toggle to remove it
  await page.getByTestId("scope-toggle-scope-2").click();
  await page.waitForTimeout(200);
  // The toggle should still exist but be deselected
  await expect(page.getByTestId("scope-toggle-scope-2")).toBeVisible();
});

test("format selection works", async ({ page }) => {
  await page.getByTestId("new-report-button").click();
  await page.getByTestId("new-report-custom").click();
  // Click Excel
  await page.getByTestId("format-toggle-excel").click();
  await page.waitForTimeout(100);
  // Now submit
  await page.getByTestId("report-name-input").fill("Excel Test");
  await page.getByTestId("new-report-submit").click();
  await page.waitForTimeout(300);
  // Toast should mention the new report
  await expect(page.getByTestId("toast")).toContainText("Excel Test");
});
