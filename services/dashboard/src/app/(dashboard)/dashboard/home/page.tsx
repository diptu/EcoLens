/**
 * /dashboard/home — Top-level dashboard / overview.
 *
 * Layout:
 *  - Hero strip (title + subtitle + date range + filters)
 *  - Row of 5 KPI cards
 *  - Two-column: Emissions trends (line) + Emissions by scope (donut)
 *  - Benchmarking + Industry comparison (horizontal bars)
 *  - Reduction opportunity analysis (table)
 *  - Emissions forecast (line + sidebar)
 */
import {
  HOME_KPIS,
  HOME_SCOPES,
  HOME_EMISSIONS_TREND,
  ANALYTICS_OPPORTUNITIES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { LineChart, BarChart, DonutChart } from "@/components/dashboard/charts";
import { LiveForecastCard } from "@/components/dashboard/live-forecast-card";
import {
  ArrowUp,
  Calendar,
  Cloud,
  DollarSign,
  Gauge,
  TrendingUp,
  Wind,
} from "lucide-react";

export const metadata = { title: "Dashboard — EcoLens" };

export default function DashboardHome() {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white md:text-3xl">Overview</h1>
            <span className="text-2xl">📊</span>
          </div>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Track your organization&apos;s emissions, monitor goals, and identify reduction
            opportunities — all in real time.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white">
            <Calendar className="h-3.5 w-3.5" /> May 1 – May 31, 2024
          </button>
          <button className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h8M3 6h6M4 9h4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
            Filters
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {HOME_KPIS.map((k) => (
          <KpiCard
            key={k.id}
            label={k.label}
            value={k.value}
            unit={"unit" in k ? k.unit : undefined}
            sub={"sub" in k ? k.sub : undefined}
            trend={"trend" in k ? k.trend : undefined}
          />
        ))}
      </div>

      {/* Live forecast (ECO-130: the one section here reading real data) */}
      <LiveForecastCard />

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Emissions Trends"
          subtitle="Total tCO₂e over time"
          actions={
            <div className="flex items-center gap-2 text-xs text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-3 bg-lime-300" /> 2024
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-3 border-b border-dashed border-white/50" /> 2023
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-3 border-b border-dotted border-white/30" /> Baseline (2023)
              </span>
            </div>
          }
        >
          <LineChart
            series={[
              { name: "2024", data: HOME_EMISSIONS_TREND.current, color: "rgba(132,204,22,0.95)", fill: true },
              { name: "2023", data: HOME_EMISSIONS_TREND.baseline.map((v) => v - 100), color: "rgba(56,189,248,0.95)", dashed: true },
              { name: "Baseline", data: HOME_EMISSIONS_TREND.baseline, color: "rgba(255,255,255,0.4)", dashed: true },
            ]}
            labels={HOME_EMISSIONS_TREND.labels}
            height={260}
          />
        </Card>

        <Card title="Emissions by Scope" subtitle="Current month breakdown">
          <div className="flex flex-col items-center gap-4">
            <DonutChart
              data={HOME_SCOPES.map((s) => ({ label: s.label, value: s.value, color: s.color }))}
              size={170}
              thickness={20}
              centerLabel="2,453"
              centerSub="tCO₂e"
            />
            <div className="w-full space-y-1.5">
              {HOME_SCOPES.map((s) => (
                <div key={s.label} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="text-white/70">{s.label}</span>
                  </span>
                  <span className="text-white">
                    {s.percent}% <span className="text-white/40">({s.value.toLocaleString()})</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Benchmarking + Industry */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card
          title="Benchmarking"
          subtitle="vs Industry Average"
          actions={
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
              vs Industry Average ▾
            </button>
          }
        >
          <div className="space-y-4">
            <div>
              <p className="text-xs text-white/50">Your Emissions Intensity</p>
              <p className="mt-1 text-2xl font-bold text-white">0.42 <span className="text-sm text-white/50">tCO₂e / $K</span></p>
              <p className="mt-0.5 text-[11px] text-emerald-400">↓ 12% vs industry average</p>
            </div>
            <div className="space-y-2.5">
              {[
                { label: "You",                value: 0.42, color: "rgba(132,204,22,0.95)" },
                { label: "Industry Average",   value: 0.48, color: "rgba(148,163,184,0.6)" },
                { label: "Top Performers",     value: 0.23, color: "rgba(148,163,184,0.3)" },
              ].map((row) => (
                <div key={row.label}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-white/70">{row.label}</span>
                    <span className="text-white">{row.value}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${(row.value / 1) * 100}%`, backgroundColor: row.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card
          title="Industry Comparison"
          subtitle="By Emissions Intensity (tCO₂e / $K Revenue)"
          actions={
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
              By Emissions Intensity ▾
            </button>
          }
        >
          <div className="flex h-44 items-end gap-2">
            {[
              { label: "You",           value: 0.42, highlight: true },
              { label: "Construction",  value: 0.73 },
              { label: "Manufacturing", value: 0.58 },
              { label: "Energy",        value: 0.24 },
              { label: "Technology",    value: 0.91 },
              { label: "Services",      value: 0.36 },
            ].map((row) => (
              <div key={row.label} className="flex flex-1 flex-col items-center gap-2">
                <span className="text-[10px] text-white/60">{row.value}</span>
                <div
                  className={`w-full rounded-t ${row.highlight ? "bg-lime-300" : "bg-white/20"}`}
                  style={{ height: `${(row.value / 1) * 100}%` }}
                />
                <span className={`text-[10px] ${row.highlight ? "text-lime-300" : "text-white/50"}`}>
                  {row.label}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Reduction opportunities */}
      <Card
        title="Reduction Opportunity Analysis"
        subtitle="Top opportunities ranked by ROI"
        actions={
          <div className="flex items-center gap-2">
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
              This Year ▾
            </button>
          </div>
        }
        noPadding
      >
        <DataTable
          rows={ANALYTICS_OPPORTUNITIES}
          columns={[
            {
              key: "name",
              header: "Opportunity",
              render: (row) => <NameCell icon={<Wind className="h-4 w-4 text-emerald-300" />} name={row.name} />,
            },
            {
              key: "reduction",
              header: "Potential Reduction (tCO₂e/yr)",
              render: (row) => (
                <div>
                  <p className="text-sm text-white">{row.reduction}</p>
                  <div className="mt-1 h-1 w-24 overflow-hidden rounded-full bg-white/5">
                    <div className="h-full rounded-full bg-emerald-400" style={{ width: `${row.percent * 4}%` }} />
                  </div>
                </div>
              ),
            },
            {
              key: "cost",
              header: "Cost Impact",
              render: (row) => <span className="text-sm text-white">{row.cost}</span>,
            },
            {
              key: "effort",
              header: "Effort",
              render: (row) => <span className="text-sm text-white">{row.effort}</span>,
            },
            {
              key: "roi",
              header: "ROI (5Y)",
              render: (row) => <span className="text-sm font-medium text-emerald-300">{row.roi}</span>,
            },
            {
              key: "priority",
              header: "Priority",
              render: (row) => (
                <Pill color={row.priority === "High" ? "rose" : row.priority === "Medium" ? "amber" : "lime"}>
                  {row.priority}
                </Pill>
              ),
            },
            { key: "actions", header: "", align: "right", render: () => <ActionsMenu />, className: "w-10" },
          ]}
        />
      </Card>
    </div>
  );
}
