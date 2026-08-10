# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: executive-detail.spec.ts >> executive page renders all chart sections
- Location: e2e/executive-detail.spec.ts:18:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('Emissions Trend')
Expected: visible
Error: strict mode violation: getByText('Emissions Trend') resolved to 2 elements:
    1) <h2 data-testid="emissions-trend-title" class="text-xl font-semibold text-white">Emissions Trend</h2> aka getByTestId('emissions-trend-title')
    2) <h2 class="text-base font-semibold text-white">Emissions Trend (compact)</h2> aka getByRole('heading', { name: 'Emissions Trend (compact)' })

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByText('Emissions Trend')

```

# Page snapshot

```yaml
- generic [active] [ref=f1e1]:
  - generic [ref=f1e2]:
    - complementary [ref=f1e3]:
      - generic [ref=f1e4]:
        - generic [ref=f1e5]: EcoLens
        - navigation [ref=f1e11]:
          - generic [ref=f1e12]:
            - paragraph [ref=f1e13]: Dashboards
            - link "Executive" [ref=f1e14] [cursor=pointer]:
              - /url: /dashboard/executive/
            - link "Operations" [ref=f1e20] [cursor=pointer]:
              - /url: /dashboard/operations/
          - generic [ref=f1e25]:
            - paragraph [ref=f1e26]: Data Platform
            - link "Data Sources" [ref=f1e27] [cursor=pointer]:
              - /url: /dashboard/data-sources/
            - link "Ingestion Pipeline" [ref=f1e33] [cursor=pointer]:
              - /url: /dashboard/ingestion/
            - link "Data Quality & Anomalies" [ref=f1e39] [cursor=pointer]:
              - /url: /dashboard/data-quality/
          - generic [ref=f1e43]:
            - paragraph [ref=f1e44]: Insights
            - link "Forecast Explorer" [ref=f1e45] [cursor=pointer]:
              - /url: /dashboard/forecast/
            - link "Carbon Intelligence" [ref=f1e50] [cursor=pointer]:
              - /url: /dashboard/carbon/
            - link "Energy Analytics" [ref=f1e55] [cursor=pointer]:
              - /url: /dashboard/analytics/
          - generic [ref=f1e59]:
            - paragraph [ref=f1e60]: ML Platform
            - link "Model Registry" [ref=f1e61] [cursor=pointer]:
              - /url: /dashboard/models/
            - link "Training & Experiments" [ref=f1e66] [cursor=pointer]:
              - /url: /dashboard/training/
            - link "Performance" [ref=f1e70] [cursor=pointer]:
              - /url: /dashboard/performance/
          - generic [ref=f1e75]:
            - paragraph [ref=f1e76]: Operations
            - link "Operational Tasks" [ref=f1e77] [cursor=pointer]:
              - /url: /dashboard/operational-tasks/
            - link "System Health" [ref=f1e81] [cursor=pointer]:
              - /url: /dashboard/system-health/
          - generic [ref=f1e85]:
            - paragraph [ref=f1e86]: About
            - link "Architecture" [ref=f1e87] [cursor=pointer]:
              - /url: /dashboard/architecture/
        - generic [ref=f1e93]:
          - generic [ref=f1e94]: EcoLens
          - paragraph [ref=f1e100]: © 2025 EcoLensAll rights reserved.
    - generic [ref=f1e101]:
      - banner [ref=f1e102]:
        - generic [ref=f1e103]:
          - navigation [ref=f1e104]:
            - link "Home" [ref=f1e106] [cursor=pointer]:
              - /url: /dashboard/executive/
            - link "Dashboard" [ref=f1e110] [cursor=pointer]:
              - /url: /dashboard/executive/
            - generic [ref=f1e113]: Executive
          - generic [ref=f1e115]:
            - textbox "Search anything…" [ref=f1e116]
            - generic: ⌘K
          - link "Notifications" [ref=f1e117] [cursor=pointer]:
            - /url: /dashboard/system-health/
            - generic [ref=f1e121]: "3"
      - main [ref=f1e122]:
        - generic [ref=f1e123]:
          - generic [ref=f1e124]:
            - heading "Executive Dashboard" [level=1] [ref=f1e125]
            - paragraph [ref=f1e129]: High-level sustainability + financial KPIs for leadership.
          - generic [ref=f1e130]:
            - generic [ref=f1e131]:
              - generic [ref=f1e132]:
                - heading "Total CO₂e (YTD)" [level=3] [ref=f1e133]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e134]
              - generic [ref=f1e135]:
                - generic [ref=f1e136]: —
                - generic [ref=f1e137]: tCO₂e
            - generic [ref=f1e138]:
              - generic [ref=f1e139]:
                - heading "Carbon Intensity" [level=3] [ref=f1e140]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e141]
              - generic [ref=f1e142]:
                - generic [ref=f1e143]: —
                - generic [ref=f1e144]: g/kWh
            - generic [ref=f1e145]:
              - generic [ref=f1e146]:
                - heading "Renewable Share" [level=3] [ref=f1e147]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e148]
              - generic [ref=f1e149]:
                - generic [ref=f1e150]: —
                - generic [ref=f1e151]: "%"
            - generic [ref=f1e152]:
              - generic [ref=f1e153]:
                - heading "Avg Wholesale Price (YTD)" [level=3] [ref=f1e154]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e155]
              - generic [ref=f1e156]:
                - generic [ref=f1e157]: —
                - generic [ref=f1e158]: $/MWh
            - generic [ref=f1e159]:
              - generic [ref=f1e160]:
                - heading "Data Quality Score" [level=3] [ref=f1e161]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e162]
              - generic [ref=f1e163]:
                - generic [ref=f1e164]: —
                - generic [ref=f1e165]: "%"
            - generic [ref=f1e166]:
              - generic [ref=f1e167]:
                - heading "Open Risks" [level=3] [ref=f1e168]
                - generic "Backend unreachable — showing placeholder, not a live value" [ref=f1e169]
              - generic [ref=f1e170]:
                - generic [ref=f1e171]: —
                - generic [ref=f1e172]: high+
          - generic [ref=f1e175]:
            - generic [ref=f1e176]:
              - generic [ref=f1e177]:
                - heading "Demand Forecast Preview" [level=2] [ref=f1e178]
                - paragraph [ref=f1e179]: P10 / P50 / P90
              - link "View full forecast →" [ref=f1e180] [cursor=pointer]:
                - /url: /dashboard/forecast/
            - paragraph [ref=f1e181]: Loading…
          - generic [ref=f1e184]:
            - generic [ref=f1e185]:
              - generic [ref=f1e186]:
                - heading "Emissions Snapshot" [level=2] [ref=f1e187]
                - paragraph [ref=f1e188]: last 24h · Scope 2 (grid)
              - link "View details →" [ref=f1e189] [cursor=pointer]:
                - /url: /dashboard/carbon/
            - paragraph [ref=f1e190]: Loading…
          - generic [ref=f1e192]:
            - generic [ref=f1e193]:
              - generic [ref=f1e199]:
                - generic [ref=f1e200]:
                  - heading "Emissions Trend" [level=2] [ref=f1e201]
                  - button "More info" [ref=f1e202] [cursor=pointer]
                - paragraph [ref=f1e205]: Rolling 7×24h tCO₂e ending now, actual + real hourly spread + forecast (NEM)
              - generic [ref=f1e206]:
                - generic [ref=f1e208]:
                  - combobox [ref=f1e212]:
                    - option "All Regions" [selected]
                    - option "NSW1"
                    - option "QLD1"
                    - option "VIC1"
                    - option "SA1"
                    - option "TAS1"
                    - option "WEM"
                  - generic: ▾
                - generic [ref=f1e214]:
                  - combobox [ref=f1e217]:
                    - option "Next 24 hours"
                    - option "Next 48 hours" [selected]
                    - option "Next 7 days"
                  - generic: ▾
            - generic [ref=f1e218]:
              - generic [ref=f1e224]: "Last updated: 2 min ago"
              - button "Refresh" [ref=f1e225] [cursor=pointer]
            - generic [ref=f1e226]:
              - generic [ref=f1e227]:
                - generic [ref=f1e228]: Actual
                - generic [ref=f1e230]: P10–P90 (hourly spread)
                - generic [ref=f1e232]: Forecast (P50)
                - generic [ref=f1e234]: Next 48 hours
              - generic [ref=f1e239]:
                - generic [ref=f1e240]: Latest Actual
                - generic [ref=f1e241]:
                  - generic [ref=f1e242]: "14.9"
                  - generic [ref=f1e243]: tCO₂e
                - generic [ref=f1e244]: Today, 14:00
              - generic [ref=f1e250]:
                - generic [ref=f1e251]: Forecast (P50) Avg
                - generic [ref=f1e252]:
                  - generic [ref=f1e253]: "21.6"
                  - generic [ref=f1e254]: tCO₂e
                - generic [ref=f1e255]: Next 48 hours
              - generic [ref=f1e259]:
                - generic [ref=f1e260]: Forecast Range (P10–P90) Avg
                - generic [ref=f1e261]:
                  - generic [ref=f1e262]: 12.1 – 31.0
                  - generic [ref=f1e263]: tCO₂e
                - generic [ref=f1e264]: Next 48 hours
            - img [ref=f1e266]:
              - generic [ref=f1e267]: 28k
              - generic [ref=f1e269]: 21k
              - generic [ref=f1e271]: 14k
              - generic [ref=f1e273]: 7k
              - generic [ref=f1e275]: "0"
              - generic [ref=f1e277]: tCO₂e
              - generic [ref=f1e282]: Now
              - generic [ref=f1e285]: ← Past (Actual)
              - generic [ref=f1e286]: Forecast (next 48h) →
              - generic [ref=f1e287]:
                - generic [ref=f1e288]:
                  - generic [ref=f1e289]: Aug 03
                  - generic [ref=f1e290]: 12:00
                - generic [ref=f1e291]:
                  - generic [ref=f1e292]: Aug 04
                  - generic [ref=f1e293]: 12:00
                - generic [ref=f1e294]:
                  - generic [ref=f1e295]: Aug 05
                  - generic [ref=f1e296]: 12:00
                - generic [ref=f1e297]:
                  - generic [ref=f1e298]: Aug 06
                  - generic [ref=f1e299]: 12:00
                - generic [ref=f1e300]:
                  - generic [ref=f1e301]: Aug 07
                  - generic [ref=f1e302]: 12:00
                - generic [ref=f1e303]:
                  - generic [ref=f1e304]: Aug 08
                  - generic [ref=f1e305]: 12:00
                - generic [ref=f1e306]:
                  - generic [ref=f1e307]: Aug 09
                  - generic [ref=f1e308]: 12:00
                - generic [ref=f1e309]:
                  - generic [ref=f1e310]: Aug 11
                  - generic [ref=f1e311]: 12:00
                - generic [ref=f1e312]:
                  - generic [ref=f1e313]: Aug 12
                  - generic [ref=f1e314]: 12:00
            - generic [ref=f1e315]:
              - generic [ref=f1e321]:
                - generic [ref=f1e322]: Actual (Now)
                - generic "14.9" [ref=f1e323]
                - generic [ref=f1e324]: Today, 14:00
              - generic [ref=f1e330]:
                - generic [ref=f1e331]: Forecast (P50) Avg
                - generic "21.6" [ref=f1e332]
                - generic [ref=f1e333]: Next 48 hours
              - generic [ref=f1e337]:
                - generic [ref=f1e338]: Forecast Range (P10–P90) Avg
                - generic "12.1 – 31.0" [ref=f1e339]
                - generic [ref=f1e340]: Next 48 hours
              - generic [ref=f1e345]:
                - generic [ref=f1e346]: Forecast Period
                - generic "Next 48 hours" [ref=f1e347]
                - generic [ref=f1e348]: Hourly resolution
            - paragraph [ref=f1e349]: tCO₂e = tonnes of carbon dioxide equivalent
          - generic [ref=f1e352]:
            - generic [ref=f1e354]:
              - generic [ref=f1e356]:
                - heading "Emissions Trend (compact)" [level=2] [ref=f1e357]
                - paragraph [ref=f1e358]: 8-day rolling tCO₂e (actual + P10-P90)
              - generic [ref=f1e359]:
                - generic [ref=f1e360]: Actual
                - generic [ref=f1e362]: P10-P90
              - img [ref=f1e365]:
                - generic [ref=f1e366]: 22k
                - generic [ref=f1e368]: 16k
                - generic [ref=f1e370]: 11k
                - generic [ref=f1e372]: 5k
                - generic [ref=f1e374]: 0k
                - generic [ref=f1e378]: 08-03
                - generic [ref=f1e379]: 08-04
                - generic [ref=f1e380]: 08-05
                - generic [ref=f1e381]: 08-06
                - generic [ref=f1e382]: 08-07
                - generic [ref=f1e383]: 08-08
                - generic [ref=f1e384]: 08-09
                - generic [ref=f1e385]: 08-10
            - generic [ref=f1e387]:
              - heading "Emissions by Source" [level=2] [ref=f1e388]
              - generic [ref=f1e390]:
                - generic [ref=f1e400]:
                  - generic [ref=f1e401]: 125,340
                  - generic [ref=f1e402]: tCO₂e
                - list [ref=f1e403]:
                  - listitem [ref=f1e404]:
                    - generic [ref=f1e405]: Grid Electricity (Scope 2)
                    - generic [ref=f1e407]: 58.4%
                  - listitem [ref=f1e408]:
                    - generic [ref=f1e409]: Natural Gas (Scope 1)
                    - generic [ref=f1e411]: 21.6%
                  - listitem [ref=f1e412]:
                    - generic [ref=f1e413]: Diesel (Scope 1)
                    - generic [ref=f1e415]: 8.2%
                  - listitem [ref=f1e416]:
                    - generic [ref=f1e417]: Refrigerants (Scope 1)
                    - generic [ref=f1e419]: 4.1%
                  - listitem [ref=f1e420]:
                    - generic [ref=f1e421]: Supply Chain (Scope 3)
                    - generic [ref=f1e423]: 5.0%
                  - listitem [ref=f1e424]:
                    - generic [ref=f1e425]: Travel (Scope 3)
                    - generic [ref=f1e427]: 2.7%
  - button "Open Next.js Dev Tools" [ref=f1e433] [cursor=pointer]
  - alert [ref=f1e437]
