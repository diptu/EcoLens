/**
 * ArcGauge — semi-circle meter (0..max sweeping 180°), animated draw-on,
 * center value + sub-caption, optional target tick mark. Same visual
 * language as `charts.tsx` (PALETTE, framer-motion, prefers-reduced-motion
 * aware) — no existing component covers this shape (coverage %, health
 * score), so it's new rather than a variant bolted onto `DonutChart`
 * (that one's a full ring with a different hover-slice interaction model
 * that doesn't fit a single-value meter).
 */
"use client";

import { m, useReducedMotion } from "framer-motion";
import { PALETTE } from "./charts";

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 180) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/** Arc path from 0% to `frac` (0..1) along a 180° sweep, left to right. */
function arcPath(cx: number, cy: number, r: number, frac: number): string {
  const startAngle = 0;
  const endAngle = 180 * Math.max(0, Math.min(1, frac));
  const start = polarToCartesian(cx, cy, r, startAngle);
  const end = polarToCartesian(cx, cy, r, endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

export function ArcGauge({
  value,
  max = 100,
  min = 0,
  label,
  sub,
  color = PALETTE.lime,
  targetValue,
  targetLabel,
  size = 220,
}: {
  value: number;
  max?: number;
  min?: number;
  label: string;
  sub?: string;
  color?: string;
  targetValue?: number;
  targetLabel?: string;
  size?: number;
}) {
  const reduced = useReducedMotion();
  const w = size;
  const h = size * 0.62;
  const cx = w / 2;
  const cy = h - 8;
  const r = w / 2 - 14;
  const frac = (value - min) / (max - min || 1);
  const targetFrac =
    targetValue !== undefined ? (targetValue - min) / (max - min || 1) : null;

  return (
    <div className="flex flex-col items-center" style={{ width: w }}>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: h }}>
        {/* Track */}
        <path
          d={arcPath(cx, cy, r, 1)}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={14}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <m.path
          d={arcPath(cx, cy, r, frac)}
          fill="none"
          stroke={color}
          strokeWidth={14}
          strokeLinecap="round"
          initial={reduced ? false : { pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: 0.9, ease: "easeInOut" }}
        />
        {/* Target tick */}
        {targetFrac !== null && (
          <line
            x1={polarToCartesian(cx, cy, r - 10, 180 * targetFrac).x}
            y1={polarToCartesian(cx, cy, r - 10, 180 * targetFrac).y}
            x2={polarToCartesian(cx, cy, r + 10, 180 * targetFrac).x}
            y2={polarToCartesian(cx, cy, r + 10, 180 * targetFrac).y}
            stroke="rgba(255,255,255,0.6)"
            strokeWidth={2}
          />
        )}
        {/* Min/max labels */}
        <text x={cx - r} y={h - 2} fontSize="9" fill="rgba(255,255,255,0.4)" textAnchor="start">
          {min}
        </text>
        <text x={cx + r} y={h - 2} fontSize="9" fill="rgba(255,255,255,0.4)" textAnchor="end">
          {max}
        </text>
      </svg>
      <div className="-mt-2 flex flex-col items-center text-center">
        <span className="text-2xl font-bold text-white">{label}</span>
        {sub && <span className="text-[11px] text-white/50">{sub}</span>}
        {targetLabel && (
          <span className="mt-0.5 text-[10px] text-white/40">{targetLabel}</span>
        )}
      </div>
    </div>
  );
}
