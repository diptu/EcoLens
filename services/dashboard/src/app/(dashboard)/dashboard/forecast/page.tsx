/**
 * /dashboard/forecast — demand forecast viewer.
 *
 * Real data from forecast-api:
 *   GET /v1/forecast?region=      (DemandLSTM inference, `lib/emissions.ts`'s fetchDemandForecast)
 *   GET /v1/model                 (currently-served model metadata, fetchModelInfo)
 *
 * No mock fallback on fetch failure — an honest empty state beats
 * silently reintroducing fabricated numbers (same policy as the Carbon
 * Intelligence and Executive Dashboard pages).
 *
 * There's no Horizon selector here (unlike the old mock): v0's
 * `/v1/forecast` doesn't resample to an arbitrary requested horizon —
 * it always returns the model's own fixed native horizon/interval
 * (48 steps at whatever cadence the source region reports at, e.g. 4h
 * at 5-min steps for a NEM region, 24h at 30-min steps for WEM). The
 * page shows that real horizon/interval as read-only info instead of
 * pretending it's user-selectable.
 *
 * Visual structure:
 *   ┌─ Header (title, "as_of"/model) ────────────────────────────┐
 *   ├─ Region tabs: NEM NSW1 QLD1 VIC1 SA1 TAS1 WEM ─────────────┤
 *   ├─ KPI row: Peak · Trough · Mean · Total · Uncertainty ──────┤
 *   ├─ Fan chart (P10/P50/P90) ───────────────────────────────────┤
 *   ├─ Sidebar: real model registry info + endpoint reference ───┤
 *   └─ Forecast table (collapsible, first/last 6 + flagged) ─────┘
 */
"use client";

import { useEffect, useMemo, useState } from "react";
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
  ALL_REGIONS,
  formatStepLabel,
  summarize,
  type Forecast,
  type Region,
} from "@/lib/forecast";
import {
  fetchDemandForecast,
  fetchModelInfo,
  type DemandForecast,
  type ModelInfo,
} from "@/lib/emissions";

const ALL_FORECAST_REGIONS: (Region | "NEM")[] = ["NEM", ...ALL_REGIONS];

function parseIntervalMinutes(interval: string): number {
  const m = /^(\d+)([mh])$/.exec(interval);
  if (!m) return 30;
  const n = parseInt(m[1], 10);
  return m[2] === "h" ? n * 60 : n;
}

function toForecast(live: DemandForecast): Forecast {
  return {
    region: live.region as Region,
    asOf: live.generated_at,
    generatedAt: live.generated_at,
    model: live.model,
    // forecast-api's DemandForecast has no model-version field to
    // surface; 0 is this type's own "no real version" convention (see
    // its docstring), and "api" marks this as real (not mock) data.
    modelVersion: 0,
    source: "api",
    intervalMinutes: parseIntervalMinutes(live.interval),
    points: live.points.map((p, i) => ({
      ts: p.ts,
      step: i + 1,
      p10: p.p10,
      p50: p.p50,
      p90: p.p90,
    })),
  };
}

