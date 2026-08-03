/**
 * Dashboard topbar — sticky, with breadcrumb (left), global search
 * with ⌘K hint, and notification bell (with badge). Subtle bottom
 * border.
 */
"use client";

import { Bell, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

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
  const [q, setQ] = useState("");

  // ⌘K to focus search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        document.getElementById("dash-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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

        {/* Search */}
        <div className="relative hidden w-72 md:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            id="dash-search"
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search anything…"
            className="w-full rounded-full border border-white/10 bg-white/5 py-1.5 pl-9 pr-12 text-sm text-white placeholder:text-white/40 focus:border-emerald-200/50 focus:outline-none"
          />
          <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-white/50">
            ⌘K
          </kbd>
        </div>

        {/* Notification bell */}
        <Link
          href="/dashboard/system-health"
          className="relative grid h-9 w-9 place-items-center rounded-full border border-white/10 bg-white/5 text-white/70 transition-colors hover:text-white"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
          <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full bg-rose-500 text-[9px] font-bold text-white">
            3
          </span>
        </Link>
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
