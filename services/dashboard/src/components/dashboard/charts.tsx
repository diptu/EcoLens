/**
 * Animated chart primitives — pure SVG, framer-motion powered.
 *
 *  - <LineChart/>  : multi-series line w/ draw-on animation, hover tooltip
 *  - <BarChart/>   : vertical bars w/ grow-on animation, hover tooltip
 *  - <DonutChart/> : ring w/ stroke-on animation, hover tooltip
 *
 * All charts are responsive (preserveAspectRatio="none" on a
 * 16:9 viewBox), respect `prefers-reduced-motion` via MotionConfig
 * (provider), and use the brand palette.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { m, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

const PALETTE = {
  lime:   "rgba(132,204,22,0.95)",
  green:  "rgba(16,185,129,0.95)",
  sky:    "rgba(56,189,248,0.95)",
  purple: "rgba(168,85,247,0.95)",
  rose:   "rgba(244,63,94,0.95)",
  gray:   "rgba(148,163,184,0.6)",
};

interface LineSeries {
  name: string;
  data: number[];
  color?: string;
  dashed?: boolean;
  fill?: boolean;
}

/** Convert points array to a smooth SVG path string. */
function linePath(points: Array<[number, number]>, smooth = true): string {
  if (points.length === 0) return "";
  if (!smooth || points.length < 3) {
    return points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0]},${p[1]}`).join(" ");
  }
  // Catmull-Rom to bezier
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const tension = 0.2;
    const cp1x = p1[0] + (p2[0] - p0[0]) * tension;
    const cp1y = p1[1] + (p2[1] - p0[1]) * tension;
    const cp2x = p2[0] - (p3[0] - p1[0]) * tension;
    const cp2y = p2[1] - (p3[1] - p1[1]) * tension;
    d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

/** Convert points array to an SVG polygon (closed) for area fill. */
function areaPath(points: Array<[number, number]>, baseY: number): string {
  if (points.length === 0) return "";
  const line = linePath(points);
  const last = points[points.length - 1];
  const first = points[0];
  return `${line} L${last[0]},${baseY} L${first[0]},${baseY} Z`;
}

function ChartTooltip({
  pos,
  children,
}: {
  pos: { x: number; y: number } | null;
  children: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  if (!pos) return null;
  return (
    <m.div
      initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
      transition={{ duration: 0.12, ease: "easeOut" }}
      className="pointer-events-none absolute z-20 min-w-[170px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
      style={{ left: pos.x, top: pos.y }}
    >
      {children}
    </m.div>
  );
}

function useChartHover(
  ref: React.RefObject<HTMLElement>,
  onMove: (cx: number, cy: number) => void,
) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    function move(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      onMove(x, y);
    }
    function leave() {
      onMove(-1, -1);
    }
    el.addEventListener("mousemove", move);
    el.addEventListener("mouseleave", leave);
    return () => {
      el.removeEventListener("mousemove", move);
      el.removeEventListener("mouseleave", leave);
    };
  }, [ref, onMove]);
}

export function LineChart({
  series,
  labels,
  height = 220,
  yMax,
  showGrid = true,
  className,
  formatTooltip,
}: {
  series: LineSeries[];
  labels: string[];
  height?: number;
  yMax?: number;
  showGrid?: boolean;
  className?: string;
  formatTooltip?: (label: string, values: Array<{ name: string; value: number; color: string }>) => React.ReactNode;
}) {
  const W = 800;
  const H = height;
  const PAD = { l: 40, r: 12, t: 8, b: 24 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const reduced = useReducedMotion();

  const allValues = series.flatMap((s) => s.data);
  const max = yMax ?? Math.max(...allValues, 1);
  const min = 0;

  const xStep = labels.length > 1 ? innerW / (labels.length - 1) : 0;
  const yScale = (v: number) => innerH - ((v - min) / (max - min)) * innerH;

  const seriesPaths = useMemo(
    () =>
      series.map((s) => ({
        s,
        points: s.data.map((v, i): [number, number] => [PAD.l + i * xStep, PAD.t + yScale(v)]),
      })),
    [series, xStep, yScale],
  );

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useChartHover(wrapRef, (x, y) => {
    if (x < 0 || labels.length < 2) {
      setHover(null);
      return;
    }
    const rect = wrapRef.current!.getBoundingClientRect();
    const cx = (x / rect.width) * W;
    const idx = Math.max(0, Math.min(labels.length - 1, Math.round((cx - PAD.l) / xStep)));
    setHover({ x, y, idx });
  });

  const hoverLabel = hover ? labels[hover.idx] : null;
  const hoverValues = hover
    ? series.map((s) => ({
        name: s.name,
        value: s.data[hover.idx] ?? 0,
        color: s.color ?? PALETTE.lime,
      }))
    : [];

  return (
    <div ref={wrapRef} className={cn("relative w-full", className)} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        <defs>
          {series.map((s, si) => (
            <linearGradient
              key={`grad-${si}`}
              id={`area-grad-${si}-${Math.random().toString(36).slice(2, 7)}`}
              x1="0"
              x2="0"
              y1="0"
              y2="1"
            >
              <stop offset="0%" stopColor={s.color ?? PALETTE.lime} stopOpacity="0.35" />
              <stop offset="100%" stopColor={s.color ?? PALETTE.lime} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>

        {/* Grid */}
        {showGrid &&
          [0, 0.25, 0.5, 0.75, 1].map((p, i) => {
            const y = PAD.t + p * innerH;
            return (
              <g key={i}>
                <line
                  x1={PAD.l}
                  x2={W - PAD.r}
                  y1={y}
                  y2={y}
                  stroke="rgba(255,255,255,0.05)"
                />
                <text
                  x={PAD.l - 6}
                  y={y + 3}
                  textAnchor="end"
                  fontSize="9"
                  fill="rgba(255,255,255,0.4)"
                >
                  {Math.round((1 - p) * max).toLocaleString()}
                </text>
              </g>
            );
          })}

        {/* X labels */}
        {labels.map((l, i) => (
          <text
            key={i}
            x={PAD.l + i * xStep}
            y={H - 6}
            textAnchor="middle"
            fontSize="9"
            fill="rgba(255,255,255,0.4)"
          >
            {l}
          </text>
        ))}

        {/* Series */}
        {seriesPaths.map(({ s, points }, si) => {
          const color = s.color ?? PALETTE.lime;
          const path = linePath(points);
          const area = s.fill ? areaPath(points, PAD.t + innerH) : null;
          return (
            <g key={si}>
              {area && (
                <m.path
                  d={area}
                  fill={color.replace("0.95", "0.18")}
                  initial={reduced ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.5, delay: 0.4 + si * 0.1, ease: "easeOut" }}
                />
              )}
              <m.path
                d={path}
                fill="none"
                stroke={color}
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray={s.dashed ? "3 3" : undefined}
                initial={reduced ? false : { pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.8, delay: si * 0.12, ease: "easeInOut" }}
              />
              {/* Point markers — staggered scale-in */}
              {points.map((p, i) => (
                <m.circle
                  key={i}
                  cx={p[0]}
                  cy={p[1]}
                  r="2.5"
                  fill={color}
                  initial={reduced ? false : { scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{
                    type: "spring",
                    stiffness: 320,
                    damping: 22,
                    delay: 0.6 + si * 0.1 + i * 0.04,
                  }}
                />
              ))}
            </g>
          );
        })}

        {/* Hover crosshair */}
        {hover && (
          <g>
            <m.line
              x1={PAD.l + hover.idx * xStep}
              x2={PAD.l + hover.idx * xStep}
              y1={PAD.t}
              y2={PAD.t + innerH}
              stroke="rgba(132,204,22,0.4)"
              strokeDasharray="2 2"
              initial={reduced ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.1 }}
            />
            {series.map((s, si) => (
              <m.circle
                key={si}
                cx={PAD.l + hover.idx * xStep}
                cy={PAD.t + yScale(s.data[hover.idx] ?? 0)}
                r="4"
                fill={s.color ?? PALETTE.lime}
                stroke="#0a1410"
                strokeWidth="1.5"
                initial={reduced ? false : { scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 500, damping: 25 }}
              />
            ))}
          </g>
        )}
      </svg>

      {hover && hoverLabel && (
        <ChartTooltip pos={hover}>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            {hoverLabel}
          </div>
          {formatTooltip ? (
            formatTooltip(hoverLabel, hoverValues)
          ) : (
            hoverValues.map((v, i) => (
              <div key={i} className="flex items-center gap-2 py-0.5">
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                <span className="text-white/65">{v.name}</span>
                <span className="ml-auto font-mono font-medium text-white">
                  {v.value.toLocaleString()}
                </span>
              </div>
            ))
          )}
        </ChartTooltip>
      )}
    </div>
  );
}

export function BarChart({
  data,
  labels,
  height = 220,
  color,
  className,
  formatTooltip,
}: {
  data: number[];
  labels: string[];
  height?: number;
  color?: string;
  className?: string;
  formatTooltip?: (label: string, value: number) => React.ReactNode;
}) {
  const W = 800;
  const H = height;
  const PAD = { l: 40, r: 12, t: 8, b: 24 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const max = Math.max(...data, 1);
  const barWidth = innerW / data.length - 4;
  const yScale = (v: number) => innerH - (v / max) * innerH;
  const reduced = useReducedMotion();

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useChartHover(wrapRef, (x, y) => {
    if (x < 0 || data.length < 1) {
      setHover(null);
      return;
    }
    const rect = wrapRef.current!.getBoundingClientRect();
    const cx = (x / rect.width) * W;
    const idx = Math.max(
      0,
      Math.min(data.length - 1, Math.floor((cx - PAD.l) / (innerW / data.length))),
    );
    setHover({ x, y, idx });
  });

  const hoverLabel = hover ? labels[hover.idx] : null;
  const hoverValue = hover ? data[hover.idx] : 0;

  return (
    <div ref={wrapRef} className={cn("relative w-full", className)} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const y = PAD.t + p * innerH;
          return (
            <g key={i}>
              <line
                x1={PAD.l}
                x2={W - PAD.r}
                y1={y}
                y2={y}
                stroke="rgba(255,255,255,0.05)"
              />
              <text
                x={PAD.l - 6}
                y={y + 3}
                textAnchor="end"
                fontSize="9"
                fill="rgba(255,255,255,0.4)"
              >
                {Math.round((1 - p) * max).toLocaleString()}
              </text>
            </g>
          );
        })}
        {data.map((v, i) => {
          const x = PAD.l + i * (innerW / data.length) + 2;
          const y = PAD.t + yScale(v);
          const isHover = hover?.idx === i;
          return (
            <g key={i}>
              <m.rect
                x={x}
                y={y}
                width={barWidth}
                height={innerH - yScale(v)}
                fill={color ?? PALETTE.lime}
                rx="2"
                initial={reduced ? false : { scaleY: 0, opacity: 0 }}
                animate={{
                  scaleY: 1,
                  opacity: hover && !isHover ? 0.55 : 1,
                }}
                style={{ transformOrigin: `${x + barWidth / 2}px ${PAD.t + innerH}px` }}
                transition={{
                  type: "spring",
                  stiffness: 240,
                  damping: 26,
                  delay: reduced ? 0 : i * 0.05,
                }}
              />
              <text
                x={x + barWidth / 2}
                y={H - 6}
                textAnchor="middle"
                fontSize="9"
                fill="rgba(255,255,255,0.4)"
              >
                {labels[i]}
              </text>
            </g>
          );
        })}
      </svg>

      {hover && hoverLabel !== null && (
        <ChartTooltip pos={hover}>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            {hoverLabel}
          </div>
          {formatTooltip ? (
            formatTooltip(hoverLabel, hoverValue)
          ) : (
            <div className="flex items-center gap-2 py-0.5">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: color ?? PALETTE.lime }}
              />
              <span className="text-white/65">Value</span>
              <span className="ml-auto font-mono font-medium text-white">
                {hoverValue.toLocaleString()}
              </span>
            </div>
          )}
        </ChartTooltip>
      )}
    </div>
  );
}

export function DonutChart({
  data,
  size = 200,
  thickness = 22,
  centerLabel,
  centerSub,
  className,
  formatTooltip,
}: {
  data: { label: string; value: number; color?: string }[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerSub?: string;
  className?: string;
  formatTooltip?: (label: string, value: number, pct: number) => React.ReactNode;
}) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const R = size / 2 - thickness / 2;
  const C = 2 * Math.PI * R;
  const reduced = useReducedMotion();

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useChartHover(wrapRef, (x, y) => {
    if (x < 0) {
      setHover(null);
      return;
    }
    const rect = wrapRef.current!.getBoundingClientRect();
    const cx = (x / rect.width) * size - size / 2;
    const cy = (y / rect.height) * size - size / 2;
    const dist = Math.sqrt(cx * cx + cy * cy);
    if (dist < R - 2 || dist > R + thickness + 2) {
      setHover(null);
      return;
    }
    let angle = Math.atan2(cx, -cy);
    if (angle < 0) angle += 2 * Math.PI;
    let acc = 0;
    for (let i = 0; i < data.length; i++) {
      const sliceFrac = data[i].value / total;
      const sliceAngle = sliceFrac * 2 * Math.PI;
      if (angle >= acc && angle < acc + sliceAngle) {
        setHover({ x, y, idx: i });
        return;
      }
      acc += sliceAngle;
    }
    setHover(null);
  });

  let offset = 0;
  return (
    <div
      ref={wrapRef}
      className={cn("relative inline-block", className)}
      style={{ width: size, height: size }}
    >
      <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={R}
          fill="none"
          stroke="rgba(255,255,255,0.05)"
          strokeWidth={thickness}
        />
        {data.map((d, i) => {
          const len = (d.value / total) * C;
          const seg = (
            <m.circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={R}
              fill="none"
              stroke={d.color ?? PALETTE.lime}
              strokeWidth={thickness}
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset}
              initial={reduced ? false : { opacity: 0, scale: 0.85 }}
              animate={{
                opacity: hover && hover.idx !== i ? 0.5 : 1,
                scale: 1,
              }}
              style={{ transformOrigin: "center" }}
              transition={{
                duration: 0.5,
                delay: reduced ? 0 : i * 0.08,
                ease: "easeOut",
              }}
            />
          );
          offset += len;
          return seg;
        })}
      </svg>
      {(centerLabel || centerSub) && (
        <m.div
          className="absolute inset-0 flex flex-col items-center justify-center text-center"
          initial={reduced ? false : { opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.3, ease: "easeOut" }}
        >
          {centerLabel && <p className="text-xl font-bold text-white">{centerLabel}</p>}
          {centerSub && <p className="text-[10px] text-white/50">{centerSub}</p>}
        </m.div>
      )}
      {hover && (
        <ChartTooltip pos={hover}>
          <div className="mb-1 flex items-center gap-2">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: data[hover.idx].color ?? PALETTE.lime }}
            />
            <span className="font-semibold text-white">{data[hover.idx].label}</span>
          </div>
          {formatTooltip ? (
            formatTooltip(data[hover.idx].label, data[hover.idx].value, (data[hover.idx].value / total) * 100)
          ) : (
            <div className="flex items-center gap-2 py-0.5">
              <span className="text-white/65">Value</span>
              <span className="ml-auto font-mono font-medium text-white">
                {data[hover.idx].value.toLocaleString()}
              </span>
            </div>
          )}
          <div className="flex items-center gap-2 py-0.5">
            <span className="text-white/65">Share</span>
            <span className="ml-auto font-mono font-medium text-emerald-100">
              {((data[hover.idx].value / total) * 100).toFixed(1)}%
            </span>
          </div>
        </ChartTooltip>
      )}
    </div>
  );
}

export function ProgressBar({
  value,
  max = 100,
  className,
  barClassName,
  label,
  color = PALETTE.lime,
}: {
  value: number;
  max?: number;
  className?: string;
  barClassName?: string;
  label?: string;
  color?: string;
}) {
  const reduced = useReducedMotion();
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={className}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
        <m.div
          className={cn("h-full rounded-full", barClassName)}
          style={{ backgroundColor: color }}
          initial={reduced ? false : { width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        />
      </div>
      {label && <p className="mt-1 text-xs text-white/60">{label}</p>}
    </div>
  );
}

/**
 * RadarChart — N-axis polygon comparison (2-4 series). Every axis is
 * expected to already be normalized to the same `maxValue`-scaled,
 * higher-is-better range before it reaches this component (this chart
 * has no opinion on units -- it draws whatever 0..maxValue numbers it's
 * given). Same visual language as the rest of this file (PALETTE,
 * framer-motion draw-on, prefers-reduced-motion aware, hover tooltip).
 */
export function RadarChart({
  axes,
  series,
  size = 280,
  maxValue = 100,
  formatTooltip,
}: {
  axes: string[];
  series: { name: string; color?: string; values: number[] }[];
  size?: number;
  maxValue?: number;
  formatTooltip?: (
    axis: string,
    values: Array<{ name: string; value: number; color: string }>,
  ) => React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 46; // leaves room for axis labels
  const n = axes.length;

  const angleFor = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pointFor = (i: number, frac: number): [number, number] => {
    const a = angleFor(i);
    const rr = r * Math.max(0, Math.min(1, frac));
    return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
  };

  const ringFracs = [0.25, 0.5, 0.75, 1];

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useChartHover(wrapRef, (x, y) => {
    if (x < 0 || n < 1) {
      setHover(null);
      return;
    }
    const rect = wrapRef.current!.getBoundingClientRect();
    const px = (x / rect.width) * size - cx;
    const py = (y / rect.height) * size - cy;
    let angle = Math.atan2(py, px) + Math.PI / 2;
    if (angle < 0) angle += Math.PI * 2;
    const idx = Math.round(angle / ((Math.PI * 2) / n)) % n;
    setHover({ x, y, idx });
  });

  const axisLabel = hover ? axes[hover.idx] : null;
  const axisValues = hover
    ? series.map((s) => ({
        name: s.name,
        value: s.values[hover.idx] ?? 0,
        color: s.color ?? PALETTE.lime,
      }))
    : [];

  return (
    <div
      ref={wrapRef}
      className="relative"
      style={{ width: size, height: size }}
      data-testid="radar-chart"
    >
      <svg
        viewBox={`0 0 ${size} ${size}`}
        className="h-full w-full"
        style={{ overflow: "visible" }}
      >
        {/* Grid rings */}
        {ringFracs.map((frac, ri) => (
          <polygon
            key={ri}
            points={axes.map((_, i) => pointFor(i, frac).join(",")).join(" ")}
            fill="none"
            stroke="rgba(255,255,255,0.07)"
            strokeWidth={1}
          />
        ))}
        {/* Spokes */}
        {axes.map((_, i) => {
          const [x, y] = pointFor(i, 1);
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={x}
              y2={y}
              stroke="rgba(255,255,255,0.07)"
              strokeWidth={1}
            />
          );
        })}
        {/* Axis labels -- anchor follows which side of center the label
            falls on (a label sitting exactly on the horizontal axis
            centered on its own point would overlap the series markers
            at that same axis, since `text-anchor="middle"` extends the
            word in both directions from the point). */}
        {axes.map((label, i) => {
          const [x, y] = pointFor(i, 1.28);
          const dx = x - cx;
          const anchor = Math.abs(dx) < 4 ? "middle" : dx > 0 ? "start" : "end";
          return (
            <text
              key={i}
              x={x}
              y={y}
              textAnchor={anchor}
              dominantBaseline="middle"
              fontSize="9.5"
              fill="rgba(255,255,255,0.55)"
            >
              {label}
            </text>
          );
        })}
        {/* Series polygons */}
        {series.map((s, si) => {
          const color = s.color ?? PALETTE.lime;
          const points = axes.map((_, i) => pointFor(i, (s.values[i] ?? 0) / maxValue));
          const pointsAttr = points.map((p) => p.join(",")).join(" ");
          return (
            <g key={si}>
              <m.polygon
                points={pointsAttr}
                fill={color.replace("0.95", "0.16")}
                stroke={color}
                strokeWidth={1.6}
                strokeLinejoin="round"
                initial={reduced ? false : { opacity: 0, scale: 0.85 }}
                animate={{ opacity: 1, scale: 1 }}
                style={{ transformOrigin: `${cx}px ${cy}px` }}
                transition={{ duration: 0.6, delay: si * 0.1, ease: "easeOut" }}
              />
              {points.map((p, i) => (
                <m.circle
                  key={i}
                  cx={p[0]}
                  cy={p[1]}
                  r={hover?.idx === i ? 4 : 2.75}
                  fill={color}
                  stroke="#0a1410"
                  strokeWidth={1}
                  initial={reduced ? false : { scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{
                    type: "spring",
                    stiffness: 320,
                    damping: 22,
                    delay: 0.4 + si * 0.1 + i * 0.04,
                  }}
                />
              ))}
            </g>
          );
        })}
      </svg>

      {hover && axisLabel && (
        <ChartTooltip pos={hover}>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            {axisLabel}
          </div>
          {formatTooltip ? (
            formatTooltip(axisLabel, axisValues)
          ) : (
            axisValues.map((v, i) => (
              <div key={i} className="flex items-center gap-2 py-0.5">
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                <span className="text-white/65">{v.name}</span>
                <span className="ml-auto font-mono font-medium text-white">
                  {v.value.toFixed(1)}
                </span>
              </div>
            ))
          )}
        </ChartTooltip>
      )}
    </div>
  );
}

export { PALETTE };