```

# Test source

```ts
  1  | /**
  2  |  * e2e tests for the Executive Dashboard:
  3  |  *  - All 4 charts (Demand Forecast, Emissions Snapshot, Emissions Trend, Emissions by Source)
  4  |  *    show details on hover
  5  |  *  - Donut slices highlight + show tooltip on hover
  6  |  *  - Sparkline / trend chart crosshair + tooltip on hover
  7  |  */
  8  | import { test, expect } from "@playwright/test";
  9  | 
  10 | import { loginAs } from "./_helpers/auth";
  11 | 
  12 | test.beforeEach(async ({ page }) => {
  13 |   await loginAs(page, "diptu");
  14 |   await page.goto("/dashboard/executive/");
  15 |   await expect(page.getByRole("heading", { name: "Executive Dashboard" })).toBeVisible();
  16 | });
  17 | 
  18 | test("executive page renders all chart sections", async ({ page }) => {
  19 |   await expect(page.getByText("Demand Forecast Preview")).toBeVisible();
  20 |   await expect(page.getByText("Emissions Snapshot")).toBeVisible();
> 21 |   await expect(page.getByText("Emissions Trend")).toBeVisible();
     |                                                   ^ Error: expect(locator).toBeVisible() failed
  22 |   await expect(page.getByText("Emissions by Source")).toBeVisible();
  23 | });
  24 | 
  25 | test("forecast sparkline shows hover tooltip", async ({ page }) => {
  26 |   const chart = page.getByTestId("forecast-sparkline");
  27 |   await chart.scrollIntoViewIfNeeded();
  28 |   const box = await chart.boundingBox();
  29 |   expect(box).not.toBeNull();
  30 |   // Use steps to ensure mousemove fires
  31 |   await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.3, { steps: 5 });
  32 |   await page.waitForTimeout(300);
  33 |   await expect(page.getByTestId("forecast-sparkline-tooltip")).toBeVisible();
  34 | });
  35 | 
  36 | test("emissions sparkline shows hover tooltip", async ({ page }) => {
  37 |   const chart = page.getByTestId("emissions-sparkline");
  38 |   await chart.scrollIntoViewIfNeeded();
  39 |   const box = await chart.boundingBox();
  40 |   expect(box).not.toBeNull();
  41 |   await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.3, { steps: 5 });
  42 |   await page.waitForTimeout(300);
  43 |   await expect(page.getByTestId("emissions-sparkline-tooltip")).toBeVisible();
  44 | });
  45 | 
  46 | test("emissions trend chart shows hover tooltip with P10-P90 band", async ({ page }) => {
  47 |   const chart = page.getByTestId("emissions-trend-chart");
  48 |   await chart.scrollIntoViewIfNeeded();
  49 |   const box = await chart.boundingBox();
  50 |   expect(box).not.toBeNull();
  51 |   await page.mouse.move(box!.x + box!.width * 0.5, box!.y + box!.height * 0.4, { steps: 5 });
  52 |   await page.waitForTimeout(300);
  53 |   await expect(page.getByTestId("emissions-trend-tooltip")).toBeVisible();
  54 |   // Tooltip should mention Actual and P10/P90
  55 |   const tooltip = page.getByTestId("emissions-trend-tooltip");
  56 |   await expect(tooltip).toContainText("Actual");
  57 |   await expect(tooltip).toContainText("P10");
  58 |   await expect(tooltip).toContainText("P90");
  59 | });
  60 | 
  61 | test("emissions by source donut shows hover tooltip", async ({ page }) => {
  62 |   // Hover over one of the legend items (which has onMouseEnter handler).
  63 |   // Use a partial match since the testid includes parens like "(Scope 2)".
  64 |   const gridItem = page.locator('[data-testid^="donut-legend-grid"]').first();
  65 |   await gridItem.scrollIntoViewIfNeeded();
  66 |   const box = await gridItem.boundingBox();
  67 |   expect(box).not.toBeNull();
  68 |   await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2, { steps: 5 });
  69 |   await page.waitForTimeout(500);
  70 |   // Tooltip should be visible with the slice data
  71 |   await expect(page.getByTestId("donut-tooltip")).toBeVisible();
  72 |   await expect(page.getByTestId("donut-tooltip")).toContainText("Grid Electricity");
  73 | });
  74 | 
  75 | test("executive page has View full forecast link", async ({ page }) => {
  76 |   const link = page.getByTestId("forecast-preview-link");
  77 |   await expect(link).toBeVisible();
  78 |   await expect(link).toHaveAttribute("href", "/dashboard/forecast/");
  79 | });
  80 | 
  81 | test("executive page has View details link to carbon", async ({ page }) => {
  82 |   const link = page.getByTestId("emissions-preview-link");
  83 |   await expect(link).toBeVisible();
  84 |   await expect(link).toHaveAttribute("href", "/dashboard/carbon/");
  85 | });
  86 | 
  87 | test("executive page shows 6 KPIs", async ({ page }) => {
  88 |   // The 6 KPI cards each have an uppercase label
  89 |   const kpiLabels = ["Total CO₂e (YTD)", "Carbon Intensity", "Renewable Share", "Avg Wholesale Price (YTD)", "Data Quality Score", "Open Risks"];
  90 |   for (const label of kpiLabels) {
  91 |     await expect(page.getByText(label).first()).toBeVisible();
  92 |   }
  93 | });
  94 | 
```