/**
 * /dashboard/carbon — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; its
 * real functionality (emissions forecast, generation/fuel mix,
 * per-region emissions) was consolidated into `/analytics-forecast`
 * (see that route's own module docstring), so nothing here was a
 * removed *feature* — just a relocated one. `/dashboard/carbon/
 * methodology` (this page's only linker) is disabled too — see its
 * own page.tsx.
 *
 * The page-local UI this route used to hold has been removed as dead
 * code, along with symbols only it called: `formatIntensity` and
 * `fetchEmissionsTrace`/`EmissionsTrace` (`lib/emissions.ts`).
 * `LineChart` (`components/dashboard/charts.tsx`) is still live —
 * Architecture and Performance both use it. `lib/emissions.ts`'s
 * `fetchEmissionsForecast`/`fetchEmissionsTimeseries`/
 * `fetchGenerationMix`/`formatFuelType`/`formatTco2e`/`fuelColor`/
 * `ALL_EMISSION_REGIONS` are still live — `/analytics-forecast` and
 * `RealEmissionsTrend` call them directly.
 */
import { notFound } from "next/navigation";

export default function CarbonIntelligencePage(): never {
  notFound();
}
