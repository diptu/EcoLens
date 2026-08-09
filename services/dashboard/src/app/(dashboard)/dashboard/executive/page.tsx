/**
 * /dashboard/executive — Executive Dashboard
 * CFO/CEO view: high-level KPIs, emissions trend, and emissions by source.
 * All charts are animated with Framer Motion and show details on hover.
 */
"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  ArrowDownRight, ArrowUpRight, Briefcase, CalendarDays, Cloud, Globe, Info, Leaf,
  Link2, RefreshCw, TrendingUp,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DetailModal, type DetailField } from "@/components/dashboard/detail-modal";
import { EmissionsTrendV2 } from "@/components/dashboard/emissions-trend-v2";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/ingestion";
import {
  getExecutiveKpis, getEmissionsTrend, getEmissionsBySource,
  type ExecutiveKpi,
} from "@/lib/dashboards";
import {
  fetchYtdEmissions, fetchCurrentEmissions, fetchEmissionsTimeseries,
  fetchGenerationMix, fetchDemandSummary, fetchDemandForecast,
} from "@/lib/emissions";
import { fetchPublicDataQualitySummary } from "@/lib/data-quality";
import type { EmissionsTrendPoint, EmissionsTrendPointV2 } from "@/lib/admin-dashboard";

function formatHourLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Richer date+time label for sparkline tooltips (see `Sparkline`'s
// `fullLabels` prop) -- same local-timezone basis as `formatHourLabel`,
// just with the date spelled out too, since a 24h/4h window can cross a
// local midnight boundary and "14:30" alone doesn't say which day.
function formatFullDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Emissions Trend's real region selector -- "NEM" (no `region` param) is
// the 5-region aggregate; the rest are the individual NEM regions the
// backend can actually serve real emissions timeseries/forecast data
// for. WEM isn't offered here -- its different native cadence means it
// was never in scope for the demand-forecast model's region training
// (root TODO.md's "NEM 5-region sum" item), so a WEM forecast segment
// would always just show its own honest "unavailable" gap.
const TREND_REGIONS = ["NEM", "NSW1", "QLD1", "VIC1", "SA1", "TAS1"] as const;

// Emissions Trend's real x-axis extent: now-5*24h (actual + real hourly
// spread) to now+{24 or 48}h (real forecast, wherever it reaches -- the
// forecast-period selector controls this second number, `trendForecastDays`
// state below, not a fixed constant). The model's real native forecast
// horizon is only ~4h (confirmed live, `GET /v1/emissions/forecast`'s
// own `horizon` field) -- there is no real 24-48h-ahead emissions
// forecast available from any served model right now, so the chart
// still only ever plots real forecast data out to that true horizon,
// leaving a real, honest empty gap for the rest of the selected window
// rather than inventing data to fill it.
const TREND_HISTORY_DAYS = 5;
const DAY_MS = 24 * 60 * 60 * 1000;

type ForecastPreview = {
  current: number;
  peak: number;
  min: number;
  sparkline: number[];
  labels: string[];
  fullLabels: string[];
  horizonLabel: string;
  scope: string;
};

type EmissionsSnapshot = {
  totalTco2e: number;
  gridIntensity: number;
  renewablePct: number;
  sparkline: number[];
  labels: string[];
  fullLabels: string[];
};

function KpiCard({ k, live }: { k: ExecutiveKpi; live: boolean }) {
  const isGood = (k.trend === k.good_when) || (k.trend === "flat");
  return (
    <m.div
      className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
        {/* Real fetch for this specific KPI never landed (backend down/
         * unreachable) -- the value shown is the mock placeholder, same
         * "no silently fabricated dashboards" convention every other
         * page this session enforces, just per-card instead of
         * per-page since this grid mixes independently-sourced KPIs. */}
        {!live && (
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-300/70"
            title="Backend unreachable — showing placeholder, not a live value"
          />
        )}
      </div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold text-white">{k.value}</span>
        {k.unit && <span className="text-xs text-white/50">{k.unit}</span>}
      </div>
      {k.delta_pct !== null && (
        <div className={cn("mt-1 flex items-center gap-1 text-xs", isGood ? "text-emerald-100" : "text-rose-200")}>
          {k.trend === "up" ? <ArrowUpRight className="h-3 w-3" /> : k.trend === "down" ? <ArrowDownRight className="h-3 w-3" /> : null}
          <span>{Math.abs(k.delta_pct).toFixed(1)}%</span>
          <span className="text-white/40">vs last period</span>
        </div>
      )}
    </m.div>
  );
}

export default function ExecutiveDashboardPage() {
  const [kpis, setKpis] = useState<ExecutiveKpi[]>(() => getExecutiveKpis());
  const [liveKpiLabels, setLiveKpiLabels] = useState<Set<string>>(new Set());

  // Every section below starts genuinely empty (`null`/`[]`), not a
  // fabricated placeholder -- this is the platform's primary landing
  // page (`/dashboard` redirects here), and a fake-looking number with
  // no visual distinction from a real one is a worse failure mode than
  // an honest "Loading…"/"Unavailable" state. Each section tracks its
  // own error separately so the empty state can say *why* (still
  // loading vs. the backend call actually failed), rather than an
  // unexplained blank forever.
  // `source`/`trend*` (Emissions by Source donut, Emissions Trend chart)
  // are handled separately below -- both explicitly mock/demo, per
  // direct request to reproduce a specific reference screenshot
  // (`getEmissionsBySource()`/`EmissionsTrendV2` -- see their own call
  // sites for the full disclosure). Not fetched here.
  const [trendDetailPoint, setTrendDetailPoint] = useState<EmissionsTrendPointV2 | null>(null);
  // Both pure/deterministic (no fetch) -- computed once, not re-derived
  // on every render.
  const compactTrend = useMemo(() => getEmissionsTrend(), []);
  const emissionsBySource = useMemo(() => getEmissionsBySource(), []);
  const emissionsBySourceTotal = useMemo(
    () => emissionsBySource.reduce((sum, s) => sum + s.tco2e, 0).toLocaleString(),
    [emissionsBySource],
  );

  const [forecastPreview, setForecastPreview] = useState<ForecastPreview | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);

  const [emissionsSnapshot, setEmissionsSnapshot] = useState<EmissionsSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  // Every fetch below hits a real backend endpoint (forecast-api, plus
  // data-pipeline's one unauthenticated data-quality summary). "Data
  // Quality Score"/"Open Risks" are real ingestion/data-quality signals,
  // not sustainability-regulatory compliance or a risk register -- no
  // such domain exists anywhere in this platform, so those numbers are
  // the closest honest substitute, not what the KPI's old "Compliance
  // Score" label implied. See TODO.md's Frontend TODO.
  useEffect(() => {
    let cancelled = false;

    fetchYtdEmissions()
      .then((ytd) => {
        if (cancelled || ytd.total_emissions_tco2e == null) return;
        setKpis((prev) =>
          prev.map((k) =>
            k.label === "Total CO₂e (YTD)"
              ? { ...k, value: Math.round(ytd.total_emissions_tco2e!).toLocaleString() }
              : k,
          ),
        );
        setLiveKpiLabels((prev) => new Set(prev).add("Total CO₂e (YTD)"));
      })
      .catch(() => {});

    fetchCurrentEmissions()
      .then((current) => {
        if (cancelled || current.intensity_kgco2e_per_mwh == null) return;
        // kgCO2e/MWh and gCO2e/kWh are the same number (both ratios of
        // 1000:1 units) -- no conversion needed, just a different label.
        setKpis((prev) =>
          prev.map((k) =>
            k.label === "Carbon Intensity"
              ? { ...k, value: Math.round(current.intensity_kgco2e_per_mwh!).toLocaleString() }
              : k,
          ),
        );
        setLiveKpiLabels((prev) => new Set(prev).add("Carbon Intensity"));
      })
      .catch(() => {});

    fetchDemandSummary()
      .then((summary) => {
        if (cancelled) return;
        setKpis((prev) =>
          prev.map((k) => {
            if (k.label === "Renewable Share" && summary.renewable_share_pct != null) {
              return { ...k, value: summary.renewable_share_pct.toFixed(1) };
            }
            if (k.label === "Avg Wholesale Price (YTD)" && summary.avg_price_mwh != null) {
              return { ...k, value: `$${summary.avg_price_mwh.toFixed(2)}` };
            }
            return k;
          }),
        );
        setLiveKpiLabels((prev) => {
          const next = new Set(prev);
          if (summary.renewable_share_pct != null) next.add("Renewable Share");
          if (summary.avg_price_mwh != null) next.add("Avg Wholesale Price (YTD)");
          return next;
        });
      })
      .catch(() => {});

    fetchPublicDataQualitySummary()
      .then((dq) => {
        if (cancelled) return;
        setKpis((prev) =>
          prev.map((k) => {
            if (k.label === "Data Quality Score" && dq.data_quality_score_pct != null) {
              return { ...k, value: dq.data_quality_score_pct.toFixed(1) };
            }
            if (k.label === "Open Risks") {
              return { ...k, value: dq.open_risks_high_plus.toLocaleString() };
            }
            return k;
          }),
        );
        setLiveKpiLabels((prev) => {
          const next = new Set(prev);
          if (dq.data_quality_score_pct != null) next.add("Data Quality Score");
          next.add("Open Risks");
          return next;
        });
      })
      .catch(() => {});

    // Emissions Snapshot's 3 mini-stats: `totalTco2e`/sparkline come from
    // the same 24h timeseries the chart line uses; `gridIntensity` is a
    // real weighted average (sum emissions / sum generation) over that
    // same 24 hourly points, not a separately-fetched "current" value --
    // `renewablePct` needs a per-fuel breakdown the timeseries endpoint
    // doesn't carry, so it's the one extra call, scoped to the same 24h
    // window (not the wider default the "Emissions by Source" donut
    // uses) so the 3 stats describe the same period.
    fetchEmissionsTimeseries("hour", 1)
      .then((series) => {
        if (cancelled || series.points.length === 0) return;
        const totalEmissions = series.points.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0);
        const totalGeneration = series.points.reduce((s, p) => s + (p.total_generation_mwh ?? 0), 0);
        setEmissionsSnapshot({
          totalTco2e: Math.round(totalEmissions / 1000),
          gridIntensity: totalGeneration ? totalEmissions / totalGeneration : 0,
          renewablePct: 0,
          sparkline: series.points.map((p) => Math.round((p.total_emissions_kgco2e ?? 0) / 1000)),
          labels: series.points.map((p) => formatHourLabel(p.bucket)),
          fullLabels: series.points.map((p) => formatFullDateTime(p.bucket)),
        });

        const untilIso = new Date().toISOString();
        const sinceIso = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
        fetchGenerationMix(undefined, sinceIso, untilIso)
          .then((mix) => {
            if (cancelled || mix.total_generation_mwh === 0) return;
            const renewableMwh = mix.items
              .filter((item) => item.is_renewable)
              .reduce((s, item) => s + item.total_generation_mwh, 0);
            setEmissionsSnapshot((prev) =>
              prev ? { ...prev, renewablePct: (renewableMwh / mix.total_generation_mwh) * 100 } : prev,
            );
          })
          .catch(() => {});
      })
      .catch((err) => {
        if (!cancelled) setSnapshotError(err instanceof Error ? err.message : "failed to load");
      });

    // NEM-wide first; falls back to NSW1 alone if the aggregate 503s
    // (only NSW1 has a trained Production model right now, same reason
    // the Emissions Trend forecast band falls back below) -- scope is
    // shown in the card so a narrower NSW1-only forecast is never
    // presented as if it were the full NEM.
    fetchDemandForecast("NEM")
      .then((forecast) => ({ forecast, scope: "NEM" }))
      .catch(() =>
        fetchDemandForecast("NSW1").then((forecast) => ({ forecast, scope: "NSW1" })),
      )
      .then(({ forecast, scope }) => {
        if (cancelled || forecast.points.length === 0) return;
        const p50s = forecast.points.map((p) => p.p50);
        setForecastPreview({
          current: Math.round(p50s[0]),
          peak: Math.round(Math.max(...p50s)),
          min: Math.round(Math.min(...p50s)),
          sparkline: p50s,
          labels: forecast.points.map((p) => formatHourLabel(p.ts)),
          fullLabels: forecast.points.map((p) => formatFullDateTime(p.ts)),
          horizonLabel: `next ${forecast.horizon}`,
          scope,
        });
      })
      .catch((err) => {
        if (!cancelled) setForecastError(err instanceof Error ? err.message : "failed to load");
      });

    return () => {
      cancelled = true;
    };
  }, []);


  return (
    <div className="space-y-6">
      <m.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
      >
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Briefcase className="h-6 w-6 text-emerald-100" />
          Executive Dashboard
        </h1>
        <p className="mt-1 text-sm text-white/60">High-level sustainability + financial KPIs for leadership.</p>
      </m.div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {kpis.map((k, i) => (
          <KpiCardWithDelay key={k.label} k={k} delay={i * 0.05} live={liveKpiLabels.has(k.label)} />
        ))}
      </div>

      {/* Forecast preview — quick view of next 4h demand */}
      <Card>
        <div data-testid="forecast-preview">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Demand Forecast Preview</h2>
              <p className="text-xs text-white/50">
                {forecastPreview
                  ? `${forecastPreview.horizonLabel} · P10 / P50 / P90${
                      forecastPreview.scope !== "NEM" ? ` · ${forecastPreview.scope} only` : ""
                    }`
                  : "P10 / P50 / P90"}
              </p>
            </div>
            <Link href="/dashboard/forecast/" className="inline-flex items-center gap-1 text-xs text-emerald-100 hover:underline" data-testid="forecast-preview-link">
              View full forecast →
            </Link>
          </div>
          {forecastPreview === null ? (
            <p className="py-8 text-center text-xs text-white/40">
              {forecastError ? `Unavailable — ${forecastError}` : "Loading…"}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <KpiMini label="Current (P50)" value={`${forecastPreview.current.toLocaleString()} MW`} />
                <KpiMini label="Peak in next 4h" value={`${forecastPreview.peak.toLocaleString()} MW`} />
                <KpiMini label="Min in next 4h" value={`${forecastPreview.min.toLocaleString()} MW`} />
              </div>
              <Sparkline
                data={forecastPreview.sparkline}
                labels={forecastPreview.labels}
                fullLabels={forecastPreview.fullLabels}
                unit="MW"
                strokeColor="#34d399"
                testId="forecast-sparkline"
                rotateLabels
              />
            </>
          )}
        </div>
      </Card>

      {/* Emissions preview — quick view of 24h emissions */}
      <Card>
        <div data-testid="emissions-preview">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Emissions Snapshot</h2>
              <p className="text-xs text-white/50">last 24h · Scope 2 (grid)</p>
            </div>
            <Link href="/dashboard/carbon/" className="inline-flex items-center gap-1 text-xs text-emerald-100 hover:underline" data-testid="emissions-preview-link">
              View details →
            </Link>
          </div>
          {emissionsSnapshot === null ? (
            <p className="py-8 text-center text-xs text-white/40">
              {snapshotError ? `Unavailable — ${snapshotError}` : "Loading…"}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <KpiMini label="Total (Scope 2)" value={`${emissionsSnapshot.totalTco2e.toLocaleString()} tCO₂e`} />
                <KpiMini label="Grid intensity" value={`${Math.round(emissionsSnapshot.gridIntensity).toLocaleString()} g/kWh`} />
                <KpiMini label="Renewable %" value={`${emissionsSnapshot.renewablePct.toFixed(1)}%`} />
              </div>
              <Sparkline
                data={emissionsSnapshot.sparkline}
                labels={emissionsSnapshot.labels}
                fullLabels={emissionsSnapshot.fullLabels}
                unit="tCO₂e/h"
                strokeColor="#34d399"
                testId="emissions-sparkline"
                padLabels
              />
            </>
          )}
        </div>
      </Card>

      {/* Emissions Trend v2 -- explicitly mock/demo (see EmissionsTrendV2's
          own header comment and lib/admin-dashboard.ts's getEmissionsTrendV2
          docstring for the full disclosure), ported per direct request to
          reproduce a specific reference screenshot exactly. */}
      <EmissionsTrendV2 onOpenDetails={setTrendDetailPoint} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Emissions Trend (compact)</h2>
              <p className="text-xs text-white/50">8-day rolling tCO₂e (actual + P10-P90)</p>
            </div>
          </div>
          <div className="mb-3 flex items-center gap-4 text-xs text-white/60">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-full bg-emerald-300" /> Actual
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-full border border-dashed border-emerald-100/50" /> P10-P90
            </span>
          </div>
          <CompactTrendChart data={compactTrend} />
        </Card>

        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Emissions by Source</h2>
          <DonutSimple slices={emissionsBySource} total={emissionsBySourceTotal} unit="tCO₂e" />
        </Card>
      </div>

      {trendDetailPoint && (
        <DetailModal
          open={trendDetailPoint !== null}
          onClose={() => setTrendDetailPoint(null)}
          title="Emissions Trend · Hour detail"
          subtitle={`${trendDetailPoint.label} · ${trendDetailPoint.segment === "forecast" ? "Forecast window" : "Past (actual)"}`}
          fields={trendDetailFieldsV2(trendDetailPoint)}
        />
      )}
    </div>
  );
}

