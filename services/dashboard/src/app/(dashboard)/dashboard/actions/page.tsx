/**
 * /dashboard/actions — AI-powered reduction recommendations.
 *
 * Layout:
 *  - Hero
 *  - 5 KPI cards
 *  - AI Recommendations table (sortable)
 *  - Right rail: Actions overview donut + Potential impact + AI Insights + Top categories
 *  - Implementation Roadmap + ROI vs Effort Matrix
 */
import { ArrowRight, Calendar, Sparkles, Zap } from "lucide-react";

import {
  ACTIONS_KPIS,
  ACTION_RECOMMENDATIONS,
  ACTION_CATEGORIES_BREAKDOWN,
  ACTION_OVERVIEW,
  ROADMAP,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart, ProgressBar } from "@/components/dashboard/charts";
import { MotionButton } from "@/components/motion/motion-button";

export const metadata = { title: "Actions — EcoLens" };

const PRIORITY_COLORS = {
  High: "rose",
  Medium: "amber",
  Low: "lime",
} as const;

export default function ActionsPage() {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Actions <span className="ml-1">⚡</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            AI-powered recommendations to reduce emissions, cut costs, and drive real impact.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white">
            <Calendar className="h-3.5 w-3.5" /> This Quarter
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {ACTIONS_KPIS.map((k) => (
          <KpiCard
            key={k.id}
            label={k.label}
            value={k.value}
            unit={"unit" in k ? k.unit : undefined}
            sub={k.sub}
          />
        ))}
      </div>

      {/* AI Recommendations + Right rail */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              AI Recommendations
              <Pill color="emerald">Beta</Pill>
            </span>
          }
          subtitle="Personalized actions based on your data, industry benchmarks, and climate goals."
          actions={
            <div className="flex items-center gap-2 text-xs">
              <span className="text-white/50">Sort by:</span>
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-white/70 hover:text-white">
                Priority ▾
              </button>
              <button className="ml-2 inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-white/70 hover:text-white">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 5h6m-6 2h6M5 8h2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
                Export
              </button>
            </div>
          }
          noPadding
        >
          <div className="flex items-center gap-2 border-b border-white/5 px-5 py-3">
            <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">All Priorities ▾</button>
            <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">All Categories ▾</button>
            <button className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">All Status ▾</button>
            <button className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/80">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h2l1 5h5l1-4H4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              Filter
            </button>
          </div>
          <div className="grid grid-cols-7 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span>Recommendation</span>
            <span className="text-center">Est. Reduction (tCO₂e/yr)</span>
            <span className="text-center">Est. Cost</span>
            <span className="text-center">Difficulty</span>
            <span className="text-center">ROI</span>
            <span className="text-center">Priority</span>
            <span className="text-right">Status</span>
          </div>
          <div className="divide-y divide-white/5">
            {ACTION_RECOMMENDATIONS.map((row) => (
              <div key={row.id} className="grid grid-cols-7 items-center gap-2 px-5 py-4 hover:bg-white/[0.02]">
                <div className="flex items-center gap-3">
                  <span className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-md bg-gradient-to-br from-emerald-400/30 to-sky-400/20">
                    {row.id === 1 ? <Zap className="h-5 w-5 text-emerald-300" /> :
                     row.id === 2 ? <span className="text-xl">🚚</span> :
                     row.id === 3 ? <span className="text-xl">👥</span> :
                     row.id === 4 ? <span className="text-xl">⚡</span> :
                     row.id === 5 ? <span className="text-xl">✈️</span> :
                     <span className="text-xl">♻️</span>}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-white">{row.title}</p>
                    <p className="text-xs text-white/50">{row.body}</p>
                    <Pill color="emerald" className="mt-1.5">{row.category}</Pill>
                  </div>
                </div>
                <p className="text-center text-sm text-white">{row.reduction} <span className="text-xs text-white/40">tCO₂e/yr</span></p>
                <p className="text-center text-sm">
                  <span className="text-emerald-300">{row.cost.split("/")[0]}</span>
                  <span className="text-xs text-white/40">{row.cost.slice(row.cost.indexOf("/"))}</span>
                </p>
                <p className={`text-center text-sm ${row.difficulty === "Low" ? "text-emerald-300" : row.difficulty === "Medium" ? "text-amber-300" : "text-rose-300"}`}>
                  {row.difficulty}
                  <span className="block text-[10px]">
                    {[1, 2, 3, 4].map((i) => (
                      <span key={i} className={i <= (row.difficulty === "Low" ? 1 : row.difficulty === "Medium" ? 2 : 3) ? "text-current" : "text-white/20"}>●</span>
                    ))}
                  </span>
                </p>
                <p className="text-center text-sm font-medium text-white">{row.roi} <span className="text-xs text-white/40">High</span></p>
                <div className="text-center">
                  <Pill color={PRIORITY_COLORS[row.priority as keyof typeof PRIORITY_COLORS]}>
                    {row.priority}
                  </Pill>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <Pill color={row.status === "Recommended" ? "emerald" : row.status === "In Progress" ? "amber" : "gray"}>
                    {row.status}
                  </Pill>
                  <button className="rounded-md border border-emerald-400/30 bg-emerald-400/5 px-2.5 py-1 text-[10px] font-medium text-emerald-300 hover:bg-emerald-400/10">
                    View Details
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-white/50">
            <span>Showing 1 to 6 of {ACTION_RECOMMENDATIONS.length} recommendations</span>
            <div className="flex items-center gap-1">
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">‹</button>
              <button className="grid h-7 w-7 place-items-center rounded border border-lime-300 bg-lime-300 text-black">1</button>
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">2</button>
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">›</button>
            </div>
          </div>
        </Card>

        {/* Right rail */}
        <div className="space-y-5">
          <Card title="Actions Overview">
            <div className="flex flex-col items-center">
              <DonutChart
                data={[
                  { label: "Recommended",  value: ACTION_OVERVIEW.recommended,  color: "rgba(132,204,22,0.95)" },
                  { label: "In Progress",  value: ACTION_OVERVIEW.inProgress,  color: "rgba(56,189,248,0.95)" },
                  { label: "Not Started",  value: ACTION_OVERVIEW.notStarted,  color: "rgba(148,163,184,0.4)" },
                  { label: "Completed",    value: ACTION_OVERVIEW.completed,    color: "rgba(168,85,247,0.95)" },
                ]}
                size={150}
                thickness={18}
                centerLabel={`${ACTION_OVERVIEW.total}`}
                centerSub="Total"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {[
                  { label: "Recommended", value: ACTION_OVERVIEW.recommended, percent: 42, color: "rgba(132,204,22,0.95)" },
                  { label: "In Progress", value: ACTION_OVERVIEW.inProgress, percent: 25, color: "rgba(56,189,248,0.95)" },
                  { label: "Not Started", value: ACTION_OVERVIEW.notStarted, percent: 25, color: "rgba(148,163,184,0.4)" },
                  { label: "Completed",   value: ACTION_OVERVIEW.completed,   percent: 8,  color: "rgba(168,85,247,0.95)" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: row.color }} />
                      <span className="text-white/70">{row.label}</span>
                    </span>
                    <span className="text-white">{row.value} ({row.percent}%)</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card title="Potential Impact" subtitle="If all recommended actions are implemented">
            <div className="space-y-3">
              {[
                { label: "Total Reduction", value: "1,246", unit: "tCO₂e", sub: "Total reduction / year" },
                { label: "Of Total Emissions", value: "31%", sub: null },
                { label: "Cost Savings", value: "$420K", sub: "Annual cost savings" },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between border-b border-white/5 pb-3 last:border-b-0 last:pb-0">
                  <p className="text-xs text-white/50">{row.label}</p>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-white">
                      {row.value}
                      {row.unit && <span className="text-xs text-white/50"> {row.unit}</span>}
                    </p>
                    {row.sub && <p className="text-[10px] text-white/40">{row.sub}</p>}
                  </div>
                </div>
              ))}
              <button className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-400/10">
                View Impact Projection <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </Card>

          <Card title="Top Impact Categories" subtitle="By potential reduction">
            <div className="space-y-3">
              {ACTION_CATEGORIES_BREAKDOWN.map((c) => (
                <div key={c.label}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2 text-white/70">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      {c.label}
                    </span>
                    <span className="text-white">
                      {c.reduction} <span className="text-white/40">tCO₂e ({c.percent}%)</span>
                    </span>
                  </div>
                  <ProgressBar value={c.percent} color="rgba(132,204,22,0.95)" />
                </div>
              ))}
            </div>
            <button className="mt-4 inline-flex items-center gap-1.5 text-xs text-emerald-300 hover:text-emerald-200">
              View all categories <ArrowRight className="h-3 w-3" />
            </button>
          </Card>

          <Card title="AI Insights" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View All Insights →</button>}>
            <div className="space-y-3">
              {[
                "Switching to renewable energy offers the highest impact for your organization.",
                "3 quick-win actions can reduce 270 tCO₂e with minimal investment.",
                "Your industry peers are reducing emissions 18% faster.",
              ].map((t) => (
                <p key={t} className="flex gap-2 text-xs text-white/70">
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300" />
                  {t}
                </p>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Roadmap + Matrix */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card
          title="Implementation Roadmap"
          subtitle="Your action plan timeline"
          actions={
            <button className="text-xs text-emerald-300 hover:text-emerald-200">
              View Full Roadmap →
            </button>
          }
        >
          <div className="grid grid-cols-3 gap-3">
            {ROADMAP.map((phase, i) => (
              <div key={phase.phase} className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-lime-300 text-sm font-bold text-black">{i === 0 ? "3" : i === 1 ? "2" : "2"}</span>
                  <h4 className="text-sm font-semibold text-lime-300">{phase.phase.split(" ")[0]} {phase.phase.split(" ")[1]}</h4>
                </div>
                <p className="mt-1 text-[10px] text-white/50">{phase.phase.match(/\((.*?)\)/)?.[1]}</p>
                <ul className="mt-2 space-y-1">
                  {phase.items.map((item) => (
                    <li key={item} className="flex items-start gap-1.5 text-[11px] text-white/70">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-emerald-400" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="ROI vs Effort Matrix"
          subtitle="Select a recommendation to see details"
          actions={
            <div className="flex items-center gap-3 text-[10px] text-white/50">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-400" /> Low</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-400" /> Medium</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-rose-400" /> High</span>
            </div>
          }
        >
          <div className="relative h-64">
            {/* Axis labels */}
            <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-5 text-[10px] text-white/50">High ROI</span>
            <span className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-4 text-[10px] text-white/50">Low ROI</span>
            <span className="absolute left-0 top-1/2 -translate-x-2 -translate-y-1/2 -rotate-90 text-[10px] text-white/50">Low Effort</span>
            <span className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-7 -rotate-90 text-[10px] text-white/50">High Effort</span>
            {/* Quadrant background */}
            <div className="absolute inset-0 grid grid-cols-2 grid-rows-2">
              <div className="border-r border-b border-white/5" />
              <div className="border-b border-white/5" />
              <div className="border-r border-white/5" />
              <div />
            </div>
            {/* Dots */}
            {[
              { label: "Business Travel",        x: 25, y: 25, color: "bg-emerald-400" },
              { label: "Logistics Optimization", x: 30, y: 30, color: "bg-emerald-400" },
              { label: "Energy Efficiency",      x: 60, y: 25, color: "bg-amber-400" },
              { label: "Renewable Energy",       x: 70, y: 20, color: "bg-rose-400" },
              { label: "Waste & Recycling",      x: 40, y: 70, color: "bg-sky-400" },
              { label: "Supplier Reduction",     x: 75, y: 75, color: "bg-amber-400" },
            ].map((d) => (
              <div
                key={d.label}
                className="absolute flex flex-col items-center"
                style={{ left: `${d.x}%`, top: `${d.y}%`, transform: "translate(-50%, -50%)" }}
              >
                <span className={`h-3 w-3 rounded-full ${d.color}`} />
                <span className="mt-1 whitespace-nowrap text-[9px] text-white/70">{d.label}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Bottom CTA */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <div className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-4">
          <span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-400/15 text-emerald-300">
            <Zap className="h-4 w-4" />
          </span>
          <div>
            <p className="text-sm font-semibold text-white">Small actions today. Big impact tomorrow.</p>
            <p className="text-xs text-white/60">Every action you take brings us closer to a sustainable future.</p>
          </div>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-4">
          <div className="flex-1">
            <p className="text-sm font-semibold text-white">Need help implementing these actions?</p>
            <p className="text-xs text-white/60">Our sustainability experts are here to support you.</p>
          </div>
          <MotionButton size="sm" iconAfter={<ArrowRight className="h-3 w-3" />}>Talk to an Expert</MotionButton>
        </div>
      </div>
    </div>
  );
}
