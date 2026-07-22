/**
 * Tiny chart primitives — pure SVG, no chart library, GPU-cheap.
 *
 *  - <LineChart/>  : multi-series line w/ optional dashed baseline
 *  - <BarChart/>   : vertical bars w/ optional value labels
 *  - <DonutChart/> : ring with center label, optional legend
 *  - <AreaChart/>  : filled area (current-year vs baseline)
 *
 * All charts are responsive (preserveAspectRatio="none" on a
 * 16:9 viewBox) and use the brand palette.
 */
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

export function LineChart({
  series,
  labels,
  height = 220,
  yMax,
  showGrid = true,
  className,
}: {
  series: LineSeries[];
  labels: string[];
  height?: number;
  yMax?: number;
  showGrid?: boolean;
  className?: string;
}) {
  const W = 800;
  const H = height;
  const PAD = { l: 40, r: 12, t: 8, b: 24 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;

  const allValues = series.flatMap((s) => s.data);
  const max = yMax ?? Math.max(...allValues, 1);
  const min = 0;

  const xStep = labels.length > 1 ? innerW / (labels.length - 1) : 0;
  const yScale = (v: number) => innerH - ((v - min) / (max - min)) * innerH;

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        {/* Grid */}
        {showGrid && [0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const y = PAD.t + p * innerH;
          return (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="rgba(255,255,255,0.05)" />
              <text x={PAD.l - 6} y={y + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.4)">
                {Math.round((1 - p) * max).toLocaleString()}
              </text>
            </g>
          );
        })}
        {/* X labels */}
        {labels.map((l, i) => {
          const x = PAD.l + i * xStep;
          return (
            <text
              key={i}
              x={x}
              y={H - 6}
              textAnchor="middle"
              fontSize="9"
              fill="rgba(255,255,255,0.4)"
            >
              {l}
            </text>
          );
        })}
        {/* Series */}
        {series.map((s, si) => {
          const points = s.data.map((v, i) => `${PAD.l + i * xStep},${PAD.t + yScale(v)}`).join(" ");
          const color = s.color ?? PALETTE.lime;
          return (
            <g key={si}>
              {s.fill && (
                <polygon
                  points={`${PAD.l},${PAD.t + innerH} ${points} ${PAD.l + (labels.length - 1) * xStep},${PAD.t + innerH}`}
                  fill={color.replace("0.95", "0.15")}
                />
              )}
              <polyline
                points={points}
                fill="none"
                stroke={color}
                strokeWidth="1.6"
                strokeDasharray={s.dashed ? "3 3" : undefined}
              />
              {s.data.map((v, i) => (
                <circle
                  key={i}
                  cx={PAD.l + i * xStep}
                  cy={PAD.t + yScale(v)}
                  r="2.5"
                  fill={color}
                />
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function BarChart({
  data,
  labels,
  height = 220,
  color,
  className,
}: {
  data: number[];
  labels: string[];
  height?: number;
  color?: string;
  className?: string;
}) {
  const W = 800;
  const H = height;
  const PAD = { l: 40, r: 12, t: 8, b: 24 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const max = Math.max(...data, 1);
  const barWidth = innerW / data.length - 4;
  const yScale = (v: number) => innerH - (v / max) * innerH;

  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-full w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const y = PAD.t + p * innerH;
          return (
            <g key={i}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="rgba(255,255,255,0.05)" />
              <text x={PAD.l - 6} y={y + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.4)">
                {Math.round((1 - p) * max).toLocaleString()}
              </text>
            </g>
          );
        })}
        {data.map((v, i) => {
          const x = PAD.l + i * (innerW / data.length) + 2;
          const y = PAD.t + yScale(v);
          return (
            <g key={i}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={innerH - yScale(v)}
                fill={color ?? PALETTE.lime}
                rx="2"
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
}: {
  data: { label: string; value: number; color?: string }[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerSub?: string;
  className?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const R = size / 2 - thickness / 2;
  const C = 2 * Math.PI * R;

  let offset = 0;
  return (
    <div className={cn("relative inline-block", className)} style={{ width: size, height: size }}>
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
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={R}
              fill="none"
              stroke={d.color ?? PALETTE.lime}
              strokeWidth={thickness}
              strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-offset}
            />
          );
          offset += len;
          return seg;
        })}
      </svg>
      {(centerLabel || centerSub) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
          {centerLabel && <p className="text-xl font-bold text-white">{centerLabel}</p>}
          {centerSub && <p className="text-[10px] text-white/50">{centerSub}</p>}
        </div>
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
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={className}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
        <div
          className={cn("h-full rounded-full transition-all", barClassName)}
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      {label && <p className="mt-1 text-xs text-white/60">{label}</p>}
    </div>
  );
}

export { PALETTE };
