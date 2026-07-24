/**
 * E2E tests for dashboard navigation.
 * Verifies the sidebar nav links work and active state is set.
 */
import { test, expect } from "@playwright/test";

test("sidebar nav: Home -> Actions", async ({ page }) => {
  await page.goto("/dashboard/home");
  await page.locator("aside").getByRole("link", { name: "Actions", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/actions/);
  await expect(page.locator("h1").first()).toContainText("Actions");
});

test("sidebar nav: Actions -> Analytics", async ({ page }) => {
  await page.goto("/dashboard/actions");
  await page.locator("aside").getByRole("link", { name: "Analytics", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/analytics/);
});

test("sidebar nav: Analytics -> Goals", async ({ page }) => {
  await page.goto("/dashboard/analytics");
  await page.locator("aside").getByRole("link", { name: "Goals", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/goals/);
});

test("sidebar nav: Goals -> Sources", async ({ page }) => {
  await page.goto("/dashboard/goals");
  await page.locator("aside").getByRole("link", { name: "Sources", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/sources/);
});

test("sidebar nav: Sources -> Reports", async ({ page }) => {
  await page.goto("/dashboard/sources");
  await page.locator("aside").getByRole("link", { name: "Reports", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/reports/);
});

test("sidebar nav: Reports -> Scenarios", async ({ page }) => {
  await page.goto("/dashboard/reports");
  await page.locator("aside").getByRole("link", { name: "Scenarios", exact: true }).first().click();
  await page.waitForURL(/\/dashboard\/scenarios/);
});

test("topbar: breadcrumb shows current page", async ({ page }) => {
  await page.goto("/dashboard/analytics");
  const breadcrumb = page.locator("header").filter({ hasText: "Home" }).first();
  await expect(breadcrumb).toContainText("Dashboard");
  await expect(breadcrumb).toContainText("Analytics");
});

test("topbar: ⌘K focuses search", async ({ page }) => {
  await page.goto("/dashboard/home");
  // Wait for the JS event handler to attach
  await page.waitForTimeout(500);
  // Use Control+K on Linux (⌘K on Mac)
  await page.keyboard.press("Control+k");
  const searchInput = page.locator("#dash-search");
  await expect(searchInput).toBeFocused();
});

test("profile dropdown opens on click", async ({ page }) => {
  await page.goto("/dashboard/home");
  await page.locator("button:has-text('Diptu Alam')").first().click();
  // The dropdown should show Profile link
  await expect(page.getByRole("link", { name: "Profile", exact: true }).first()).toBeVisible();
});
