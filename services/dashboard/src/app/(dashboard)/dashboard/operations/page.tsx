/**
 * /dashboard/operations — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore; the
 * Ops Manager UI this page used to hold (Ingestion Pipelines panel,
 * Service Health / Service Components tabs) has been removed as dead
 * code. `lib/health.ts`'s `fetchAllServicesHealth` is still live — the
 * Data Ingestion and System Health pages use it directly.
 * `lib/data-sources.ts` (`fetchPublicDataSources`/`healthDotStatus`)
 * was this page's only caller and has been removed entirely — nothing
 * in the app calls ingestion's `GET /v1/data-sources` catalog anymore.
 */
import { notFound } from "next/navigation";

export default function OperationsDashboardPage(): never {
  notFound();
}
