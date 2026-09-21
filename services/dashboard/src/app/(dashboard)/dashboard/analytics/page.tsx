/**
 * /dashboard/analytics — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; its
 * real functionality (generation mix, emissions trend, weather
 * correlation, key insights) was consolidated into
 * `/analytics-forecast` (see that route's own module docstring), so
 * nothing here was a removed *feature* — just a relocated one.
 *
 * The page-local UI this route used to hold has been removed as dead
 * code. Every `lib/emissions.ts` symbol it imported
 * (`fetchGenerationMix`/`fetchDemandSummary`/`fetchEmissionsTimeseries`/
 * `fetchEmissionsForecast`/`formatFuelType`/`fuelColor`/`formatEnergy`/
 * `ALL_EMISSION_REGIONS`) and `RealEmissionsTrend`/`DonutChart`/
 * `Sparkline`/`formatRelativeTime` are all still live — `/analytics-
 * forecast` and other still-active pages call them directly.
 */
import { notFound } from "next/navigation";

export default function EnergyAnalyticsPage(): never {
  notFound();
}
