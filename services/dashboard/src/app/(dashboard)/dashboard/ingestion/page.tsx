/**
 * /dashboard/ingestion — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar or from
 * Data Ingestion anymore; the pipeline-management UI this page used
 * to hold (trigger/poll runs, failed jobs, retry queue, scheduler
 * status) has been removed as dead code. `lib/ingestion.ts`'s
 * `PIPELINE_CATALOG`/`triggerIngestionRun`/`pollLatestRun`/
 * `fetchPublicRuns`/`formatRelativeTime`/`formatTimeUntil`/
 * `TriggerIngestionError` are still live — the Data Ingestion page
 * uses them directly.
 */
import { notFound } from "next/navigation";

export default function DataIngestionPage(): never {
  notFound();
}
