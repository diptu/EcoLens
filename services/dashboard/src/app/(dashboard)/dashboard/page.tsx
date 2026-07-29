/**
 * /dashboard — default landing route.
 *
 * Redirects to the Executive Dashboard (the platform's primary view).
 */
import { redirect } from "next/navigation";

export default function DashboardIndexPage() {
  redirect("/dashboard/executive/");
}
