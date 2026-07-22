/**
 * Dashboard sidebar — persistent left nav with logo, items grouped
 * by section (default / Data & Tools / Settings), a Premium upsell
 * card at the bottom, and the small brand/footer.
 *
 * Sticky on desktop (>= lg), drawer-style overlay on mobile.
 *
 * Active route is detected from `usePathname()` and highlighted
 * with a green border + lime text.
 */
"use client";

import { useState } from "react";
import { AnimatePresence, m } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  Building2,
  Calculator,
  CheckCircle2,
  Cloud,
  Code2,
  Cog,
  CreditCard,
  Database,
  FileText,
  FlaskConical,
  Gauge,
  Home,
  Key,
  Layers,
  Leaf,
  Lightbulb,
  LineChart,
  Menu,
  Plug,
  Search as SearchIcon,
  Settings as SettingsIcon,
  Sparkles,
  Target,
  TrendingUp,
  Users,
  X,
  Zap,
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

const PRIMARY: NavItem[] = [
  { label: "Home",       href: "/dashboard/home",       icon: Home },
  { label: "Overview",   href: "/dashboard/overview",   icon: Gauge },
  { label: "Emissions",  href: "/dashboard/emissions",  icon: Activity },
  { label: "Sources",    href: "/dashboard/sources",    icon: Database },
  { label: "Products",   href: "/dashboard/products",   icon: Layers },
  { label: "Reports",    href: "/dashboard/reports",    icon: FileText },
  { label: "Goals",      href: "/dashboard/goals",      icon: Target },
  { label: "Actions",    href: "/dashboard/actions",    icon: Zap },
  { label: "Scenarios",  href: "/dashboard/scenarios",  icon: FlaskConical },
  { label: "Analytics",  href: "/dashboard/analytics",  icon: BarChart3 },
  { label: "Insights",   href: "/dashboard/insights",   icon: Lightbulb },
];

const DATA_TOOLS: NavItem[] = [
  { label: "Data Sources",  href: "/dashboard/sources",      icon: Database },
  { label: "Integrations",  href: "/dashboard/integrations", icon: Plug },
  { label: "API Access",    href: "/dashboard/api-access",   icon: Code2 },
];

const SETTINGS: NavItem[] = [
  { label: "Organization",  href: "/dashboard/organization", icon: Building2 },
  { label: "Users & Teams", href: "/dashboard/users",        icon: Users },
  { label: "Preferences",   href: "/dashboard/preferences",  icon: SettingsIcon },
  { label: "Billing",       href: "/dashboard/billing",      icon: CreditCard },
  { label: "Notifications", href: "/dashboard/notifications", icon: Bell },
  { label: "Profile",       href: "/dashboard/profile",      icon: Key },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-2 mt-6 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/40">
      {children}
    </p>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-emerald-400/10 text-white"
          : "text-white/70 hover:bg-white/5 hover:text-white",
      )}
    >
      {active && (
        <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r bg-emerald-400" />
      )}
      <Icon
        className={cn(
          "h-4 w-4 transition-colors",
          active ? "text-emerald-300" : "text-white/60 group-hover:text-white",
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
        <SidebarBody pathname={pathname} isActive={isActive} />
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
              <SidebarBody pathname={pathname} isActive={isActive} />
            </m.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}

function SidebarBody({
  pathname,
  isActive,
}: {
  pathname: string;
  isActive: (href: string) => boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2 border-b border-white/5 px-5">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300">
          <Leaf className="h-4 w-4 text-black" />
        </span>
        <span className="text-lg font-bold text-white">EcoLens</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {PRIMARY.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}

        <SectionLabel>Data &amp; Tools</SectionLabel>
        {DATA_TOOLS.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}

        <SectionLabel>Settings</SectionLabel>
        {SETTINGS.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}
      </nav>

      {/* Premium upsell */}
      <div className="m-3 rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-white">
          Go Premium
          <Sparkles className="h-3.5 w-3.5 text-emerald-300" />
        </div>
        <p className="mt-1 text-xs leading-relaxed text-white/60">
          Unlock advanced insights, custom reports &amp; more.
        </p>
        <button
          type="button"
          className="mt-3 w-full rounded-md bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black transition-colors hover:bg-lime-200"
        >
          Upgrade Now
        </button>
      </div>

      {/* Brand footer */}
      <div className="border-t border-white/5 px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300">
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
