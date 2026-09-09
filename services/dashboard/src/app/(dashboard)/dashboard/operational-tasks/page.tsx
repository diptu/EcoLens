/**
 * /dashboard/operational-tasks — renamed to /data-ingestion.
 *
 * Redirects rather than 404s — same content, just relocated (see
 * `(dashboard)/data-ingestion/page.tsx`), not a removed feature. Same
 * pattern as the /dashboard/executive -> / redirect. Points straight
 * at the current canonical path (not through `/dashboard/data-
 * ingestion`'s own redirect stub) to avoid a double redirect.
 */
import { redirect } from "next/navigation";

export default function OperationalTasksRedirect(): never {
  redirect("/data-ingestion/");
}
