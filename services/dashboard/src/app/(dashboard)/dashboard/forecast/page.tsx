/**
 * /dashboard/forecast — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; its
 * real functionality (demand forecast chart, model performance,
 * actual-vs-predicted backtest) was consolidated into
 * `/analytics-forecast` (see that route's own module docstring), so
 * nothing here was a removed *feature* — just a relocated one. The
 * page-local UI this route used to hold has been removed as dead
 * code, along with symbols only it called: `FanChart`
 * (`components/dashboard/fan-chart.tsx` — `Sparkline` in the same
 * file is still live) and `formatStepLabel` (`lib/forecast.ts`).
 * `lib/emissions.ts`'s `fetchDemandForecast`/`fetchModelInfo`/
 * `fetchRecentBacktest` and `lib/forecast.ts`'s `ALL_REGIONS`/
 * `summarize` are still live — `/analytics-forecast` calls them
 * directly.
 */
import { notFound } from "next/navigation";

export default function ForecastExplorerPage(): never {
  notFound();
}
