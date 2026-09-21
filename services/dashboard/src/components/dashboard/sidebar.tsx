/**
 * Dashboard sidebar — persistent left nav with logo, a flat list of
 * nav items, and the small brand/footer.
 *
 * Sticky on desktop (>= lg), drawer-style overlay on mobile.
 *
 * Active route is detected from `usePathname()` and highlighted
 * with a green border + lime text.
 *
 * Nav structure mirrors the ecoLens page taxonomy (Settings & Users
 * and Reports still exist as pages, just aren't linked from the
 * sidebar nav; Data Sources, Ingestion Pipeline, Data Quality &
 * Anomalies, the Operations Dashboard, the Model Registry, Forecast
 * Explorer, Carbon Intelligence, Energy Analytics, Carbon
 * Intelligence's own Methodology subpage, Performance, System Health,
 * and Model Training & Experiments are disabled entirely — see those
 * routes' own page.tsx. Forecast Explorer/Carbon Intelligence/Energy
 * Analytics' real functionality (demand forecast, emissions/generation
 * mix, weather correlation) was consolidated into Analytics &
 * Forecast; Performance/System Health/Training's own real data (model
 * eval/backtest, service health, MLflow experiments) is still live via
 * other still-active pages — none of these disablings was a removed
 * feature so much as a removed dedicated page for it. Architecture
 * (2026-09-09) is back with new, different content — a rendering of
 * `docs/architecture/model-architecture.md`'s real end-to-end model
 * flow, not the old tabbed pipeline-overview page it replaces):
 *   1. Overview (Executive Dashboard) /                              — executives
 *   2. Analytics & Forecast           /analytics-forecast            — analysts (combines
 *                                       Forecast Explorer/Carbon Intelligence/Energy Analytics)
 *   3. Data Ingestion                 /data-ingestion                — platform eng
 *   4. Model Architecture             /architecture                  — all users (about)
 *   5. Engineering Blog               /blog                          — all users (marketing/engineering write-ups)
 */
"use client";

import { useState } from "react";
import { AnimatePresence, m } from "framer-motion";
import {
  Gauge, LayoutDashboard, Leaf, Menu,
  Newspaper, Workflow, X, Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  active?: boolean;
}

/**
 * Primary nav — the live dashboard pages (auth handled outside
 * sidebar). Flat list, in the same order the page taxonomy above
 * lists them.
 */
const NAV_ITEMS: NavItem[] = [
  { label: "Overview",               href: "/",                             icon: Gauge },
  { label: "Analytics & Forecast",   href: "/analytics-forecast",           icon: LayoutDashboard },
  { label: "Data Ingestion",         href: "/data-ingestion",              icon: Zap },
  { label: "Model Architecture",     href: "/architecture",                icon: Workflow },
  { label: "Engineering Blog",       href: "/blog",                        icon: Newspaper },
];

function NavLink({ item, active, accent }: { item: NavItem; active: boolean; accent?: "emerald" }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? accent === "emerald"
            ? "bg-emerald-200/10 text-white ring-1 ring-emerald-200/20"
            : "bg-emerald-200/10 text-white"
          : accent === "emerald"
            ? "text-emerald-100/80 hover:bg-emerald-200/5 hover:text-emerald-100"
            : "text-white/70 hover:bg-white/5 hover:text-white",
      )}
    >
      {active && (
        <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r bg-emerald-200" />
      )}
      <Icon
        className={cn(
          "h-4 w-4 transition-colors",
          active ? "text-emerald-100" : "text-white/60 group-hover:text-white",
        )}
      />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/") || pathname === href.replace(/\/$/, "");

  return (
    <>
      {/* Mobile toggle (rendered in Topbar) */}
      <MobileToggle onOpen={() => setOpen(true)} />

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-white/5 bg-[#050a08] lg:flex">
        <SidebarBody isActive={isActive} />
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {open && (
          <>
            <m.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 z-40 bg-black/60 lg:hidden"
              onClick={() => setOpen(false)}
            />
            <m.aside
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className="fixed inset-y-0 left-0 z-50 w-64 border-r border-white/5 bg-[#050a08] lg:hidden"
            >
              <div className="absolute right-3 top-3">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="grid h-9 w-9 place-items-center rounded-full border border-white/10 bg-white/5 text-white/70 hover:text-white"
                  aria-label="Close menu"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <SidebarBody isActive={isActive} />
            </m.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

function SidebarBody({
  isActive,
}: {
  isActive: (href: string) => boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2 border-b border-white/5 px-5">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-emerald-200 to-lime-100">
          <Leaf className="h-4 w-4 text-black" />
        </span>
        <span className="text-lg font-bold text-white">EcoLens</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            active={isActive(item.href)}
          />
        ))}
      </nav>

      {/* Brand footer */}
      <div className="border-t border-white/5 px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-gradient-to-br from-emerald-200 to-lime-100">
            <Leaf className="h-3.5 w-3.5 text-black" />
          </span>
          <span className="text-sm font-semibold text-white">EcoLens</span>
        </div>
        <p className="mt-1 text-[10px] text-white/40">
          © 2025 EcoLens<br />All rights reserved.
        </p>
      </div>
    </div>
  );
}

function MobileToggle({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="fixed left-4 top-4 z-30 grid h-10 w-10 place-items-center rounded-full border border-white/10 bg-white/5 text-white lg:hidden"
      aria-label="Open menu"
    >
      <Menu className="h-4 w-4" />
    </button>
  );
}

