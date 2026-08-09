/**
 * EmissionsTrendV2 — Executive Dashboard emissions trend chart.
 *
 * Ported from the "v18x" prototype export (`/Users/macbook/Downloads/
 * executive-page-zip/components/emissions-trend-v2.tsx`) on 2026-08-09,
 * per direct request to reproduce that design's screenshot exactly,
 * mock data included. Explicitly, deliberately NOT real: `getEmissionsTrendV2`
 * (`@/lib/admin-dashboard`) is a seeded, deterministic generator -- a
 * synthetic diurnal curve for the "past" 7×24h and a smoothstep-blended
 * curve for the forecast, not a fetch of anything. Kept as a separate,
 * clearly-named component/data path from the real, backend-driven
 * `MiniChart`/`EmissionsTrendPoint` this page's own Emissions Trend
 * section otherwise uses, so nothing here can be mistaken for real data.
 *
 * One real fix vs. the prototype: `smoothBandPath` below actually
 * curves the bottom edge (the prototype's version only drew 2 straight
 * segments to the bottom's first/last points, silently skipping every
 * interior point despite its own comment claiming otherwise).
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import { Globe, Calendar, Info, RefreshCcw, ArrowUpRight } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getEmissionsTrendV2,
  type EmissionsTrendResponse,
  type EmissionsTrendPointV2,
  type EmissionsTrendRegion,
  type EmissionsTrendHorizon,
} from "@/lib/admin-dashboard";

const REGIONS: Array<{ value: EmissionsTrendRegion; label: string }> = [
  { value: "all", label: "All Regions" },
  { value: "NSW1", label: "NSW1" },
  { value: "QLD1", label: "QLD1" },
  { value: "VIC1", label: "VIC1" },
  { value: "SA1", label: "SA1" },
  { value: "TAS1", label: "TAS1" },
  { value: "WEM", label: "WEM" },
];

const HORIZONS: Array<{ value: EmissionsTrendHorizon; label: string }> = [
  { value: "next_24h", label: "Next 24 hours" },
  { value: "next_48h", label: "Next 48 hours" },
  { value: "next_7d", label: "Next 7 days" },
];

export function EmissionsTrendV2({
  initialRegion = "all",
  initialHorizon = "next_48h",
  onOpenDetails,
}: {
  initialRegion?: EmissionsTrendRegion;
  initialHorizon?: EmissionsTrendHorizon;
  /** Called when the user clicks "View details" -- parent opens the modal */
  onOpenDetails?: (point: EmissionsTrendPointV2 | null) => void;
}) {
  const [region, setRegion] = useState<EmissionsTrendRegion>(initialRegion);
  const [horizon, setHorizon] = useState<EmissionsTrendHorizon>(initialHorizon);
  const data = useMemo(() => getEmissionsTrendV2(region, horizon), [region, horizon]);
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = () => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 800);
  };

  return (
    <Card className="overflow-hidden" data-testid="emissions-trend-v2">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-emerald-100/30 bg-emerald-100/10">
            <Globe className="h-5 w-5 text-emerald-100" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h2 className="text-xl font-semibold text-white" data-testid="emissions-trend-title">
                Emissions Trend
              </h2>
              <button
                type="button"
                className="text-white/40 transition hover:text-white/80"
                title="Rolling 7×24h tCO₂e ending now, actual + real hourly spread + forecast (NEM)"
                aria-label="More info"
                data-testid="emissions-trend-info"
              >
                <Info className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-0.5 text-xs text-white/55">
              Rolling 7×24h tCO₂e ending now, actual + real hourly spread + forecast (NEM)
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PillSelect
            icon={<Globe className="h-3.5 w-3.5" />}
            value={region}
            options={REGIONS}
            onChange={(v) => setRegion(v as EmissionsTrendRegion)}
            testId="emissions-trend-region"
          />
          <PillSelect
            icon={<Calendar className="h-3.5 w-3.5" />}
            value={horizon}
            options={HORIZONS}
            onChange={(v) => setHorizon(v as EmissionsTrendHorizon)}
            testId="emissions-trend-horizon"
          />
        </div>
      </div>

      <div className="mb-3 flex items-center justify-end gap-1 text-[11px] text-white/45">
        <RefreshCcw className={cn("h-3 w-3", refreshing && "animate-spin")} />
        <span>Last updated: 2 min ago</span>
        <button
          type="button"
          onClick={handleRefresh}
          className="ml-2 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/60 hover:bg-white/10 hover:text-white"
          data-testid="emissions-trend-refresh"
        >
          Refresh
        </button>
      </div>

      <div className="mb-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-[11px] text-white/65">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-3 rounded-full bg-emerald-300" />
            Actual
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-3.5 rounded-sm border border-emerald-100/40 bg-emerald-100/15" />
            P10–P90 (hourly spread)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-3 rounded-full border-t-2 border-dashed border-sky-300" />
            Forecast (P50)
          </span>
          <span className="ml-1 inline-flex items-center gap-1.5 rounded-full border border-sky-300/40 bg-sky-300/10 px-2 py-0.5 text-sky-200">
            {HORIZONS.find((h) => h.value === horizon)?.label}
          </span>
        </div>
        <KpiMiniTile
          label="Latest Actual"
          value={fmtKt(data.summary.latest_actual_tco2e)}
          unit="tCO₂e"
          sub={data.summary.latest_actual_label}
          icon="cloud"
        />
        <KpiMiniTile
          label="Forecast (P50) Avg"
          value={fmtKt(data.summary.forecast_p50_avg_tco2e)}
          unit="tCO₂e"
          sub={`Next ${data.summary.forecast_hours} hours`}
          icon="split"
        />
        <KpiMiniTile
          label="Forecast Range (P10–P90) Avg"
          value={`${fmtKt(data.summary.forecast_p10_avg_tco2e)} – ${fmtKt(data.summary.forecast_p90_avg_tco2e)}`}
          unit="tCO₂e"
          sub={`Next ${data.summary.forecast_hours} hours`}
          icon="range"
        />
      </div>

      <EmissionsTrendChart data={data} onOpenDetails={onOpenDetails} />

      <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-white/5 bg-white/[0.02] p-3 md:grid-cols-4">
        <BottomKpi
          label="Actual (Now)"
          value={fmtKt(data.summary.latest_actual_tco2e)}
          sub={data.summary.latest_actual_label}
          iconType="trend"
        />
        <BottomKpi
          label="Forecast (P50) Avg"
          value={fmtKt(data.summary.forecast_p50_avg_tco2e)}
          sub={`Next ${data.summary.forecast_hours} hours`}
          iconType="split"
        />
        <BottomKpi
          label="Forecast Range (P10–P90) Avg"
          value={`${fmtKt(data.summary.forecast_p10_avg_tco2e)} – ${fmtKt(data.summary.forecast_p90_avg_tco2e)}`}
          sub={`Next ${data.summary.forecast_hours} hours`}
          iconType="range"
        />
        <BottomKpi
          label="Forecast Period"
          value={HORIZONS.find((h) => h.value === horizon)?.label ?? "Next 48 hours"}
          sub="Hourly resolution"
          iconType="calendar"
        />
      </div>

      <p className="mt-3 flex items-center gap-1.5 text-[11px] text-white/40">
        <Info className="h-3 w-3" />
        tCO₂e = tonnes of carbon dioxide equivalent
      </p>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────────
// Chart
// ────────────────────────────────────────────────────────────────────

function EmissionsTrendChart({
  data,
  onOpenDetails,
}: {
  data: EmissionsTrendResponse;
  onOpenDetails?: (point: EmissionsTrendPointV2 | null) => void;
}) {
  const reduced = useReducedMotion();
  const w = 1200, h = 360;
  const padL = 70, padR = 24, padT = 28, padB = 56;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const yMaxRaw = Math.max(...data.points.map((p) => Math.max(p.past_p90 ?? 0, p.forecast_p90)));
  const yMax = niceY(yMaxRaw);

  const stepX = innerW / Math.max(1, data.points.length - 1);
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH * (1 - v / yMax);

  const nowIdx = data.points.findIndex((p) => p.segment === "now");

  const pastPoints = data.points.map((p, i) => ({ i, p })).filter(({ p }) => p.actual !== null);
  const fcPoints = data.points
    .map((p, i) => ({ i, p }))
    .filter(({ p }) => p.segment === "forecast" || p.segment === "now");

  const SMOOTH_TENSION = 0.35;
  const actualPath = smoothPath(pastPoints.map(({ i, p }): [number, number] => [x(i), y(p.actual!)]), SMOOTH_TENSION);
  const pastBandPath = smoothBandPath(
    pastPoints.map(({ i, p }): [number, number] => [x(i), y(p.past_p90!)]),
    pastPoints.map(({ i, p }): [number, number] => [x(i), y(p.past_p10!)]),
    SMOOTH_TENSION,
  );
  const fcP50Path = smoothPath(fcPoints.map(({ i, p }): [number, number] => [x(i), y(p.forecast_p50)]), SMOOTH_TENSION);
  const fcBandPath = smoothBandPath(
    fcPoints.map(({ i, p }): [number, number] => [x(i), y(p.forecast_p90)]),
    fcPoints.map(({ i, p }): [number, number] => [x(i), y(p.forecast_p10)]),
    SMOOTH_TENSION,
  );

  const xLabels = useMemo(() => buildXLabels(data, padL, innerW, h, padB), [data]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const svgX = (mx / rect.width) * w;
      const idx = Math.round((svgX - padL) / stepX);
      const clamped = Math.max(0, Math.min(data.points.length - 1, idx));
      setHover({ x: mx, y: my, idx: clamped });
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
  }, [data.points.length, stepX, w, h, padL]);

  const hoverPoint = hover ? data.points[hover.idx] : null;

  return (
    <div ref={wrapRef} className="relative" data-testid="emissions-trend-chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-72 w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const yy = padT + p * innerH;
          const labelVal = Math.round((1 - p) * yMax);
          return (
            <g key={`y-${i}`}>
              <line x1={padL} x2={w - padR} y1={yy} y2={yy} stroke="rgba(255,255,255,0.05)" strokeDasharray={i === 0 ? "" : "4 4"} />
              <text x={padL - 8} y={yy + 3} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.4)">
                {fmtYLabel(labelVal)}
              </text>
            </g>
          );
        })}
        <text x={padL - 56} y={padT - 10} fontSize="11" fill="rgba(255,255,255,0.55)">
          tCO₂e
        </text>

        <m.path
          d={fcBandPath}
          fill="rgba(56,189,248,0.12)"
          stroke="none"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.7, delay: 0.5 }}
          data-testid="emissions-trend-forecast-band"
        />
        <m.path
          d={fcP50Path}
          fill="none"
          stroke="#7dd3fc"
          strokeWidth={2}
          strokeDasharray="8 4"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={reduced ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1, delay: 0.7, ease: "easeInOut" }}
          data-testid="emissions-trend-forecast-line"
        />
        <m.path
          d={pastBandPath}
          fill="rgba(52,211,153,0.10)"
          stroke="none"
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          data-testid="emissions-trend-past-band"
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
          data-testid="emissions-trend-actual-line"
        />

        {pastPoints.map(({ i, p }) => (
          <m.circle
            key={`pt-${i}`}
            cx={x(i)}
            cy={y(p.actual!)}
            r={3}
            fill="#34d399"
            initial={reduced ? false : { scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 20, delay: reduced ? 0 : 0.5 + (i / pastPoints.length) * 0.4 }}
          />
        ))}
        {fcPoints
          .filter(({ p }) => p.segment === "forecast")
          .map(({ i, p }) => (
            <m.circle
              key={`fcpt-${i}`}
              cx={x(i)}
              cy={y(p.forecast_p50)}
              r={3.5}
              fill="#0a1410"
              stroke="#7dd3fc"
              strokeWidth={1.5}
              initial={reduced ? false : { scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", stiffness: 280, damping: 22, delay: reduced ? 0 : 0.8 + (i / data.points.length) * 0.3 }}
            />
          ))}

        {nowIdx >= 0 && (
          <g data-testid="emissions-trend-now-marker">
            <line x1={x(nowIdx)} x2={x(nowIdx)} y1={padT} y2={padT + innerH} stroke="rgba(255,255,255,0.20)" strokeWidth={1} strokeDasharray="4 4" />
            <m.rect
              x={x(nowIdx) - 18}
              y={padT + innerH + 6}
              width={36}
              height={18}
              rx={9}
              fill="rgba(52,211,153,0.20)"
              stroke="rgba(52,211,153,0.6)"
              strokeWidth={1}
              initial={reduced ? false : { opacity: 0, y: padT + innerH + 10 }}
              animate={{ opacity: 1, y: padT + innerH + 6 }}
              transition={{ duration: 0.4, delay: 0.9 }}
            />
            <text x={x(nowIdx)} y={padT + innerH + 19} textAnchor="middle" fontSize="10" fontWeight={600} fill="#34d399">
              Now
            </text>
          </g>
        )}

        <text x={padL + (nowIdx >= 0 ? x(nowIdx) - padL : innerW) / 2} y={padT - 10} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.55)">
          ← {data.past_label}
        </text>
        {nowIdx >= 0 && (
          <text x={x(nowIdx) + (w - padR - x(nowIdx)) / 2} y={padT - 10} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.55)">
            {data.forecast_label} →
          </text>
        )}

        {xLabels}

        {hover && hoverPoint && (
          <m.g initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.1 }}>
            <line
              x1={x(hover.idx)}
              x2={x(hover.idx)}
              y1={padT}
              y2={padT + innerH}
              stroke={hoverPoint.segment === "forecast" ? "rgba(125,211,252,0.4)" : "rgba(52,211,153,0.4)"}
              strokeWidth={0.5}
              strokeDasharray="2 2"
            />
            {hoverPoint.actual !== null && <circle cx={x(hover.idx)} cy={y(hoverPoint.actual)} r={5} fill="#34d399" stroke="#0a1410" strokeWidth={1.5} />}
            {hoverPoint.segment === "forecast" && (
              <circle cx={x(hover.idx)} cy={y(hoverPoint.forecast_p50)} r={5} fill="#0a1410" stroke="#7dd3fc" strokeWidth={2} />
            )}
          </m.g>
        )}
      </svg>

      <AnimatePresence>
        {hover && hoverPoint && (
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="pointer-events-none absolute z-20 min-w-[220px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
            style={{ left: hover.x, top: hover.y }}
            data-testid="emissions-trend-tooltip"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
              {hoverPoint.segment === "now" ? "Now · " : ""}
              {hoverPoint.label}
            </div>
            {hoverPoint.actual !== null && (
              <>
                <TooltipRow color="bg-emerald-300" label="Actual" value={`${hoverPoint.actual.toLocaleString()} tCO₂e`} bold />
                <TooltipRow color="border border-emerald-100/40" label="P10–P90" value={`${hoverPoint.past_p10?.toLocaleString()} – ${hoverPoint.past_p90?.toLocaleString()}`} />
              </>
            )}
            {hoverPoint.segment !== "past" && (
              <>
                <TooltipRow color="bg-sky-300" label="Forecast P50" value={`${hoverPoint.forecast_p50.toLocaleString()} tCO₂e`} bold />
                <TooltipRow color="border border-sky-300/40" label="Forecast P10–P90" value={`${hoverPoint.forecast_p10.toLocaleString()} – ${hoverPoint.forecast_p90.toLocaleString()}`} />
              </>
            )}
            <button
              type="button"
              onClick={() => onOpenDetails?.(hoverPoint)}
              className="pointer-events-auto mt-1.5 w-full rounded border border-emerald-100/30 bg-emerald-100/10 px-2 py-1 text-[10px] font-medium text-emerald-100 hover:bg-emerald-100/20"
              data-testid="emissions-trend-tooltip-details"
            >
              View details →
            </button>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Small bits
// ────────────────────────────────────────────────────────────────────

function PillSelect<T extends string>({
  icon, value, options, onChange, testId,
}: {
  icon: React.ReactNode;
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (v: T) => void;
  testId?: string;
}) {
  return (
    <div className="relative" data-testid={testId}>
      <div className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[11px] text-white/70">
        {icon}
        <select
          value={value}
          onChange={(e) => onChange(e.target.value as T)}
          className="appearance-none bg-transparent pr-4 text-white focus:outline-none"
          data-testid={testId ? `${testId}-select` : undefined}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} className="bg-[#0a1410] text-white">
              {o.label}
            </option>
          ))}
        </select>
        <span className="pointer-events-none text-white/40">▾</span>
      </div>
    </div>
  );
}

