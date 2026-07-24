/**
 * /dashboard/scenarios — Scenario modeling with comparison & templates.
 */
import { ChevronDown, Filter, FlaskConical, Plus } from "lucide-react";

import {
  SCENARIOS_KPIS,
  SCENARIOS_LIST,
  SCENARIO_TEMPLATES,
  SCENARIO_REDUCTION_BREAKDOWN,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { LineChart, DonutChart } from "@/components/dashboard/charts";

export const metadata = { title: "Scenarios — EcoLens" };

const CATEGORY_COLORS: Record<string, "emerald" | "sky" | "purple" | "amber" | "rose" | "lime"> = {
  Energy:      "emerald",
  Logistics:   "sky",
  "Supply Chain": "purple",
  Operations:  "amber",
  Travel:      "rose",
  Overall:     "lime",
};

const STATUS_COLORS = {
  Projected:    "emerald",
  "In Progress": "sky",
  Completed:    "lime",
  Draft:        "gray",
} as const;

export default function ScenariosPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Scenarios <span className="ml-1">🧪</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Model different actions, compare outcomes,<br />and make data-driven sustainability decisions.
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-md bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200">
          <Plus className="h-3.5 w-3.5" /> New Scenario <ChevronDown className="h-3 w-3" />
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {SCENARIOS_KPIS.map((k) => (
          <KpiCard key={k.id} label={k.label} value={k.value} unit={"unit" in k ? k.unit : undefined} sub={k.sub} />
        ))}
      </div>

      {/* Create scenario + Selected scenario impact */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Create a New Scenario"
          subtitle="Simulate changes to see their potential impact on your emissions."
          actions={
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">Use Templates</button>
          }
        >
          <div className="mb-4 flex items-center gap-2">
            {[
              { step: 1, label: "Select Category",   sub: "Choose what to change" },
              { step: 2, label: "Define Change",     sub: "Set the percentage or value" },
              { step: 3, label: "Set Timeframe",     sub: "Choose duration" },
              { step: 4, label: "Run Simulation",    sub: "See the estimated impact" },
            ].map((s) => (
              <div key={s.step} className="flex flex-1 items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-lime-300 text-xs font-bold text-black">{s.step}</div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-white">{s.label}</p>
                  <p className="truncate text-[10px] text-white/50">{s.sub}</p>
                </div>
                {s.step < 4 && <span className="text-white/30">→</span>}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              { label: "I want to", value: "Reduce", type: "select" },
              { label: "Category", value: "Electricity Consumption", type: "select" },
            ].map((row) => (
              <div key={row.label}>
                <p className="text-xs text-white/50">{row.label}</p>
                <p className="mt-1 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white">{row.value} <span className="float-right text-white/40">▾</span></p>
              </div>
            ))}
            <div className="flex items-center gap-2">
              <p className="text-xs text-white/50">By</p>
              <p className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white w-20 text-center">50</p>
              <p className="text-xs text-white/50">%</p>
              <p className="ml-2 text-xs text-white/50">switching to</p>
              <p className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white flex-1">Renewable Energy <span className="float-right text-white/40">▾</span></p>
            </div>
            <div className="flex items-center gap-2">
              <p className="text-xs text-white/50">Over</p>
              <p className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white w-32 text-center">12 Months <span className="float-right text-white/40">▾</span></p>
              <button className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-lime-300 px-4 py-2 text-xs font-semibold text-black hover:bg-lime-200">
                ▶ Run Scenario
              </button>
            </div>
          </div>
        </Card>

        <div className="space-y-5">
          <Card
            title="Selected Scenario Impact"
            actions={<Pill color="sky">Projected</Pill>}
          >
            <p className="text-sm font-semibold text-white">Switch 50% Electricity to Renewable Energy</p>
            <p className="mt-2 text-3xl font-bold text-white">1,226 <span className="text-base text-white/50">tCO₂e</span></p>
            <p className="mt-0.5 text-xs text-emerald-400">↓ Total reduction (50%)</p>
            <div className="mt-4 space-y-3">
              {[
                { label: "Cost Impact",           value: "One-time: $80,000", sub: "Annual: $40,000" },
                { label: "ROI (5 Years)",         value: "2.8x", sub: "Good" },
                { label: "Payback Period",        value: "2.3 years" },
                { label: "Implementation Difficulty", value: "Medium" },
              ].map((row, i) => (
                <div key={row.label} className="flex items-center justify-between border-b border-white/5 pb-2 text-xs last:border-b-0 last:pb-0">
                  <div className="flex items-center gap-2 text-white/60">
                    <span className="grid h-6 w-6 place-items-center rounded-full bg-emerald-400/10 text-emerald-300 text-[10px]">
                      {i === 0 ? "💰" : i === 1 ? "📈" : i === 2 ? "⏱️" : "🛠️"}
                    </span>
                    {row.label}
                  </div>
                  <p className="text-white">
                    {row.value}
                    {row.sub && <span className="block text-[10px] text-white/40">{row.sub}</span>}
                  </p>
                </div>
              ))}
              <div className="flex items-center gap-1.5 pt-2">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                <span className="h-1.5 w-1.5 rounded-full bg-white/20" />
              </div>
            </div>
            <button className="mt-4 inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10">
              View Full Results →
            </button>
          </Card>

          <Card title="Reduction Breakdown" subtitle="By emission scope">
            <div className="flex flex-col items-center">
              <DonutChart
                data={SCENARIO_REDUCTION_BREAKDOWN.map((s) => ({ label: s.label, value: s.value, color: s.color }))}
                size={150}
                thickness={18}
                centerLabel="1,226"
                centerSub="tCO₂e"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {SCENARIO_REDUCTION_BREAKDOWN.map((s) => (
                  <div key={s.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-white/70">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                      {s.label}
                    </span>
                    <span className="text-white">{s.value} <span className="text-white/40">({s.percent}%)</span></span>
                  </div>
                ))}
              </div>
            </div>
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View Detailed Breakdown →</button>
          </Card>

          <Card title="Key Assumptions" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">Edit</button>}>
            <div className="space-y-2">
              {[
                "Renewable energy sourced from solar and wind",
                "Grid emission factor will decrease by 5% annually",
                "Energy demand remains constant",
                "No change to other emission sources",
                "Market prices remain stable",
              ].map((t) => (
                <p key={t} className="flex items-start gap-2 text-xs text-white/70">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" /> {t}
                </p>
              ))}
            </div>
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View All Assumptions →</button>
          </Card>
        </div>
      </div>

      {/* Your Scenarios */}
      <Card
        title="Your Scenarios"
        actions={
          <div className="flex items-center gap-2">
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">All Status ▾</button>
            <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
              <Filter className="h-3 w-3" />
            </button>
          </div>
        }
        noPadding
      >
        <div className="grid grid-cols-7 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
          <span className="col-span-2">Scenario Name</span>
          <span>Category</span>
          <span className="text-center">Change</span>
          <span className="text-center">Reduction</span>
          <span className="text-center">Cost</span>
          <span className="text-right">ROI / Status / Actions</span>
        </div>
        <div className="divide-y divide-white/5">
          {SCENARIOS_LIST.map((row) => (
            <div key={row.id} className="grid grid-cols-7 items-center gap-2 px-5 py-3 hover:bg-white/[0.02]">
              <NameCell
                icon={<FlaskConical className="h-4 w-4 text-emerald-300" />}
                name={row.name}
              />
              <Pill color={CATEGORY_COLORS[row.category as keyof typeof CATEGORY_COLORS] || "emerald"}>{row.category}</Pill>
              <p className="text-center text-sm text-white">{row.change}</p>
              <p className="text-center text-sm">
                <span className="text-white">{row.reduction.toLocaleString()}</span>
                <span className="block text-[10px] text-white/40">tCO₂e ({Math.round((row.reduction / 2453) * 100)}%)</span>
              </p>
              <p className="text-center text-sm">
                <span className="text-white">{row.cost}</span>
                <span className="block text-[10px] text-white/40">{row.roi}/yr</span>
              </p>
              <div className="flex items-center justify-end gap-2">
                <span className="text-sm font-medium text-emerald-300">{row.roi}</span>
                <Pill color={STATUS_COLORS[row.status as keyof typeof STATUS_COLORS]}>{row.status}</Pill>
                <span className="text-[10px] text-white/50">{row.updated}</span>
                <ActionsMenu />
              </div>
            </div>
          ))}
        </div>
        <div className="border-t border-white/5 px-5 py-3 text-xs text-white/50">Showing 1 to {SCENARIOS_LIST.length} of {SCENARIOS_LIST.length} scenarios</div>
      </Card>

      {/* Compare Scenarios + Scenario Metrics */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Compare Scenarios" subtitle="Compare up to 4 scenarios with the baseline." actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>Select Scenarios (4)</option>
          </select>
        }>
          <LineChart
            series={[
              { name: "Baseline (2023)",         data: [2453, 2400, 2300, 2200, 2050, 1900, 1750, 1500], color: "rgba(255,255,255,0.4)", dashed: true },
              { name: "Switch 50% Electricity",  data: [2453, 2100, 1750, 1450, 1200, 1000, 800, 600], color: "rgba(132,204,22,0.95)" },
              { name: "Reduce Transportation 20%", data: [2453, 2300, 2100, 1900, 1700, 1550, 1350, 1200], color: "rgba(56,189,248,0.95)", dashed: true },
              { name: "Optimize Supply Chain 15%", data: [2453, 2350, 2200, 2050, 1900, 1750, 1600, 1450], color: "rgba(168,85,247,0.95)", dashed: true },
              { name: "Net Zero Pathway 2030",   data: [2453, 1900, 1400, 950, 600, 300, 100, 0], color: "rgba(244,63,94,0.95)" },
            ]}
            labels={["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"]}
            height={220}
          />
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View Full Comparison →</button>
        </Card>

        <Card title="Scenario Metrics" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <div className="space-y-3">
            {[
              { label: "Total Potential Reduction", value: "2,658", unit: "tCO₂e", sub: "Across selected scenarios" },
              { label: "Total Cost Impact",         value: "$2.1M", sub: "One-time: $1.3M, Annual: $800K" },
              { label: "Average ROI (5 Years)",     value: "2.9x", sub: "Across selected scenarios" },
              { label: "Average Payback Period",    value: "2.7 years", sub: "Across selected scenarios" },
            ].map((row) => (
              <div key={row.label} className="rounded-md border border-white/5 bg-white/[0.02] p-3">
                <p className="text-[10px] text-white/50">{row.label}</p>
                <p className="mt-1 text-2xl font-bold text-lime-300">
                  {row.value}
                  {row.unit && <span className="text-xs text-white/50"> {row.unit}</span>}
                </p>
                <p className="text-[10px] text-white/40">{row.sub}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Popular Scenario Templates */}
      <Card
        title="Popular Scenario Templates"
        subtitle="Use pre-built templates to get started quickly."
        actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all templates →</button>}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {SCENARIO_TEMPLATES.map((t) => (
            <div key={t.id} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-colors hover:border-emerald-400/30">
              <span className="grid h-9 w-9 place-items-center rounded-md bg-emerald-400/15 text-emerald-300">
                {t.id === 1 ? "⚡" : t.id === 2 ? "🚛" : t.id === 3 ? "🔗" : t.id === 4 ? "🏢" : "🌿"}
              </span>
              <p className="mt-2 text-sm font-semibold text-white">{t.name}</p>
              <p className="mt-1 text-[10px] text-white/60">{t.sub}</p>
              <button className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-[10px] font-medium text-emerald-300 hover:bg-emerald-400/10">
                {t.cta} →
              </button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
