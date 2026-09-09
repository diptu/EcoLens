/**
 * /dashboard/architecture — moved to "/architecture".
 *
 * Redirects rather than 404s — "Architecture" is a real concept in
 * this app again (a different, more specific page than what used to
 * live here — see `(dashboard)/architecture/page.tsx`'s own module
 * docstring for the full history), so this old path shouldn't dead-end
 * bookmarks/links. Same pattern `/dashboard/executive`'s and
 * `/dashboard/analytics-forecast`'s own redirect stubs already
 * established.
 */
import { redirect } from "next/navigation";

export default function DashboardArchitectureRedirect(): never {
  redirect("/architecture/");
}
