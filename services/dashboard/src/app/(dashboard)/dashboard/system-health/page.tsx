/**
 * /dashboard/system-health — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar anymore. No
 * dead code left behind — everything this page imported
 * (`lib/health.ts`'s `fetchAllServicesHealth`/`ServiceHealth`) is
 * still live, called directly by the Data Ingestion page's own
 * service-health panel.
 */
import { notFound } from "next/navigation";

export default function SystemHealthPage(): never {
  notFound();
}