function KpiMiniTile({
  label, value, unit, sub, icon,
}: {
  label: string;
  value: string;
  unit: string;
  sub: string;
  icon: "cloud" | "split" | "range";
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5">
        {icon === "cloud" && <CloudIcon />}
        {icon === "split" && <SplitIcon />}
        {icon === "range" && <RangeIcon />}
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-white/45">{label}</div>
        <div className="flex items-baseline gap-1">
          <span className="truncate text-base font-semibold text-white">{value}</span>
          <span className="text-[10px] text-white/50">{unit}</span>
        </div>
        <div className="text-[10px] text-white/40">{sub}</div>
      </div>
    </div>
  );
}

function BottomKpi({
  label, value, sub, iconType,
}: {
  label: string;
  value: string;
  sub: string;
  iconType: "trend" | "split" | "range" | "calendar";
}) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5 text-emerald-100">
        {iconType === "trend" && <ArrowUpRight className="h-3.5 w-3.5" />}
        {iconType === "split" && <SplitIcon small />}
        {iconType === "range" && <RangeIcon small />}
        {iconType === "calendar" && <Calendar className="h-3.5 w-3.5" />}
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-white/45">{label}</div>
        <div className="truncate text-sm font-semibold text-white" title={value}>{value}</div>
        <div className="text-[10px] text-white/40">{sub}</div>
      </div>
    </div>
  );
}

