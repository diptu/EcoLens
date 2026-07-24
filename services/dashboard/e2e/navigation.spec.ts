/**
 * E2E navigation tests.
 * Verifies the navbar is present, visible, and navigable on every page.
 */
import { test, expect } from "@playwright/test";

const PAGES = ["/", "/product", "/resources", "/solutions", "/pricing", "/about"];

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

test("home → product link works", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Product", exact: true }).first().click();
  await page.waitForURL(/\/product/);
  await expect(page).toHaveURL(/\/product/);
});

test("home → solutions link works", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Solutions", exact: true }).first().click();
  await page.waitForURL(/\/solutions/);
});

test("home → resources link works", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Resources", exact: true }).first().click();
  await page.waitForURL(/\/resources/);
});

test("logo returns to home", async ({ page }) => {
  await page.goto("/product");
  await page.getByRole("link", { name: /EcoLens/i }).first().click();
  await page.waitForURL(/\/$/);
});
