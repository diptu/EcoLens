/**
 * /dashboard/reports — Reports list with type cards, recent reports
 * table, and report summary charts.
 */
import { ChevronDown, FileText, Plus } from "lucide-react";

import {
  REPORTS_KPIS,
  REPORT_TYPES,
  RECENT_REPORTS,
  REPORT_FRAMEWORK_BREAKDOWN,
  REPORT_METRICS_POPULARITY,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { DataTable, Pill, NameCell, ActionsMenu } from "@/components/dashboard/data-table";
import { DonutChart, BarChart } from "@/components/dashboard/charts";

export const metadata = { title: "Reports — EcoLens" };

const TYPE_ICON: Record<string, string> = {
  ghg:   "🌿",
  scope: "📊",
  esg:   "🌍",
  cdp:   "📋",
  tcfd:  "💼",
  csrd:  "🌱",
  custom:"🛠️",
  audit: "🔒",
};

const FRAMEWORK_COLORS: Record<string, string> = {
  ESG:           "rgba(16,185,129,0.95)",
  "GHG Protocol": "rgba(132,204,22,0.95)",
  "Scope 1/2/3":  "rgba(56,189,248,0.95)",
  CDP:           "rgba(244,63,94,0.95)",
  TCFD:          "rgba(168,85,247,0.95)",
  CSRD:          "rgba(245,158,11,0.95)",
  Custom:        "rgba(148,163,184,0.6)",
  "Audit Package":"rgba(245,158,11,0.95)",
};

export default function ReportsPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Reports <span className="ml-1">📄</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Generate, manage, and export sustainability reports with confidence.<br />Compliant. Transparent. Audit-ready.
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-md bg-lime-300 px-3 py-1.5 text-xs font-semibold text-black hover:bg-lime-200">
          <Plus className="h-3.5 w-3.5" /> New Report <ChevronDown className="h-3 w-3" />
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {REPORTS_KPIS.map((k) => (
          <KpiCard key={k.id} label={k.label} value={k.value} sub={k.sub} />
        ))}
      </div>

      {/* Report Types + Summary */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Report Types"
          subtitle="Choose a report framework or create a custom report tailored to your needs."
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all frameworks →</button>}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-2">
            {REPORT_TYPES.map((t) => (
              <div key={t.id} className="rounded-xl border border-white/5 bg-white/[0.02] p-4 transition-colors hover:border-emerald-400/30">
                <div className="flex items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-emerald-400/10 text-lg">{TYPE_ICON[t.id]}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-white">{t.name}</p>
                    <p className="mt-1 text-xs text-white/60">{t.sub}</p>
                    <button className="mt-2 inline-flex items-center gap-1 rounded-md border border-emerald-400/30 bg-emerald-400/5 px-3 py-1 text-[10px] font-medium text-emerald-300 hover:bg-emerald-400/10">
                      {t.cta} →
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-5">
          <Card title="Report Summary" actions={
            <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
              <option>This Year</option>
            </select>
          }>
            <div className="flex flex-col items-center">
              <DonutChart
                data={REPORT_FRAMEWORK_BREAKDOWN.map((f) => ({ label: f.label, value: f.value, color: f.color }))}
                size={160}
                thickness={20}
                centerLabel={`${REPORT_FRAMEWORK_BREAKDOWN.reduce((s, f) => s + f.value, 0)}`}
                centerSub="Total"
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {REPORT_FRAMEWORK_BREAKDOWN.map((f) => (
                  <div key={f.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-white/70">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: f.color }} />
                      {f.label}
                    </span>
                    <span className="text-white">{f.value} ({f.percent}%)</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card title="Export formats" subtitle="All reports can be exported in multiple formats for your convenience.">
            <div className="space-y-2.5">
              {[
                { label: "Export as PDF",  icon: "📄", color: "rgba(244,63,94,0.95)" },
                { label: "Export as CSV",  icon: "📊", color: "rgba(132,204,22,0.95)" },
                { label: "Export as Excel", icon: "📈", color: "rgba(16,185,129,0.95)" },
              ].map((row) => (
                <button
                  key={row.label}
                  className="flex w-full items-center gap-3 rounded-md border border-white/5 bg-white/[0.02] p-2.5 text-left transition-colors hover:bg-white/5"
                >
                  <span className="grid h-8 w-8 place-items-center rounded-md text-base" style={{ backgroundColor: row.color + "20" }}>{row.icon}</span>
                  <span className="flex-1 text-sm text-white">{row.label}</span>
                  <span className="text-emerald-300">→</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* Recent Reports + Audit Trail */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Recent Reports"
          actions={<button className="text-xs text-emerald-300 hover:text-emerald-200">View all reports →</button>}
          noPadding
        >
          <div className="grid grid-cols-6 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span className="col-span-2">Report Name</span>
            <span>Framework</span>
            <span>Period</span>
            <span>Generated On</span>
            <span className="text-right">Status / Size / Actions</span>
          </div>
          <div className="divide-y divide-white/5">
            {RECENT_REPORTS.map((row) => (
              <div key={row.id} className="grid grid-cols-6 items-center gap-3 px-5 py-3 hover:bg-white/[0.02]">
                <NameCell icon={<FileText className="h-4 w-4 text-emerald-300" />} name={row.name} sub={row.sub} />
                <Pill color="lime">{row.framework}</Pill>
                <div>
                  <p className="text-sm text-white">{row.period}</p>
                  <p className="text-[10px] text-white/50">Jan - Dec 2023</p>
                </div>
                <div>
                  <p className="text-sm text-white">{row.generated.split(" ")[0]}</p>
                  <p className="text-[10px] text-white/50">{row.generated.split(" ").slice(1).join(" ")}</p>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <Pill color="emerald">✓ Completed</Pill>
                  <span className="text-xs text-white/70">{row.size}</span>
                  <button className="rounded-md border border-rose-400/30 bg-rose-400/5 p-1 text-rose-300 hover:bg-rose-400/10">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 2h6M4 2V1h4v1M5 4v6M7 4v6M2 2h8l-1 8H3L2 2z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>
                  <button className="rounded-md border border-emerald-400/30 bg-emerald-400/5 p-1 text-emerald-300 hover:bg-emerald-400/10">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 6h6M3 8h6M3 4h6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg>
                  </button>
                  <ActionsMenu />
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-white/5 px-5 py-3 text-xs text-white/50">
            <span>Showing 1 to 8 of 28 reports</span>
            <div className="flex items-center gap-1">
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">‹</button>
              {["1", "2", "3", "4"].map((p) => (
                <button key={p} className={`grid h-7 w-7 place-items-center rounded border ${p === "1" ? "border-lime-300 bg-lime-300 text-black" : "border-white/10 bg-white/5 text-white/60"}`}>{p}</button>
              ))}
              <button className="grid h-7 w-7 place-items-center rounded border border-white/10 bg-white/5 text-white/60 hover:text-white">›</button>
            </div>
          </div>
        </Card>

        <Card title="Audit Trail" subtitle="All report activities are tracked for transparency and compliance.">
          <div className="space-y-4">
            {RECENT_REPORTS.slice(0, 3).map((r) => (
              <div key={r.id} className="flex items-start gap-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald-400/10 text-emerald-300">📄</span>
                <div>
                  <p className="text-sm font-semibold text-white">{r.name}</p>
                  <p className="text-[10px] text-white/50">{r.framework === "ESG" ? "Generated by Diptu Alam" : r.framework === "GHG Protocol" ? "Downloaded by Diptu Alam" : "Exported as PDF by Diptu Alam"}</p>
                  <p className="text-[10px] text-white/40">{r.generated}</p>
                </div>
              </div>
            ))}
          </div>
          <button className="mt-4 text-xs text-emerald-300 hover:text-emerald-200">View full audit log →</button>
        </Card>
      </div>

      {/* Reports Over Time + Popular Metrics */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Reports Over Time" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <BarChart
            data={[5, 7, 5, 7, 6, 4, 2, 3, 1, 2, 1, 3]}
            labels={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
            height={200}
            color="rgba(132,204,22,0.95)"
          />
          <div className="mt-2 flex items-center gap-2 text-[10px] text-white/50">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-lime-300" /> Reports Generated</span>
          </div>
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View analytics →</button>
        </Card>

        <Card title="Popular Metrics in Reports" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>This Year</option>
          </select>
        }>
          <div className="space-y-3">
            {REPORT_METRICS_POPULARITY.map((m) => (
              <div key={m.label} className="flex items-center gap-3">
                <span className="text-base">🌿</span>
                <p className="flex-1 text-xs text-white/70">{m.label}</p>
                <div className="h-1.5 w-32 overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full bg-lime-300" style={{ width: `${(m.value / 28) * 100}%` }} />
                </div>
                <span className="w-8 text-right text-sm font-medium text-white">{m.value}</span>
              </div>
            ))}
          </div>
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View all metrics →</button>
        </Card>
      </div>

      {/* Need a custom report? */}
      <div className="flex items-center gap-3 rounded-xl border border-white/5 bg-white/[0.02] p-4">
        <span className="grid h-12 w-12 place-items-center rounded-full bg-emerald-400/15 text-2xl">🌿</span>
        <div className="flex-1">
          <p className="text-sm font-semibold text-white">Need a custom report?</p>
          <p className="text-xs text-white/60">Our experts can help you build a report tailored to your business and compliance needs.</p>
        </div>
        <button className="inline-flex items-center gap-1.5 rounded-md bg-lime-300 px-3 py-2 text-xs font-semibold text-black hover:bg-lime-200">
          Request Custom Report →
        </button>
      </div>
    </div>
  );
}
