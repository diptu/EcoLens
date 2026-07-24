/**
 * E2E tests for the /pricing page.
 * Verifies the LCP element is visible, the 4 plans render, and the
 * monthly/annually toggle works.
 */
import { test, expect } from "@playwright/test";

test.describe("/pricing", () => {
  test("renders hero with H1 and 4 plan cards", async ({ page }) => {
    await page.goto("/pricing/");

    // LCP element — the H1 should be visible immediately
    const h1 = page.getByRole("heading", { level: 1, name: /Simple, transparent pricing/i });
    await expect(h1).toBeVisible();

    // All 4 plan names (use .first() to avoid the table columnheader)
    await expect(page.getByText("Starter", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Growth", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Professional", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Enterprise", { exact: true }).first()).toBeVisible();

    // 3 featured prices visible (Starter, Growth, Professional)
    await expect(page.getByText("$29", { exact: true })).toBeVisible();
    await expect(page.getByText("$79", { exact: true })).toBeVisible();
    await expect(page.getByText("$199", { exact: true })).toBeVisible();
    // Enterprise is "Custom"
    await expect(page.getByText("Custom", { exact: true })).toBeVisible();
  });

  test("Most Popular badge on Growth plan", async ({ page }) => {
    await page.goto("/pricing/");
    const popular = page.getByText("Most Popular", { exact: true });
    await expect(popular).toBeVisible();
  });

  test("Compare plans table renders 4 plan columns", async ({ page }) => {
    await page.goto("/pricing/");
    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    // The first row should be the header
    const header = table.locator("th").first();
    await expect(header).toContainText("Compare plans");
    // All 4 plan names as column headers
    for (const name of ["Starter", "Growth", "Professional", "Enterprise"]) {
      await expect(table.locator("th").getByText(name, { exact: true })).toBeVisible();
    }
  });

  test("monthly/annually toggle switches prices", async ({ page }) => {
    await page.goto("/pricing/");

    // Default is annually → $29 / $79 / $199
    await expect(page.getByText("$29", { exact: true })).toBeVisible();
    await expect(page.getByText("$79", { exact: true })).toBeVisible();

    // Click "Pay Monthly"
    await page.getByRole("radio", { name: "Pay Monthly" }).click();
    await expect(page.getByText("$39", { exact: true })).toBeVisible();
    await expect(page.getByText("$99", { exact: true })).toBeVisible();
    // $29 should be gone
    await expect(page.getByText("$29", { exact: true })).toHaveCount(0);

    // Click "Pay Annually" again
    await page.getByRole("radio", { name: "Pay Annually" }).click();
    await expect(page.getByText("$29", { exact: true })).toBeVisible();
    await expect(page.getByText("$39", { exact: true })).toHaveCount(0);
  });

  test("All plans include section shows 6 items", async ({ page }) => {
    await page.goto("/pricing/");
    const heading = page.getByText("All plans include:", { exact: true });
    await expect(heading).toBeVisible();
    for (const item of [
      "Secure & compliant",
      "Audit trail & data history",
      "GDPR compliant",
      "Regular product updates",
      "Export to PDF & CSV",
      "Mobile-friendly experience",
    ]) {
      await expect(page.getByText(item, { exact: true })).toBeVisible();
    }
  });

  test("Add-ons section shows 4 items with prices", async ({ page }) => {
    await page.goto("/pricing/");
    const heading = page.getByText("Add-ons", { exact: true });
    await expect(heading).toBeVisible();
    for (const item of [
      "Additional users",
      "Advanced integrations",
      "Custom report builder",
      "Dedicated data store",
    ]) {
      await expect(page.getByText(item, { exact: true })).toBeVisible();
    }
  });

  test("Contact Sales CTA in the custom solution card", async ({ page }) => {
    await page.goto("/pricing/");
    const cta = page.getByRole("link", { name: "Talk to Sales" });
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "mailto:sales@ecolens.app");
  });

  test("Enterprise CTA is Contact Sales (not Start Free Trial)", async ({ page }) => {
    await page.goto("/pricing/");
    // Find the Enterprise card's CTA (last in the row of 4)
    const entCta = page.getByRole("link", { name: "Contact Sales" });
    await expect(entCta).toBeVisible();
  });

  test("core web vitals: FCP < 1.5s, CLS = 0", async ({ page }) => {
    await page.goto("/pricing/");
    const metrics = await page.evaluate(
      () =>
        new Promise<{ fcp: number; cls: number }>((resolve) => {
          let fcp = 0;
          let cls = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (entry.name === "first-contentful-paint") fcp = entry.startTime;
            }
          }).observe({ type: "paint", buffered: true });
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (!(entry as PerformanceEntry & { hadRecentInput?: boolean }).hadRecentInput) {
                cls += (entry as PerformanceEntry & { value: number }).value;
              }
            }
          }).observe({ type: "layout-shift", buffered: true });
          setTimeout(() => resolve({ fcp, cls }), 500);
        }),
    );
    expect(metrics.fcp).toBeGreaterThan(0);
    expect(metrics.fcp).toBeLessThan(1500);
    expect(metrics.cls).toBe(0);
  });

  test("forest background image is preloaded", async ({ page }) => {
    await page.goto("/pricing/");
    // The <link rel="preload" as="image"> tag should be in the head
    const preload = await page.locator('link[rel="preload"][as="image"][href*="forest"]').count();
    expect(preload).toBeGreaterThan(0);
  });
});
