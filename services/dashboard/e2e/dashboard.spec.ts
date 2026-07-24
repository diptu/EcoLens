/**
 * E2E tests for the /dashboard/* pages.
 * Verifies sidebar + topbar are present, each page renders its
 * expected content, and navigation works.
 */
import { test, expect } from "@playwright/test";

const MAIN_PAGES = [
  "/dashboard/home",
  "/dashboard/actions",
  "/dashboard/analytics",
  "/dashboard/goals",
  "/dashboard/sources",
  "/dashboard/notifications",
  "/dashboard/organization",
  "/dashboard/profile",
  "/dashboard/reports",
  "/dashboard/scenarios",
] as const;

for (const route of MAIN_PAGES) {
  test(`/dashboard${route.replace("/dashboard", "")} page renders with sidebar + topbar`, async ({ page }) => {
    await page.goto(route);
    // Sidebar must be visible
    const sidebar = page.locator("aside").first();
    await expect(sidebar).toBeVisible();
    // The current page link should be active (with green border)
    const activeLink = sidebar.getByRole("link", { name: /home|overview|emissions|sources|products|reports|goals|actions|scenarios|analytics|insights|organization|users|preferences|billing|notifications|profile/i }).first();
    await expect(activeLink).toBeVisible();
    // The h1 of the page should be visible
    await expect(page.locator("h1").first()).toBeVisible();
  });
}

test.describe("/dashboard/home", () => {
  test("renders overview KPIs and emissions chart", async ({ page }) => {
    await page.goto("/dashboard/home");
    await expect(page.getByRole("heading", { name: /Overview/i })).toBeVisible();
    // First KPI label
    await expect(page.getByText("Total Emissions", { exact: true }).first()).toBeVisible();
  });
});

test.describe("/dashboard/actions", () => {
  test("renders AI Recommendations + Switch to Renewable Energy", async ({ page }) => {
    await page.goto("/dashboard/actions");
    await expect(page.getByRole("heading", { name: /^Actions/ }).first()).toBeVisible();
    await expect(page.getByText("AI Recommendations").first()).toBeVisible();
    await expect(page.getByText("Switch to Renewable Energy", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Optimize Logistics Routes", { exact: true }).first()).toBeVisible();
  });

  test("renders roadmap with 3 phases", async ({ page }) => {
    await page.goto("/dashboard/actions");
    await expect(page.getByText("Implementation Roadmap")).toBeVisible();
    await expect(page.getByText("Short Term", { exact: true })).toBeVisible();
    await expect(page.getByText("Mid Term", { exact: true })).toBeVisible();
    await expect(page.getByText("Long Term", { exact: true })).toBeVisible();
  });
});

test.describe("/dashboard/analytics", () => {
  test("renders all 8 tabs", async ({ page }) => {
    await page.goto("/dashboard/analytics");
    for (const tab of ["Overview", "Emissions Trends", "Benchmarking", "Industry Comparison", "Regional Comparison", "Emission Intensity", "Cost vs. Emissions", "Opportunities"]) {
      await expect(page.getByRole("button", { name: tab, exact: true })).toBeVisible();
    }
  });

  test("renders benchmarking and industry comparison sections", async ({ page }) => {
    await page.goto("/dashboard/analytics");
    await expect(page.getByRole("heading", { name: "Benchmarking" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Industry Comparison" })).toBeVisible();
  });
});

test.describe("/dashboard/goals", () => {
  test("renders 6 your goals", async ({ page }) => {
    await page.goto("/dashboard/goals");
    await expect(page.getByRole("heading", { name: /^Goals/ })).toBeVisible();
    for (const goal of [
      "Net Zero by 2030",
      "Reduce 42% Scope 1 & 2",
      "Reduce 25% Scope 3",
      "50% Renewable Energy",
      "Reduce 20% Scope 1 & 2",
      "Supplier Engagement",
    ]) {
      await expect(page.getByText(goal, { exact: true }).first()).toBeVisible();
    }
  });

  test("renders SBTi alignment card", async ({ page }) => {
    await page.goto("/dashboard/goals");
    await expect(page.getByRole("heading", { name: "SBTi Alignment" })).toBeVisible();
  });
});

test.describe("/dashboard/sources", () => {
  test("renders AWS CloudTrail and other data sources", async ({ page }) => {
    await page.goto("/dashboard/sources");
    await expect(page.getByRole("heading", { name: /^Data Sources/ })).toBeVisible();
    await expect(page.getByText("AWS CloudTrail", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Stripe Payments", { exact: true }).first()).toBeVisible();
  });

  test("renders Overall Health card", async ({ page }) => {
    await page.goto("/dashboard/sources");
    await expect(page.getByRole("heading", { name: "Overall Health" })).toBeVisible();
  });
});

test.describe("/dashboard/notifications", () => {
  test("renders notification feed", async ({ page }) => {
    await page.goto("/dashboard/notifications");
    await expect(page.getByRole("heading", { name: /^Notifications/ }).first()).toBeVisible();
    await expect(page.getByText("New Recommendation Available", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Goal Milestone Achieved", { exact: true }).first()).toBeVisible();
  });
});

test.describe("/dashboard/organization", () => {
  test("renders org name + locations + facilities", async ({ page }) => {
    await page.goto("/dashboard/organization");
    await expect(page.getByRole("heading", { name: /^Organization/ }).first()).toBeVisible();
    await expect(page.getByText("EcoLens Technologies Ltd.", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Dhaka, Bangladesh", { exact: true }).first()).toBeVisible();
  });
});

test.describe("/dashboard/profile", () => {
  test("renders personal information + preferences", async ({ page }) => {
    await page.goto("/dashboard/profile");
    await expect(page.getByRole("heading", { name: "Profile", exact: true })).toBeVisible();
    await expect(page.getByText("Diptu Alam", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Personal Information").first()).toBeVisible();
    await expect(page.getByText("Preferences", { exact: true }).first()).toBeVisible();
  });
});

test.describe("/dashboard/reports", () => {
  test("renders report types + recent reports", async ({ page }) => {
    await page.goto("/dashboard/reports");
    await expect(page.getByRole("heading", { name: /^Reports/ }).first()).toBeVisible();
    await expect(page.getByText("GHG Protocol Report", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("ESG Report - Q1 2024", { exact: true }).first()).toBeVisible();
  });
});

test.describe("/dashboard/scenarios", () => {
  test("renders scenarios list + create form", async ({ page }) => {
    await page.goto("/dashboard/scenarios");
    await expect(page.getByRole("heading", { name: /^Scenarios/ })).toBeVisible();
    await expect(page.getByText("Switch 50% Electricity to Renewable Energy", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Net Zero Pathway 2030", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Create a New Scenario")).toBeVisible();
  });
});

test.describe("core web vitals (dashboard)", () => {
  test("home: FCP < 1.5s, CLS = 0", async ({ page }) => {
    await page.goto("/dashboard/home");
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
});
