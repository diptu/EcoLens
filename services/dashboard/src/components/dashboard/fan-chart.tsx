/**
 * FanChart — pure-SVG chart that draws a P10/P50/P90 fan for a
 * single time series. The P50 line is solid, the P10/P90 envelope
 * is a translucent band.
 *
 * Why pure SVG (no chart lib)?
 *  - bundle stays tiny (no recharts/visx overhead)
 *  - dark theme tokens are consistent with the rest of the app
 *  - SSR-friendly (no client hydration mismatch)
 *
 * The component is "use client" only if you need interactive
 * features (tooltips). For the forecast page, hover tooltips are
 * client-only and rendered via a sibling <ForecastTooltip> wrapper.
 */
"use client";

import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import { formatStepLabel, type Forecast, type ForecastPoint } from "@/lib/forecast";

interface Props {
  forecast: Forecast;
  /** Optional height override. Default 280. */
  height?: number;
  /** Show the x-axis step labels. Default true. */
  showLabels?: boolean;
  /** Highlight a single step (e.g. the current step). 1-indexed. */
  highlightStep?: number;
  className?: string;
}

const W = 800;
const PAD = { l: 56, r: 16, t: 16, b: 28 };

export function FanChart({
  forecast,
  height = 280,
  showLabels = true,
  highlightStep,
  className,
}: Props) {
  const { points } = forecast;
  const total = points.length;
  const innerW = W - PAD.l - PAD.r;
  const innerH = height - PAD.t - PAD.b;

  // y-domain
  const yMax = useMemo(
    () => Math.max(...points.map((p) => p.p90), 1) * 1.08,
    [points],
  );
  const yMin = 0;

  const xStep = total > 1 ? innerW / (total - 1) : 0;
  const yScale = (v: number) =>
    PAD.t + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  // Track which point the user is hovering (for the tooltip)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Build path strings once
  const p50Path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${(PAD.l + i * xStep).toFixed(2)} ${yScale(p.p50).toFixed(2)}`)
    .join(" ");
  const bandPath = useMemo(() => {
    if (points.length === 0) return "";
    // Top edge (P90) left-to-right, then bottom edge (P10) right-to-left.
    const top = points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${(PAD.l + i * xStep).toFixed(2)} ${yScale(p.p90).toFixed(2)}`)
      .join(" ");
    const bottom = points
      .map((p, i) =>
        `${i === 0 ? "L" : "L"} ${(PAD.l + (points.length - 1 - i) * xStep).toFixed(2)} ${yScale(
          points[points.length - 1 - i].p10,
        ).toFixed(2)}`,
      )
      .join(" ");
    return `${top} ${bottom} Z`;
  }, [points, xStep]);

  // y-axis grid lines (5 ticks)
  const gridYs = [0, 0.25, 0.5, 0.75, 1].map((p) => ({
    y: PAD.t + p * innerH,
    value: yMin + (1 - p) * (yMax - yMin),
  }));

  // x-axis labels — sparse to keep the chart readable
  const labelStride = Math.max(1, Math.floor(total / 6));
  const labels = points
    .map((p, i) => ({ idx: i, label: formatStepLabel(p.ts, i + 1, total) }))
    .filter((l) => l.label);

  return (
    <div className={cn("relative w-full", className)} style={{ height }} data-testid="fan-chart">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        className="h-full w-full"
        role="img"
        aria-label={`Demand forecast fan chart for ${forecast.region}`}
        onMouseLeave={() => setHoverIdx(null)}
        onMouseMove={(e) => {
          // Map cursor x → nearest step
          const rect = e.currentTarget.getBoundingClientRect();
          const ratio = (e.clientX - rect.left) / rect.width;
          const idx = Math.round(ratio * (total - 1));
          if (idx >= 0 && idx < total) setHoverIdx(idx);
        }}
      >
        {/* Grid lines + y-axis labels */}
        {gridYs.map((g, i) => (
          <g key={i}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={g.y}
              y2={g.y}
              stroke="rgba(255,255,255,0.05)"
            />
            <text
              x={PAD.l - 6}
              y={g.y + 3}
              textAnchor="end"
              fontSize="9"
              fill="rgba(255,255,255,0.4)"
            >
              {Math.round(g.value).toLocaleString()}
            </text>
          </g>
        ))}

        {/* Fan band (P10 ↔ P90) */}
        {bandPath && (
          <path
            d={bandPath}
            fill="rgba(132,204,22,0.12)"
            stroke="rgba(132,204,22,0.35)"
            strokeWidth="0.6"
          />
        )}

        {/* P50 line */}
        <path
          d={p50Path}
          fill="none"
          stroke="rgba(132,204,22,0.95)"
          strokeWidth="1.6"
        />

        {/* P50 dots (sparse) */}
        {points.map((p, i) => {
          const stride = Math.max(1, Math.floor(total / 12));
          if (i !== 0 && i !== total - 1 && i % stride !== 0) return null;
          return (
            <circle
              key={i}
              cx={PAD.l + i * xStep}
              cy={yScale(p.p50)}
              r="2.4"
              fill="rgba(132,204,22,1)"
            />
          );
        })}

        {/* Highlighted step (e.g. "now" if passed in) */}
        {highlightStep != null && highlightStep >= 1 && highlightStep <= total && (
          <line
            x1={PAD.l + (highlightStep - 1) * xStep}
            x2={PAD.l + (highlightStep - 1) * xStep}
            y1={PAD.t}
            y2={PAD.t + innerH}
            stroke="rgba(132,204,22,0.5)"
            strokeDasharray="2 3"
          />
        )}

        {/* Hover crosshair */}
        {hoverIdx != null && (
          <line
            x1={PAD.l + hoverIdx * xStep}
            x2={PAD.l + hoverIdx * xStep}
            y1={PAD.t}
            y2={PAD.t + innerH}
            stroke="rgba(255,255,255,0.3)"
            strokeDasharray="2 3"
          />
        )}

        {/* X-axis labels */}
        {showLabels &&
          labels.map((l) => (
            <text
              key={l.idx}
              x={PAD.l + l.idx * xStep}
              y={height - 8}
              textAnchor="middle"
              fontSize="9"
              fill="rgba(255,255,255,0.45)"
            >
              {l.label}
            </text>
          ))}
      </svg>

      {/* Tooltip overlay (positioned with CSS, not SVG, so it survives zoom) */}
      {hoverIdx != null && (
        <FanTooltip
          point={points[hoverIdx]}
          xPct={((PAD.l + hoverIdx * xStep) / W) * 100}
          region={forecast.region}
        />
      )}
    </div>
  );
}

function FanTooltip({
  point,
  xPct,
  region,
}: {
  point: ForecastPoint;
  xPct: number;
  region: string;
}) {
  // Clamp so the tooltip never overflows the container
  const left = Math.max(2, Math.min(98, xPct));
  const dateLabel = new Date(point.ts).toLocaleString("en-AU", {
    timeZone: "Australia/Sydney",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    day: "numeric",
    month: "short",
  });
  return (
    <div
      className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl"
      style={{ left: `${left}%` }}
    >
      <div className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
        {region} · {dateLabel}
      </div>
      <div className="grid grid-cols-3 gap-3 text-[11px]">
        <div>
          <div className="text-white/40">P10</div>
          <div className="font-mono font-semibold text-rose-300">{point.p10.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-white/40">P50</div>
          <div className="font-mono font-semibold text-lime-100">{point.p50.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-white/40">P90</div>
          <div className="font-mono font-semibold text-emerald-100">{point.p90.toFixed(0)}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * Sparkline — single-line miniature, no axes, no labels.
 * Used in cards and the home-page preview widget. ~30 lines of SVG.
 */
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
