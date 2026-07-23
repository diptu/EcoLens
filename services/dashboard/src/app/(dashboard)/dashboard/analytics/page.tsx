/**
 * /dashboard/analytics — Analytics with 7 tabs (Overview, Emissions
 * Trends, Benchmarking, Industry Comparison, Regional Comparison,
 * Emission Intensity, Cost vs. Emissions, Opportunities).
 *
 * Layout:
 *  - Hero
 *  - 5 KPIs
 *  - Tab nav (single active tab "Overview")
 *  - 2-col: Trends line chart + Scope donut
 *  - 2-col: Benchmarking + Industry comparison
 *  - 2-col: Regional map (CSS) + Emission intensity over time
 *  - 2-col: Cost vs Emissions scatter + Reduction opportunities
 *  - Forecast
 */
import { Calendar } from "lucide-react";

import {
  ANALYTICS_KPIS,
  ANALYTICS_SCOPES,
  ANALYTICS_TREND,
  ANALYTICS_INDUSTRY,
  ANALYTICS_OPPORTUNITIES,
} from "@/lib/data";

import { Card } from "@/components/dashboard/card";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { Pill, ActionsMenu } from "@/components/dashboard/data-table";
import { LineChart, BarChart, DonutChart } from "@/components/dashboard/charts";
import { AnalyticsTabs } from "@/components/dashboard/analytics-tabs";
import { LiveForecastCard } from "@/components/dashboard/live-forecast-card";

export const metadata = { title: "Analytics — EcoLens" };

export default function AnalyticsPage() {
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

      {/* Live forecast (ECO-130: the one section here reading real data) */}
      <LiveForecastCard />

      {/* Tabs */}
      <AnalyticsTabs />

      {/* Row 1 */}
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
            <span className="text-xs text-emerald-400">↑ 18% vs previous month</span>
          </div>
          <LineChart
            series={[
              { name: "2024",       data: ANALYTICS_TREND.current,                       color: "rgba(132,204,22,0.95)", fill: true },
              { name: "2023",       data: ANALYTICS_TREND.baseline.map((v) => v - 100),  color: "rgba(56,189,248,0.95)", dashed: true },
              { name: "Baseline",   data: ANALYTICS_TREND.baseline,                      color: "rgba(255,255,255,0.4)", dashed: true },
            ]}
            labels={ANALYTICS_TREND.labels}
            height={240}
          />
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
            <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View full breakdown →</button>
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
          <p className="mt-0.5 text-[11px] text-emerald-400">↓ 12% vs industry average</p>
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
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View benchmarking detail →</button>
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
          />
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View full industry comparison →</button>
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
          <RegionalMap />
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View regional breakdown →</button>
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
          />
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
          <button className="mt-3 text-xs text-emerald-300 hover:text-emerald-200">View detailed analysis →</button>
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
              <div key={row.id} className="grid grid-cols-5 items-center gap-2 px-5 py-3 hover:bg-white/[0.02]">
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
              </div>
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
            />
          </div>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-white/50">2024 Forecast</p>
              <p className="mt-1 text-3xl font-bold text-white">28,650 <span className="text-sm text-white/50">tCO₂e</span></p>
              <p className="mt-0.5 text-xs text-emerald-400">↓ 14% vs 2023 forecast</p>
            </div>
            <div>
              <p className="text-xs text-white/50">2030 Goal Progress</p>
              <p className="mt-1 text-2xl font-bold text-white">42%</p>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                <div className="h-full rounded-full bg-lime-300" style={{ width: "42%" }} />
              </div>
              <p className="mt-1 text-[10px] text-emerald-400">On track</p>
            </div>
          </div>
        </div>
        <button className="mt-4 text-xs text-emerald-300 hover:text-emerald-200">View forecast details →</button>
      </Card>
    </div>
  );
}

