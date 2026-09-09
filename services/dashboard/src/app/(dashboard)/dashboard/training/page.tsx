/**
 * /dashboard/training — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; the
 * model registry/experiments UI this page used to hold (MLflow
 * experiments/runs, per-architecture version list) has been removed
 * as dead code, along with the functions/types only it called
 * (`fetchMlflowExperiments`/`MlflowExperiment`,
 * `fetchMlflowRuns`/`MlflowRun`, and `MODEL_ARCHITECTURES` in
 * `lib/emissions.ts`). `lib/emissions.ts`'s `fetchModelVersions`/
 * `ModelVersion`/`fetchModelInfo`/`ModelInfo` and `lib/ingestion.ts`'s
 * `fetchTrainingRuns`/`TrainingRunLog`/`formatRelativeTime` are all
 * still live — Analytics & Forecast and Data Ingestion use them
 * directly.
 */
import { notFound } from "next/navigation";

export default function TrainingPage(): never {
  notFound();
}