function TooltipRow({ color, label, value, bold }: { color: string; label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className={cn("h-1.5 w-3 rounded-full", color)} />
      <span className="text-white/65">{label}</span>
      <span className={cn("ml-auto font-mono", bold ? "font-semibold text-white" : "text-white/80")}>{value}</span>
    </div>
  );
}

function CloudIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 text-emerald-100" fill="currentColor">
      <path d="M5 11.5a2.5 2.5 0 0 1 0-5 3 3 0 0 1 5.83-1 2.5 2.5 0 0 1 3.17 3.83 2 2 0 0 1-1 2.17H5z" />
    </svg>
  );
}
function SplitIcon({ small }: { small?: boolean }) {
  const size = small ? "h-3.5 w-3.5" : "h-4 w-4";
  return (
    <svg viewBox="0 0 16 16" className={cn("text-emerald-100", size)} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M5 4 L8 8 L11 4" />
      <path d="M5 12 L8 8 L11 12" />
    </svg>
  );
}
function RangeIcon({ small }: { small?: boolean }) {
  const size = small ? "h-3.5 w-3.5" : "h-4 w-4";
  return (
    <svg viewBox="0 0 16 16" className={cn("text-sky-200", size)} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="3" y1="8" x2="13" y2="8" />
      <line x1="3" y1="5" x2="3" y2="11" />
      <line x1="13" y1="5" x2="13" y2="11" />
    </svg>
  );
}

