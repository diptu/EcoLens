/**
 * /dashboard/executive — Executive Dashboard
 * CFO/CEO view: high-level KPIs, emissions trend, and emissions by source.
 * All charts are animated with Framer Motion and show details on hover.
 */
"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  ArrowDownRight, ArrowUpRight, Briefcase,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getExecutiveKpis, getEmissionsBySource, getExecutiveTrend,
  type ExecutiveKpi,
} from "@/lib/dashboards";
import {
  fetchYtdEmissions, fetchCurrentEmissions, fetchEmissionsTimeseries,
  fetchGenerationMix, fetchDemandSummary, fetchDemandForecast,
  formatFuelType, fuelColor,
} from "@/lib/emissions";
import { fetchPublicDataQualitySummary } from "@/lib/data-quality";
import type { EmissionsTrendPoint } from "@/lib/admin-dashboard";

function formatHourLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function KpiCard({ k }: { k: ExecutiveKpi }) {
  const isGood = (k.trend === k.good_when) || (k.trend === "flat");
  return (
    <m.div
      className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
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

const MOCK_FORECAST_PREVIEW = {
  current: 6840,
  peak: 8920,
  min: 4120,
  sparkline: [6800, 7200, 7600, 8200, 8920, 8500, 7400, 5800],
  labels: ["now", "+30m", "+1h", "+1h30", "+2h", "+2h30", "+3h", "+4h"],
  horizonLabel: "next 4 hours",
};

const MOCK_EMISSIONS_SNAPSHOT = {
  totalTco2e: 1284,
  gridIntensity: 612,
  renewablePct: 38.6,
  sparkline: [52, 48, 55, 62, 58, 50, 45, 51, 49, 53, 47, 56, 60, 55, 50, 44, 48, 52, 58, 62, 58, 53, 50, 49],
  labels: ["00h", "02h", "04h", "06h", "08h", "10h", "12h", "14h", "16h", "18h", "20h", "22h", "24h", "", "", "", "", "", "", "", "", "", "", "", ""],
};

export default function ExecutiveDashboardPage() {
  const [kpis, setKpis] = useState<ExecutiveKpi[]>(() => getExecutiveKpis());
  const [source, setSource] = useState(() => getEmissionsBySource());
  const [sourceTotal, setSourceTotal] = useState("125,340");
  const [sourceHeading, setSourceHeading] = useState("Emissions by Source");
  const [trend, setTrend] = useState<EmissionsTrendPoint[]>(() => getExecutiveTrend());
  const [forecastPreview, setForecastPreview] = useState(MOCK_FORECAST_PREVIEW);
  const [emissionsSnapshot, setEmissionsSnapshot] = useState(MOCK_EMISSIONS_SNAPSHOT);

  // Every fetch below hits a real backend endpoint (forecast-api, plus
  // data-pipeline's one unauthenticated data-quality summary). Each is
  // independent and fails soft -- if the backend is unreachable (e.g.
  // not running in dev, or during a static e2e preview with no backend
  // at all) the mock placeholder for that section stays put instead of
  // showing a broken card. "Data Quality Score"/"Open Risks" are real
  // ingestion/data-quality signals, not sustainability-regulatory
  // compliance or a risk register -- no such domain exists anywhere in
  // this platform, so those numbers are the closest honest substitute,
  // not what the KPI's old "Compliance Score" label implied. See
  // TODO.md's Frontend TODO.
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
      })
      .catch(() => {});

    fetchGenerationMix()
      .then((mix) => {
        if (cancelled || mix.items.length === 0) return;
        setSource(
          mix.items.map((item) => ({
            name: formatFuelType(item.fuel_type),
            pct: mix.total_emissions_kgco2e
              ? (item.total_emissions_kgco2e / mix.total_emissions_kgco2e) * 100
              : 0,
            tco2e: Math.round(item.total_emissions_kgco2e / 1000),
            color: fuelColor(item.fuel_type),
          })),
        );
        setSourceTotal(Math.round(mix.total_emissions_kgco2e / 1000).toLocaleString());
        setSourceHeading("Grid Electricity by Fuel Type");
      })
      .catch(() => {});

    fetchEmissionsTimeseries("day", 8)
      .then((series) => {
        if (cancelled || series.points.length === 0) return;
        // Every point here is a measured historical fact, not a
        // projection -- there's no real day-level forecast to show a
        // P10-P90 band against (the model's own horizon tops out at
        // ~24h), so the band collapses to the actual value rather than
        // fabricate an uncertainty range that doesn't exist.
        setTrend(
          series.points.map((p) => {
            const actual = Math.round((p.total_emissions_kgco2e ?? 0) / 1000);
            return {
              date: p.bucket.slice(0, 10),
              actual,
              forecast_p10: actual,
              forecast_p50: actual,
              forecast_p90: actual,
            };
          }),
        );
      })
      .catch(() => {});

    fetchEmissionsTimeseries("hour", 1)
      .then((series) => {
        if (cancelled || series.points.length === 0) return;
        setEmissionsSnapshot((prev) => ({
          ...prev,
          totalTco2e: Math.round(
            series.points.reduce((sum, p) => sum + (p.total_emissions_kgco2e ?? 0), 0) / 1000,
          ),
          sparkline: series.points.map((p) => Math.round((p.total_emissions_kgco2e ?? 0) / 1000)),
          labels: series.points.map((p) => formatHourLabel(p.bucket)),
        }));
      })
      .catch(() => {});

    fetchDemandForecast("NEM")
      .then((forecast) => {
        if (cancelled || forecast.points.length === 0) return;
        const p50s = forecast.points.map((p) => p.p50);
        setForecastPreview({
          current: Math.round(p50s[0]),
          peak: Math.round(Math.max(...p50s)),
          min: Math.round(Math.min(...p50s)),
          sparkline: p50s,
          labels: forecast.points.map((p) => formatHourLabel(p.ts)),
          horizonLabel: `next ${forecast.horizon}`,
        });
      })
      .catch(() => {});

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
          <KpiCardWithDelay key={k.label} k={k} delay={i * 0.05} />
        ))}
      </div>

      {/* Forecast preview — quick view of next 4h demand */}
      <Card>
        <div data-testid="forecast-preview">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Demand Forecast Preview</h2>
              <p className="text-xs text-white/50">{forecastPreview.horizonLabel} · P10 / P50 / P90</p>
            </div>
            <Link href="/dashboard/forecast/" className="inline-flex items-center gap-1 text-xs text-emerald-100 hover:underline" data-testid="forecast-preview-link">
              View full forecast →
            </Link>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <KpiMini label="Current (P50)" value={`${forecastPreview.current.toLocaleString()} MW`} />
            <KpiMini label="Peak in next 4h" value={`${forecastPreview.peak.toLocaleString()} MW`} />
            <KpiMini label="Min in next 4h" value={`${forecastPreview.min.toLocaleString()} MW`} />
          </div>
          <Sparkline
            data={forecastPreview.sparkline}
            labels={forecastPreview.labels}
            unit="MW"
            strokeColor="#34d399"
            testId="forecast-sparkline"
          />
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
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <KpiMini label="Total (Scope 2)" value={`${emissionsSnapshot.totalTco2e.toLocaleString()} tCO₂e`} />
            <KpiMini label="Grid intensity" value={`${Math.round(emissionsSnapshot.gridIntensity).toLocaleString()} g/kWh`} />
            <KpiMini label="Renewable %" value={`${emissionsSnapshot.renewablePct.toFixed(1)}%`} />
          </div>
          <Sparkline
            data={emissionsSnapshot.sparkline}
            labels={emissionsSnapshot.labels}
            unit="tCO₂e/h"
            strokeColor="#34d399"
            testId="emissions-sparkline"
            padLabels
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Emissions Trend</h2>
              <p className="text-xs text-white/50">8-day rolling tCO₂e, actual</p>
            </div>
          </div>
          <div className="mb-3 flex items-center gap-4 text-xs text-white/60">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-full bg-emerald-300" /> Actual
            </span>
          </div>
          <MiniChart data={trend} />
        </Card>

        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">{sourceHeading}</h2>
          <DonutSimple slices={source} total={sourceTotal} unit="tCO₂e" />
        </Card>
      </div>
    </div>
  );
}