export default function ForecastPage() {
  const [region, setRegion] = useState<Region | "NEM">("NEM");
  const [showTable, setShowTable] = useState(false);

  const [live, setLive] = useState<DemandForecast | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadFailed(false);
    fetchDemandForecast(region)
      .then((f) => {
        if (!cancelled) setLive(f);
      })
      .catch(() => {
        if (!cancelled) {
          setLive(null);
          setLoadFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [region]);

  useEffect(() => {
    let cancelled = false;
    fetchModelInfo()
      .then((m) => {
        if (!cancelled) setModelInfo(m);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const forecast = useMemo(() => (live ? toForecast(live) : null), [live]);
  const summary = useMemo(
    () => (forecast ? summarize(forecast) : null),
    [forecast],
  );

  // First/last 6 points for the table preview
  const tablePoints = useMemo(() => {
    if (!forecast) return [];
    const n = forecast.points.length;
    if (n <= 12) return forecast.points;
    return [...forecast.points.slice(0, 6), ...forecast.points.slice(-6)];
  }, [forecast]);

  // Find the index of the peak for the highlight line
  const peakIdx = useMemo(() => {
    if (!forecast || !summary) return undefined;
    const idx = forecast.points.findIndex((p) => p.ts === summary.peak.ts);
    return idx >= 0 ? idx + 1 : undefined;
  }, [forecast, summary]);

  return (
    <div className="space-y-6">
      {/* ── Header ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Demand Forecast</h1>
          <p className="mt-1 text-sm text-white/55">
            DemandLSTM P10 / P50 / P90 electricity demand forecast, at the
            model&apos;s own native cadence and horizon for the selected
            region.
          </p>
        </div>
        <div className="text-right text-xs text-white/40">
          <div>
            <span className="text-white/30">as_of:</span>{" "}
            <span className="font-mono text-white/70">
              {live
                ? new Date(live.generated_at).toLocaleString("en-AU", {
                    timeZone: "Australia/Sydney",
                  })
                : "—"}
            </span>
          </div>
          <div>
            <span className="text-white/30">model:</span>{" "}
            <span className="font-mono text-white/70">{live?.model ?? "—"}</span>
          </div>
        </div>
      </div>

      {/* ── Region selector ──────────────────────────────────── */}
      <Card>
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Region
          </div>
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Region">
            {ALL_FORECAST_REGIONS.map((r) => {
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
                  {r === "NEM" ? "NEM (5-region sum)" : r}
                </button>
              );
            })}
          </div>
        </div>
      </Card>

      {/* ── KPI row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi
          icon={ArrowUpRight}
          label="Peak demand"
          value={summary ? `${summary.peak.value.toLocaleString()} MW` : "—"}
          hint={
            summary && forecast && peakIdx
              ? formatStepLabel(summary.peak.ts, peakIdx, forecast.points.length)
              : loadFailed
                ? "forecast unavailable"
                : undefined
          }
          tone="up"
        />
        <Kpi
          icon={ArrowDownRight}
          label="Trough"
          value={summary ? `${summary.trough.value.toLocaleString()} MW` : "—"}
          hint={
            summary && forecast
              ? formatStepLabel(
                  summary.trough.ts,
                  forecast.points.findIndex((p) => p.ts === summary.trough.ts) + 1,
                  forecast.points.length,
                )
              : undefined
          }
          tone="down"
        />
        <Kpi
          icon={Activity}
          label="Mean"
          value={summary ? `${summary.mean.toLocaleString()} MW` : "—"}
          hint={forecast ? `over ${forecast.points.length} steps` : undefined}
        />
        <Kpi
          icon={Zap}
          label="Total energy"
          value={summary ? `${summary.total.toLocaleString()} MWh` : "—"}
          hint="sum of median × interval"
        />
        <Kpi
          icon={Gauge}
          label="Uncertainty"
          value={summary ? `±${summary.uncertaintyAtPeak.toLocaleString()} MW` : "—"}
          hint={summary ? `${summary.uncertaintyGrowth}× growth over horizon` : undefined}
        />
      </div>

      {/* ── Main chart + sidebar ──────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-200" />
              {region} — next {live?.horizon ?? "—"}
            </span>
          }
        >
          {forecast ? (
            <>
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
                        const isPeak = summary && p.ts === summary.peak.ts;
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
            </>
          ) : (
            <p className="py-12 text-center text-sm text-white/40">
              {loadFailed
                ? "No forecast available for this region right now — is forecast-api running, and is a model loaded?"
                : "Loading forecast…"}
            </p>
          )}
        </Card>

        {/* ── Sidebar: real model info + endpoint reference ────── */}
        <div className="space-y-4">
          <Card title="Model info">
            {modelInfo ? (
              <dl className="space-y-2 text-xs">
                <Row label="Status" value={modelInfo.status} />
                <Row label="Name" value={modelInfo.name} />
                <Row label="Version" value={modelInfo.version ?? "—"} />
                <Row label="Stage" value={modelInfo.stage ?? "—"} />
                <Row label="Native horizon" value={modelInfo.horizon != null ? `${modelInfo.horizon} steps` : "—"} />
                <Row label="Lookback" value={modelInfo.lookback != null ? `${modelInfo.lookback} steps` : "—"} />
                <Row
                  label="Loaded at"
                  value={
                    modelInfo.loaded_at
                      ? new Date(modelInfo.loaded_at).toLocaleString("en-AU", { timeZone: "Australia/Sydney" })
                      : "—"
                  }
                />
                <Row label="Git SHA" value={modelInfo.git_sha ? modelInfo.git_sha.slice(0, 8) : "—"} />
                {Object.entries(modelInfo.metrics).map(([k, v]) => (
                  <Row key={k} label={k} value={v.toFixed(4)} />
                ))}
              </dl>
            ) : (
              <p className="text-xs text-white/40">No model metadata available.</p>
            )}
          </Card>
          <Card title="Endpoint">
            <div className="space-y-2 text-xs">
              <p className="text-white/55">
                Served live by <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-lime-100">forecast-api</code>{" "}
                (FastAPI + PyTorch LSTM, MLflow Registry). <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-lime-100">horizon</code>/
                <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-lime-100">interval</code> always
                reflect the model&apos;s real native cadence — requesting a
                different one isn&apos;t supported yet, so there&apos;s no
                horizon selector here.
              </p>
              <pre className="overflow-x-auto rounded-md border border-white/5 bg-black/40 p-2 text-[11px] text-white/70">
{`GET /v1/forecast?region=${region}
→ { region, model, horizon, interval, points: [{ ts, p10, p50, p90 }] }`}
              </pre>
            </div>
          </Card>
          <Card title="Now (sparkline)">
            {forecast && forecast.points.length > 0 ? (
              <div className="flex items-center gap-3">
                <Sparkline
                  values={forecast.points.slice(0, 12).map((p) => p.p50)}
                  width={140}
                  height={40}
                />
                <div className="text-xs">
                  <div className="text-white/50">Next {live?.interval}</div>
                  <div className="text-lg font-bold text-white">
                    {forecast.points[0].p50.toFixed(0)} <span className="text-xs font-normal text-white/40">MW</span>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-white/40">No data available.</p>
            )}
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
