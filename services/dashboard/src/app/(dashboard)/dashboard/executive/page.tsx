/**
 * /dashboard/executive — Executive Dashboard
 * CFO/CEO view: high-level KPIs, emissions trend, and emissions by source.
 * All charts are animated with Framer Motion and show details on hover.
 */
"use client";

import { useState, useEffect, useMemo, useRef, useId } from "react";
import Link from "next/link";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  AlertCircle, AlertTriangle, ArrowDownRight, ArrowUpRight, Briefcase, ChevronRight, Cloud, Database,
  DollarSign, Gauge as GaugeIcon, Info, Leaf, ShieldCheck, TrendingUp, Wind, Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DemandForecastChart, type DemandActualPoint } from "@/components/dashboard/demand-forecast-chart";
import { ArcGauge } from "@/components/dashboard/gauge";
import { RealEmissionsTrend } from "@/components/dashboard/real-emissions-trend";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/ingestion";
import { getExecutiveKpis, type ExecutiveKpi } from "@/lib/dashboards";
import { getCached, getCachedAgeMs, setCached } from "@/lib/local-cache";
import {
  fetchCurrentEmissions, fetchEmissionsTimeseries,
  fetchGenerationMix, fetchDemandSummary, fetchDemandForecast,
  fetchRecentBacktest,
  fuelColor, formatFuelType, type GenerationMix,
} from "@/lib/emissions";
import { fetchPublicDataQualitySummary } from "@/lib/data-quality";
import { fetchAnomalies, type Anomaly, type AnomalySeverity } from "@/lib/anomalies";

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

// Emissions Trend's real region selector + history window now live in
// `@/components/dashboard/real-emissions-trend` (its own `REGIONS`/
// `HISTORY_DAYS`) alongside the fetches that use them -- kept together
// there since 2026-08-10, not duplicated here.

type ForecastPreview = {
  current: number;
  peak: number;
  min: number;
  points: { ts: string; tMs: number; p10: number; p50: number; p90: number }[];
  horizonLabel: string;
  scope: string;
};

// Demand Forecast Preview's own `localStorage` cache (`lib/local-cache.ts`)
// -- separate from `forecast-api`'s own Redis caching of `GET /v1/forecast`
// itself (that cache makes a real miss here cheap; this one survives a
// full page reload so the card can paint real data immediately on mount
// instead of "Loading…" on every visit, then quietly refresh). 2h max
// age: stale enough data isn't worth showing instantly in place of a real
// loading state, but generous enough that same-session revisits and most
// next-morning reloads render instantly.
const DEMAND_FORECAST_CACHE_KEY = "executive:demand-forecast-preview";
const DEMAND_ACTUAL_CACHE_KEY = "executive:demand-actual-preview";
const DEMAND_PREVIEW_CACHE_MAX_AGE_MS = 2 * 60 * 60 * 1000;

// `DemandActualPoint`/`DemandForecastChart` now live in
// `@/components/dashboard/demand-forecast-chart` (extracted 2026-08-10,
// shared with the Forecast Explorer page's own "Actual vs Predicted"
// section). "Actual" is real hourly total generation (MWh) -- see that
// file's own header comment for why that's the honest proxy this
// platform actually has for demand (no separately-metered demand time
// series of its own).

type EmissionsSnapshot = {
  totalTco2e: number;
  gridIntensity: number;
  renewablePct: number;
  sparkline: number[];
  /** Per-hour intensity (g/kWh) over the same 24h window as `sparkline`
   * -- real, from the same `fetchEmissionsTimeseries` points, not a
   * second fetch -- backs the "Grid Intensity" mini-stat's own sparkline. */
  intensitySparkline: number[];
  labels: string[];
  fullLabels: string[];
  /** Real `ts` of the most recent point in `sparkline` -- this card's
   * own sparklines plot points index-by-index with no timestamp-aware
   * gap logic (unlike `RealEmissionsTrend`'s Actual line), so a missing
   * recent hour never renders as a visible break -- it just silently
   * shifts the whole window backward in time instead, while the "last
   * 24h" label keeps claiming to be current. This backs a real staleness
   * caption instead of leaving that silent. */
  latestPointIso: string;
};

/** Live, recent-window snapshot for the "Live Grid Status" panel --
 * same `GenerationMix` shape as the YTD "Emissions by Source" donut's
 * data source, just scoped to a short recent window instead of YTD so
 * it reflects what's generating *right now*, not the whole year. */
type LiveGridStatus = {
  mix: GenerationMix;
  windowHours: number;
};

// Real daily-bucketed actual emissions for "Emission History" -- plus
// an optional real derived P10/P50/P90 band (2026-08-11, replacing the
// earlier "no real multi-day emissions forecast" state): there's still
// no real *emissions* forecast model in this platform, but the real
// walk-forward *demand* backtest (`GET /v1/forecast/recent-actual-vs-
// predicted`) already exists, and every one of its real hourly steps
// has a real historical grid intensity (`GET /v1/emissions/timeseries`)
// this platform already knows -- multiplying the two (same real
// methodology `GET /v1/emissions/forecast` already uses for the
// near-term future, demand × intensity, just with each hour's own real
// historical intensity instead of holding "now"'s intensity constant)
// gives a real, honestly-derived historical emissions confidence band,
// not a fabricated one. See `historicalForecastByDate`'s own comment
// for why this only ever covers a bounded recent real window, not
// whichever period (7D/15D/30D) is currently selected.
type CompactTrendPoint = {
  date: string;
  ts: string;
  actualTco2e: number;
  forecastP10Tco2e?: number;
  forecastP50Tco2e?: number;
  forecastP90Tco2e?: number;
};

// Icon + accent color per KPI, keyed by label -- purely presentational
// (matches the reference design's colored icon chip per card), no
// bearing on which fetch backs the value. Falls back to a neutral
// gauge icon for any label not listed here.
const KPI_ICONS: Record<string, { icon: React.ComponentType<{ className?: string }>; className: string }> = {
  "Total CO₂e (MTD)":              { icon: Cloud,       className: "bg-emerald-200/10 text-emerald-100" },
  "Carbon Intensity":              { icon: Leaf,        className: "bg-lime-200/10 text-lime-100" },
  "Renewable Share":               { icon: Wind,        className: "bg-sky-300/10 text-sky-200" },
  "Avg Wholesale Price (YTD)":     { icon: DollarSign,  className: "bg-amber-300/10 text-amber-200" },
  "Data Quality Score":            { icon: ShieldCheck, className: "bg-violet-300/10 text-violet-200" },
  "Open Risks":                    { icon: AlertTriangle, className: "bg-rose-300/10 text-rose-200" },
};

// Sparkline stroke color per KPI -- matches each card's own icon accent
// above. Only KPIs with a real fetchable trend series get an entry (see
// `ExecutiveDashboardPage`'s own comments on `dailySummary`/
// `compactTrend`/`emissionsSnapshot.intensitySparkline` for exactly
// which four); Data Quality Score/Open Risks have no historical
// endpoint to build one from, so they're deliberately absent rather than
// backed by a fabricated flat line.
const KPI_SPARK_COLOR: Record<string, string> = {
  "Total CO₂e (MTD)":          "#6ee7b7",
  "Carbon Intensity":          "#bef264",
  "Renewable Share":           "#7dd3fc",
  "Avg Wholesale Price (YTD)": "#fcd34d",
};

// "Total CO₂e (MTD)" has no real prior-period comparison available (a
// full prior calendar month to compare against isn't always available
// this early in real data collection) -- omitted here, not defaulted to
// "vs last period", so that KPI honestly never renders a delta row.
const KPI_COMPARISON_LABEL: Record<string, string> = {
  "Carbon Intensity": "vs yesterday",
  "Renewable Share": "vs yesterday",
  "Avg Wholesale Price (YTD)": "vs yesterday",
};

/** Small, non-interactive draw-on trendline for a KPI card footer --
 * deliberately not the full `Sparkline` component (hover tooltip + axis
 * labels) used elsewhere on this page: at this size, in a 6-up grid,
 * that much chrome would be noise, not signal. Gradient area fill under
 * the line is purely decorative (same real points as the stroke). */
