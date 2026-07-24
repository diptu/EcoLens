/**
 * /dashboard/sources — Data sources list with health, sync info.
 */
import { Calendar, Plus, Search, Server, Settings2 } from "lucide-react";

import {
  SOURCES_KPIS,
  DATA_SOURCES,
  SOURCE_HEALTH,
  SOURCES_BY_TYPE,
  SOURCE_BREAKDOWN,
  SOURCE_ALERTS,
  POPULAR_INTEGRATIONS,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, StatusDot, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart, ProgressBar } from "@/components/dashboard/charts";

export const metadata = { title: "Data Sources — EcoLens" };

const SOURCE_ICON: Record<string, string> = {
  Cloud:        "☁️",
  Finance:      "💳",
  Logistics:    "🚛",
  Energy:       "⚡",
  Waste:        "🗑️",
  Utilities:    "💧",
  SaaS:         "📦",
  "Supply Chain": "🔗",
  Manual:       "📥",
  ERP:          "🏢",
};

const STATUS_COLORS = {
  Active: "green",
  Inactive: "gray",
  Syncing: "amber",
} as const;

const FRESHNESS_COLORS = (v: number) => v >= 95 ? "emerald" : v >= 90 ? "lime" : v >= 80 ? "amber" : v === 0 ? "gray" : "rose";

