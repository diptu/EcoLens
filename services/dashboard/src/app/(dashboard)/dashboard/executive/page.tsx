/**
 * /dashboard/executive — moved to "/".
 *
 * Redirects rather than 404s (unlike the disabled data-sources/
 * ingestion/data-quality routes) — this is the same Executive
 * Dashboard content, just relocated to its new canonical path
 * (`app/(dashboard)/page.tsx`), not a removed feature.
 */
import { redirect } from "next/navigation";

export default function ExecutiveDashboardRedirect(): never {
  redirect("/");
}
