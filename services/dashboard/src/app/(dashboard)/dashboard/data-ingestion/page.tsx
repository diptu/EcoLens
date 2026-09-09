/**
 * /dashboard/data-ingestion — moved to "/data-ingestion".
 *
 * Redirects rather than 404s — this is the same Data Ingestion
 * content, just relocated to its new canonical path
 * (`app/(dashboard)/data-ingestion/page.tsx`), not a removed feature.
 * Same pattern `/dashboard/executive`'s and `/dashboard/analytics-
 * forecast`'s own redirect stubs already established.
 */
import { redirect } from "next/navigation";

export default function DataIngestionRedirect(): never {
  redirect("/data-ingestion/");
}