/** Fields for the (explicitly mock/demo -- see `EmissionsTrendV2`'s own
 * header comment) Emissions Trend chart's click-to-detail modal. Every
 * value comes straight off the clicked `EmissionsTrendPointV2`. */
function trendDetailFieldsV2(p: EmissionsTrendPointV2): DetailField[] {
  const fields: DetailField[] = [
    { label: "Datetime", value: p.ts.replace("T", " ").slice(0, 16) },
    {
      label: "Window",
      value: p.segment === "past" ? "Past (Actual)" : p.segment === "now" ? "Now" : "Forecast",
    },
    { label: "Label", value: p.label },
  ];
  if (p.actual !== null) {
    fields.push(
      { label: "Actual (hourly)", value: `${p.actual.toLocaleString()} tCO₂e`, tone: "positive" },
      { label: "Past P10", value: `${p.past_p10?.toLocaleString()} tCO₂e` },
      { label: "Past P90", value: `${p.past_p90?.toLocaleString()} tCO₂e` },
    );
  }
  if (p.segment === "forecast") {
    fields.push(
      { label: "Forecast P10", value: `${p.forecast_p10.toLocaleString()} tCO₂e` },
      { label: "Forecast P50", value: `${p.forecast_p50.toLocaleString()} tCO₂e`, tone: "positive" },
      { label: "Forecast P90", value: `${p.forecast_p90.toLocaleString()} tCO₂e` },
      {
        label: "Forecast Spread",
        value: `${(p.forecast_p90 - p.forecast_p10).toLocaleString()} tCO₂e (P10–P90)`,
      },
    );
  }
  return fields;
}

