/**
 * Dashboard topbar — sticky, with breadcrumb (left). Subtle bottom
 * border.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface Crumb {
  label: string;
  href?: string;
}

function buildCrumbs(pathname: string): Crumb[] {
  const path = pathname.replace(/^\/+/, "").replace(/\/+$/, "");
  if (!path) return [];
  const segments = path.split("/");
  // Always start with "Home" -> /dashboard
  const crumbs: Crumb[] = [{ label: "Home", href: "/dashboard/executive" }];
  if (segments[0] === "dashboard") {
    if (segments[1]) {
      crumbs.push({ label: "Dashboard", href: "/dashboard/executive" });
      const label = segments[1]
        .replace(/-/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
      crumbs.push({ label });
    }
  } else {
    segments.forEach((seg, i) => {
      const isLast = i === segments.length - 1;
      crumbs.push({
        label: seg.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        href: isLast ? undefined : "/" + segments.slice(0, i + 1).join("/"),
      });
    });
  }
  return crumbs;
}

export function Topbar() {
  const pathname = usePathname() ?? "";
  const crumbs = buildCrumbs(pathname);

  return (
    <header className="sticky top-0 z-20 border-b border-white/5 bg-[#050a08]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-4 px-4 md:px-6">
        {/* Breadcrumb (desktop) */}
        <nav className="hidden flex-1 items-center gap-1.5 text-sm text-white/60 md:flex">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {c.href ? (
                <Link href={c.href} className="hover:text-white">{c.label}</Link>
              ) : (
                <span className="text-white">{c.label}</span>
              )}
              {i < crumbs.length - 1 && <Chevron />}
            </span>
          ))}
        </nav>

        {/* Spacer (mobile) */}
        <div className="flex-1 md:hidden" />
      </div>
    </header>
  );
}

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="text-white/30">
      <path d="M3 2L7 5L3 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
