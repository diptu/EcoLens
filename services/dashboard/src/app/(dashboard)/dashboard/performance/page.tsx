/**
 * /dashboard/performance — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; the
 * model-performance UI this page used to hold (drift, loss curve,
 * evaluation history, feature-rebuild runs) has been removed as dead
 * code, along with the functions/types only it called
 * (`fetchDrift`/`DriftReport`, `fetchLossCurve`/`LossCurve`,
 * `fetchModelEvaluationHistory`/`EvaluationHistory` in
 * `lib/emissions.ts`, and `fetchFeatureRebuildRuns`/
 * `FeatureRebuildRun`/`FeatureRebuildRunsList` in `lib/ingestion.ts`).
 * `lib/emissions.ts`'s `fetchModelEvaluation`/`fetchModelVersions`/
 * `fetchRecentBacktest`, `lib/ingestion.ts`'s `fetchTrainingRuns`/
 * `formatRelativeTime`, `lib/data-quality.ts`'s
 * `fetchPublicDataQualitySummary`, `components/dashboard/charts.tsx`'s
 * `BarChart`/`LineChart`, `components/dashboard/gauge.tsx`'s
 * `ArcGauge`, and `components/dashboard/illustrative-badge.tsx`'s
 * `IllustrativeBadge` are all still live — Analytics & Forecast, the
 * Executive Dashboard, Training, Data Ingestion, and Reports use them
 * directly.
 */
import { notFound } from "next/navigation";

export default function PerformancePage(): never {
  notFound();
}
