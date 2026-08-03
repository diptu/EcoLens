/**
 * E2E tests for the new Architecture page (/dashboard/architecture).
 *
 * Verifies:
 *   - Page loads with all 5 tabs
 *   - Each tab content renders the expected key elements
 *   - Sidebar nav link is present
 */
import { test, expect } from "@playwright/test";

test.describe("/dashboard/architecture", () => {
  test("page loads with title and all 5 tabs", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await expect(page.getByRole("heading", { name: /Platform Architecture/i })).toBeVisible();

    for (const tab of [
      "Pipeline Overview",
      "Anomaly Detection",
      "ML Lifecycle",
      "Storage Strategy",
      "Frontend & API",
    ]) {
      await expect(page.getByTestId(`arch-tab-${tab.toLowerCase().split(" ")[0]}`)).toBeVisible();
    }
  });

  test("Pipeline Overview shows all 4 stages", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await expect(page.getByText("1. Ingestion")).toBeVisible();
    await expect(page.getByText("2. Warehousing")).toBeVisible();
    await expect(page.getByText("3. Predictive Modeling")).toBeVisible();
    await expect(page.getByText("4. Frontend")).toBeVisible();
  });

  test("Pipeline Overview mentions key terms", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await expect(page.getByText(/DuckDB/).first()).toBeVisible();
    await expect(page.getByText(/RabbitMQ/).first()).toBeVisible();
    await expect(page.getByText(/dbt/).first()).toBeVisible();
    await expect(page.getByText(/PostgreSQL/).first()).toBeVisible();
    await expect(page.getByText(/LSTM/).first()).toBeVisible();
    await expect(page.getByText(/TFT/).first()).toBeVisible();
    await expect(page.getByText(/TimesFM/).first()).toBeVisible();
    await expect(page.getByText(/Next\.js/).first()).toBeVisible();
  });

  test("Anomaly Detection tab shows flag-not-remove philosophy", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await page.getByTestId("arch-tab-anomaly").click();
    await expect(page.getByRole("heading", { name: /Hybrid anomaly detection/i })).toBeVisible();
    await expect(page.getByText(/Flag, never remove/i)).toBeVisible();
    await expect(page.getByText(/z-score/i).first()).toBeVisible();
  });

  test("ML Lifecycle tab shows P10/P50/P90 + conformal calibration", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await page.getByTestId("arch-tab-ml").click();
    await expect(page.getByText(/Probabilistic forecasts/i)).toBeVisible();
    await expect(page.getByText(/Conformal calibration/i)).toBeVisible();
    await expect(page.getByText(/MLflow/i).toBeVisible();
    await expect(page.getByText(/seasonal-naïve/i).first()).toBeVisible();
  });

  test("Storage Strategy tab shows raw/stg/int/mart schema layers", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await page.getByTestId("arch-tab-storage").click();
    await expect(page.getByText(/Layered storage/i)).toBeVisible();
    await expect(page.getByText("raw.*").first()).toBeVisible();
    await expect(page.getByText("stg_*").first()).toBeVisible();
    await expect(page.getByText("int_*").first()).toBeVisible();
    await expect(page.getByText("mart_*").first()).toBeVisible();
  });

  test("Frontend & API tab mentions REST decoupling", async ({ page }) => {
    await page.goto("/dashboard/architecture");
    await page.getByTestId("arch-tab-frontend").click();
    await expect(page.getByText(/Frontend & API/i)).toBeVisible();
    await expect(page.getByText(/Why REST/i)).toBeVisible();
    await expect(page.getByText(/forecast-api/).first()).toBeVisible();
    await expect(page.getByText(/data-pipeline/).first()).toBeVisible();
  });

  test("sidebar has Architecture link under About group", async ({ page }) => {
    test.skip((await page.viewportSize())?.width !== undefined && (await page.viewportSize())!.width < 1024,
              "Sidebar is a drawer on mobile");
    await page.goto("/dashboard/executive");
    await expect(page.locator("aside").getByRole("link", { name: "Architecture", exact: true })).toBeVisible();
  });
});