function KpiCardWithDelay({ k, delay, live }: { k: ExecutiveKpi; delay: number; live: boolean }) {
  return (
    <KpiCard k={k} live={live} key={k.label + delay} />
  );
}

// ────────────────────────────────────────────────────────────────────
// Animated chart helpers
// ────────────────────────────────────────────────────────────────────

/**
 * Sparkline — animated line chart for small previews with hover tooltip.
 */
function Sparkline({
  data,
  labels,
  fullLabels,
  unit,
  strokeColor,
  testId,
  padLabels = false,
  rotateLabels = false,
}: {
  data: number[];
  labels: string[];
  /** Richer date+time label per point, shown in the hover tooltip only --
   * `labels` stays short (e.g. "14:30") for the always-visible axis row;
   * this carries the full "Sat, Aug 9 · 14:30 UTC" version so hovering
   * disambiguates which real day a point falls on (the Emissions
   * Snapshot's 24h window can cross a midnight boundary). Falls back to
   * `labels` when omitted. */
  fullLabels?: string[];
  unit: string;
  strokeColor: string;
  testId?: string;
  padLabels?: boolean;
  rotateLabels?: boolean;
}) {
  const reduced = useReducedMotion();
  const w = 100, h = 60;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const points = data.map((v, i) => [i * stepX, h - ((v - min) / range) * (h - 4) - 2] as [number, number]);
  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(2)} ${p[1].toFixed(2)}`)
    .join(" ");

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const idx = Math.max(0, Math.min(data.length - 1, Math.round((x / rect.width) * (data.length - 1))));
      setHover({ x, y, idx });
    }
    function onLeave() {
      setHover(null);
    }
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [data.length]);

  const hoverLabel = hover ? (fullLabels?.[hover.idx] ?? labels[hover.idx]) : null;
  const hoverValue = hover ? data[hover.idx] : 0;

  // Filter labels to avoid overlap
  const visibleLabels = padLabels
    ? labels.filter((_, i) => i % 3 === 0)
    : labels;

  return (
    <div ref={wrapRef} className="relative mt-3 h-16 w-full" data-testid={testId}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-full w-full">
        <m.path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth={1.4}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          initial={reduced ? false : { pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: 0.9, ease: "easeInOut" }}
        />
        {/* Hover crosshair */}
        {hover && (
          <m.g
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.1 }}
          >
            <line
              x1={hover.idx * stepX}
              x2={hover.idx * stepX}
              y1={0}
              y2={h}
              stroke="rgba(132,204,22,0.4)"
              strokeWidth={0.5}
              strokeDasharray="1 1"
            />
            <circle
              cx={hover.idx * stepX}
              cy={h - ((hoverValue - min) / range) * (h - 4) - 2}
              r={1.5}
              fill={strokeColor}
              stroke="#0a1410"
              strokeWidth={0.5}
            />
          </m.g>
        )}
        {/* Invisible hit areas for easier hovering */}
        {data.map((_, i) => (
          <rect
            key={i}
            x={i * stepX - stepX / 2}
            y={0}
            width={stepX}
            height={h}
            fill="transparent"
          />
        ))}
      </svg>
      {/* Labels -- rotated 90° when the chart has many short-interval
          steps (e.g. Demand Forecast Preview's "now/+30m/+1h/..."),
          which crowd badly in a horizontal row at this card's width */}
      <div
        className={cn(
          "mt-2 flex text-[11px] text-white/50",
          rotateLabels ? "h-9 items-start justify-between" : "items-center justify-between",
        )}
      >
        {visibleLabels.map((l, i) => (
          <span
            key={i}
            className={rotateLabels ? "origin-top-left translate-y-1 whitespace-nowrap rotate-90" : undefined}
          >
            {l}
          </span>
        ))}
      </div>
      {/* Hover tooltip */}
      <AnimatePresence>
        {hover && hoverLabel && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="pointer-events-none absolute z-20 min-w-[110px] -translate-x-1/2 -translate-y-[calc(100%+8px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-2.5 py-1.5 text-xs shadow-2xl backdrop-blur"
            style={{ left: hover.x, top: hover.y }}
            data-testid={`${testId}-tooltip`}
          >
            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-white/50">
              {hoverLabel}
            </div>
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: strokeColor }} />
              <span className="text-white/65">Value</span>
              <span className="ml-auto font-mono font-medium text-white">
                {hoverValue.toLocaleString()} {unit}
              </span>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * CompactTrendChart — simple animated area chart (actual line + P10-P90
 * band, index-spaced x-axis) for the "Emissions Trend (compact)" panel.
 * Ported from the v18x prototype's own simple inline `MiniChart(data)`
 * (`/Users/macbook/Downloads/executive-page-zip/page.tsx`) -- explicitly
 * mock/demo, fed by `getEmissionsTrend()` (`@/lib/dashboards`), same
 * disclosure as `EmissionsTrendV2` above. Distinct from that component's
 * own, much more developed chart -- this one is deliberately simple
 * (no region/horizon selectors, no smoothing), matching the reference
 * screenshot's smaller bottom-left panel.
 */
function CompactTrendChart({ data }: { data: EmissionsTrendPoint[] }) {
  const reduced = useReducedMotion();
  const w = 720, h = 200, padL = 40, padR = 8, padT = 8, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const yMax = Math.max(...data.flatMap((d) => [d.actual, d.forecast_p90])) * 1.1;
  const stepX = innerW / (data.length - 1);
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const actualPath = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.actual).toFixed(1)}`).join(" ");
  const bandTop = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.forecast_p90).toFixed(1)}`).join(" ");
  const bandBot = data
    .slice()
    .reverse()
    .map((d, i) => {
      const j = data.length - 1 - i;
      return `L ${x(j).toFixed(1)} ${y(d.forecast_p10).toFixed(1)}`;
    })
    .join(" ");

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const cx = (mx / rect.width) * w;
      const idx = Math.max(0, Math.min(data.length - 1, Math.round((cx - padL) / stepX)));
      setHover({ x: mx, y: my, idx });
    }
    function onLeave() {
      setHover(null);
    }
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [data.length, stepX]);

  const hoverPoint = hover ? data[hover.idx] : null;
  const hoverLabel = hoverPoint ? hoverPoint.date : null;

  return (
    <div ref={wrapRef} className="relative" data-testid="emissions-trend-compact-chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-48 w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <g key={i}>
            <line x1={padL} x2={w - padR} y1={padT + p * innerH} y2={padT + p * innerH} stroke="rgba(255,255,255,0.05)" />
            <text x={padL - 6} y={padT + p * innerH + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.4)">
              {Math.round((1 - p) * yMax / 1000).toLocaleString()}k
            </text>
          </g>
        ))}

        <m.path
          d={`${bandTop} ${bandBot} Z`}
          fill="rgba(52,211,153,0.10)"
          stroke="none"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        />
        <m.path
          d={actualPath}
          fill="none"
          stroke="#34d399"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={reduced ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1, ease: "easeInOut" }}
        />
        {data.map((d, i) => (
          <m.circle
            key={d.date}
            cx={x(i)}
            cy={y(d.actual)}
            r={3}
            fill="#34d399"
            initial={reduced ? false : { scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 20, delay: reduced ? 0 : 0.6 + i * 0.06 }}
          />
        ))}
        {data.map((d, i) => (
          <text key={d.date} x={x(i)} y={h - 8} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">
            {d.date.slice(5)}
          </text>
        ))}
        {hover && hoverPoint && (
          <m.g initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.1 }}>
            <line x1={x(hover.idx)} x2={x(hover.idx)} y1={padT} y2={padT + innerH} stroke="rgba(132,204,22,0.4)" strokeWidth={0.5} strokeDasharray="2 2" />
            <circle cx={x(hover.idx)} cy={y(hoverPoint.actual)} r={5} fill="#34d399" stroke="#0a1410" strokeWidth={1.5} />
            <line x1={x(hover.idx)} x2={x(hover.idx)} y1={y(hoverPoint.forecast_p90)} y2={y(hoverPoint.forecast_p10)} stroke="rgba(132,204,22,0.3)" strokeWidth={2} />
          </m.g>
        )}
      </svg>

      <AnimatePresence>
        {hover && hoverPoint && hoverLabel && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="pointer-events-none absolute z-20 min-w-[180px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
            style={{ left: hover.x, top: hover.y }}
            data-testid="emissions-trend-compact-tooltip"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">{hoverLabel}</div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
              <span className="text-white/65">Actual</span>
              <span className="ml-auto font-mono font-medium text-white">{hoverPoint.actual.toLocaleString()} tCO₂e</span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full border border-emerald-100/50" />
              <span className="text-white/65">P10 (lower)</span>
              <span className="ml-auto font-mono font-medium text-white/80">{hoverPoint.forecast_p10.toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full border border-emerald-100/50" />
              <span className="text-white/65">P90 (upper)</span>
              <span className="ml-auto font-mono font-medium text-white/80">{hoverPoint.forecast_p90.toLocaleString()}</span>
            </div>
            <div className="mt-1 flex items-center gap-2 border-t border-white/5 pt-1 text-[10px] text-white/40">
              <span>Band: ±{Math.round((hoverPoint.forecast_p90 - hoverPoint.forecast_p10) / 2).toLocaleString()} tCO₂e</span>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * DonutSimple — animated ring with hover-to-highlight slices and tooltip.
 */
function DonutSimple({
  slices, total, unit,
}: { slices: { name: string; pct: number; tco2e: number; color: string }[]; total: string; unit: string }) {
  const reduced = useReducedMotion();
  const cx = 80, cy = 80, r = 56, C = 2 * Math.PI * r;
  let acc = 0;
  const totalTco2e = slices.reduce((s, sl) => s + sl.tco2e, 0) || 1;

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      // Donut is in a 160x160 svg, centered at 80,80 with r=56
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      // Only update hover if the cursor is inside the donut SVG area
      // (160x160 px). Otherwise leave the existing state alone so
      // legend hover still works.
      if (x < 0 || y < 0 || x > 160 || y > 160) {
        return;
      }
      // Map screen px to SVG coords (160 viewBox)
      const sx = (x / rect.width) * 160 - cx;
      const sy = (y / rect.height) * 160 - cy;
      const dist = Math.sqrt(sx * sx + sy * sy);
      // Accept anywhere within 160 box (donut + text + legend)
      let angle = Math.atan2(sx, -sy);
      if (angle < 0) angle += 2 * Math.PI;
      let running = 0;
      for (let i = 0; i < slices.length; i++) {
        const sliceFrac = slices[i].pct / 100;
        const sliceAngle = sliceFrac * 2 * Math.PI;
        if (angle >= running && angle < running + sliceAngle && dist < 80) {
          setHover({ x, y, idx: i });
          return;
        }
        running += sliceAngle;
      }
      setHover(null);
    }
    function onLeave() {
      setHover(null);
    }
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [slices]);

  const hoverSlice = hover ? slices[hover.idx] : null;
  const hoverPct = hoverSlice ? (hoverSlice.tco2e / totalTco2e) * 100 : 0;

  return (
    <div ref={wrapRef} className="relative">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-6">
        <div className="relative h-40 w-40 shrink-0">
          <svg width={160} height={160} viewBox="0 0 160 160">
            <circle
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke="rgba(255,255,255,0.04)"
              strokeWidth={20}
            />
            {slices.map((s, i) => {
              const dash = (s.pct / 100) * C;
              const offset = -acc;
              acc += dash;
              const isHover = hover?.idx === i;
              return (
                <m.circle
                  key={s.name}
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={20}
                  strokeDasharray={`${dash} ${C - dash}`}
                  strokeDashoffset={offset}
                  transform={`rotate(-90 ${cx} ${cy})`}
                  initial={reduced ? false : { opacity: 0, scale: 0.85 }}
                  animate={{
                    opacity: hover && !isHover ? 0.4 : 1,
                    scale: 1,
                  }}
                  style={{ transformOrigin: `${cx}px ${cy}px`, transformBox: "view-box" as const }}
                  transition={{
                    duration: 0.4,
                    delay: reduced ? 0 : i * 0.08,
                    ease: "easeOut",
                  }}
                />
              );
            })}
          </svg>
          <m.div
            className="absolute inset-0 flex flex-col items-center justify-center text-center"
            initial={reduced ? false : { opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5, delay: 0.3, ease: "easeOut" }}
          >
            <div className="px-2 text-sm font-bold leading-tight text-white tabular-nums">{total}</div>
            <div className="text-[10px] text-white/50">{unit}</div>
          </m.div>
        </div>
        <ul className="flex-1 space-y-1.5 text-sm">
          {slices.map((s, i) => (
            <li
              key={s.name}
              data-testid={`donut-legend-${s.name.toLowerCase().replace(/\s+/g, "-")}`}
              className={cn(
                "flex cursor-default items-center justify-between rounded-md px-2 py-1 text-white/80 transition-colors",
                hover?.idx === i ? "bg-white/5" : "hover:bg-white/5",
              )}
              onMouseEnter={() => setHover({ x: 0, y: 0, idx: i })}
              onMouseLeave={() => setHover(null)}
              style={{
                opacity: reduced ? 1 : undefined,
                animation: reduced ? undefined : `fadeIn 0.3s ease-out ${0.2 + i * 0.06}s both`,
              }}
            >
              <span className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.name}
              </span>
              <span className="text-white/60">{s.pct.toFixed(1)}%</span>
            </li>
          ))}
        </ul>
      </div>
      <AnimatePresence>
        {hover && hoverSlice && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="pointer-events-none absolute right-2 top-2 z-20 min-w-[170px] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
            data-testid="donut-tooltip"
          >
            <div className="mb-1 flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: hoverSlice.color }}
              />
              <span className="font-semibold text-white">{hoverSlice.name}</span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="text-white/65">Value</span>
              <span className="ml-auto font-mono font-medium text-white">
                {hoverSlice.tco2e.toLocaleString()} {unit}
              </span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="text-white/65">Share</span>
              <span className="ml-auto font-mono font-medium text-emerald-100">
                {hoverPct.toFixed(1)}%
              </span>
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function KpiMini({ label, value }: { label: string; value: string }) {
  return (
    <m.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <div className="text-[11px] uppercase tracking-wide text-white/60">{label}</div>
      <div className="mt-1 text-xl font-bold text-emerald-100">{value}</div>
    </m.div>
  );
}
