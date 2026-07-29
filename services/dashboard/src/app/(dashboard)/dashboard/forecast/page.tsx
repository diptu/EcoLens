/**
 * /dashboard/forecast — demand forecast viewer.
 *
 * The page renders server-side with mock data (so the chart is
 * always available even if forecast-api is down) and exposes a
 * client component for the interactive controls (region, horizon,
 * data source).
 *
 * Visual structure:
 *   ┌─ Header (title, "last updated", mock/api badge) ──────────┐
 *   ├─ Region tabs: NSW1 QLD1 VIC1 SA1 TAS1 WEM ───────────────┤
 *   ├─ Horizon tabs: 2h 4h 6h 12h 24h 2d 3.5d 1wk ─────────────┤
 *   ├─ KPI row: Peak · Trough · Mean · Total · Uncertainty ─────┤
 *   ├─ Fan chart (P10/P50/P90) ────────────────────────────────┤
 *   ├─ Sidebar: model metadata + link to API docs ─────────────┤
 *   └─ Forecast table (collapsible, first/last 10 + flagged) ──┘
 */
"use client";

import { useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Activity,
  ChevronDown,
  ChevronRight,
  Gauge,
  TrendingUp,
  Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { FanChart, Sparkline } from "@/components/dashboard/fan-chart";
import { cn } from "@/lib/utils";
import {
  ALL_HORIZONS,
  ALL_REGIONS,
  formatStepLabel,
  generateMockForecast,
  summarize,
  type Horizon,
  type Region,
} from "@/lib/forecast";

export default function ForecastPage() {
  const [region, setRegion] = useState<Region>("NSW1");
  const [horizon, setHorizon] = useState<Horizon>(48);
  const [showTable, setShowTable] = useState(false);

  // The forecast is regenerated client-side whenever the controls
  // change. The mock generator is deterministic for the same
  // (region, asOf, horizon) so the initial SSR render matches
  // the first client render exactly.
  const forecast = useMemo(
    () => generateMockForecast(region, horizon),
    [region, horizon],
  );
  const summary = useMemo(() => summarize(forecast), [forecast]);

  // First/last 6 points for the table preview
  const tablePoints = useMemo(() => {
    const n = forecast.points.length;
    if (n <= 12) return forecast.points;
    return [...forecast.points.slice(0, 6), ...forecast.points.slice(-6)];
  }, [forecast]);

  // Find the index of the peak for the highlight line
  const peakIdx = useMemo(
    () => forecast.points.findIndex((p) => p.ts === summary.peak.ts) + 1,
    [forecast.points, summary.peak.ts],
  );

  return (
    <div className="space-y-6">
      {/* ── Header ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white">Demand Forecast</h1>
            <span
              data-testid="forecast-source"
              className="rounded-full border border-amber-400/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-300"
            >
              mock
            </span>
          </div>
          <p className="mt-1 text-sm text-white/55">
            Near-real-time electricity demand forecast with P10 / P50 / P90 uncertainty bands.
            Updated every 30 minutes when the data-pipeline cron runs.
          </p>
        </div>
        <div className="text-right text-xs text-white/40">
          <div>
            <span className="text-white/30">as_of:</span>{" "}
            <span className="font-mono text-white/70">
              {new Date(forecast.asOf).toLocaleString("en-AU", { timeZone: "Australia/Sydney" })}
            </span>
          </div>
          <div>
            <span className="text-white/30">model:</span>{" "}
            <span className="font-mono text-white/70">
              {forecast.model} v{forecast.modelVersion}
            </span>
          </div>
        </div>
      </div>

      {/* ── Region + Horizon selectors ───────────────────────── */}
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Region
            </div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Region">
              {ALL_REGIONS.map((r) => {
                const active = r === region;
                return (
                  <button
                    key={r}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setRegion(r)}
                    data-testid={`region-${r}`}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-lime-100 text-black"
                        : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                    )}
                  >
                    {r}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Horizon
            </div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Horizon">
              {ALL_HORIZONS.map((h) => {
                const active = h.steps === horizon;
                return (
                  <button
                    key={h.steps}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setHorizon(h.steps)}
                    data-testid={`horizon-${h.steps}`}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-emerald-200 text-black"
                        : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                    )}
                  >
                    {h.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      {/* ── KPI row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi
          icon={ArrowUpRight}
          label="Peak demand"
          value={`${summary.peak.value.toLocaleString()} MW`}
          hint={formatStepLabel(summary.peak.ts, peakIdx, forecast.points.length)}
          tone="up"
        />
        <Kpi
          icon={ArrowDownRight}
          label="Trough"
          value={`${summary.trough.value.toLocaleString()} MW`}
          hint={formatStepLabel(
            summary.trough.ts,
            forecast.points.findIndex((p) => p.ts === summary.trough.ts) + 1,
            forecast.points.length,
          )}
          tone="down"
        />
        <Kpi
          icon={Activity}
          label="Mean"
          value={`${summary.mean.toLocaleString()} MW`}
          hint={`over ${forecast.points.length} steps`}
        />
        <Kpi
          icon={Zap}
          label="Total energy"
          value={`${summary.total.toLocaleString()} MWh`}
          hint="sum of median × 30 min"
        />
        <Kpi
          icon={Gauge}
          label="Uncertainty"
          value={`±${summary.uncertaintyAtPeak.toLocaleString()} MW`}
          hint={`${summary.uncertaintyGrowth}× growth over horizon`}
        />
      </div>

      {/* ── Main chart + sidebar ──────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-200" />
              {region} — next {horizon} steps
            </span>
          }
        >
          <FanChart forecast={forecast} highlightStep={peakIdx} />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/45">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-0.5 w-4 bg-lime-100" /> P50 (median)
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-4 rounded-sm"
                  style={{ background: "rgba(132,204,22,0.18)", border: "1px solid rgba(132,204,22,0.4)" }}
                />{" "}
                P10–P90 band (80% interval)
              </span>
            </div>
            <div>Hover the chart to inspect any step</div>
          </div>

          {/* Collapsible table preview */}
          <button
            type="button"
            onClick={() => setShowTable((s) => !s)}
            className="mt-4 flex w-full items-center gap-2 rounded-md border border-white/5 bg-white/[0.02] px-3 py-2 text-xs text-white/55 transition-colors hover:bg-white/5"
            aria-expanded={showTable}
          >
            {showTable ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {showTable ? "Hide" : "Show"} forecast table ({tablePoints.length} of {forecast.points.length} steps)
          </button>
          {showTable && (
            <div className="mt-2 max-h-72 overflow-auto rounded-md border border-white/5">
              <table className="w-full text-xs" data-testid="forecast-table">
                <thead className="sticky top-0 bg-[#0a1410] text-left text-[10px] uppercase tracking-wider text-white/40">
                  <tr>
                    <th className="px-3 py-2">Step</th>
                    <th className="px-3 py-2">Time (AEST)</th>
                    <th className="px-3 py-2 text-right">P10</th>
                    <th className="px-3 py-2 text-right">P50</th>
                    <th className="px-3 py-2 text-right">P90</th>
                    <th className="px-3 py-2 text-right">Width</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-white/80">
                  {tablePoints.map((p, i) => {
                    const width = p.p90 - p.p10;
                    const isPeak = p.ts === summary.peak.ts;
                    return (
                      <tr
                        key={`${p.step}-${i}`}
                        className={cn(
                          "border-t border-white/5",
                          isPeak && "bg-lime-100/5 text-lime-100",
                        )}
                      >
                        <td className="px-3 py-1.5">{p.step}</td>
                        <td className="px-3 py-1.5 text-white/60">
                          {new Date(p.ts).toLocaleString("en-AU", {
                            timeZone: "Australia/Sydney",
                            weekday: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                            day: "numeric",
                            month: "short",
                          })}
                        </td>
                        <td className="px-3 py-1.5 text-right text-rose-300/80">{p.p10.toFixed(0)}</td>
                        <td className="px-3 py-1.5 text-right text-lime-100">{p.p50.toFixed(0)}</td>
                        <td className="px-3 py-1.5 text-right text-emerald-100/80">{p.p90.toFixed(0)}</td>
                        <td className="px-3 py-1.5 text-right text-white/50">±{(width / 2).toFixed(0)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* ── Sidebar: model + sparkline preview ─────────────── */}
        <div className="space-y-4">
          <Card title="Model info">
            <dl className="space-y-2 text-xs">
              <Row label="Architecture" value="2-layer LSTM + attention + 3 heads" />
              <Row label="Hidden size" value="128" />
              <Row label="Parameters" value="232,721" />
              <Row label="Lookback" value={`${forecast.points.length > 0 ? 48 : 0} steps (24h)`} />
              <Row label="Interval" value={`${forecast.intervalMinutes} min`} />
              <Row label="Trained on" value="~3 years of NEM 30-min data" />
              <Row label="Last promoted" value="—" />
            </dl>
          </Card>
          <Card title="Endpoint">
            <div className="space-y-2 text-xs">
              <p className="text-white/55">
                Real-time forecast is served by the <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-lime-100">forecast-api</code> service
                (FastAPI + PyTorch LSTM, MLflow Registry). In this dashboard deployment the live
                service isn&apos;t attached, so the page renders a deterministic mock that
                matches the same response contract:
              </p>
              <pre className="overflow-x-auto rounded-md border border-white/5 bg-black/40 p-2 text-[11px] text-white/70">
{`GET /v1/forecast/${region}?horizon=${horizon}
→ { region, model, points: [{ ts, p10, p50, p90 }] }`}
              </pre>
              <a
                href="/dashboard/settings/"
                className="inline-block text-emerald-100 hover:text-emerald-100"
              >
                See the full API reference →
              </a>
            </div>
          </Card>
          <Card title="Now (sparkline)">
            <div className="flex items-center gap-3">
              <Sparkline
                values={forecast.points.slice(0, 12).map((p) => p.p50)}
                width={140}
                height={40}
              />
              <div className="text-xs">
                <div className="text-white/50">Next 6h</div>
                <div className="text-lg font-bold text-white">
                  {forecast.points[0]?.p50.toFixed(0) ?? "—"} <span className="text-xs font-normal text-white/40">MW</span>
                </div>
                <div className="text-[10px] text-emerald-100">↑ rising</div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            {label}
          </div>
          <div className="mt-1 text-xl font-bold text-white">{value}</div>
          {hint && <div className="mt-0.5 text-[10px] text-white/40">{hint}</div>}
        </div>
        <Icon
          className={cn(
            "h-4 w-4",
            tone === "up" && "text-emerald-200",
            tone === "down" && "text-rose-400",
            !tone && "text-white/40",
          )}
        />
      </div>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-white/45">{label}</dt>
      <dd className="font-mono text-white/80">{value}</dd>
    </div>
  );
}