function KpiCardWithDelay({ k, delay }: { k: ExecutiveKpi; delay: number }) {
  return (
    <KpiCard k={k} key={k.label + delay} />
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
  unit,
  strokeColor,
  testId,
  padLabels = false,
}: {
  data: number[];
  labels: string[];
  unit: string;
  strokeColor: string;
  testId?: string;
  padLabels?: boolean;
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

  const hoverLabel = hover ? labels[hover.idx] : null;
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
      {/* Labels */}
      <div className="mt-2 flex items-center justify-between text-[11px] text-white/50">
        {visibleLabels.map((l, i) => (
          <span key={i}>{l}</span>
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
 * MiniChart — animated area chart with P10-P90 band, actual line, hover tooltip.
 */
function MiniChart({ data }: { data: EmissionsTrendPoint[] }) {
  const reduced = useReducedMotion();
  const w = 720, h = 200, padL = 40, padR = 8, padT = 8, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const yMax = Math.max(...data.flatMap((d) => [d.actual, d.forecast_p90])) * 1.1;
  const stepX = innerW / (data.length - 1);
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const actualPath = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.actual).toFixed(1)}`).join(" ");
  const bandTop = data.map((d, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(d.forecast_p90).toFixed(1)}`).join(" ");
  const bandBot = data.slice().reverse().map((d, i) => {
    const j = data.length - 1 - i;
    return `L ${x(j).toFixed(1)} ${y(d.forecast_p10).toFixed(1)}`;
  }).join(" ");

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const cx = (x / rect.width) * w;
      const idx = Math.max(0, Math.min(data.length - 1, Math.round((cx - padL) / stepX)));
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
  }, [data.length, stepX]);

  const hoverPoint = hover ? data[hover.idx] : null;
  const hoverLabel = hoverPoint ? hoverPoint.date : null;

  return (
    <div ref={wrapRef} className="relative" data-testid="emissions-trend-chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-48 w-full">
        {/* Y grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <g key={i}>
            <line
              x1={padL}
              x2={w - padR}
              y1={padT + p * innerH}
              y2={padT + p * innerH}
              stroke="rgba(255,255,255,0.05)"
            />
            <text
              x={padL - 6}
              y={padT + p * innerH + 3}
              textAnchor="end"
              fontSize="9"
              fill="rgba(255,255,255,0.4)"
            >
              {Math.round((1 - p) * yMax / 1000).toLocaleString()}k
            </text>
          </g>
        ))}

        {/* P10-P90 band */}
        <m.path
          d={`${bandTop} ${bandBot} Z`}
          fill="rgba(52,211,153,0.10)"
          stroke="none"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.2 }}
        />

        {/* Actual line */}
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

        {/* Data points — staggered spring-in */}
        {data.map((d, i) => (
          <m.circle
            key={d.date}
            cx={x(i)}
            cy={y(d.actual)}
            r={3}
            fill="#34d399"
            initial={reduced ? false : { scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{
              type: "spring",
              stiffness: 300,
              damping: 20,
              delay: reduced ? 0 : 0.6 + i * 0.06,
            }}
          />
        ))}

        {/* X labels */}
        {data.map((d, i) => (
          <text
            key={d.date}
            x={x(i)}
            y={h - 8}
            textAnchor="middle"
            fontSize="10"
            fill="rgba(255,255,255,0.5)"
          >
            {d.date.slice(5)}
          </text>
        ))}

        {/* Hover crosshair */}
        {hover && hoverPoint && (
          <m.g
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.1 }}
          >
            <line
              x1={x(hover.idx)}
              x2={x(hover.idx)}
              y1={padT}
              y2={padT + innerH}
              stroke="rgba(132,204,22,0.4)"
              strokeWidth={0.5}
              strokeDasharray="2 2"
            />
            <circle
              cx={x(hover.idx)}
              cy={y(hoverPoint.actual)}
              r={5}
              fill="#34d399"
              stroke="#0a1410"
              strokeWidth={1.5}
            />
            <line
              x1={x(hover.idx)}
              x2={x(hover.idx)}
              y1={y(hoverPoint.forecast_p90)}
              y2={y(hoverPoint.forecast_p10)}
              stroke="rgba(132,204,22,0.3)"
              strokeWidth={2}
            />
          </m.g>
        )}
      </svg>

      {/* Hover tooltip */}
      <AnimatePresence>
        {hover && hoverPoint && hoverLabel && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="pointer-events-none absolute z-20 min-w-[180px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
            style={{ left: hover.x, top: hover.y }}
            data-testid="emissions-trend-tooltip"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
              {hoverLabel}
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
              <span className="text-white/65">Actual</span>
              <span className="ml-auto font-mono font-medium text-white">
                {hoverPoint.actual.toLocaleString()} tCO₂e
              </span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full border border-emerald-100/50" />
              <span className="text-white/65">P10 (lower)</span>
              <span className="ml-auto font-mono font-medium text-white/80">
                {hoverPoint.forecast_p10.toLocaleString()}
              </span>
            </div>
            <div className="flex items-center gap-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full border border-emerald-100/50" />
              <span className="text-white/65">P90 (upper)</span>
              <span className="ml-auto font-mono font-medium text-white/80">
                {hoverPoint.forecast_p90.toLocaleString()}
              </span>
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
            <div className="text-2xl font-bold text-white">{total}</div>
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
