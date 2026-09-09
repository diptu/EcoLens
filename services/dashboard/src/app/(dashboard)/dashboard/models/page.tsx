/**
 * /dashboard/models — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar or from the
 * Performance/Data Ingestion pages anymore; the model registry/train/
 * fine-tune/import UI this page used to hold has been removed as dead
 * code, along with the functions/types only it called
 * (`promoteModelVersion`/`deleteModelVersion`/`importModelBundle`/
 * `importOnnxBundle`/`ModelImportResult` in `lib/emissions.ts`,
 * `pollForTrainingRun`/`TrainingRunMatch` in `lib/ingestion.ts`, and
 * the unused `RadarChart` in `components/dashboard/charts.tsx`).
 * `lib/emissions.ts`'s `fetchModelVersions`/`ModelVersion` and
 * `fetchLossCurve`/`LossCurve`/`fetchModelEvaluation`/
 * `fetchModelEvaluationHistory` are still live — the Training,
 * Data Ingestion, and Performance pages use them directly.
 */
import { notFound } from "next/navigation";

export default function ModelRegistryPage(): never {
  notFound();
}
