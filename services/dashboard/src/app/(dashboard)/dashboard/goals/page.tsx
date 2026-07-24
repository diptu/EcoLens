/**
 * /dashboard/goals — SBTi tracker + your goals list.
 *
 * Layout:
 *  - Hero + New Goal button
 *  - 5 KPIs
 *  - 2-col: Overall Goal Progress (donut + chart) | Targets by Type
 *  - 2-col: Your Goals (table) | Right rail (Upcoming Deadlines + Milestones)
 *  - 2-col: SBTi Alignment | Projected vs Target | Impact Summary
 */
import { Calendar, Plus, Sparkles, Target } from "lucide-react";

import {
  GOALS_KPIS,
  GOAL_ROADMAP_DATA,
  YOUR_GOALS,
  GOAL_TYPES,
  UPCOMING_DEADLINES,
  MILESTONES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart, LineChart, ProgressBar } from "@/components/dashboard/charts";

export const metadata = { title: "Goals — EcoLens" };

const STATUS_COLORS = {
  "On Track": "lime",
  "At Risk": "amber",
  "Behind": "rose",
  "Completed": "emerald",
} as const;

export default function GoalsPage() {
  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Goals <span className="ml-1">🎯</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Set, track, and achieve your sustainability goals.<br />
            Drive real impact with measurable progress.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:text-white">
            <Calendar className="h-3.5 w-3.5" /> This Year
          </button>
          <button className="inline-flex items-center gap-2 rounded-full bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200">
            <Plus className="h-3.5 w-3.5" /> New Goal
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {GOALS_KPIS.map((k) => (
          <KpiCard
            key={k.id}
            label={k.label}
            value={k.value}
            unit={"unit" in k ? k.unit : undefined}
            sub={k.sub}
          />
        ))}
      </div>

      {/* Overall progress + Targets by type */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Overall Goal Progress"
          actions={
            <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
              <option>All Goals</option>
            </select>
          }
        >
          <div className="flex items-center gap-6">
            <div className="relative grid place-items-center">
              <DonutChart
                data={[
                  { label: "Progress", value: 58, color: "rgba(132,204,22,0.95)" },
                ]}
                size={140}
                thickness={14}
                centerLabel="58%"
                centerSub="Progress"
              />
            </div>
            <div className="flex items-center gap-1.5 rounded-md border border-emerald-400/20 bg-emerald-400/5 px-2.5 py-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <p className="text-xs font-medium text-white">On Track</p>
            </div>
            <p className="text-xs text-white/50">You&apos;re on track to meet your 2030 target.</p>
          </div>

          <div className="mt-4 flex items-center justify-end gap-3 text-[10px] text-white/50">
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-lime-300" /> Actual Emissions</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 border-b border-dashed border-white/50" /> Target Pathway</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 border-b border-dotted border-white/30" /> Baseline</span>
          </div>
          <div className="relative">
            <LineChart
              series={[
                { name: "Actual",  data: GOAL_ROADMAP_DATA.actual,  color: "rgba(132,204,22,0.95)", fill: true },
                { name: "Target",  data: GOAL_ROADMAP_DATA.target,  color: "rgba(255,255,255,0.7)", dashed: true },
                { name: "Baseline", data: GOAL_ROADMAP_DATA.baseline, color: "rgba(255,255,255,0.3)", dashed: true },
              ]}
              labels={GOAL_ROADMAP_DATA.labels}
              height={200}
              yMax={3200}
            />
            <div className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2">
              <p className="text-[10px] text-white/50">2030 Target</p>
              <p className="text-xs font-semibold text-white">Net Zero</p>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-4 gap-3 border-t border-white/5 pt-3 text-xs">
            {[
              { label: "Baseline (2023)", value: "2,976", unit: "tCO₂e" },
              { label: "Current (2025)",  value: "1,730", unit: "tCO₂e" },
              { label: "2030 Target",     value: "0",     unit: "tCO₂e" },
              { label: "Reduction Needed", value: "1,730", unit: "tCO₂e" },
            ].map((row) => (
              <div key={row.label} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                <p className="text-[10px] text-white/50">{row.label}</p>
                <p className="mt-0.5 text-lg font-bold text-white">{row.value} <span className="text-[10px] text-white/50">{row.unit}</span></p>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Targets by Type" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">Manage →</button>}>
          <div className="flex flex-col items-center">
            <DonutChart
              data={GOAL_TYPES.map((t) => ({ label: t.label, value: t.value, color: t.color }))}
              size={160}
              thickness={20}
              centerLabel={`${GOAL_TYPES.reduce((s, t) => s + t.value, 0)}`}
              centerSub="Total"
            />
            <div className="mt-4 w-full space-y-1.5 text-xs">
              {GOAL_TYPES.map((t) => (
                <div key={t.label} className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: t.color }} />
                    <span className="text-white/70">{t.label}</span>
                  </span>
                  <span className="text-white">{t.value} ({t.percent}%)</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Your Goals + Right rail */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Your Goals"
          actions={
            <div className="flex items-center gap-2">
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
                All Status ▾
              </button>
              <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2 3h2l1 5h5l1-4H4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </div>
          }
          noPadding
        >
          <div className="grid grid-cols-6 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span className="col-span-2">Goal</span>
            <span>Type</span>
            <span>Target</span>
            <span>Progress</span>
            <span>Status / Deadline</span>
          </div>
          <div className="divide-y divide-white/5">
            {YOUR_GOALS.map((row) => (
              <div key={row.id} className="grid grid-cols-6 items-center gap-3 px-5 py-3.5 hover:bg-white/[0.02]">
                <div className="col-span-2 flex items-center gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-emerald-400/20 bg-emerald-400/5 text-emerald-300">
                    <Target className="h-4 w-4" />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-white">{row.name}</p>
                    <p className="text-xs text-white/50">{row.sub}</p>
                  </div>
                </div>
                <Pill color={row.type === "SBTi" ? "lime" : "purple"}>{row.type}</Pill>
                <p className="text-sm text-white">{row.target}</p>
                <div>
                  <p className="text-sm text-white">{row.progress}%</p>
                  <div className="mt-1 h-1 w-24 overflow-hidden rounded-full bg-white/5">
                    <div
                      className={`h-full rounded-full ${row.status === "On Track" ? "bg-emerald-400" : row.status === "At Risk" ? "bg-amber-400" : "bg-rose-400"}`}
                      style={{ width: `${row.progress}%` }}
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <Pill color={STATUS_COLORS[row.status as keyof typeof STATUS_COLORS]}>{row.status}</Pill>
                  <span className="text-xs text-white/60">{row.deadline}</span>
                  <ActionsMenu />
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-white/50">
            <span>Showing 1 to 6 of {YOUR_GOALS.length} goals</span>
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Upcoming Deadlines" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}>
            <div className="space-y-3">
              {UPCOMING_DEADLINES.map((d) => (
                <div key={d.id} className="flex items-start gap-3 rounded-md border border-white/5 bg-white/[0.02] p-3">
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
                    <Target className="h-4 w-4" />
                  </span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">{d.name}</p>
                    <p className="text-[10px] text-white/50">{d.date}</p>
                  </div>
                  <Pill color="amber" className="shrink-0">In {d.daysLeft} days</Pill>
                </div>
              ))}
            </div>
            <button className="mt-4 inline-flex items-center gap-1.5 text-xs text-emerald-300 hover:text-emerald-200">
              <Calendar className="h-3.5 w-3.5" /> View calendar
            </button>
          </Card>

          <Card title="Milestone Tracking" actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all →</button>}>
            <ol className="relative space-y-4 border-l border-white/10 pl-4">
              {MILESTONES.map((m, i) => (
                <li key={m.id} className="relative">
                  <span className={`absolute -left-[19px] grid h-4 w-4 place-items-center rounded-full ring-2 ring-[#0a1410] ${
                    m.status === "Completed" ? "bg-emerald-400" :
                    m.status === "On Track" ? "bg-emerald-400" :
                    "bg-white/20"
                  }`}>
                    {m.status === "Completed" && <span className="text-[8px] font-bold text-black">✓</span>}
                  </span>
                  <p className="text-sm font-medium text-white">{m.name}</p>
                  <p className="text-xs text-white/50">{m.date}</p>
                  <Pill color={m.status === "Completed" ? "emerald" : m.status === "On Track" ? "lime" : "gray"} className="mt-1">{m.status}</Pill>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>

      {/* SBTi + Projected + Impact */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card title="SBTi Alignment" subtitle="Science Based Targets initiative" actions={<Pill color="emerald">Verified</Pill>}>
          <div className="mb-3 flex items-center gap-3 rounded-md border border-emerald-400/20 bg-emerald-400/5 p-3">
            <span className="grid h-9 w-9 place-items-center rounded-full border border-emerald-400/30 bg-emerald-400/10 text-emerald-300 text-[10px] font-bold">SBTi</span>
            <p className="text-xs text-white/80">Your targets are aligned with the Science Based Targets initiative.</p>
          </div>
          <div className="space-y-1">
            {[
              { label: "1.5°C-aligned",            value: "Yes" },
              { label: "Absolute reduction targets", value: "Yes" },
              { label: "Scope 1, 2 & 3 coverage",   value: "Yes" },
              { label: "Regular target review",     value: "Yes" },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between border-b border-white/5 py-2 text-xs last:border-b-0">
                <span className="text-white/70">{row.label}</span>
                <Pill color="lime">{row.value}</Pill>
              </div>
            ))}
          </div>
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View SBTi Summary →</button>
        </Card>

        <Card title="Projected vs Target" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <p className="text-xs text-white/50">You&apos;re projected to</p>
          <p className="text-lg font-bold text-lime-300">meet your targets.</p>
          <p className="text-xs text-white/50">Continue your efforts to stay on track.</p>
          <div className="mt-3 flex items-center justify-end gap-3 text-[10px] text-white/50">
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 border-b border-dashed border-white/50" /> Projected</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-white/40" /> Target</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 bg-lime-300" /> Actual</span>
          </div>
          <LineChart
            series={[
              { name: "Projected", data: [2976, 2700, 2450, 2200, 1900, 1500, 1100, 700, 0], color: "rgba(255,255,255,0.5)", dashed: true },
              { name: "Target",    data: [2976, 2650, 2350, 2050, 1750, 1450, 1150, 850, 0], color: "rgba(132,204,22,0.95)" },
              { name: "Actual",    data: [2976, 2730, 2453, 2453, 2453, 2453, 2453, 2453, 2453], color: "rgba(132,204,22,0.5)", fill: true },
            ]}
            labels={["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030", ""]}
            height={150}
            yMax={3200}
          />
        </Card>

        <Card title="Impact Summary" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <div className="space-y-3">
            {[
              { value: "1,246", unit: "tCO₂e", sub: "Emissions reduced to date", color: "rgba(132,204,22,0.95)", icon: "🌱" },
              { value: "312,000", sub: "Trees equivalent planted", color: "rgba(16,185,129,0.95)", icon: "🌳" },
              { value: "$420K", sub: "Cost savings achieved", color: "rgba(132,204,22,0.95)", icon: "💰" },
              { value: "12%", sub: "Progress vs last year", color: "rgba(132,204,22,0.95)", icon: "📈" },
            ].map((row) => (
              <div key={row.sub} className="flex items-center gap-3 border-b border-white/5 pb-3 last:border-b-0 last:pb-0">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-emerald-400/10 text-base">{row.icon}</span>
                <div className="flex-1">
                  <p className="text-lg font-bold text-white">
                    {row.value}
                    {row.unit && <span className="text-xs text-white/50"> {row.unit}</span>}
                  </p>
                  <p className="text-[10px] text-white/50">{row.sub}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Did you know banner */}
      <div className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-white">Did you know?</p>
          <p className="text-xs text-white/60">Companies with strong climate goals are 3x more likely to see improved financial performance.</p>
        </div>
        <button className="text-xs text-emerald-300 hover:text-emerald-200">Learn more →</button>
      </div>
    </div>
  );
}
