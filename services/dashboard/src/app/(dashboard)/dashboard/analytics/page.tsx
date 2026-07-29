/**
 * /dashboard/analytics — All sections on a single page (no tab nav):
 *   Overview KPIs • Emissions Trends • Benchmarking • Industry Comparison
 *   • Regional Comparison • Emission Intensity • Cost vs. Emissions
 *   • Opportunities • Forecast.
 *
 * Every chart has hover tooltips; every "View details" link opens a
 * drill-down modal with field-level data.
 */
"use client";

import { useState } from "react";
import { m, useReducedMotion } from "framer-motion";
import { Calendar, X } from "lucide-react";

import {
  ANALYTICS_KPIS,
  ANALYTICS_SCOPES,
  ANALYTICS_TREND,
  ANALYTICS_INDUSTRY,
  ANALYTICS_OPPORTUNITIES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { Pill } from "@/components/dashboard/data-table";
import { LineChart, BarChart, DonutChart } from "@/components/dashboard/charts";
import { DetailModal, type DetailField } from "@/components/dashboard/detail-modal";

type ModalId =
  | "trends"
  | "scopes"
  | "benchmark"
  | "industry"
  | "regional"
  | "intensity"
  | "cost"
  | "opportunities"
  | "forecast"
  | null;

type OpportunityRow = (typeof ANALYTICS_OPPORTUNITIES)[number];
interface SelectedRow {
  id: string;
  name: string;
  reduction: string | number;
  percent?: number;
  cost: string;
  effort: string;
  roi: string;
  priority: string;
}

export default function AnalyticsPage() {
  const [modal, setModal] = useState<ModalId>(null);
  const [selectedOpportunity, setSelectedOpportunity] = useState<SelectedRow | null>(null);

  const open = (id: ModalId) => setModal(id);
  const close = () => {
    setModal(null);
    setSelectedOpportunity(null);
  };

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">
            Analytics <span className="ml-1">📈</span>
          </h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Advanced insights to understand your emissions and drive maximum impact.
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
        {ANALYTICS_KPIS.map((k) => (
          <KpiCard key={k.id} label={k.label} value={k.value} unit={"unit" in k ? k.unit : undefined} sub={"sub" in k ? k.sub : undefined} trend={"trend" in k ? k.trend : undefined} />
        ))}
      </div>

      {/* Row 1 — Trends + Scopes donut */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              Emissions Trends
              <Pill color="emerald">Beta</Pill>
            </span>
          }
          subtitle="Monthly emissions with year-over-year comparison"
          actions={
            <div className="flex items-center gap-2">
              <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
                <option>Monthly</option>
                <option>Weekly</option>
                <option>Daily</option>
              </select>
              <button className="grid h-7 w-7 place-items-center rounded-md border border-white/10 bg-white/5 text-white/60 hover:text-white">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 7v3M6 5v5M9 3v7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
              </button>
            </div>
          }
        >
          <div className="mb-3 flex items-baseline gap-2">
            <p className="text-2xl font-bold text-white">2,453 <span className="text-sm text-white/50">tCO₂e</span></p>
            <span className="text-xs text-emerald-200">↑ 18% vs previous month</span>
          </div>
          <LineChart
            series={[
              { name: "2024",       data: ANALYTICS_TREND.current,                       color: "rgba(132,204,22,0.95)", fill: true },
              { name: "2023",       data: ANALYTICS_TREND.baseline.map((v) => v - 100),  color: "rgba(56,189,248,0.95)", dashed: true },
              { name: "Baseline",   data: ANALYTICS_TREND.baseline,                      color: "rgba(255,255,255,0.4)", dashed: true },
            ]}
            labels={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
            height={220}
            formatTooltip={(label, values) => (
              <div className="space-y-0.5">
                {values.map((v, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                    <span className="text-white/65">{v.name}</span>
                    <span className="ml-auto font-mono font-medium text-white">
                      {v.value.toLocaleString()} tCO₂e
                    </span>
                  </div>
                ))}
              </div>
            )}
          />
          <button
            onClick={() => open("trends")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-trends-detail"
          >
            View full breakdown →
          </button>
        </Card>

        <Card title="Emissions by Scope" actions={
          <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
            This Month ▾
          </button>
        }>
          <div className="flex flex-col items-center">
            <DonutChart
              data={ANALYTICS_SCOPES.map((s) => ({ label: s.label, value: s.value, color: s.color }))}
              size={170}
              thickness={20}
              centerLabel="2,453"
              centerSub="tCO₂e"
              formatTooltip={(label, value, pct) => (
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">Value</span>
                    <span className="ml-auto font-mono font-medium text-white">
                      {value.toLocaleString()} tCO₂e
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">Share</span>
                    <span className="ml-auto font-mono font-medium text-emerald-100">
                      {pct.toFixed(1)}%
                    </span>
                  </div>
                </div>
              )}
            />
            <div className="mt-4 w-full space-y-1.5 text-xs">
              {ANALYTICS_SCOPES.map((s) => (
                <div key={s.label} className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="text-white/70">{s.label}</span>
                  </span>
                  <span className="text-white">{s.percent}% <span className="text-white/40">({s.value.toLocaleString()})</span></span>
                </div>
              ))}
            </div>
            <button
              onClick={() => open("scopes")}
              className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
              data-testid="open-scopes-detail"
            >
              View full breakdown →
            </button>
          </div>
        </Card>
      </div>

      {/* Row 2 */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Benchmarking" subtitle="vs Industry Average" actions={
          <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
            vs Industry Average ▾
          </button>
        }>
          <p className="text-xs text-white/50">Your Emissions Intensity</p>
          <p className="mt-1 text-3xl font-bold text-white">0.42 <span className="text-sm text-white/50">tCO₂e / $K</span></p>
          <p className="mt-0.5 text-[11px] text-emerald-200">↓ 12% vs industry average</p>
          <div className="mt-4 space-y-2.5">
            {[
              { label: "You", value: 0.42, color: "rgba(132,204,22,0.95)", width: 42 },
              { label: "Industry Average", value: 0.48, color: "rgba(148,163,184,0.6)", width: 48 },
              { label: "Top Performers", value: 0.23, color: "rgba(148,163,184,0.3)", width: 23 },
            ].map((row) => (
              <div key={row.label}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="text-white/70">{row.label}</span>
                  <span className="text-white">{row.value}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full" style={{ width: `${row.width}%`, backgroundColor: row.color }} />
                </div>
              </div>
            ))}
          </div>
          <button
            onClick={() => open("benchmark")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-benchmark-detail"
          >
            View benchmarking detail →
          </button>
        </Card>

        <Card title="Industry Comparison" subtitle="By Emissions Intensity (tCO₂e / $K Revenue)" actions={
          <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
            By Emissions Intensity ▾
          </button>
        }>
          <BarChart
            data={ANALYTICS_INDUSTRY.map((i) => i.value)}
            labels={ANALYTICS_INDUSTRY.map((i) => i.label)}
            height={220}
            color="rgba(132,204,22,0.95)"
            formatTooltip={(label, value) => (
              <div className="flex items-center gap-2">
                <span className="text-white/65">Emissions Intensity</span>
                <span className="ml-auto font-mono font-medium text-white">
                  {value.toFixed(2)} tCO₂e/$K
                </span>
              </div>
            )}
          />
          <button
            onClick={() => open("industry")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-industry-detail"
          >
            View full industry comparison →
          </button>
        </Card>
      </div>

      {/* Row 3 — Regional + Intensity */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Regional Comparison" subtitle="By Total Emissions" actions={
          <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
            By Total Emissions ▾
          </button>
        }>
          <div className="mb-3 flex items-center gap-3 text-[10px] text-white/60">
            {[
              { color: "rgba(132,204,22,0.9)", label: "High",     range: "> 500 tCO₂e" },
              { color: "rgba(132,204,22,0.6)", label: "Medium",   range: "100 – 500" },
              { color: "rgba(132,204,22,0.4)", label: "Low",      range: "10 – 100" },
              { color: "rgba(148,163,184,0.2)", label: "Very Low", range: "< 10" },
              { color: "rgba(148,163,184,0.4)", label: "No Data",  range: "" },
            ].map((r) => (
              <span key={r.label} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: r.color }} /> {r.label}{r.range && <span className="text-white/40">({r.range})</span>}
              </span>
            ))}
          </div>
          <RegionalMap onSelect={(region) => {
            setSelectedOpportunity({
              id: `region-${region.id}`,
              name: region.label,
              reduction: region.value.toLocaleString(),
              percent: 0,
              cost: "—",
              effort: "—",
              roi: "—",
              priority: "Low",
            });
            open("regional");
          }} />
          <button
            onClick={() => open("regional")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-regional-detail"
          >
            View regional breakdown →
          </button>
        </Card>

        <Card title="Emission Intensity Over Time" subtitle="tCO₂e / $K Revenue" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>Monthly</option>
          </select>
        }>
          <LineChart
            series={[
              { name: "2024", data: [0.50, 0.48, 0.45, 0.43, 0.42, 0.41, 0.42, 0.43, 0.42, 0.41, 0.40, 0.39], color: "rgba(132,204,22,0.95)", fill: true },
              { name: "2023", data: [0.55, 0.53, 0.51, 0.50, 0.48, 0.47, 0.46, 0.46, 0.45, 0.45, 0.44, 0.43], color: "rgba(56,189,248,0.95)", dashed: true },
              { name: "Industry Average", data: [0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48, 0.48], color: "rgba(255,255,255,0.4)", dashed: true },
            ]}
            labels={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
            height={240}
            formatTooltip={(label, values) => (
              <div className="space-y-0.5">
                {values.map((v, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                    <span className="text-white/65">{v.name}</span>
                    <span className="ml-auto font-mono font-medium text-white">
                      {v.value.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          />
          <button
            onClick={() => open("intensity")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-intensity-detail"
          >
            View intensity history →
          </button>
        </Card>
      </div>

      {/* Row 4 — Cost vs Emissions + Opportunities */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Cost vs. Emissions" subtitle="Bubble size = monthly emissions" actions={
          <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
            <option>Monthly</option>
          </select>
        }>
          <CostVsEmissionsChart />
          <button
            onClick={() => open("cost")}
            className="mt-3 text-xs text-emerald-100 hover:text-emerald-200"
            data-testid="open-cost-detail"
          >
            View detailed analysis →
          </button>
        </Card>

        <Card title="Reduction Opportunity Analysis" actions={
          <button className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:text-white">
            This Year ▾
          </button>
        } noPadding>
          <div className="grid grid-cols-5 gap-2 border-b border-white/5 px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-white/40">
            <span>Opportunity</span>
            <span className="text-right">Potential (tCO₂e/yr)</span>
            <span>Cost</span>
            <span>Effort</span>
            <span className="text-right">ROI / Priority</span>
          </div>
          <div className="divide-y divide-white/5">
            {ANALYTICS_OPPORTUNITIES.map((row) => (
              <button
                key={row.id}
                onClick={() => {
                  setSelectedOpportunity({
                    id: String(row.id),
                    name: row.name,
                    reduction: row.reduction,
                    percent: row.percent,
                    cost: row.cost,
                    effort: row.effort,
                    roi: row.roi,
                    priority: row.priority,
                  });
                  open("opportunities");
                }}
                className="grid w-full grid-cols-5 items-center gap-2 px-5 py-3 text-left hover:bg-white/[0.04]"
                data-testid={`opportunity-${row.id}`}
              >
                <p className="text-sm text-white">{row.name}</p>
                <p className="text-right text-sm">
                  <span className="text-white">{row.reduction}</span>
                  <span className="text-[10px] text-white/40"> ({row.percent}%)</span>
                </p>
                <Pill color="amber">{row.cost}</Pill>
                <Pill color="lime">{row.effort}</Pill>
                <div className="text-right">
                  <p className="text-xs text-white">{row.roi}</p>
                  <Pill color={row.priority === "High" ? "rose" : row.priority === "Medium" ? "amber" : "lime"} className="mt-0.5">{row.priority}</Pill>
                </div>
              </button>
            ))}
          </div>
        </Card>
      </div>

      {/* Forecast */}
      <Card
        title={
          <span className="flex items-center gap-2">
            Emissions Forecast
            <Pill color="emerald">Beta</Pill>
          </span>
        }
        subtitle="Based on current trends, your total emissions for 2024 are projected to be 28,650 tCO₂e."
        actions={
          <div className="flex items-center gap-2">
            <select className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70">
              <option>2024 Forecast</option>
            </select>
            <button className="grid h-7 w-7 place-items-center rounded-md border border-white/10 bg-white/5 text-white/60 hover:text-white">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 7v3M6 5v5M9 3v7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
            </button>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <LineChart
              series={[
                { name: "Actual",   data: [1850, 1920, 2050, 2180, 2300, 2400, 2350, 2420, 2380, 2450, 2453, 2400], color: "rgba(132,204,22,0.95)", fill: true },
                { name: "Forecast", data: [2453, 2453, 2453, 2453, 2453, 2453, 2453, 2453, 2453, 2453, 2453, 2550, 2700, 2820, 2865].slice(0, 12), color: "rgba(132,204,22,0.5)", dashed: true },
                { name: "Baseline (2023)", data: [2200, 2250, 2300, 2350, 2400, 2450, 2480, 2500, 2520, 2540, 2550, 2560], color: "rgba(255,255,255,0.4)", dashed: true },
              ]}
              labels={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
              height={200}
              formatTooltip={(label, values) => (
                <div className="space-y-0.5">
                  {values.map((v, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                      <span className="text-white/65">{v.name}</span>
                      <span className="ml-auto font-mono font-medium text-white">
                        {v.value.toLocaleString()} tCO₂e
                      </span>
                    </div>
                  ))}
                </div>
              )}
            />
          </div>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-white/50">2024 Forecast</p>
              <p className="mt-1 text-3xl font-bold text-white">28,650 <span className="text-sm text-white/50">tCO₂e</span></p>
              <p className="mt-0.5 text-xs text-emerald-200">↓ 14% vs 2023 forecast</p>
            </div>
            <div>
              <p className="text-xs text-white/50">2030 Goal Progress</p>
              <p className="mt-1 text-2xl font-bold text-white">42%</p>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                <div className="h-full rounded-full bg-lime-100" style={{ width: "42%" }} />
              </div>
              <p className="mt-1 text-[10px] text-emerald-200">On track</p>
            </div>
          </div>
        </div>
        <button
          onClick={() => open("forecast")}
          className="mt-4 text-xs text-emerald-100 hover:text-emerald-200"
          data-testid="open-forecast-detail"
        >
          View forecast details →
        </button>
      </Card>

      {/* All modals */}
      {modal === "trends" && (
        <DetailModal
          open
          onClose={close}
          title="Emissions Trends — Full Breakdown"
          subtitle="Monthly comparison: 2024 actual, 2023 baseline, and stretch baseline"
          fields={[
            { label: "2024 Total (Jan–May)", value: "10,503 tCO₂e", tone: "positive", hint: "Year-to-date" },
            { label: "2023 Same Period", value: "11,950 tCO₂e", hint: "Comparable 5-month window" },
            { label: "YoY Change", value: "−1,447 tCO₂e (−12.1%)", tone: "positive", hint: "Year-over-year reduction" },
            { label: "Trend Slope", value: "+18 tCO₂e / month", tone: "warning", hint: "Slight upward drift" },
            { label: "Best Month", value: "February (1,920)", tone: "positive" },
            { label: "Worst Month", value: "November (2,453)", tone: "negative" },
            { label: "Baseline vs Actual", value: "1.5% above", hint: "Performance against plan" },
            { label: "Volatility (σ)", value: "208 tCO₂e", hint: "Std. dev. across 12 months" },
          ]}
        >
          <p className="mt-3 text-xs text-white/60">
            The 2024 series shows a 12.1% improvement on 2023 with some late-year drift.
            Forecast for Q4 is tracking slightly above target. Consider running a Pareto
            analysis on Scope 3 categories to find reduction levers.
          </p>
        </DetailModal>
      )}

      {modal === "scopes" && (
        <DetailModal
          open
          onClose={close}
          title="Emissions by Scope — Full Breakdown"
          subtitle="GHG Protocol classification for May 2024"
          fields={ANALYTICS_SCOPES.map((s) => ({
            label: s.label,
            value: `${s.value.toLocaleString()} tCO₂e (${s.percent}%)`,
            hint:
              s.label === "Scope 1"
                ? "Direct emissions from owned/controlled sources"
                : s.label === "Scope 2"
                  ? "Indirect emissions from purchased electricity"
                  : "All other indirect emissions in the value chain",
          }))}
        >
          <p className="mt-3 text-xs text-white/60">
            Hover any donut slice to see live share. Click a scope above to drill into
            the underlying activity data.
          </p>
        </DetailModal>
      )}

      {modal === "benchmark" && (
        <DetailModal
          open
          onClose={close}
          title="Benchmarking — vs Industry Average"
          subtitle="Emissions intensity comparison (tCO₂e per $K revenue)"
          fields={[
            { label: "Your Intensity", value: "0.42 tCO₂e/$K", tone: "positive", hint: "Lower is better" },
            { label: "Industry Average", value: "0.48 tCO₂e/$K", hint: "Same sector, 2024 Q1" },
            { label: "Top 10% Performers", value: "0.23 tCO₂e/$K", tone: "positive", hint: "P10 of peer group" },
            { label: "Gap to Top 10%", value: "0.19 tCO₂e/$K", tone: "warning", hint: "45% reduction opportunity" },
            { label: "Percentile Rank", value: "62nd percentile", tone: "positive" },
            { label: "vs Peer Median", value: "−12.5% below median", tone: "positive" },
            { label: "Improvement (YoY)", value: "−0.08 tCO₂e/$K", tone: "positive" },
            { label: "Sample Size", value: "142 facilities" },
          ]}
        />
      )}

      {modal === "industry" && (
        <DetailModal
          open
          onClose={close}
          title="Industry Comparison — Full Table"
          subtitle="Emissions intensity across sectors (tCO₂e / $K revenue)"
          fields={ANALYTICS_INDUSTRY.map((i) => ({
            label: i.label,
            value: `${i.value.toFixed(2)} tCO₂e/$K`,
            tone: i.label === "You" ? "positive" : "default",
            hint: i.label === "You" ? "This facility" : "Sector benchmark",
          }))}
        />
      )}

      {modal === "regional" && (
        <DetailModal
          open
          onClose={close}
          title={selectedOpportunity ? `Region: ${selectedOpportunity.name}` : "Regional Breakdown"}
          subtitle={selectedOpportunity ? "Click a dot on the map for per-region detail" : "Total emissions by region (tCO₂e)"}
          fields={
            selectedOpportunity
              ? [
                  { label: "Region", value: selectedOpportunity.name },
                  { label: "Total Emissions", value: `${selectedOpportunity.reduction} tCO₂e` },
                  { label: "Share of Global", value: "4.8%" },
                  { label: "Trend", value: "−3.2% YoY", tone: "positive" },
                  { label: "Renewable Share", value: "34%" },
                  { label: "Largest Source", value: "Grid Electricity" },
                ]
              : [
                  { label: "North America", value: "742 tCO₂e", tone: "warning" },
                  { label: "Europe",        value: "623 tCO₂e" },
                  { label: "Asia",          value: "518 tCO₂e" },
                  { label: "South America", value: "287 tCO₂e" },
                  { label: "Africa",        value: "183 tCO₂e" },
                  { label: "Oceania",       value: "100 tCO₂e", tone: "positive" },
                ]
          }
        >
          <p className="mt-3 text-xs text-white/60">
            Click any dot on the map for the per-region detail above. The Oceania cluster
            has the lowest absolute total but the highest growth rate (+8.2% YoY).
          </p>
        </DetailModal>
      )}

      {modal === "intensity" && (
        <DetailModal
          open
          onClose={close}
          title="Emission Intensity — Full History"
          subtitle="tCO₂e per $K revenue, 2023 vs 2024 vs industry average"
          fields={[
            { label: "2024 YTD Average", value: "0.43", tone: "positive" },
            { label: "2023 YTD Average", value: "0.48" },
            { label: "YoY Improvement", value: "−10.4%", tone: "positive" },
            { label: "Best 2024 Month", value: "Dec — 0.39", tone: "positive" },
            { label: "Worst 2024 Month", value: "Jan — 0.50", tone: "warning" },
            { label: "Industry Average", value: "0.48 (flat)" },
            { label: "Target 2030", value: "0.20 tCO₂e/$K", hint: "−52% from current" },
            { label: "Annualized Rate", value: "−0.012 tCO₂e/$K / yr" },
          ]}
        />
      )}

      {modal === "cost" && (
        <DetailModal
          open
          onClose={close}
          title="Cost vs. Emissions — Detailed Analysis"
          subtitle="Monthly energy spend ($K) vs emissions (tCO₂e)"
          fields={[
            { label: "Total Spend (12mo)", value: "$1,820K" },
            { label: "Total Emissions (12mo)", value: "27,560 tCO₂e" },
            { label: "Cost per tCO₂e", value: "$66.04" },
            { label: "Highest-Cost Month", value: "May — $185K", tone: "warning" },
            { label: "Highest-Emission Month", value: "May — 2,453 tCO₂e", tone: "negative" },
            { label: "Best Efficiency Month", value: "Aug — $49/tCO₂e", tone: "positive" },
            { label: "Avg Carbon Price (implicit)", value: "$66.04/tCO₂e" },
            { label: "Volatility (cost)", value: "σ = $24K", tone: "warning" },
          ]}
        />
      )}

      {modal === "opportunities" && selectedOpportunity && (
        <DetailModal
          open
          onClose={close}
          title={selectedOpportunity.name}
          subtitle="Reduction opportunity detail"
          fields={[
            { label: "Annual Potential", value: `${selectedOpportunity.reduction} tCO₂e (${selectedOpportunity.percent}%)`, tone: "positive" },
            { label: "Estimated Cost", value: selectedOpportunity.cost, hint: "CapEx + OpEx over 12 months" },
            { label: "Effort", value: selectedOpportunity.effort },
            { label: "Priority", value: selectedOpportunity.priority, tone: selectedOpportunity.priority === "High" ? "negative" : selectedOpportunity.priority === "Medium" ? "warning" : "default" },
            { label: "ROI", value: selectedOpportunity.roi },
            { label: "Payback Period", value: "2.4 years" },
            { label: "Recommended Owner", value: "Sustainability Lead" },
            { label: "Next Review", value: "Q3 2024" },
          ]}
        >
          <p className="mt-3 text-xs text-white/60">
            This opportunity was identified via the quarterly decarbonisation review.
            Approve the work order in <span className="text-emerald-100">Operational Tasks → Reduction Programs</span> to advance.
          </p>
        </DetailModal>
      )}

      {modal === "opportunities" && !selectedOpportunity && (
        <DetailModal
          open
          onClose={close}
          title="Reduction Opportunity Analysis"
          subtitle="Top 5 ranked by ROI"
          fields={ANALYTICS_OPPORTUNITIES.map((o) => ({
            label: o.name,
            value: `${o.reduction} tCO₂e/yr • ${o.priority} priority`,
            tone: o.priority === "High" ? "positive" : "default",
            hint: `Cost: ${o.cost} • Effort: ${o.effort} • ROI: ${o.roi}`,
          }))}
        >
          <p className="mt-3 text-xs text-white/60">
            Click any row in the table to drill into the per-opportunity detail.
          </p>
        </DetailModal>
      )}

      {modal === "forecast" && (
        <DetailModal
          open
          onClose={close}
          title="2024 Emissions Forecast — Full Detail"
          subtitle="Model: LSTM with quantile heads (P10 / P50 / P90)"
          fields={[
            { label: "2024 Forecast (P50)", value: "28,650 tCO₂e", tone: "positive" },
            { label: "Lower Bound (P10)", value: "26,420 tCO₂e", tone: "positive" },
            { label: "Upper Bound (P90)", value: "30,980 tCO₂e", tone: "warning" },
            { label: "vs 2023", value: "−4,690 tCO₂e (−14%)", tone: "positive" },
            { label: "2030 Goal", value: "18,000 tCO₂e", hint: "−37% from forecast" },
            { label: "On Track to Goal", value: "Yes (42% progress)", tone: "positive" },
            { label: "Model Confidence", value: "92%", tone: "positive" },
            { label: "Last Trained", value: "2 hours ago" },
          ]}
        >
          <p className="mt-3 text-xs text-white/60">
            Forecasts are produced by the LSTM model in <code className="rounded bg-white/10 px-1 text-white/80">forecast-api</code> and
            stored in <code className="rounded bg-white/10 px-1 text-white/80">market_data.forecast_quantiles</code>. The model is
            retrained nightly at 02:00 AEST.
          </p>
        </DetailModal>
      )}
    </div>
  );
}

function RegionalMap({ onSelect }: { onSelect: (region: { id: string; label: string; value: number }) => void }) {
  const reduced = useReducedMotion();
  const dots = [
    { id: "na-1", x: 18, y: 38, label: "North America — West", value: 412, color: "rgba(132,204,22,0.8)" },
    { id: "na-2", x: 22, y: 45, label: "North America — East", value: 330, color: "rgba(132,204,22,0.7)" },
    { id: "eu-1", x: 50, y: 32, label: "Europe — North", value: 280, color: "rgba(132,204,22,0.5)" },
    { id: "eu-2", x: 55, y: 38, label: "Europe — West", value: 220, color: "rgba(132,204,22,0.6)" },
    { id: "eu-3", x: 60, y: 42, label: "Europe — South", value: 123, color: "rgba(132,204,22,0.5)" },
    { id: "as-1", x: 72, y: 50, label: "Asia — East", value: 250, color: "rgba(132,204,22,0.5)" },
    { id: "as-2", x: 80, y: 55, label: "Asia — South", value: 180, color: "rgba(132,204,22,0.6)" },
    { id: "as-3", x: 78, y: 60, label: "Asia — SE", value: 88, color: "rgba(132,204,22,0.6)" },
    { id: "oc-1", x: 85, y: 65, label: "Oceania", value: 100, color: "rgba(132,204,22,0.5)" },
    { id: "af-1", x: 55, y: 65, label: "Africa — North", value: 95, color: "rgba(132,204,22,0.5)" },
    { id: "af-2", x: 50, y: 75, label: "Africa — South", value: 88, color: "rgba(132,204,22,0.4)" },
    { id: "sa-1", x: 32, y: 70, label: "South America — N", value: 175, color: "rgba(132,204,22,0.4)" },
    { id: "sa-2", x: 28, y: 80, label: "South America — S", value: 112, color: "rgba(132,204,22,0.4)" },
  ];
  return (
    <div className="relative aspect-[2/1] w-full">
      <svg viewBox="0 0 100 50" className="h-full w-full">
        {dots.map((d, i) => (
          <m.circle
            key={i}
            cx={d.x}
            cy={d.y}
            r="1.2"
            fill={d.color}
            className="cursor-pointer"
            onClick={() => onSelect(d)}
            data-testid={`map-dot-${d.id}`}
            initial={reduced ? false : { scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            whileHover={reduced ? undefined : { scale: 2.2 }}
            whileTap={reduced ? undefined : { scale: 1.6 }}
            transition={{ type: "spring", stiffness: 280, damping: 18, delay: reduced ? 0 : i * 0.03 }}
            style={{ transformOrigin: `${d.x}px ${d.y}px`, transformBox: "fill-box" as const }}
          >
            <title>{`${d.label} — ${d.value} tCO₂e`}</title>
          </m.circle>
        ))}
      </svg>
    </div>
  );
}

function CostVsEmissionsChart() {
  const reduced = useReducedMotion();
  // Each bubble is a month. We render them on an SVG and detect hover.
  const bubbles: { x: number; y: number; size: number; color: string; label: string; value: number; cost: number }[] = [
    { x: 50,  y: 50, size: 14, color: "rgba(168,85,247,0.7)", label: "Jan", value: 1850, cost: 120 },
    { x: 150, y: 30, size: 12, color: "rgba(244,63,94,0.7)", label: "Feb", value: 1920, cost: 138 },
    { x: 250, y: 25, size: 13, color: "rgba(244,63,94,0.7)", label: "Mar", value: 2050, cost: 152 },
    { x: 350, y: 35, size: 14, color: "rgba(132,204,22,0.7)", label: "Apr", value: 2180, cost: 168 },
    { x: 450, y: 30, size: 15, color: "rgba(56,189,248,0.7)", label: "May", value: 2453, cost: 185 },
    { x: 550, y: 50, size: 12, color: "rgba(168,85,247,0.6)", label: "Jun", value: 2400, cost: 175 },
    { x: 650, y: 70, size: 11, color: "rgba(56,189,248,0.6)", label: "Jul", value: 2350, cost: 162 },
    { x: 750, y: 80, size: 11, color: "rgba(168,85,247,0.6)", label: "Aug", value: 2420, cost: 158 },
  ];
  const W = 800, H = 200;

  const [hover, setHover] = useState<{ x: number; y: number; b: typeof bubbles[number] } | null>(null);

  return (
    <div
      className="relative h-48"
      onMouseMove={(e) => {
        const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        // find nearest bubble
        const svg = (e.currentTarget.querySelector("svg") as SVGSVGElement).getBoundingClientRect();
        const sx = ((x - (svg.left - rect.left)) / svg.width) * W;
        const sy = ((y - (svg.top - rect.top)) / svg.height) * H;
        let nearest: { b: typeof bubbles[number]; dist: number } | null = null;
        for (const b of bubbles) {
          const dx = sx - b.x;
          const dy = sy - b.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (!nearest || d < nearest.dist) nearest = { b, dist: d };
        }
        if (nearest && nearest.dist < nearest.b.size + 6) {
          setHover({ x, y, b: nearest.b });
        } else {
          setHover(null);
        }
      }}
      onMouseLeave={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <line key={i} x1={40} x2={W - 8} y1={10 + p * (H - 30)} y2={10 + p * (H - 30)} stroke="rgba(255,255,255,0.05)" />
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <line key={i} y1={10} y2={H - 20} x1={40 + p * (W - 48)} x2={40 + p * (W - 48)} stroke="rgba(255,255,255,0.05)" />
        ))}
        {bubbles.map((b, i) => {
          const isHover = hover?.b.label === b.label;
          return (
            <m.circle
              key={i}
              cx={b.x}
              cy={b.y}
              r={b.size}
              fill={b.color}
              initial={reduced ? false : { scale: 0, opacity: 0 }}
              animate={{
                scale: isHover ? 1.3 : 1,
                opacity: hover && !isHover ? 0.5 : 1,
              }}
              style={{ transformOrigin: `${b.x}px ${b.y}px`, transformBox: "view-box" as const }}
              transition={{ type: "spring", stiffness: 220, damping: 18, delay: reduced ? 0 : 0.1 + i * 0.06 }}
            />
          );
        })}
        {/* Callout */}
        <m.g
          initial={reduced ? false : { opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.7, duration: 0.4, ease: "easeOut" }}
          style={{ transformOrigin: "450px 30px", transformBox: "view-box" as const }}
        >
          <circle cx={450} cy={30} r="22" fill="none" stroke="rgba(132,204,22,0.5)" />
          <line x1={450} y1={30} x2={550} y2={50} stroke="rgba(132,204,22,0.4)" />
          <rect x={550} y={38} width={130} height={28} rx="4" fill="rgba(0,0,0,0.85)" stroke="rgba(255,255,255,0.1)" />
          <text x={560} y={50} fontSize="9" fill="rgba(255,255,255,0.9)">May 2024</text>
          <text x={560} y={62} fontSize="9" fill="rgba(132,204,22,0.9)">2,453 tCO₂e</text>
        </m.g>
        {/* Axis labels */}
        <text x="6" y="20" fontSize="9" fill="rgba(255,255,255,0.5)">$200K</text>
        <text x="6" y={H / 2} fontSize="9" fill="rgba(255,255,255,0.5)">$100K</text>
        <text x="6" y={H - 22} fontSize="9" fill="rgba(255,255,255,0.5)">$0</text>
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">Emissions (tCO₂e)</text>
      </svg>
      {/* Tooltip */}
      {hover && (
        <m.div
          initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.12, ease: "easeOut" }}
          className="pointer-events-none absolute z-20 min-w-[170px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
          style={{ left: hover.x, top: hover.y }}
          data-testid="bubble-tooltip"
        >
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            {hover.b.label} 2024
          </div>
          <div className="flex items-center gap-2 py-0.5">
            <span className="text-white/65">Emissions</span>
            <span className="ml-auto font-mono font-medium text-white">
              {hover.b.value.toLocaleString()} tCO₂e
            </span>
          </div>
          <div className="flex items-center gap-2 py-0.5">
            <span className="text-white/65">Cost</span>
            <span className="ml-auto font-mono font-medium text-white">
              ${hover.b.cost}K
            </span>
          </div>
          <div className="flex items-center gap-2 py-0.5">
            <span className="text-white/65">$ / tCO₂e</span>
            <span className="ml-auto font-mono font-medium text-emerald-100">
              ${(hover.b.cost * 1000 / hover.b.value).toFixed(2)}
            </span>
          </div>
        </m.div>
      )}
      {/* Legend */}
      <div className="absolute right-2 top-1 space-y-1 text-[9px] text-white/60">
        {bubbles.map((b) => (
          <div key={b.label} className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: b.color }} /> {b.label}
          </div>
        ))}
      </div>
    </div>
  );
}
