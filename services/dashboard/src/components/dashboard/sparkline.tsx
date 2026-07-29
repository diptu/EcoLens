/**
 * Tiny SVG sparkline — used in parameter cards, KPI mini-charts,
 * etc. Pure SVG, no third-party chart library.
 */
"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";

type Props = {
  values: number[];
  color?: string;
  height?: number;
  className?: string;
  fill?: boolean;
};

export function Sparkline({ values, color = "#d1fae5", height = 36, className, fill = true }: Props) {
  const path = useMemo(() => buildPath(values, 100, height, fill), [values, height, fill]);
  if (!path) return null;
  return (
    <svg
      viewBox={`0 0 100 ${height}`}
      preserveAspectRatio="none"
      className={cn("w-full", className)}
      style={{ height }}
      aria-hidden
    >
      {fill && (
        <path d={path.area} fill={color} fillOpacity="0.10" />
      )}
      <path d={path.line} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function buildPath(values: number[], w: number, h: number, fill: boolean) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const dx = w / (values.length - 1);
  let line = "";
  let area = "";
  values.forEach((v, i) => {
    const x = i * dx;
    const y = h - ((v - min) / range) * h;
    line += `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)} `;
  });
  if (fill) {
    area = line + `L${w},${h} L0,${h} Z`;
  }
  return { line, area };
}