function MiniTrendline({ data, color }: { data: number[]; color: string }) {
  const reduced = useReducedMotion();
  const gradId = useId().replace(/:/g, "");
  if (data.length < 2) return null;
  const w = 100;
  const h = 28;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const xy = data.map((v, i) => [i * stepX, h - ((v - min) / range) * h] as [number, number]);
  const points = xy.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const linePath = xy.map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${xy[xy.length - 1][0].toFixed(1)} ${h} L ${xy[0][0].toFixed(1)} ${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="mt-2.5 h-7 w-full">
      <defs>
        <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} stroke="none" />
      <m.polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        initial={reduced ? false : { pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.9, ease: "easeInOut" }}
      />
    </svg>
  );
}

function KpiCard({ k, live, sparkline }: { k: ExecutiveKpi; live: boolean; sparkline?: number[] }) {
  const isGood = (k.trend === k.good_when) || (k.trend === "flat");
  const { icon: Icon, className: iconClassName } = KPI_ICONS[k.label] ?? {
    icon: GaugeIcon,
    className: "bg-white/10 text-white/70",
  };
  const trendColor = isGood ? "text-emerald-300" : "text-rose-300";
  return (
    <m.div
      className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-lg", iconClassName)}>
            <Icon className="h-3.5 w-3.5" />
          </span>
          <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {k.delta_pct !== null && (
            k.trend === "up" ? <ArrowUpRight className={cn("h-3.5 w-3.5", trendColor)} />
            : k.trend === "down" ? <ArrowDownRight className={cn("h-3.5 w-3.5", trendColor)} />
            : null
          )}
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
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold text-white">{k.value}</span>
        {k.unit && <span className="text-xs text-white/50">{k.unit}</span>}
      </div>
      {k.delta_pct !== null && (
        <div className={cn("mt-1 flex items-center gap-1 text-xs", isGood ? "text-emerald-100" : "text-rose-200")}>
          {k.trend === "up" ? <ArrowUpRight className="h-3 w-3" /> : k.trend === "down" ? <ArrowDownRight className="h-3 w-3" /> : null}
          <span>{Math.abs(k.delta_pct).toFixed(1)}%</span>
          <span className="text-white/40">{KPI_COMPARISON_LABEL[k.label] ?? "vs last period"}</span>
        </div>
      )}
      {sparkline && sparkline.length >= 2 && (
        <MiniTrendline data={sparkline} color={KPI_SPARK_COLOR[k.label] ?? "#6ee7b7"} />
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
  //
  // `RealEmissionsTrend` (2026-08-10, replacing the formerly-mock
  // `EmissionsTrendV2`) manages its own fetches internally. "Emissions
  // Trend (compact)"/"Emissions by Source" below (2026-08-10, replacing
  // the formerly-mock `getEmissionsTrend()`/`getEmissionsBySource()`)
  // are real fetches, tracked the same "own error, own honest empty
  // state" way every other section on this page already is.
  const [compactTrend, setCompactTrend] = useState<CompactTrendPoint[] | null>(null);
  const [compactTrendError, setCompactTrendError] = useState<string | null>(null);

  // "Emission History"'s own 7D/15D/30D period toggle -- kept
  // separate from `compactTrend` above (always a fixed real 8 days) so
  // switching this period never changes the "Total CO₂e (MTD)" KPI
  // card's own sparkline out from under it.
  const PERIOD_DAYS = { "7D": 7, "15D": 15, "30D": 30 } as const;
  type TrendPeriod = keyof typeof PERIOD_DAYS;
  const [trendPeriod, setTrendPeriod] = useState<TrendPeriod>("7D");
  const [periodTrend, setPeriodTrend] = useState<CompactTrendPoint[] | null>(null);
  const [periodTrendError, setPeriodTrendError] = useState<string | null>(null);
  // Real average of the *preceding* real window of the same length
  // (e.g. the 7 real days before the visible 7D window) -- backs the
  // "vs previous period" stat. `null` until enough real history exists
  // to fill both halves.
  const [periodTrendPrevAvg, setPeriodTrendPrevAvg] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPeriodTrend(null);
    setPeriodTrendError(null);
    setPeriodTrendPrevAvg(null);
    const days = PERIOD_DAYS[trendPeriod];
    fetchEmissionsTimeseries("day", days * 2)
      .then((series) => {
        if (cancelled) return;
        const pts = series.points.filter((p) => p.total_emissions_kgco2e !== null);
        const current = pts.slice(-days);
        const previous = pts.slice(Math.max(0, pts.length - days * 2), pts.length - days);
        setPeriodTrend(
          current.map((p) => ({
            date: new Date(p.bucket).toLocaleDateString([], { month: "short", day: "2-digit" }),
            ts: p.bucket,
            actualTco2e: p.total_emissions_kgco2e! / 1000,
          })),
        );
        if (previous.length > 0) {
          const avgPrev =
            previous.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0) / previous.length / 1000;
          setPeriodTrendPrevAvg(avgPrev);
        }
      })
      .catch((err) => {
        if (!cancelled) setPeriodTrendError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendPeriod]);

  // Real historical demand-backtest × real historical intensity, bucketed
  // by real day -- backs "Emission History"'s optional forecast band (see
  // `CompactTrendPoint`'s own comment for the full methodology). Fixed
  // real 7-day window, independent of `trendPeriod`'s own 7D/15D/30D
  // selection (same "don't widen the expensive real fetch just because a
  // wider actual-history window was picked" reasoning `RealEmissionsTrend`
  // already applies) -- confirmed live: `region=NEM` over 30 real days
  // took ~50s to compute uncached, well past this fetch's own timeout,
  // while 7 real days stays a safe ~15s. A caption below the chart
  // discloses the narrower real band window whenever a wider period is
  // selected, rather than silently truncating with no explanation.
  const HISTORICAL_BAND_DAYS = 7;
  const [historicalForecastByDate, setHistoricalForecastByDate] = useState<
    Map<string, { p10: number; p50: number; p90: number }>
  >(new Map());
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchRecentBacktest("NEM", HISTORICAL_BAND_DAYS),
      // +1 real day of buffer so every real backtest hour near the
      // window's own start still has a real intensity match.
      fetchEmissionsTimeseries("hour", HISTORICAL_BAND_DAYS + 1),
    ])
      .then(([backtest, series]) => {
        if (cancelled) return;
        const intensityByHour = new Map<string, number>();
        for (const p of series.points) {
          if (p.intensity_kgco2e_per_mwh != null) {
            intensityByHour.set(new Date(p.bucket).toISOString(), p.intensity_kgco2e_per_mwh);
          }
        }
        const byDate = new Map<string, { p10: number; p50: number; p90: number }>();
        for (const pt of backtest.points) {
          const intensity = intensityByHour.get(new Date(pt.ts).toISOString());
          // No real intensity for this exact real hour -- skip it rather
          // than guess one, same "real data or nothing" convention every
          // other derived number on this page follows.
          if (intensity == null) continue;
          const dateKey = pt.ts.slice(0, 10);
          const existing = byDate.get(dateKey) ?? { p10: 0, p50: 0, p90: 0 };
          // Real per-point energy is `p50 (MW) * 1 real hour` -- every
          // point is one real hourly step (`RecentBacktestResponse.
          // interval` is always real "1h"), NOT `pt.step_hours` (a real
          // but different thing: the 1-48 "hours-ahead-of-its-own-origin"
          // label `evaluate.py`'s `RecentBacktestPoint` docstring
          // defines -- multiplying by that instead of 1 was a real bug
          // caught before shipping, confirmed live: it inflated daily
          // totals ~10x above the real `GET /v1/generation-mix` figure
          // for the same real day).
          existing.p10 += (pt.p10 * intensity) / 1000; // kgCO2e -> tCO2e
          existing.p50 += (pt.p50 * intensity) / 1000;
          existing.p90 += (pt.p90 * intensity) / 1000;
          byDate.set(dateKey, existing);
        }
        setHistoricalForecastByDate(byDate);
      })
      .catch(() => {
        if (!cancelled) setHistoricalForecastByDate(new Map());
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // `periodTrend` (real actual, whichever period is selected) + the
  // real derived band above, joined by real calendar date -- the band
  // only attaches to days actually inside its own bounded real window;
  // every other day keeps its real actual-only point, unchanged.
  const periodTrendWithBand = useMemo(() => {
    if (!periodTrend) return null;
    if (historicalForecastByDate.size === 0) return periodTrend;
    return periodTrend.map((d) => {
      const band = historicalForecastByDate.get(d.ts.slice(0, 10));
      return band
        ? { ...d, forecastP10Tco2e: band.p10, forecastP50Tco2e: band.p50, forecastP90Tco2e: band.p90 }
        : d;
    });
  }, [periodTrend, historicalForecastByDate]);

  const periodTrendStats = useMemo(() => {
    if (!periodTrend || periodTrend.length === 0) return null;
    const values = periodTrend.map((d) => d.actualTco2e);
    const avg = values.reduce((a, b) => a + b, 0) / values.length;
    const lowest = periodTrend.reduce((a, b) => (b.actualTco2e < a.actualTco2e ? b : a));
    const highest = periodTrend.reduce((a, b) => (b.actualTco2e > a.actualTco2e ? b : a));
    const deltaPct =
      periodTrendPrevAvg !== null && periodTrendPrevAvg > 0
        ? ((avg - periodTrendPrevAvg) / periodTrendPrevAvg) * 100
        : null;
    return { avg, lowest, highest, deltaPct };
  }, [periodTrend, periodTrendPrevAvg]);

  const [generationMix, setGenerationMix] = useState<GenerationMix | null>(null);
  const [generationMixError, setGenerationMixError] = useState<string | null>(null);
  const emissionsBySource = useMemo(() => {
    if (!generationMix) return null;
    const totalEmissions = generationMix.items.reduce((s, i) => s + i.total_emissions_kgco2e, 0);
    return generationMix.items
      .filter((i) => i.total_emissions_kgco2e > 0)
      .map((i) => ({
        name: formatFuelType(i.fuel_type),
        pct: totalEmissions ? (i.total_emissions_kgco2e / totalEmissions) * 100 : 0,
        tco2e: Math.round(i.total_emissions_kgco2e / 1000),
        color: fuelColor(i.fuel_type),
        category: i.category,
      }))
      .sort((a, b) => b.tco2e - a.tco2e);
  }, [generationMix]);
  const emissionsBySourceTotal = useMemo(
    () => (emissionsBySource ?? []).reduce((sum, s) => sum + s.tco2e, 0).toLocaleString(),
    [emissionsBySource],
  );

  // Starts `null` on every render, server or client -- `localStorage`
  // hydration happens in a mount-only `useEffect` below instead of a
  // lazy `useState` initializer, deliberately: this page is a client
  // component but still server-rendered for its initial HTML, and
  // `getCached` can only ever see real `localStorage` state on the
  // client (`typeof window === "undefined"` server-side). A lazy
  // initializer would make the client's first render diverge from what
  // the server actually sent, a real hydration mismatch -- the
  // mount-effect pattern below keeps the first render identical on both
  // sides, then repaints with the cached value one tick later.
  const [forecastPreview, setForecastPreview] = useState<ForecastPreview | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  // Real age of the cached value this card painted from on mount (`null`
  // if there wasn't one) -- set once by the same mount-effect that
  // hydrates `forecastPreview`, not re-read on every render, so it
  // reflects "how stale was the instant-paint" rather than ticking live.
  // Cleared once the real fetch below lands a fresh response, so the
  // "cached" note never lingers after this session's own live data has
  // actually arrived.
  const [forecastCachedAgeMs, setForecastCachedAgeMs] = useState<number | null>(null);

  const [emissionsSnapshot, setEmissionsSnapshot] = useState<EmissionsSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  // Real day-over-day % change in total emissions (this 24h window's sum
  // vs the preceding 24h's), derived from the same 48h timeseries fetch
  // `emissionsSnapshot` uses -- backs Live Grid Status's "Compared to
  // yesterday" line. `null` until that fetch resolves with a real,
  // non-zero prior-day total to divide by.
  const [emissionsVsYesterdayPct, setEmissionsVsYesterdayPct] = useState<number | null>(null);
  // Real "Actual" demand history for the Demand Forecast Preview chart
  // -- see `DemandActualPoint`'s own comment. Derived from the exact
  // same 48h `fetchEmissionsTimeseries` call `emissionsSnapshot` above
  // uses, not a separate fetch. Same mount-effect `localStorage`
  // hydration as `forecastPreview` above (same hydration-mismatch
  // reasoning -- see that state's own comment).
  const [demandActual, setDemandActual] = useState<DemandActualPoint[] | null>(null);

  // Real last-7-real-days of `GET /v1/demand/summary`, one call per
  // calendar day -- backs the Renewable Share / Avg Wholesale Price KPI
  // cards' own sparkline + "vs yesterday" delta (today vs the previous
  // real day in this same series), same real-data-only basis every
  // other trend on this page already uses. `null` entries are real,
  // possible gaps (a day with no real readings), not zero-filled.
  const [dailySummary, setDailySummary] = useState<
    { renewablePct: number | null; priceMwh: number | null }[] | null
  >(null);

  const [liveGrid, setLiveGrid] = useState<LiveGridStatus | null>(null);
  const [liveGridError, setLiveGridError] = useState<string | null>(null);
  const liveGridFuels = useMemo(() => {
    if (!liveGrid) return null;
    return liveGrid.mix.items
      .filter((i) => i.total_generation_mwh > 0)
      .map((i) => ({
        name: formatFuelType(i.fuel_type),
        pct: i.pct_of_total_generation,
        mw: Math.round(i.total_generation_mwh / liveGrid.windowHours),
        color: fuelColor(i.fuel_type),
      }))
      .sort((a, b) => b.mw - a.mw);
  }, [liveGrid]);

  // Real `meta.anomalies` (ingestion), not a fabricated alerts feed --
  // this platform has no unified cross-domain alerting system, so this
  // is the closest honest substitute (same "closest real signal"
  // reasoning as "Data Quality Score"/"Open Risks" above). Labeled
  // "Recent Alerts" to match the reference layout, but scoped honestly
  // in its own subtitle.
  const [alerts, setAlerts] = useState<Anomaly[] | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);

  // Mount-only `localStorage` hydration for the Demand Forecast Preview
  // card (`forecastPreview`/`demandActual`/`forecastCachedAgeMs` all
  // start `null` above specifically so this runs after the same first
  // render on both server and client -- see those states' own comments).
  // Runs once, before the real fetch effect below starts (React runs
  // effects in declaration order within one commit), so a cached value
  // paints on the very next tick instead of the "Loading…" state ever
  // being visible when a usable cache entry exists. Deliberately doesn't
  // touch any other KPI/section on this page -- this is scoped to only
  // the two states that back this one card, per what was actually asked.
  useEffect(() => {
    const cachedForecast = getCached<ForecastPreview>(
      DEMAND_FORECAST_CACHE_KEY,
      DEMAND_PREVIEW_CACHE_MAX_AGE_MS,
    );
    if (cachedForecast) {
      setForecastPreview(cachedForecast);
      setForecastCachedAgeMs(getCachedAgeMs(DEMAND_FORECAST_CACHE_KEY));
    }
    const cachedActual = getCached<DemandActualPoint[]>(
      DEMAND_ACTUAL_CACHE_KEY,
      DEMAND_PREVIEW_CACHE_MAX_AGE_MS,
    );
    if (cachedActual) setDemandActual(cachedActual);
  }, []);

  // Every fetch below hits a real backend endpoint (forecast-api, plus
  // data-pipeline's one unauthenticated data-quality summary). "Data
  // Quality Score"/"Open Risks" are real ingestion/data-quality signals,
  // not sustainability-regulatory compliance or a risk register -- no
  // such domain exists anywhere in this platform, so those numbers are
  // the closest honest substitute, not what the KPI's old "Compliance
  // Score" label implied. See TODO.md's Frontend TODO.
  useEffect(() => {
    let cancelled = false;

    // Real month-to-date total, not YTD: `GET /v1/emissions/ytd` is
    // hardcoded to Jan-1-to-now server-side with no period param, so
    // this reuses `GET /v1/generation-mix` (already real, already used
    // below for the "Emissions by Source" donut) with an explicit
    // `since` at this real calendar month's start instead -- same real
    // `fct_generation_mix` rows, just summed over a real MTD window.
    const now = new Date();
    const monthStartIso = new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1)).toISOString();

    fetchGenerationMix(undefined, monthStartIso)
      .then((mix) => {
        if (cancelled) return;
        const mtdTco2e = mix.total_emissions_kgco2e / 1000;
        setKpis((prev) =>
          prev.map((k) =>
            k.label === "Total CO₂e (MTD)"
              ? { ...k, value: Math.round(mtdTco2e).toLocaleString() }
              : k,
          ),
        );
        setLiveKpiLabels((prev) => new Set(prev).add("Total CO₂e (MTD)"));
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

    // Real last-7-days daily `GET /v1/demand/summary` -- backs the
    // Renewable Share / Avg Wholesale Price KPI cards' own sparkline +
    // "vs yesterday" delta (today vs. the previous real day in this same
    // series). 7 separate one-day-window calls, not one 7-day call,
    // because the endpoint only ever returns a single period aggregate,
    // never a per-day breakdown.
    {
      const DAYS = 7;
      const dayBounds = Array.from({ length: DAYS }, (_, i) => {
        const end = new Date();
        end.setUTCHours(0, 0, 0, 0);
        end.setUTCDate(end.getUTCDate() - i);
        const start = new Date(end);
        start.setUTCDate(start.getUTCDate() - 1);
        return { since: start.toISOString(), until: end.toISOString() };
      }).reverse(); // oldest first, so the last entry is "today"

      Promise.all(
        dayBounds.map((d) =>
          fetchDemandSummary(d.since, d.until).catch(() => null),
        ),
      ).then((results) => {
        if (cancelled) return;
        const rows = results.map((r) => ({
          renewablePct: r?.renewable_share_pct ?? null,
          priceMwh: r?.avg_price_mwh ?? null,
        }));
        setDailySummary(rows);

        const today = rows[rows.length - 1];
        const yesterday = rows[rows.length - 2];
        if (today?.renewablePct != null && yesterday?.renewablePct != null && yesterday.renewablePct !== 0) {
          const d = ((today.renewablePct - yesterday.renewablePct) / yesterday.renewablePct) * 100;
          setKpis((prev) =>
            prev.map((k) =>
              k.label === "Renewable Share"
                ? { ...k, delta_pct: d, trend: d === 0 ? "flat" : d > 0 ? "up" : "down" }
                : k,
            ),
          );
        }
        if (today?.priceMwh != null && yesterday?.priceMwh != null && yesterday.priceMwh !== 0) {
          const d = ((today.priceMwh - yesterday.priceMwh) / yesterday.priceMwh) * 100;
          setKpis((prev) =>
            prev.map((k) =>
              k.label === "Avg Wholesale Price (YTD)"
                ? { ...k, delta_pct: d, trend: d === 0 ? "flat" : d > 0 ? "up" : "down" }
                : k,
            ),
          );
        }
      });
    }

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
    // the last 24 of a real 48h timeseries fetch; `gridIntensity` is a
    // real weighted average (sum emissions / sum generation) over those
    // same 24 hourly points, not a separately-fetched "current" value --
    // `renewablePct` needs a per-fuel breakdown the timeseries endpoint
    // doesn't carry, so it's the one extra call, scoped to the same 24h
    // window (not the wider default the "Emissions by Source" donut
    // uses) so the 3 stats describe the same period. The *preceding* 24h
    // (this same 48h fetch's first half) backs two real "vs yesterday"
    // comparisons that would otherwise need their own extra calls: the
    // Carbon Intensity KPI's delta and Live Grid Status's own footer --
    // one fetch, two honest reuses, not a fabricated pair of numbers.
    // Fetches 3 real days, not 2 -- `emissionsSnapshot`/"vs yesterday"
    // below only ever need the last 48h of this (unaffected by the
    // wider window, since both still slice relative to the *end* of
    // the array), but `demandActual` needs real history reaching back
    // far enough to fully precede the demand forecast's own real start
    // point even when that forecast is running behind live (real,
    // observed lag up to ~21h as of 2026-08-10) -- see `demandActual`'s
    // own setter below for exactly why.
    fetchEmissionsTimeseries("hour", 3)
      .then((series) => {
        if (cancelled || series.points.length === 0) return;
        const todayPoints = series.points.slice(-24);
        const yesterdayPoints = series.points.slice(
          Math.max(0, series.points.length - 48),
          series.points.length - 24,
        );
        const sumEmissions = (pts: typeof series.points) =>
          pts.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0);
        const sumGeneration = (pts: typeof series.points) =>
          pts.reduce((s, p) => s + (p.total_generation_mwh ?? 0), 0);

        const totalEmissions = sumEmissions(todayPoints);
        const totalGeneration = sumGeneration(todayPoints);
        const todayIntensity = totalGeneration ? totalEmissions / totalGeneration : 0;

        setEmissionsSnapshot({
          totalTco2e: Math.round(totalEmissions / 1000),
          gridIntensity: todayIntensity,
          renewablePct: 0,
          sparkline: todayPoints.map((p) => Math.round((p.total_emissions_kgco2e ?? 0) / 1000)),
          intensitySparkline: todayPoints.map((p) => Math.round(p.intensity_kgco2e_per_mwh ?? 0)),
          labels: todayPoints.map((p) => formatHourLabel(p.bucket)),
          fullLabels: todayPoints.map((p) => formatFullDateTime(p.bucket)),
          latestPointIso: todayPoints[todayPoints.length - 1].bucket,
        });
        // Full 3-day series, NOT sliced to the last 24h like
        // `emissionsSnapshot` above -- the Demand Forecast Preview
        // chart (see its own `alignedDemandActual` memo) needs to look
        // back far enough to find real actual points ending exactly at
        // the forecast's own real start, which can itself be well
        // behind live.
        const freshDemandActual = series.points
          .filter((p) => p.total_generation_mwh !== null)
          .map((p) => ({
            ts: p.bucket,
            tMs: new Date(p.bucket).getTime(),
            mw: Math.round(p.total_generation_mwh!),
          }));
        setDemandActual(freshDemandActual);
        setCached(DEMAND_ACTUAL_CACHE_KEY, freshDemandActual);

        if (yesterdayPoints.length > 0) {
          const yEmissions = sumEmissions(yesterdayPoints);
          const yGeneration = sumGeneration(yesterdayPoints);
          const yIntensity = yGeneration ? yEmissions / yGeneration : 0;

          if (yIntensity > 0) {
            const deltaPct = ((todayIntensity - yIntensity) / yIntensity) * 100;
            setKpis((prev) =>
              prev.map((k) =>
                k.label === "Carbon Intensity"
                  ? { ...k, delta_pct: deltaPct, trend: deltaPct === 0 ? "flat" : deltaPct > 0 ? "up" : "down" }
                  : k,
              ),
            );
          }
          if (yEmissions > 0) {
            setEmissionsVsYesterdayPct(((totalEmissions - yEmissions) / yEmissions) * 100);
          }
        }

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
        const freshForecastPreview: ForecastPreview = {
          current: Math.round(p50s[0]),
          peak: Math.round(Math.max(...p50s)),
          min: Math.round(Math.min(...p50s)),
          points: forecast.points.map((p) => ({
            ts: p.ts,
            tMs: new Date(p.ts).getTime(),
            p10: p.p10,
            p50: p.p50,
            p90: p.p90,
          })),
          horizonLabel: `next ${forecast.horizon}`,
          scope,
        };
        setForecastPreview(freshForecastPreview);
        setCached(DEMAND_FORECAST_CACHE_KEY, freshForecastPreview);
        setForecastCachedAgeMs(null);
      })
      .catch((err) => {
        if (!cancelled) setForecastError(err instanceof Error ? err.message : "failed to load");
      });

    // "Emissions Trend (compact)" -- real daily-bucketed actual
    // emissions, last 8 days, NEM-wide. No forecast band (see
    // `CompactTrendPoint`'s own comment).
    fetchEmissionsTimeseries("day", 8)
      .then((series) => {
        if (cancelled) return;
        setCompactTrend(
          series.points
            .filter((p) => p.total_emissions_kgco2e !== null)
            .map((p) => ({
              date: new Date(p.bucket).toLocaleDateString([], { month: "short", day: "2-digit" }),
              ts: p.bucket,
              actualTco2e: p.total_emissions_kgco2e! / 1000,
            })),
        );
      })
      .catch((err) => {
        if (!cancelled) setCompactTrendError(err instanceof Error ? err.message : "failed to load");
      });

    // "Emissions by Source" -- real last-24h, NEM-wide per-fuel-type
    // generation mix (`GET /v1/generation-mix`) -- see `emissionsBySource`'s
    // own comment for why this replaces the formerly-mock Scope 1/2/3
    // breakdown (no Scope 1/3 data source exists anywhere in this
    // platform; this is the closest honest substitute). Scoped to 24h
    // (not YTD, 2026-08-10) to match "Live Grid Status"/"Emissions
    // Snapshot"'s own real-time framing rather than a whole-year total.
    {
      const sourceUntilIso = new Date().toISOString();
      const sourceSinceIso = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      fetchGenerationMix(undefined, sourceSinceIso, sourceUntilIso)
        .then((mix) => {
          if (!cancelled) setGenerationMix(mix);
        })
        .catch((err) => {
          if (!cancelled) setGenerationMixError(err instanceof Error ? err.message : "failed to load");
        });
    }

    // "Live Grid Status" -- same `GET /v1/generation-mix` endpoint as
    // "Emissions by Source" above, just windowed to the last few hours
    // instead of YTD so the gauge + fuel list reflect what's generating
    // right now rather than the whole year. A single-hour window risks
    // an empty/still-landing latest bucket, so this widens to 6h (still
    // "recent", never mislabeled as instantaneous -- the card's own
    // subtitle discloses the exact window).
    const LIVE_WINDOW_HOURS = 6;
    const liveUntilIso = new Date().toISOString();
    const liveSinceIso = new Date(Date.now() - LIVE_WINDOW_HOURS * 60 * 60 * 1000).toISOString();
    fetchGenerationMix(undefined, liveSinceIso, liveUntilIso)
      .then((mix) => {
        if (!cancelled) setLiveGrid({ mix, windowHours: LIVE_WINDOW_HOURS });
      })
      .catch((err) => {
        if (!cancelled) setLiveGridError(err instanceof Error ? err.message : "failed to load");
      });

    // "Recent Alerts" -- real `meta.anomalies`, newest-detected first
    // (see `alerts`'s own comment above for why this stands in for a
    // unified alerts feed this platform doesn't have).
    fetchAnomalies({ limit: 4 })
      .then((res) => {
        if (cancelled) return;
        setAlerts(
          [...res.data].sort(
            (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime(),
          ),
        );
      })
      .catch((err) => {
        if (!cancelled) setAlertsError(err instanceof Error ? err.message : "failed to load");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Per-KPI sparkline data, real-fetch-backed only (see `KPI_SPARK_COLOR`'s
  // own comment for which four KPIs this covers and why the other two
  // don't get one). `dailySummary`'s two series are omitted entirely
  // (not zero-filled) if any real day in the window is missing, rather
  // than drawing a trendline through a fabricated gap-fill value.
  const kpiSparklines = useMemo(() => {
    const allPresent = (arr: (number | null)[]): arr is number[] => arr.every((v) => v !== null);
    const renewableSeries = dailySummary?.map((d) => d.renewablePct) ?? null;
    const priceSeries = dailySummary?.map((d) => d.priceMwh) ?? null;
    return {
      "Total CO₂e (MTD)": compactTrend ? compactTrend.map((d) => Math.round(d.actualTco2e)) : undefined,
      "Carbon Intensity": emissionsSnapshot?.intensitySparkline,
      "Renewable Share": renewableSeries && allPresent(renewableSeries) ? renewableSeries : undefined,
      "Avg Wholesale Price (YTD)": priceSeries && allPresent(priceSeries) ? priceSeries : undefined,
    } as Record<string, number[] | undefined>;
  }, [compactTrend, emissionsSnapshot, dailySummary]);

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
          <KpiCardWithDelay
            key={k.label}
            k={k}
            delay={i * 0.05}
            live={liveKpiLabels.has(k.label)}
            sparkline={kpiSparklines[k.label]}
          />
        ))}
      </div>

      {/* Demand Forecast Preview (wide) + Emissions Snapshot + Live Grid
          Status -- 2:1:1 layout matching the reference design's row. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <Card className="lg:col-span-2">
          <div data-testid="forecast-preview">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="flex items-center gap-1.5 text-base font-semibold text-white">
                  Demand Forecast Preview
                  <span
                    title={`Real ${forecastPreview?.scope ?? "NEM"} demand forecast (GET /v1/forecast) + real last-24h total generation as the "Actual" line`}
                  >
                    <Info className="h-3.5 w-3.5 text-white/40" />
                  </span>
                </h2>
                <p className="text-xs text-white/50">
                  P50 forecast with P10 – P90 range
                  {forecastPreview && forecastPreview.scope !== "NEM" ? ` · ${forecastPreview.scope} only` : ""}
                  {forecastCachedAgeMs !== null && (
                    <span
                      className="ml-1 text-white/30"
                      title="Showing a cached value from your browser's localStorage while a fresh forecast loads in the background"
                    >
                      · cached {formatRelativeTime(new Date(Date.now() - forecastCachedAgeMs).toISOString())}
                    </span>
                  )}
                </p>
              </div>
            </div>
            {forecastPreview === null ? (
              <p className="py-8 text-center text-xs text-white/40">
                {forecastError ? `Unavailable — ${forecastError}` : "Loading…"}
              </p>
            ) : (
              <>
                <div className="mb-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <KpiMini label="Current (P50)" value={`${forecastPreview.current.toLocaleString()} MW`} />
                  <KpiMini label={`Peak in ${forecastPreview.horizonLabel}`} value={`${forecastPreview.peak.toLocaleString()} MW`} />
                  <KpiMini label={`Min in ${forecastPreview.horizonLabel}`} value={`${forecastPreview.min.toLocaleString()} MW`} />
                </div>
                <div className="mb-3 flex flex-wrap items-center gap-4 text-[11px] text-white/65">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-1.5 w-3 rounded-full border border-dashed border-emerald-100/50" /> P10 (Lower)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-0.5 w-3 rounded-full bg-emerald-300" /> P50 (Median)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-1.5 w-3 rounded-full border border-dashed border-emerald-100/50" /> P90 (Upper)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-0.5 w-3 rounded-full bg-white" /> Actual
                  </span>
                </div>
                <DemandForecastChart actual={demandActual ?? []} forecast={forecastPreview.points} />
                <Link
                  href="/dashboard/forecast/"
                  className="mt-3 flex w-full items-center justify-between rounded-md border border-white/5 bg-white/[0.02] px-3 py-2 text-left text-[11px] text-white/70 hover:bg-white/[0.05]"
                  data-testid="forecast-preview-link"
                >
                  <span>
                    Forecasts are probabilistic and calibrated.{" "}
                    <span className="text-emerald-100">See details</span>
                  </span>
                  <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              </>
            )}
          </div>
        </Card>

        {/* Emissions preview — quick view of 24h emissions, as 3
            stacked mini-stat boxes (matching the reference design). */}
        <Card>
          <div data-testid="emissions-preview">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-white">Emissions Snapshot</h2>
                <p className="text-xs text-white/50">most recent 24 real hours · Scope 2 (grid)</p>
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
              <div className="space-y-3">
                <SnapshotStatBox
                  icon={Cloud}
                  label="Total (Scope 2)"
                  value={`${emissionsSnapshot.totalTco2e.toLocaleString()} tCO₂e`}
                  sparkline={emissionsSnapshot.sparkline}
                  labels={emissionsSnapshot.labels}
                  fullLabels={emissionsSnapshot.fullLabels}
                  unit="tCO₂e/h"
                  testId="emissions-sparkline"
                />
                <SnapshotStatBox
                  icon={Zap}
                  label="Grid intensity"
                  value={`${Math.round(emissionsSnapshot.gridIntensity).toLocaleString()} g/kWh`}
                  sparkline={emissionsSnapshot.intensitySparkline}
                  labels={emissionsSnapshot.labels}
                  fullLabels={emissionsSnapshot.fullLabels}
                  unit="g/kWh"
                />
                <SnapshotStatBox
                  icon={Wind}
                  label="Renewable %"
                  value={`${emissionsSnapshot.renewablePct.toFixed(1)}%`}
                />
                {(() => {
                  // Real staleness disclosure -- this card's sparklines plot
                  // points index-by-index (see `EmissionsSnapshot.
                  // latestPointIso`'s own comment), so a real ingestion gap
                  // never shows up as a visible break the way `RealEmissions
                  // Trend`'s Actual line does; it just silently shifts this
                  // "most recent 24h" window further behind true now. 90min
                  // threshold matches `RealEmissionsTrend`'s own real-gap
                  // convention (`GAP_THRESHOLD_MS`).
                  const staleMs = Date.now() - new Date(emissionsSnapshot.latestPointIso).getTime();
                  if (staleMs <= 90 * 60 * 1000) return null;
                  return (
                    <p className="flex items-center gap-1.5 text-[11px] text-amber-200/80">
                      <Info className="h-3 w-3" />
                      Most recent real reading is from {formatRelativeTime(emissionsSnapshot.latestPointIso)}
                      , not this instant — real ingestion is currently behind live.
                    </p>
                  );
                })()}
              </div>
            )}
          </div>
        </Card>

        {/* Live Grid Status — recent-window generation mix (see
            `LiveGridStatus`'s own comment for exactly how "live" this
            is). Gauge value reuses the Demand Forecast Preview's own
            P50 nowcast rather than issuing a second, differently-scoped
            "current demand" call. */}
        <Card>
          <div data-testid="live-grid-status">
            <div className="mb-1 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Live Grid Status</h2>
            </div>
            <p className="mb-3 text-xs text-white/50">
              {liveGrid ? `Fuel mix · last ${liveGrid.windowHours}h avg` : "Fuel mix · recent"}
            </p>
            {forecastPreview && (
              <div className="flex justify-center">
                <ArcGauge
                  value={forecastPreview.current}
                  max={Math.ceil((Math.max(forecastPreview.peak, forecastPreview.current) * 1.25) / 5000) * 5000}
                  label={`${forecastPreview.current.toLocaleString()} MW`}
                  sub="Current demand (P50 nowcast)"
                  size={200}
                />
              </div>
            )}
            {/* Same 24h emissions snapshot the "Emissions Snapshot" card
                shows, repeated here -- intentional, not a copy/paste
                leftover: this card is meant to be a self-contained "grid
                status at a glance" panel, so it carries the same 3 real
                stats alongside the fuel mix rather than requiring a
                glance at the card next to it. */}
            {emissionsSnapshot && (
              <div className="mt-4 space-y-2.5 border-t border-white/5 pt-3">
                <GridMiniStatRow
                  icon={Cloud}
                  label="Total emissions (24h)"
                  value={`${emissionsSnapshot.totalTco2e.toLocaleString()} tCO₂e`}
                  sparkline={emissionsSnapshot.sparkline}
                  color="#34d399"
                />
                <GridMiniStatRow
                  icon={Zap}
                  label="Grid intensity (avg)"
                  value={`${Math.round(emissionsSnapshot.gridIntensity).toLocaleString()} g/kWh`}
                  sparkline={emissionsSnapshot.intensitySparkline}
                  color="#fbbf24"
                />
                <GridMiniStatRow
                  icon={Wind}
                  label="Renewable %"
                  value={`${emissionsSnapshot.renewablePct.toFixed(1)}%`}
                  color="#c4b5fd"
                />
              </div>
            )}
            {liveGridFuels === null ? (
              <p className="py-8 text-center text-xs text-white/40">
                {liveGridError ? `Unavailable — ${liveGridError}` : "Loading…"}
              </p>
            ) : (
              <ul className="mt-1 space-y-1 text-xs">
                {liveGridFuels.map((f) => (
                  <li key={f.name} className="flex items-center justify-between py-0.5">
                    <span className="flex items-center gap-1.5 text-white/70">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: f.color }} />
                      {f.name}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-white/50">{f.pct.toFixed(1)}%</span>
                      <span className="w-16 text-right font-mono text-white/80">
                        {f.mw.toLocaleString()} MW
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-3 text-xs">
              <span className="text-white/50">
                Compared to yesterday
                {emissionsVsYesterdayPct !== null && (
                  <span
                    className={cn(
                      "ml-1.5 inline-flex items-center gap-0.5 font-medium",
                      emissionsVsYesterdayPct <= 0 ? "text-emerald-200" : "text-rose-200",
                    )}
                  >
                    {emissionsVsYesterdayPct <= 0 ? (
                      <ArrowDownRight className="h-3 w-3" />
                    ) : (
                      <ArrowUpRight className="h-3 w-3" />
                    )}
                    {Math.abs(emissionsVsYesterdayPct).toFixed(1)}%
                  </span>
                )}
              </span>
              <Link href="/dashboard/carbon/" className="text-emerald-100 hover:underline">
                View Generation Mix →
              </Link>
            </div>
          </div>
        </Card>
      </div>

      {/* Real Emissions Trend (2026-08-10) -- replaces the formerly-mock
          EmissionsTrendV2; see RealEmissionsTrend's own header comment
          for the real data sources and the disclosed forecast-lag
          signal. */}
      <RealEmissionsTrend />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <Card className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Emission History</h2>
              <p className="text-xs text-white/50">
                Daily total emissions (tCO₂e, real) + real historical forecast confidence band
              </p>
            </div>
            <div className="flex items-center gap-1 rounded-full border border-white/10 bg-white/5 p-0.5">
              {(Object.keys(PERIOD_DAYS) as TrendPeriod[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setTrendPeriod(p)}
                  className={cn(
                    "rounded-full px-2.5 py-1 text-[10px] font-semibold transition",
                    trendPeriod === p ? "bg-white/10 text-white" : "text-white/55 hover:text-white/85",
                  )}
                  data-testid={`emissions-trend-compact-period-${p}`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          {periodTrend === null ? (
            <p className="py-16 text-center text-xs text-white/40">
              {periodTrendError ? `Unavailable — ${periodTrendError}` : "Loading…"}
            </p>
          ) : (
            <>
              <CompactTrendChart data={periodTrendWithBand ?? periodTrend} />
              {PERIOD_DAYS[trendPeriod] > HISTORICAL_BAND_DAYS && (
                <p className="mt-2 flex items-center gap-1.5 text-[11px] text-white/40">
                  <Info className="h-3 w-3" />
                  The forecast confidence band only covers the most recent {HISTORICAL_BAND_DAYS} real
                  days — a real walk-forward re-forecast that wide gets expensive fast (confirmed
                  live: 30 real days took ~50s to compute).
                </p>
              )}
              {periodTrendStats && (
                <div className="mt-4 grid grid-cols-2 gap-4 border-t border-white/5 pt-4 text-[11px] md:grid-cols-4">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-white/50">Avg ({trendPeriod})</div>
                    <div className="mt-1 text-sm font-semibold text-white">
                      {Math.round(periodTrendStats.avg).toLocaleString()} tCO₂e
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-white/50">vs previous {trendPeriod}</div>
                    <div className="mt-1 flex items-center gap-1 text-sm font-semibold text-white">
                      {periodTrendStats.deltaPct === null ? (
                        "—"
                      ) : (
                        <>
                          {periodTrendStats.deltaPct <= 0 ? (
                            <ArrowDownRight className="h-3.5 w-3.5 text-emerald-200" />
                          ) : (
                            <ArrowUpRight className="h-3.5 w-3.5 text-rose-200" />
                          )}
                          {periodTrendStats.deltaPct >= 0 ? "+" : ""}
                          {periodTrendStats.deltaPct.toFixed(1)}%
                        </>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-white/50">Lowest Day</div>
                    <div className="mt-1 text-sm font-semibold text-white">{periodTrendStats.lowest.date}</div>
                    <div className="text-[10px] text-white/45">
                      {Math.round(periodTrendStats.lowest.actualTco2e).toLocaleString()} tCO₂e
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-white/50">Highest Day</div>
                    <div className="mt-1 text-sm font-semibold text-white">{periodTrendStats.highest.date}</div>
                    <div className="text-[10px] text-white/45">
                      {Math.round(periodTrendStats.highest.actualTco2e).toLocaleString()} tCO₂e
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>

        {/* Recent Alerts — real anomalies feed (see `alerts`'s own
            comment above on why this substitutes for a dedicated
            cross-platform alerting system this app doesn't have). */}
        <Card>
          <div className="mb-1 flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Recent Alerts</h2>
            <Link href="/dashboard/data-quality/" className="text-xs text-emerald-100 hover:underline">
              View all →
            </Link>
          </div>
          <p className="mb-2 text-xs text-white/50">Data-quality &amp; ingestion anomalies</p>
          {alerts === null ? (
            <p className="py-16 text-center text-xs text-white/40">
              {alertsError ? `Unavailable — ${alertsError}` : "Loading…"}
            </p>
          ) : alerts.length === 0 ? (
            <p className="py-16 text-center text-xs text-white/40">No recent anomalies.</p>
          ) : (
            <ul className="divide-y divide-white/5">
              {alerts.map((a) => (
                <AlertRow key={a.id} a={a} />
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Emissions by Source</h2>
          <p className="mb-3 -mt-2 text-xs text-white/50">
            Last 24 hours, by fuel type (Scope 2 grid electricity — no Scope 1/3 source exists in
            this platform)
          </p>
          {emissionsBySource === null ? (
            <p className="py-16 text-center text-xs text-white/40">
              {generationMixError ? `Unavailable — ${generationMixError}` : "Loading…"}
            </p>
          ) : (
            <DonutSimple slices={emissionsBySource} total={emissionsBySourceTotal} unit="tCO₂e" />
          )}
        </Card>
      </div>

    </div>
  );
}

function KpiCardWithDelay({
  k, delay, live, sparkline,
}: { k: ExecutiveKpi; delay: number; live: boolean; sparkline?: number[] }) {
  return (
    <KpiCard k={k} live={live} sparkline={sparkline} key={k.label + delay} />
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
 * CompactTrendChart — animated area chart for the "Emission History"
 * panel: real actual line + an optional real derived forecast confidence
 * band (see `CompactTrendPoint`'s own comment for the full methodology
 * -- real historical demand-backtest quantiles × real historical grid
 * intensity, not fabricated). Ported from the v18x prototype's own
 * simple inline `MiniChart(data)` layout, but real data since the
 * 2026-08-08 cutover -- `data` is real `fetchEmissionsTimeseries` points
 * (`periodTrend`/`compactTrend`), not `getEmissionsTrend()`'s mock
 * (unused anywhere in this file now). Distinct from `RealEmissionsTrend`
 * -- this one is deliberately simpler (no region/horizon selectors),
 * matching the reference screenshot's smaller bottom-left panel.
 */
function CompactTrendChart({ data }: { data: CompactTrendPoint[] }) {
  const reduced = useReducedMotion();
  const gradId = useId().replace(/:/g, "");
  const w = 720, h = 200, padL = 40, padR = 8, padT = 8, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const yMax =
    Math.max(...data.map((d) => Math.max(d.actualTco2e, d.forecastP90Tco2e ?? 0)), 1) * 1.1;
  const stepX = innerW / Math.max(1, data.length - 1);
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const actualPath = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.actualTco2e).toFixed(1)}`).join(" ");
  const areaPath = `${actualPath} L ${x(data.length - 1).toFixed(1)} ${padT + innerH} L ${x(0).toFixed(1)} ${padT + innerH} Z`;

  // Real forecast band -- only the (in practice contiguous, most-recent)
  // days `historicalForecastByDate` actually covers carry these fields;
  // every other day is plotted as real actual-only, same as before.
  const bandPoints = data
    .map((d, i) => ({ i, d }))
    .filter(
      (
        p,
      ): p is { i: number; d: CompactTrendPoint & { forecastP10Tco2e: number; forecastP50Tco2e: number; forecastP90Tco2e: number } } =>
        p.d.forecastP10Tco2e !== undefined && p.d.forecastP50Tco2e !== undefined && p.d.forecastP90Tco2e !== undefined,
    );
  const bandAreaPath =
    bandPoints.length > 0
      ? [
          ...bandPoints.map(({ i, d }, j) => `${j === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.forecastP90Tco2e).toFixed(1)}`),
          ...[...bandPoints].reverse().map(({ i, d }) => `L ${x(i).toFixed(1)} ${y(d.forecastP10Tco2e).toFixed(1)}`),
          "Z",
        ].join(" ")
      : "";
  const forecastP50Path = bandPoints
    .map(({ i, d }, j) => `${j === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.forecastP50Tco2e).toFixed(1)}`)
    .join(" ");

  // Real peak/low day, highlighted with a bigger marker -- ties (more
  // than one day sharing the exact max/min) highlight every matching
  // day rather than arbitrarily picking one.
  const maxVal = Math.max(...data.map((d) => d.actualTco2e));
  const minVal = Math.min(...data.map((d) => d.actualTco2e));

  // Longer real windows (15D/30D) can't label every single day without
  // the axis becoming unreadable -- thin to roughly the same visual
  // density the 7D view already has.
  const labelEvery = data.length > 45 ? 15 : data.length > 14 ? 5 : 1;

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || data.length === 0) return;
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

  // Same real edge-clipping fix `RealEmissionsTrend`'s own tooltip
  // needed (2026-08-11): centering on the cursor pushed the tooltip
  // partly outside this card's `overflow-hidden` bounds near either
  // edge of the chart. Clamped to stay fully on-screen everywhere.
  const TOOLTIP_WIDTH_PX = 190; // matches this tooltip's own `min-w-[180px]` below, plus margin
  const tooltipContainerWidth = wrapRef.current?.clientWidth ?? w;
  const tooltipLeft = hover
    ? Math.min(
        Math.max(hover.x, TOOLTIP_WIDTH_PX / 2),
        Math.max(TOOLTIP_WIDTH_PX / 2, tooltipContainerWidth - TOOLTIP_WIDTH_PX / 2),
      )
    : 0;

  if (data.length === 0) {
    return <p className="py-16 text-center text-xs text-white/40">No real data for this window yet.</p>;
  }

  return (
    <>
      {bandPoints.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-3 text-[10px] text-white/55">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-3 rounded-full bg-emerald-300" /> Actual
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-3 rounded-full border-t-2 border-dashed border-sky-300" /> Forecast (P50)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-3.5 rounded-sm border border-sky-300/40 bg-sky-300/15" /> P10-P90
          </span>
        </div>
      )}
      <div ref={wrapRef} className="relative" data-testid="emissions-trend-compact-chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-48 w-full">
        <defs>
          <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <g key={i}>
            <line x1={padL} x2={w - padR} y1={padT + p * innerH} y2={padT + p * innerH} stroke="rgba(255,255,255,0.05)" />
            <text x={padL - 6} y={padT + p * innerH + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.4)">
              {Math.round((1 - p) * yMax / 1000).toLocaleString()}k
            </text>
          </g>
        ))}

        {bandAreaPath && (
          <m.path
            d={bandAreaPath}
            fill="rgba(56,189,248,0.16)"
            stroke="none"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            data-testid="emissions-trend-compact-forecast-band"
          />
        )}
        {forecastP50Path && (
          <m.path
            d={forecastP50Path}
            fill="none"
            stroke="#7dd3fc"
            strokeWidth={1.75}
            strokeDasharray="6 4"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.9, delay: 0.3, ease: "easeInOut" }}
          />
        )}

        <m.path
          d={areaPath}
          fill={`url(#${gradId})`}
          stroke="none"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6 }}
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
        {data.map((d, i) => {
          const isPeak = d.actualTco2e === maxVal;
          const isLow = d.actualTco2e === minVal;
          return (
            <m.circle
              key={d.date}
              cx={x(i)}
              cy={y(d.actualTco2e)}
              r={isPeak || isLow ? 4.5 : 3}
              fill={isLow ? "#0a1410" : "#34d399"}
              stroke={isLow ? "#34d399" : "none"}
              strokeWidth={isLow ? 1.5 : 0}
              initial={reduced ? false : { scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 20, delay: reduced ? 0 : 0.6 + i * 0.06 }}
            />
          );
        })}
        {data.map((d, i) => (
          (i % labelEvery === 0 || i === data.length - 1) && (
            <text key={d.date} x={x(i)} y={h - 8} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">
              {d.date}
            </text>
          )
        ))}
        {hover && hoverPoint && (
          <m.g initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.1 }}>
            <line x1={x(hover.idx)} x2={x(hover.idx)} y1={padT} y2={padT + innerH} stroke="rgba(132,204,22,0.4)" strokeWidth={0.5} strokeDasharray="2 2" />
            <circle cx={x(hover.idx)} cy={y(hoverPoint.actualTco2e)} r={5} fill="#34d399" stroke="#0a1410" strokeWidth={1.5} />
            {hoverPoint.forecastP50Tco2e !== undefined && (
              <circle cx={x(hover.idx)} cy={y(hoverPoint.forecastP50Tco2e)} r={5} fill="#0a1410" stroke="#7dd3fc" strokeWidth={2} />
            )}
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
            style={{ left: tooltipLeft, top: hover.y }}
            data-testid="emissions-trend-compact-tooltip"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">{hoverLabel}</div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
              <span className="text-white/65">Actual</span>
              <span className="ml-auto font-mono font-medium text-white">
                {hoverPoint.actualTco2e.toLocaleString(undefined, { maximumFractionDigits: 0 })} tCO₂e
              </span>
            </div>
            {hoverPoint.forecastP50Tco2e !== undefined && (
              <>
                <div className="flex items-center gap-2 py-0.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-300" />
                  <span className="text-white/65">Forecast P50</span>
                  <span className="ml-auto font-mono font-medium text-white">
                    {hoverPoint.forecastP50Tco2e.toLocaleString(undefined, { maximumFractionDigits: 0 })} tCO₂e
                  </span>
                </div>
                <div className="flex items-center gap-2 py-0.5">
                  <span className="h-1.5 w-1.5 rounded-full border border-sky-300/40" />
                  <span className="text-white/65">Forecast P10-P90</span>
                  <span className="ml-auto font-mono text-white/80">
                    {hoverPoint.forecastP10Tco2e?.toLocaleString(undefined, { maximumFractionDigits: 0 })} –{" "}
                    {hoverPoint.forecastP90Tco2e?.toLocaleString(undefined, { maximumFractionDigits: 0 })} tCO₂e
                  </span>
                </div>
              </>
            )}
          </m.div>
        )}
      </AnimatePresence>
      </div>
    </>
  );
}

/**
 * DonutSimple — animated ring with hover-to-highlight slices and tooltip.
 */
function DonutSimple({
  slices, total, unit,
}: {
  slices: { name: string; pct: number; tco2e: number; color: string; category?: string }[];
  total: string;
  unit: string;
}) {
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
            {slices.length > 0 && (
              <div className="mt-0.5 text-[10px] text-white/60">
                <span className="font-semibold" style={{ color: slices[0].color }}>
                  {slices[0].name}
                </span>{" "}
                {slices[0].pct.toFixed(1)}%
              </div>
            )}
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
              <span className="flex items-start gap-2">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: s.color }} />
                <span>
                  <span className="block">{s.name}</span>
                  {s.category && (
                    <span className="block text-[10px] capitalize text-white/40">
                      {s.category} · {s.tco2e.toLocaleString()} t
                    </span>
                  )}
                </span>
              </span>
              <span className="flex flex-col items-end gap-1">
                <span className="text-white/60">{s.pct.toFixed(1)}%</span>
                <span className="h-1 w-14 overflow-hidden rounded-full bg-white/5">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${Math.min(100, s.pct)}%`, background: s.color }}
                  />
                </span>
              </span>
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

/**
 * GridMiniStatRow — compact icon + label/value + trendline row for Live
 * Grid Status's own copy of the Emissions Snapshot stats. Deliberately
 * non-interactive (`MiniTrendline`, not the full hover-tooltip
 * `Sparkline`) -- this is the second, decorative appearance of this
 * data on the page, so it doesn't need its own hover affordance.
 */
function GridMiniStatRow({
  icon: Icon,
  label,
  value,
  sparkline,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sparkline?: number[];
  color: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5 text-white/70">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wider text-white/50">{label}</div>
        <div className="text-sm font-semibold text-white">{value}</div>
      </div>
      {sparkline && sparkline.length >= 2 && (
        <div className="w-20 shrink-0">
          <MiniTrendline data={sparkline} color={color} />
        </div>
      )}
    </div>
  );
}

/**
 * SnapshotStatBox — one bordered mini-stat row for the "Emissions
 * Snapshot" panel's stacked layout: icon + label + value, with an
 * optional inline sparkline underneath. `sparkline` omitted (Renewable
 * %) renders the value alone -- there's no real per-hour renewable-share
 * series fetched for this window (see `emissionsSnapshot`'s own
 * comment), so this deliberately doesn't fabricate one.
 */
function SnapshotStatBox({
  icon: Icon,
  label,
  value,
  sparkline,
  labels,
  fullLabels,
  unit,
  testId,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sparkline?: number[];
  labels?: string[];
  fullLabels?: string[];
  unit?: string;
  testId?: string;
}) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.015] p-3">
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-emerald-200/10 text-emerald-100">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="text-[10px] uppercase tracking-wide text-white/50">{label}</span>
      </div>
      <div className="mt-1 text-lg font-bold text-white">{value}</div>
      {sparkline && labels && (
        <Sparkline
          data={sparkline}
          labels={labels}
          fullLabels={fullLabels}
          unit={unit ?? ""}
          strokeColor="#34d399"
          testId={testId}
          padLabels
        />
      )}
    </div>
  );
}

const ALERT_SEVERITY_STYLES: Record<AnomalySeverity, { label: string; className: string }> = {
  high:   { label: "High",   className: "border-rose-300/40 bg-rose-300/10 text-rose-200" },
  medium: { label: "Medium", className: "border-amber-300/40 bg-amber-300/10 text-amber-200" },
  low:    { label: "Low",    className: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" },
};

/** "Recent Alerts" row -- real `Anomaly` (see `alerts`'s own comment).
 * Title is derived from `reason`'s own kind prefix (the only structure
 * that field has -- see data-quality page's `REASON_KIND_FILTERS`),
 * falling back to the raw `source` if the prefix isn't one of the 4
 * known kinds. */
// Icon per real reason-kind prefix (the only 4 that exist in
// `meta.anomalies`, same vocabulary `data-quality/page.tsx`'s own
// `REASON_KIND_FILTERS` uses) -- purely presentational variety, not a
// claim about severity; falls back to `AlertTriangle` for anything else.
const ALERT_KIND_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  missing_value: Database,
  out_of_range: AlertCircle,
  statistical_outlier: TrendingUp,
  ml_outlier: AlertTriangle,
};

function AlertRow({ a }: { a: Anomaly }) {
  const sev = ALERT_SEVERITY_STYLES[a.severity];
  const kindRaw = a.reason.split(":")[0]?.trim();
  const kind = kindRaw?.replace(/_/g, " ");
  const title = kind && kind.length < 40 ? kind.replace(/^\w/, (c) => c.toUpperCase()) : a.source;
  const Icon = (kindRaw ? ALERT_KIND_ICONS[kindRaw] : undefined) ?? AlertTriangle;
  return (
    <li className="flex items-start gap-2.5 py-2">
      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-rose-300/10 text-rose-200">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-xs font-medium text-white/90">{title}</p>
          <span className={cn("shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium", sev.className)}>
            {sev.label}
          </span>
        </div>
        <p className="truncate text-[11px] text-white/50">{a.reason}</p>
        <p className="mt-0.5 text-[10px] text-white/35">{formatRelativeTime(a.detected_at)}</p>
      </div>
    </li>
  );
}
