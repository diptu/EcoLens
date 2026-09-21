/**
 * E2E page content tests.
 * Verifies the inner pages render their expected content from the
 * static data layer.
 */
import { test, expect } from "@playwright/test";

test.describe("/resources", () => {
  test("renders hero", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByRole("heading", { name: /Knowledge Today/i })).toBeVisible();
  });
  test("renders all 6 categories", async ({ page }) => {
    await page.goto("/resources");
    for (const title of [
      "Guides & Playbooks",
      "Reports & Research",
      "Tools & Calculators",
      "Videos & Webinars",
      "Case Studies",
      "Policy & Standards",
    ]) {
      // Use heading role to avoid matching paragraph text
      await expect(page.getByRole("heading", { name: title, level: 3 })).toBeVisible();
    }
  });
  test("renders featured resources", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByRole("heading", { name: "Carbon Accounting 101" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "GHG Inventory Template" })).toBeVisible();
  });
  test("renders search input", async ({ page }) => {
    await page.goto("/resources");
    await expect(page.getByPlaceholder("Search resources...")).toBeVisible();
  });
});
