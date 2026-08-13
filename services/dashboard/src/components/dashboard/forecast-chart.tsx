/**
 * Pure-SVG line + confidence band chart for forecast series.
 *
 * Accepts a list of points with `historical | forecast | lower | upper`
 * values. Renders:
 *  - a green historical line for the past half
 *  - a dashed forecast line for the future half
 *  - a shaded confidence band (lower..upper)
 *  - a horizontal critical-threshold line in red
 *  - x-axis time labels
 *  - a vertical "Forecast start" divider
 *
 * No third-party chart library — keeps the bundle small.
 */
"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";

export type ForecastPoint = {
  ts: string;
  historical: number | null;
  forecast: number | null;
  lower: number | null;
  upper: number | null;
};

type Props = {
  points: ForecastPoint[];
  critical: number;         // threshold value
  unit: string;
  yMin?: number;
  yMax?: number;
  height?: number;
  className?: string;
};

const PADDING = { top: 12, right: 16, bottom: 28, left: 44 };

export function ForecastChart({
  points,
  critical,
  unit,
  yMin,
  yMax,
  height = 360,
  className,
}: Props) {
  const data = useMemo(() => buildData(points, yMin, yMax), [points, yMin, yMax]);

  if (!data) {
    return <div className="text-center text-sm text-white/45">No data</div>;
  }

  const w = 800;
  const innerW = w - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const xAt = (i: number) => PADDING.left + (i / Math.max(points.length - 1, 1)) * innerW;
  const yAt = (v: number) => PADDING.top + (1 - (v - data.min) / Math.max(data.max - data.min, 0.0001)) * innerH;

  const histPath = pathFromPoints(points, (p) => p.historical, xAt, yAt);
  const fcstPath = pathFromPoints(points, (p) => p.forecast, xAt, yAt);
  const lowerPath = pathFromPoints(points, (p) => p.lower, xAt, yAt);
  const upperPath = pathFromPoints(points, (p) => p.upper, xAt, yAt);
  const bandPath = bandPathFromPoints(points, xAt, yAt);

  // Find the join index (first forecast point)
  const joinIdx = points.findIndex((p) => p.forecast != null && p.historical == null);
  const joinX = joinIdx >= 0 ? xAt(joinIdx) : null;

  // Y-axis ticks
  const yTicks = useMemo(() => niceTicks(data.min, data.max, 5), [data.min, data.max]);
  // X-axis ticks — pick ~6 labels evenly
  const xTickIdxs = useMemo(() => pickXTicks(points.length), [points.length]);

  return (
    <div className={cn("relative w-full overflow-hidden", className)} data-testid="forecast-chart">
      <svg
        viewBox={`0 0 ${w} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
      >
        {/* Grid */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PADDING.left} y1={yAt(t)} x2={w - PADDING.right} y2={yAt(t)}
              stroke="rgba(255,255,255,0.06)" strokeWidth="1"
            />
            <text
              x={PADDING.left - 8} y={yAt(t) + 4}
              textAnchor="end"
              className="fill-white/45"
              fontSize="10"
            >
              {formatNumber(t)}
            </text>
          </g>
        ))}

        {/* Confidence band */}
        {bandPath && (
          <path d={bandPath} fill="rgba(56, 189, 248, 0.10)" stroke="none" />
        )}

        {/* Historical line */}
        {histPath && (
          <path d={histPath} fill="none" stroke="#d1fae5" strokeWidth="2" />
        )}

        {/* Lower bound dashed */}
        {lowerPath && (
          <path d={lowerPath} fill="none" stroke="#7dd3fc" strokeWidth="1" strokeDasharray="3 3" />
        )}

        {/* Upper bound dashed */}
        {upperPath && (
          <path d={upperPath} fill="none" stroke="#7dd3fc" strokeWidth="1" strokeDasharray="3 3" />
        )}

        {/* Forecast line */}
        {fcstPath && (
          <path d={fcstPath} fill="none" stroke="#3b82f6" strokeWidth="2" strokeDasharray="6 4" />
        )}

        {/* Critical threshold */}
        <line
          x1={PADDING.left} y1={yAt(critical)} x2={w - PADDING.right} y2={yAt(critical)}
          stroke="#ef4444" strokeWidth="1.5" strokeDasharray="6 4"
        />
        <text
          x={w - PADDING.right - 4} y={yAt(critical) - 6}
          textAnchor="end" fontSize="10"
          className="fill-rose-300"
        >
          Critical ({formatNumber(critical)} {unit})
        </text>

        {/* Forecast start vertical */}
        {joinX != null && (
          <g>
            <line x1={joinX} y1={PADDING.top} x2={joinX} y2={height - PADDING.bottom}
              stroke="rgba(255,255,255,0.15)" strokeWidth="1" strokeDasharray="2 4" />
            <rect
              x={joinX - 38} y={height - PADDING.bottom - 18} width="76" height="18" rx="4"
              fill="rgba(255,255,255,0.06)"
            />
            <text
              x={joinX} y={height - PADDING.bottom - 5}
              textAnchor="middle" fontSize="10"
              className="fill-white/55"
            >
              Forecast Start
            </text>
          </g>
        )}

        {/* X-axis labels */}
        {xTickIdxs.map((i) => (
          <text
            key={i}
            x={xAt(i)} y={height - PADDING.bottom + 16}
            textAnchor="middle" fontSize="10"
            className="fill-white/45"
          >
            {formatXLabel(points[i].ts)}
          </text>
        ))}

        {/* Y-axis unit */}
        <text
          x={4} y={PADDING.top - 2} fontSize="10"
          className="fill-white/45"
        >
          {unit}
        </text>
      </svg>
    </div>
  );
}

function buildData(points: ForecastPoint[], yMin?: number, yMax?: number) {
  if (points.length === 0) return null;
  const allValues: number[] = [];
  for (const p of points) {
    if (p.historical != null) allValues.push(p.historical);
    if (p.forecast != null)   allValues.push(p.forecast);
    if (p.lower != null)      allValues.push(p.lower);
    if (p.upper != null)      allValues.push(p.upper);
  }
  if (allValues.length === 0) return null;
  const min = yMin != null ? yMin : Math.min(...allValues);
  const max = yMax != null ? yMax : Math.max(...allValues);
  return { min, max };
}

function pathFromPoints(
  points: ForecastPoint[],
  pick: (p: ForecastPoint) => number | null,
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string | null {
  let d = "";
  let started = false;
  for (let i = 0; i < points.length; i++) {
    const v = pick(points[i]);
    if (v == null) {
      started = false;
      continue;
    }
    const cmd = started ? "L" : "M";
    d += `${cmd}${xAt(i).toFixed(2)},${yAt(v).toFixed(2)} `;
    started = true;
  }
  return d || null;
}

function bandPathFromPoints(
  points: ForecastPoint[],
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string | null {
  let top = "";
  let bottom = "";
  let started = false;
  for (let i = 0; i < points.length; i++) {
    const u = points[i].upper;
    if (u == null) {
      started = false;
      continue;
    }
    const cmd = started ? "L" : "M";
    top += `${cmd}${xAt(i).toFixed(2)},${yAt(u).toFixed(2)} `;
    started = true;
  }
  started = false;
  for (let i = points.length - 1; i >= 0; i--) {
    const l = points[i].lower;
    if (l == null) {
      started = false;
      continue;
    }
    const cmd = started ? "L" : "M";
    bottom += `${cmd}${xAt(i).toFixed(2)},${yAt(l).toFixed(2)} `;
    started = true;
  }
  if (!top || !bottom) return null;
  return `${top}${bottom}Z`;
}

function niceTicks(min: number, max: number, count: number): number[] {
  if (max === min) return [min];
  const range = max - min;
  const step = range / count;
  const out: number[] = [];
  for (let i = 0; i <= count; i++) {
    out.push(min + i * step);
  }
  return out;
}

function pickXTicks(n: number): number[] {
  if (n <= 6) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  const step = (n - 1) / 5;
  for (let i = 0; i <= 5; i++) {
    out.push(Math.round(i * step));
  }
  return out;
}

function formatNumber(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10)   return v.toFixed(1);
  return v.toFixed(1);
}

function formatXLabel(iso: string): string {
  const d = new Date(iso);
  const sameDay = d.getDate() === new Date().getDate();
  if (sameDay) {
    return d.toLocaleString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return d.toLocaleString("en-AU", { day: "numeric", month: "short" });
}
