/**
 * /dashboard/analytics-forecast — moved to "/analytics-forecast".
 *
 * Redirects rather than 404s (unlike the disabled data-sources/
 * ingestion/data-quality routes) — this is the same Analytics &
 * Forecast content, just relocated to its new canonical path
 * (`app/(dashboard)/analytics-forecast/page.tsx`), not a removed
 * feature. Same pattern `/dashboard/executive`'s own redirect stub
 * already established for the Executive Dashboard's move to "/".
 */
import { redirect } from "next/navigation";

export default function AnalyticsForecastRedirect(): never {
  redirect("/analytics-forecast");
}