export default function SourcesPage() {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Data Sources <span className="ml-1">🌱</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Connect, manage, and monitor the data sources<br />that power your carbon intelligence.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70">
            <option>All Sources</option>
          </select>
          <button className="inline-flex items-center gap-1.5 rounded-full bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200">
            <Plus className="h-3.5 w-3.5" /> Add New Source
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {SOURCES_KPIS.map((k) => (
          <KpiCard key={k.id} label={k.label} value={k.value} unit={"unit" in k ? k.unit : undefined} sub={k.sub} />
        ))}
      </div>

      {/* All Sources + Right rail */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="All Data Sources"
          actions={
            <button className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 7v3M6 5v5M9 3v7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
              Export
            </button>
          }
          noPadding
        >
          <div className="flex items-center gap-2 border-b border-white/5 px-5 py-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input type="text" placeholder="Search sources…" className="w-full rounded-md border border-white/10 bg-white/5 py-1.5 pl-9 pr-3 text-xs text-white placeholder:text-white/40 focus:border-emerald-400/50 focus:outline-none" />
            </div>
            <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">All Status ▾</button>
            <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">All Types ▾</button>
            <button className="ml-auto rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h2l1 5h5l1-4H4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          </div>
          <div className="grid grid-cols-7 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span className="col-span-2">Source Name</span>
            <span>Type</span>
            <span>Status</span>
            <span>Last Sync</span>
            <span className="text-right">Data Points</span>
            <span className="text-right">Emissions (tCO₂e)</span>
            <span className="text-right">Actions</span>
          </div>
          <div className="divide-y divide-white/5">
            {DATA_SOURCES.map((row) => (
              <div key={row.id} className="grid grid-cols-7 items-center gap-2 px-5 py-3 hover:bg-white/[0.02]">
                <NameCell
                  icon={<span className="text-base">{SOURCE_ICON[row.type] ?? "📊"}</span>}
                  name={row.name}
                  sub={row.sub}
                />
                <Pill color={row.type === "Cloud" ? "sky" : row.type === "Energy" ? "emerald" : row.type === "Finance" ? "purple" : row.type === "Logistics" ? "lime" : "gray"}>{row.type}</Pill>
                <StatusDot color={STATUS_COLORS[row.status as keyof typeof STATUS_COLORS]} label={row.status} />
                <span className="text-xs text-white/60 flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> {row.lastSync}
                </span>
                <span className="text-right text-xs text-white">{row.dataPoints.toLocaleString()}</span>
                <span className="text-right text-xs text-white">
                  {row.emissions > 0 ? row.emissions.toFixed(2) : "—"}
                  {row.emissions > 0 && <span className="ml-1 text-lime-300">📈</span>}
                </span>
                <div className="text-right"><ActionsMenu /></div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-white/50">
            <span>Showing 1 to {DATA_SOURCES.length} of {DATA_SOURCES.length} sources</span>
            <div className="flex items-center gap-1">
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">‹</button>
              <button className="grid h-7 w-7 place-items-center rounded border border-lime-300 bg-lime-300 text-black">1</button>
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">›</button>
            </div>
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Overall Health" actions={
            <button className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/70 hover:text-white">All Sources ▾</button>
          }>
            <div className="flex flex-col items-center">
              <DonutChart
                data={[
                  { label: "Healthy",  value: SOURCE_HEALTH.healthy,  color: "rgba(132,204,22,0.95)" },
                  { label: "Syncing",  value: SOURCE_HEALTH.syncing,  color: "rgba(56,189,248,0.95)" },
                  { label: "Inactive", value: SOURCE_HEALTH.inactive, color: "rgba(148,163,184,0.4)" },
                ]}
                size={140}
                thickness={16}
                centerLabel={`${SOURCE_HEALTH.percent}%`}
                centerSub="Healthy"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-lime-400" />Healthy</span><span className="text-white">{SOURCE_HEALTH.healthy}</span></div>
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-sky-400" />Syncing</span><span className="text-white">{SOURCE_HEALTH.syncing}</span></div>
                <div className="flex items-center justify-between"><span className="flex items-center gap-2 text-white/70"><span className="h-2 w-2 rounded-full bg-white/30" />Inactive</span><span className="text-white">{SOURCE_HEALTH.inactive}</span></div>
              </div>
            </div>
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View all alerts →</button>
          </Card>

          <Card title="Sources by Type" subtitle="By count">
            <div className="flex flex-col items-center">
              <DonutChart
                data={SOURCES_BY_TYPE.map((s) => ({ label: s.label, value: s.value, color: s.color }))}
                size={150}
                thickness={18}
                centerLabel={`${SOURCES_BY_TYPE.reduce((s, t) => s + t.value, 0)}`}
                centerSub="Total"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {SOURCES_BY_TYPE.map((s) => (
                  <div key={s.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-white/70">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />{s.label}
                    </span>
                    <span className="text-white">{s.value} ({s.percent}%)</span>
                  </div>
                ))}
              </div>
            </div>
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View detailed breakdown →</button>
          </Card>

          <Card title="Recent Alerts" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}>
            <div className="space-y-3">
              {SOURCE_ALERTS.map((a) => (
                <div key={a.id} className="flex items-start gap-2 text-xs">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    a.type.includes("failed") ? "bg-rose-400" :
                    a.type.includes("delayed") ? "bg-amber-400" : "bg-emerald-400"
                  }`} />
                  <div>
                    <p className="font-medium text-white">{a.name}</p>
                    <p className="text-[10px] text-white/50">{a.type} · {a.time}</p>
                  </div>
                </div>
              ))}
            </div>
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View all alerts →</button>
          </Card>
        </div>
      </div>

      {/* Emissions by source + trend */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Emissions by Source (tCO₂e)" subtitle="Current month" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Month</option>
          </select>
        }>
          <div className="flex items-center gap-4">
            <DonutChart
              data={SOURCE_BREAKDOWN.map((s) => ({ label: s.label, value: s.value, color: ["rgba(132,204,22,0.95)", "rgba(56,189,248,0.95)", "rgba(168,85,247,0.95)", "rgba(245,158,11,0.95)", "rgba(244,63,94,0.95)", "rgba(148,163,184,0.6)"][SOURCE_BREAKDOWN.indexOf(s) % 6] }))}
              size={170}
              thickness={20}
              centerLabel="2,453"
              centerSub="tCO₂e"
            />
            <div className="flex-1 space-y-2 text-xs">
              {SOURCE_BREAKDOWN.map((s, i) => (
                <div key={s.label} className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-white/70">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: ["rgba(132,204,22,0.95)", "rgba(56,189,248,0.95)", "rgba(168,85,247,0.95)", "rgba(245,158,11,0.95)", "rgba(244,63,94,0.95)", "rgba(148,163,184,0.6)"][i] }} />
                    {s.label}
                  </span>
                  <span className="text-white">{s.value.toFixed(2)} ({s.percent}%)</span>
                </div>
              ))}
            </div>
          </div>
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View full report →</button>
        </Card>

        <Card title="Emissions Trend by Top Sources" subtitle="Daily" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Month</option>
          </select>
        }>
          <div className="flex items-center gap-3 text-[10px] text-white/50">
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-lime-300" /> Fleet GPS Data</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-sky-300" /> AWS CloudTrail</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-purple-300" /> Electricity Usage</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-amber-300" /> Stripe Payments</span>
          </div>
          {/* SVG inline line chart for emissions trend */}
          <svg viewBox="0 0 800 200" preserveAspectRatio="none" className="mt-3 h-44 w-full">
            {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
              <line key={i} x1="40" x2="800" y1={10 + p * 170} y2={10 + p * 170} stroke="rgba(255,255,255,0.05)" />
            ))}
            {["Jul 1", "Jul 7", "Jul 13", "Jul 19", "Jul 25", "Jul 31"].map((l, i) => (
              <text key={i} x={40 + i * 152} y="195" fontSize="9" fill="rgba(255,255,255,0.4)" textAnchor="middle">{l}</text>
            ))}
            <polyline points="40,80 120,70 200,75 280,60 360,55 440,65 520,50 600,55 680,45 760,40" fill="none" stroke="rgba(132,204,22,0.9)" strokeWidth="1.6" />
            <polyline points="40,140 120,135 200,140 280,130 360,125 440,135 520,120 600,130 680,120 760,115" fill="none" stroke="rgba(56,189,248,0.9)" strokeWidth="1.6" />
            <polyline points="40,160 120,165 200,158 280,162 360,155 440,160 520,150 600,155 680,148 760,150" fill="none" stroke="rgba(168,85,247,0.9)" strokeWidth="1.6" />
            <polyline points="40,180 120,178 200,182 280,176 360,180 440,175 520,178 600,170 680,175 760,172" fill="none" stroke="rgba(245,158,11,0.9)" strokeWidth="1.6" />
          </svg>
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View analytics →</button>
        </Card>
      </div>

      {/* Popular Integrations + Add New Source */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Popular Integrations"
          subtitle="Connect your favorite tools and platforms"
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all integrations →</button>}
        >
          <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
            {POPULAR_INTEGRATIONS.map((i) => (
              <div key={i.id} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-center transition-colors hover:border-emerald-400/30">
                <div
                  className="mx-auto grid h-12 w-12 place-items-center rounded-xl text-lg font-bold text-white"
                  style={{ backgroundColor: i.color }}
                >
                  {i.name[0]}
                </div>
                <p className="mt-2 text-sm font-semibold text-white">{i.name}</p>
                <p className="text-[10px] text-white/50">{i.sub}</p>
                <button className="mt-2 inline-flex items-center gap-1 rounded-md bg-lime-300/15 px-3 py-1 text-[10px] font-medium text-lime-300 hover:bg-lime-300/25">
                  Connect
                </button>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Add New Source" subtitle="Connect a new data source to start tracking">
          <div className="flex h-48 flex-col items-center justify-center rounded-xl border-2 border-dashed border-white/10 p-6 text-center">
            <Server className="mb-2 h-8 w-8 text-white/30" />
            <p className="text-sm font-semibold text-white">Choose a connector or drag and drop</p>
            <p className="text-xs text-white/50 mt-1">Supported formats: CSV, JSON, API</p>
            <button className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200">
              <Settings2 className="h-3.5 w-3.5" /> Browse Connectors
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}
