/**
 * SectionPage — A reusable layout for section landing pages.
 *
 * Each major section (e.g. Forecasting, Carbon Intelligence, ML) has a
 * landing page that explains what's there and links/tabs to its
 * sub-pages. This is the shared chrome.
 */
"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";

export interface SubRoute {
  id: string;
  label: string;
  description?: string;
  icon?: React.ReactNode;
}

export function SectionPage({
  icon, title, description, tabs, defaultTab, panels, kpis,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  tabs: SubRoute[];
  defaultTab: string;
  panels: Record<string, React.ReactNode>;
  kpis?: Array<{ label: string; value: string; sub?: string }>;
}) {
  const [active, setActive] = useState(defaultTab);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <span className="text-emerald-100">{icon}</span>
          {title}
        </h1>
        <p className="mt-1 text-sm text-white/60">{description}</p>
      </div>

      {kpis && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {kpis.map((k) => (
            <div key={k.label} className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
              <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
              <div className="mt-1.5 text-2xl font-bold text-white">{k.value}</div>
              {k.sub && <p className="mt-1 text-[11px] text-white/50">{k.sub}</p>}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t.id)}
            className={cn(
              "border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
              active === t.id
                ? "border-emerald-200 text-emerald-100"
                : "border-transparent text-white/60 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {panels[active] ?? null}
    </div>
  );
}

export function SubRouteList({ items }: { items: SubRoute[] }) {
  return (
    <Card>
      <ul className="space-y-1.5">
        {items.map((i) => (
          <li key={i.id}>
            <a className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-3 transition-colors hover:border-emerald-200/30 hover:bg-emerald-200/5">
              <div>
                <div className="text-sm font-medium text-white">{i.label}</div>
                <div className="text-[11px] text-white/50">{i.description}</div>
              </div>
              <ChevronRight className="h-4 w-4 text-white/30" />
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