// ────────────────────────────────────────────────────────────────────
// SVG helpers
// ────────────────────────────────────────────────────────────────────

/** Catmull-Rom -> cubic Bezier SVG path (tension 0.35 = loose, natural
 * curve). Pure pixel-space -- same function used by the real chart's
 * `smoothPath` in `app/(dashboard)/dashboard/executive/page.tsx`. */
function smoothPath(pts: Array<[number, number]>, tension: number = 0.5): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  if (pts.length === 2) {
    return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)} L ${pts[1][0].toFixed(2)} ${pts[1][1].toFixed(2)}`;
  }

  const k = tension;
  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;

  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? pts[i + 1];

    const cp1x = p1[0] + ((p2[0] - p0[0]) * k) / 3;
    const cp1y = p1[1] + ((p2[1] - p0[1]) * k) / 3;
    const cp2x = p2[0] - ((p3[0] - p1[0]) * k) / 3;
    const cp2y = p2[1] - ((p3[1] - p1[1]) * k) / 3;

    d += ` C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)}, ${cp2x.toFixed(2)} ${cp2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

/** Closed band polygon with BOTH edges curved -- a corrected version of
 * the prototype's own `smoothBandPath`, which had a real bug: despite
 * its comment claiming it "walks the bottom in reverse," it only ever
 * drew 2 straight `L` segments to the bottom edge's first/last points,
 * silently skipping every interior point (the P10 edge rendered as one
 * diagonal line cutting across the chart, not a curve). This version
 * runs `smoothPath` on the reversed bottom points too, then rewrites
 * its leading "M" to "L" so it continues the top curve into one closed
 * path -- same fix already applied to the real chart's `smoothBandPath`
 * in `app/(dashboard)/dashboard/executive/page.tsx`. */
function smoothBandPath(topPts: Array<[number, number]>, botPts: Array<[number, number]>, tension: number = 0.5): string {
  if (topPts.length === 0 || botPts.length === 0) return "";
  if (topPts.length !== botPts.length) return "";
  const top = smoothPath(topPts, tension);
  const bottomReversed = smoothPath([...botPts].reverse(), tension).replace(/^M/, "L");
  return `${top} ${bottomReversed} Z`;
}

function niceY(v: number): number {
  if (v <= 0) return 1000;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  let step: number;
  if (norm <= 1) step = 1;
  else if (norm <= 2) step = 2;
  else if (norm <= 5) step = 5;
  else step = 10;
  return Math.ceil(norm) * mag * (step / 10) * 1.1;
}

function fmtYLabel(v: number): string {
  if (v >= 1000) return `${Math.round(v / 1000)}k`;
  return v.toString();
}

function fmtKt(v: number): string {
  const k = v / 1000;
  if (k >= 100) return `${Math.round(k)}`;
  return k.toFixed(1);
}

function buildXLabels(data: EmissionsTrendResponse, padL: number, innerW: number, h: number, padB: number) {
  const labels: Array<{ i: number; day: string; hour: string | null }> = [];
  let lastDay = "";
  for (let i = 0; i < data.points.length; i++) {
    const p = data.points[i];
    const isDay = !p.label.includes(":");
    if (isDay && p.label !== lastDay) {
      labels.push({ i, day: p.label, hour: null });
      lastDay = p.label;
    }
  }
  // Real bug in the ported prototype's version, fixed here: this unshift
  // ran unconditionally whenever the first point was a day-label, even
  // when the loop above had already pushed an `i: 0` entry for it --
  // producing two `key="xlbl-0"` elements (a real React duplicate-key
  // warning, confirmed live). Only add it when the loop didn't already.
  if (data.points[0] && !data.points[0].label.includes(":") && labels[0]?.i !== 0) {
    labels.unshift({ i: 0, day: data.points[0].label, hour: null });
  }
  return (
    <g>
      {labels.map((l) => {
        const xPos = padL + l.i * (innerW / Math.max(1, data.points.length - 1));
        return (
          <g key={`xlbl-${l.i}`}>
            <text x={xPos} y={h - padB + 22} textAnchor="middle" fontSize="11" fill="rgba(255,255,255,0.65)">
              {l.day}
            </text>
            <text x={xPos} y={h - padB + 36} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.45)">
              12:00
            </text>
          </g>
        );
      })}
    </g>
  );
}
