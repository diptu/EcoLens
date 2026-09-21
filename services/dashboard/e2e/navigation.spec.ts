/**
 * E2E navigation tests.
 * Verifies the navbar is present, visible, and navigable on every page.
 */
import { test, expect } from "@playwright/test";

const PAGES = ["/resources"];

for (const route of PAGES) {
  test(`navbar is visible on ${route}`, async ({ page }) => {
    await page.goto(route);
    const header = page.locator("header").first();
    await expect(header).toBeVisible();
    // The header should NOT be opacity:0 (the bug we just fixed)
    const opacity = await header.evaluate((el) => getComputedStyle(el).opacity);
    expect(parseFloat(opacity)).toBeGreaterThan(0.5);
  });
}

const AUTH_PAGES = ["/login/", "/signup/", "/forgot-password/", "/reset-password/", "/verify-email/", "/onboarding/"];

for (const route of AUTH_PAGES) {
  test(`auth page ${route} has no marketing navbar`, async ({ page }) => {
    await page.goto(route);
    // The marketing navbar should NOT be on auth pages
    const nav = page.locator("nav").first();
    await expect(nav).toHaveCount(0);
  });
}

test("resources → blog link works", async ({ page }) => {
  await page.goto("/resources");
  await page.getByRole("link", { name: "Blog", exact: true }).first().click();
  await page.waitForURL(/\/blog/);
});

test("/ renders the Executive Dashboard directly", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Executive Dashboard/ })).toBeVisible();
});

test("/dashboard/executive redirects to /", async ({ page }) => {
  await page.goto("/dashboard/executive/");
  await page.waitForURL((url) => url.pathname === "/");
});

test("logo goes to /", async ({ page }) => {
  await page.goto("/resources");
  await page.getByRole("link", { name: /EcoLens/i }).first().click();
  await page.waitForURL((url) => url.pathname === "/");
});
