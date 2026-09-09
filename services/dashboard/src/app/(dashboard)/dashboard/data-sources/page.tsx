/**
 * /dashboard/data-sources — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar or from
 * Operations anymore (that page is disabled too — see its own
 * page.tsx); the per-source management UI this page used to hold
 * (category filter, refresh/backfill triggers, cron cheat sheet) has
 * been removed as dead code. `lib/data-sources.ts` (`fetchPublicDataSources`/
 * `healthDotStatus`, the Operations page's only caller) has been
 * deleted entirely — nothing in the app calls ingestion's
 * `GET /v1/data-sources` catalog anymore.
 */
import { notFound } from "next/navigation";

export default function DataSourcesPage(): never {
  notFound();
}
