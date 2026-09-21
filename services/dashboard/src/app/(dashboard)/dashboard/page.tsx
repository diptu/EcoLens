/**
 * /dashboard — default landing route.
 *
 * Redirects to the Executive Dashboard (the platform's primary view),
 * now canonically at "/".
 */
import { redirect } from "next/navigation";

export default function DashboardIndexPage(): never {
  redirect("/");
}