function RegionalMap() {
  // Stylized world map dots
  const dots = [
    { x: 18, y: 38, color: "rgba(132,204,22,0.8)" }, // NA
    { x: 22, y: 45, color: "rgba(132,204,22,0.7)" },
    { x: 50, y: 32, color: "rgba(132,204,22,0.5)" }, // EU
    { x: 55, y: 38, color: "rgba(132,204,22,0.6)" },
    { x: 60, y: 42, color: "rgba(132,204,22,0.5)" },
    { x: 72, y: 50, color: "rgba(132,204,22,0.5)" }, // Asia
    { x: 80, y: 55, color: "rgba(132,204,22,0.6)" },
    { x: 78, y: 60, color: "rgba(132,204,22,0.6)" },
    { x: 85, y: 65, color: "rgba(132,204,22,0.5)" },
    { x: 55, y: 65, color: "rgba(132,204,22,0.5)" }, // Africa
    { x: 50, y: 75, color: "rgba(132,204,22,0.4)" },
    { x: 32, y: 70, color: "rgba(132,204,22,0.4)" }, // SA
    { x: 28, y: 80, color: "rgba(132,204,22,0.4)" },
  ];
  return (
    <div className="relative aspect-[2/1] w-full">
      <svg viewBox="0 0 100 50" className="h-full w-full">
        {dots.map((d, i) => (
          <circle key={i} cx={d.x} cy={d.y} r="1" fill={d.color} />
        ))}
      </svg>
    </div>
  );
}

function CostVsEmissionsChart() {
  // Bubbles
  const bubbles = [
    { x: 50, y: 50, size: 14, color: "rgba(168,85,247,0.7)" },   // Jan
    { x: 150, y: 30, size: 12, color: "rgba(244,63,94,0.7)" },    // Feb
    { x: 250, y: 25, size: 13, color: "rgba(244,63,94,0.7)" },    // Mar
    { x: 350, y: 35, size: 14, color: "rgba(132,204,22,0.7)" },   // Apr
    { x: 450, y: 30, size: 15, color: "rgba(56,189,248,0.7)" },   // May
    { x: 550, y: 50, size: 12, color: "rgba(168,85,247,0.6)" },   // Jun
    { x: 650, y: 70, size: 11, color: "rgba(56,189,248,0.6)" },   // Jul
    { x: 750, y: 80, size: 11, color: "rgba(168,85,247,0.6)" },   // Aug
    { x: 750, y: 90, size: 10, color: "rgba(168,85,247,0.5)" },
  ];
  const W = 800, H = 200;
  return (
    <div className="relative h-48">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <line key={i} x1={40} x2={W - 8} y1={10 + p * (H - 30)} y2={10 + p * (H - 30)} stroke="rgba(255,255,255,0.05)" />
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <line key={i} y1={10} y2={H - 20} x1={40 + p * (W - 48)} x2={40 + p * (W - 48)} stroke="rgba(255,255,255,0.05)" />
        ))}
        {bubbles.map((b, i) => (
          <circle key={i} cx={b.x} cy={b.y} r={b.size} fill={b.color} />
        ))}
        {/* Callout */}
        <g>
          <circle cx={450} cy={30} r="22" fill="none" stroke="rgba(132,204,22,0.5)" />
          <line x1={450} y1={30} x2={550} y2={50} stroke="rgba(132,204,22,0.4)" />
          <rect x={550} y={38} width={130} height={28} rx="4" fill="rgba(0,0,0,0.85)" stroke="rgba(255,255,255,0.1)" />
          <text x={560} y={50} fontSize="9" fill="rgba(255,255,255,0.9)">May 2024</text>
          <text x={560} y={62} fontSize="9" fill="rgba(132,204,22,0.9)">2,453 tCO₂e</text>
        </g>
        {/* Axis labels */}
        <text x="6" y="20" fontSize="9" fill="rgba(255,255,255,0.5)">$200K</text>
        <text x="6" y={H / 2} fontSize="9" fill="rgba(255,255,255,0.5)">$100K</text>
        <text x="6" y={H - 22} fontSize="9" fill="rgba(255,255,255,0.5)">$0</text>
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">Emissions (tCO₂e)</text>
      </svg>
      {/* Legend */}
      <div className="absolute right-2 top-1 space-y-1 text-[9px] text-white/60">
        {["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map((m) => (
          <div key={m} className="flex items-center gap-1">
            <span className={`h-1.5 w-1.5 rounded-full ${["", "bg-purple-400", "bg-rose-400", "bg-rose-400", "bg-lime-400", "bg-sky-400", "bg-purple-400", "bg-sky-400", "bg-purple-400", "bg-sky-400", "bg-rose-400", "bg-purple-400"][new Date().getMonth() + 1] || "bg-white/30"}`} /> {m}
          </div>
        ))}
      </div>
    </div>
  );
}
