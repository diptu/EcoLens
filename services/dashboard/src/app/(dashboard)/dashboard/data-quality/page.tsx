/**
 * /dashboard/data-quality — disabled.
 *
 * Route intentionally 404s. Not linked from the sidebar or from the
 * Executive Dashboard anymore; the anomaly-log UI this page used to
 * hold (filters, master-detail table, overview/behavior charts,
 * acknowledge/resolve/false-positive mutations) has been removed as
 * dead code. `lib/anomalies.ts`'s `fetchAnomalies`/`Anomaly`/
 * `AnomalySeverity` are still live — the Executive Dashboard's Recent
 * Alerts panel uses them directly.
 */
import { notFound } from "next/navigation";

export default function AdminAnomalyDetectionPage(): never {
  notFound();
}
