/**
 * Sparkline — single-line miniature, no axes, no labels.
 * Used in cards and the home-page preview widget. ~30 lines of SVG.
 *
 * `FanChart`/`FanTooltip` (the P10/P50/P90 fan-chart pair this file
 * used to also export) were removed as dead code once `/dashboard/
 * forecast` (their only caller) was disabled — see that route's own
 * page.tsx. The Demand Forecast chart's real functionality lives in
 * `DemandForecastChart` (`components/dashboard/demand-forecast-
 * chart.tsx`) now, not here.
 */
"use client";

import { cn } from "@/lib/utils";

export function Sparkline({
  values,
  width = 120,
  height = 32,
  color = "rgba(132,204,22,0.95)",
  fill = "rgba(132,204,22,0.18)",
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: string;
  className?: string;
}) {
  if (values.length < 2) {
    return <div className={cn("h-8 w-32", className)} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xStep = width / (values.length - 1);
  const yScale = (v: number) => height - 2 - ((v - min) / range) * (height - 4);
  const points = values.map((v, i) => `${i * xStep},${yScale(v)}`).join(" ");
  const polygon = `0,${height} ${points} ${width},${height}`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("block", className)}
      role="img"
      aria-hidden="true"
    >
      <polygon points={polygon} fill={fill} />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
