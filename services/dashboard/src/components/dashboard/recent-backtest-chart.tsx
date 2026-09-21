/**
 * RecentBacktestChart — real actual demand overlaid with what the
 * currently-served model actually would have predicted, walking forward
 * through the real last `days` days, both series ending at the same
 * real point ("Now").
 *
 * Distinct from `DemandForecastChart` (this same directory): that
 * component shows real actual ending where a real *live* forecast
 * begins -- two adjacent, non-overlapping regions. This component shows
 * two OVERLAPPING series over the SAME real historical window, because
 * the question it answers is different: not "what's coming next" but
 * "how well has the model actually been tracking reality." Backed by
 * `GET /v1/forecast/recent-actual-vs-predicted`
 * (`lib/emissions.ts`'s `fetchRecentBacktest`) -- a real walk-forward
 * re-forecast built on demand from real history, not a live single-shot
 * forecast repositioned to look retrospective.
 *
 * Real gaps happen (a genuine warehouse gap in `actual`, same reality
 * `RealEmissionsTrend`/`DemandForecastChart` already disclose rather
 * than smooth over) -- `actual` breaks its line at any real gap wider
 * than 1.5 real hourly steps; the predicted P50/band line does not
 * break the same way since the model's own predicted points are always
 * real for every real origin that scored (see the backend's own
 * per-step-not-per-origin gap handling).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import { Info } from "lucide-react";

export type RecentBacktestPoint = {
  ts: string;
  tMs: number;
  actualMw: number | null;
  p10Mw: number;
  p50Mw: number;
  p90Mw: number;
};

function hourLabel(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fullLabel(ts: string): string {
  return new Date(ts).toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function smoothPath(pts: Array<[number, number]>, tension: number = 0.35): string {
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

function smoothBandPath(topPts: Array<[number, number]>, botPts: Array<[number, number]>): string {
  if (topPts.length === 0 || botPts.length === 0 || topPts.length !== botPts.length) return "";
  const top = smoothPath(topPts);
  const bottomReversed = smoothPath([...botPts].reverse()).replace(/^M/, "L");
  return `${top} ${bottomReversed} Z`;
}

// Real data here is always hourly (forecast-api's `date_trunc('hour',
// ts)` aggregation, same as `RealEmissionsTrend`'s hourly bucket) -- a
// jump bigger than 1.5 real hours is a genuine gap, not clock jitter.
const GAP_THRESHOLD_MS = 90 * 60 * 1000;

function splitOnGaps<T extends { tMs: number }>(pts: T[]): T[][] {
  if (pts.length === 0) return [];
  const segments: T[][] = [[pts[0]]];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].tMs - pts[i - 1].tMs > GAP_THRESHOLD_MS) {
      segments.push([pts[i]]);
    } else {
      segments[segments.length - 1].push(pts[i]);
    }
  }
  return segments;
}

function niceY(v: number): number {
  if (v <= 0) return 1000;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = (v / mag) * 1.1;
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (norm <= step) return step * mag;
  }
  return 10 * mag;
}

function fmtMwLabel(v: number): string {
  if (v >= 1000) return `${Math.round(v / 1000)}K`;
  return Math.round(v).toString();
}

export function RecentBacktestChart({
  points,
  testId = "recent-backtest-chart",
}: {
  points: RecentBacktestPoint[];
  testId?: string;
}) {
  const reduced = useReducedMotion();
  const w = 1200, h = 320, padL = 50, padR = 16, padT = 20, padB = 40;
  const innerW = w - padL - padR, innerH = h - padT - padB;

  const sorted = [...points].sort((a, b) => a.tMs - b.tMs);

  const yMaxRaw = Math.max(1, ...sorted.map((p) => Math.max(p.actualMw ?? 0, p.p90Mw)));
  const yMax = niceY(yMaxRaw);

  const tMin = sorted.length ? sorted[0].tMs : Date.now();
  const tMax = sorted.length ? sorted[sorted.length - 1].tMs : Date.now();
  const tSpan = Math.max(1, tMax - tMin);
  const x = (tMs: number) => padL + ((tMs - tMin) / tSpan) * innerW;
  const y = (v: number) => padT + innerH * (1 - v / yMax);

  const actualPts = sorted.filter((p) => p.actualMw !== null);

  const actualSegments = splitOnGaps(actualPts).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.actualMw!)])),
  );
  const p50Segments = splitOnGaps(sorted).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.p50Mw)])),
  );
  const bandSegments = splitOnGaps(sorted).map((seg) =>
    smoothBandPath(
      seg.map((p) => [x(p.tMs), y(p.p90Mw)]),
      seg.map((p) => [x(p.tMs), y(p.p10Mw)]),
    ),
  );

  // Both series end at the same real point by construction (the
  // backend's own walk-forward always scores up to its last valid real
  // origin) -- "Now" marks that shared real endpoint, not `Date.now()`.
  const nowMs = sorted.length > 0 ? sorted[sorted.length - 1].tMs : Date.now();

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || sorted.length === 0) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const svgX = (mx / rect.width) * w;
      let nearest = 0;
      let best = Infinity;
      for (let i = 0; i < sorted.length; i++) {
        const d = Math.abs(x(sorted[i].tMs) - svgX);
        if (d < best) {
          best = d;
          nearest = i;
        }
      }
      setHover({ x: mx, y: my, idx: nearest });
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sorted.length, tMin, tSpan, innerW]);

  const hoverPoint = hover ? sorted[hover.idx] : null;

  if (sorted.length === 0) {
    return <p className="py-16 text-center text-xs text-white/40">No real data for this window yet.</p>;
  }

  const yLabels = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: padT + (1 - f) * innerH,
    label: fmtMwLabel(f * yMax),
  }));
  const labelEvery = sorted.length > 60 ? 12 : sorted.length > 30 ? 6 : sorted.length > 16 ? 3 : 1;

  // Real fix (2026-09-12): this tooltip previously had no edge-clamping
  // at all (raw `left: hover.x`), so hovering near either edge of the
  // chart pushed roughly half the box outside this card's own bounds --
  // same bug class `RealEmissionsTrend`'s tooltip already had fixed
  // (2026-08-11) and `DemandForecastChart`'s got fixed alongside it
  // (2026-09-12). Clamped the same way, against a real fixed
  // `w-[220px]` (matches this tooltip's own fixed width below, not a
  // `min-w` -- the assumed width used for the clamp math must always
  // match what's actually rendered).
  const TOOLTIP_WIDTH_PX = 220;
  const tooltipContainerWidth = wrapRef.current?.clientWidth ?? w;
  const tooltipLeft = hover
    ? Math.min(
        Math.max(hover.x, TOOLTIP_WIDTH_PX / 2),
        Math.max(TOOLTIP_WIDTH_PX / 2, tooltipContainerWidth - TOOLTIP_WIDTH_PX / 2),
      )
    : 0;

  return (
    <div ref={wrapRef} className="relative" data-testid={testId}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ aspectRatio: `${w} / ${h}` }}
      >
        {yLabels.map((l, i) => (
          <g key={i}>
            <line x1={padL} x2={w - padR} y1={l.y} y2={l.y} stroke="rgba(255,255,255,0.05)" />
            <text x={padL - 8} y={l.y + 3} textAnchor="end" fontSize="10" fill="rgba(255,255,255,0.4)">
              {l.label}
            </text>
          </g>
        ))}
        <text x={padL - 40} y={padT - 6} fontSize="10" fill="rgba(255,255,255,0.5)">MW</text>

        {bandSegments.map((d, i) => (
          <m.path
            key={`band-${i}`}
            d={d}
            fill="rgba(125,211,252,0.14)"
            stroke="none"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.3 }}
            data-testid={`${testId}-band`}
          />
        ))}
        {p50Segments.map((d, i) => (
          <m.path
            key={`p50-${i}`}
            d={d}
            fill="none"
            stroke="#7dd3fc"
            strokeWidth={2}
            strokeDasharray="6 3"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1, delay: 0.4, ease: "easeInOut" }}
            data-testid={`${testId}-predicted-line`}
          />
        ))}
        {actualSegments.map((d, i) => (
          <m.path
            key={`actual-${i}`}
            d={d}
            fill="none"
            stroke="#ffffff"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.1, ease: "easeInOut" }}
            data-testid={`${testId}-actual-line`}
          />
        ))}

        <g data-testid={`${testId}-now-marker`}>
          <line
            x1={x(nowMs)} x2={x(nowMs)} y1={padT} y2={padT + innerH}
            stroke="rgba(255,255,255,0.20)" strokeWidth={1} strokeDasharray="4 4"
          />
          <text x={x(nowMs)} y={padT - 6} textAnchor="middle" fontSize="10" fontWeight={600} fill="rgba(255,255,255,0.7)">
            Now
          </text>
        </g>

        {sorted.map(
          (p, i) =>
            (i % labelEvery === 0 || i === sorted.length - 1) && (
              <text key={`xlbl-${i}`} x={x(p.tMs)} y={h - 12} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.45)">
                {hourLabel(p.ts)}
              </text>
            ),
        )}
        <g>
          <text x={padL} y={h - 2} fontSize="9" fill="rgba(255,255,255,0.5)">
            {new Date(sorted[0].tMs).toLocaleDateString([], { month: "short", day: "numeric" })}
          </text>
          <text x={w - padR} y={h - 2} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.5)">
            {new Date(sorted[sorted.length - 1].tMs).toLocaleDateString([], { month: "short", day: "numeric" })}
          </text>
        </g>

        {hover && hoverPoint && (
          <m.g initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.1 }}>
            <line
              x1={x(hoverPoint.tMs)} x2={x(hoverPoint.tMs)} y1={padT} y2={padT + innerH}
              stroke="rgba(255,255,255,0.3)" strokeWidth={0.5} strokeDasharray="2 2"
            />
            {hoverPoint.actualMw !== null && (
              <circle cx={x(hoverPoint.tMs)} cy={y(hoverPoint.actualMw)} r={4} fill="#fff" stroke="#0a1410" strokeWidth={1.5} />
            )}
            <circle cx={x(hoverPoint.tMs)} cy={y(hoverPoint.p50Mw)} r={4} fill="#0a1410" stroke="#7dd3fc" strokeWidth={2} />
          </m.g>
        )}
      </svg>

      {/* Real fix (2026-09-12): the positioning transform
          (`-translate-x-1/2 -translate-y-[...]`, what the clamp math
          above assumes keeps this centered on the cursor) lived on the
          same element as framer-motion's `animate`. Framer Motion takes
          over the whole CSS `transform` property once any of
          `x`/`y`/`scale`/`rotate` is animated, silently dropping the
          Tailwind transform classes -- confirmed live via
          `getComputedStyle`, `transform` reads back as `none` despite
          the classes being present. Static positioning now lives on
          this plain outer div (real CSS transform, never touched by
          motion); the inner `m.div` only handles the entrance
          animation, its own independent transform. */}
      <AnimatePresence>
        {hover && hoverPoint && (
          <div
            className="pointer-events-none absolute z-20 w-[220px] -translate-x-1/2 -translate-y-[calc(100%+10px)]"
            style={{ left: tooltipLeft, top: hover.y }}
            data-testid={`${testId}-tooltip`}
          >
          <m.div
            initial={reduced ? false : { opacity: 0, y: 4, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? undefined : { opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12, ease: "easeOut" }}
            className="rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
              {fullLabel(hoverPoint.ts)}
            </div>
            {/* `justify-between` + `min-w-0` on each value span (not
                plain `ml-auto`, 2026-09-12 real fix -- same flexbox
                gotcha `RealEmissionsTrend`'s tooltip had): a bare
                `ml-auto` flex item keeps the browser's default
                `min-width: auto`, refusing to shrink/wrap below its own
                content width. */}
            {hoverPoint.actualMw !== null ? (
              <div className="flex items-start justify-between gap-2 py-0.5">
                <span className="flex shrink-0 items-center gap-2">
                  <span className="h-1.5 w-3 rounded-full bg-white" />
                  <span className="text-white/65">Actual</span>
                </span>
                <span className="min-w-0 text-right font-mono font-semibold text-white">
                  {hoverPoint.actualMw.toLocaleString()} MW
                </span>
              </div>
            ) : (
              <div className="py-0.5 text-white/40">Actual — not landed yet</div>
            )}
            <div className="flex items-start justify-between gap-2 py-0.5">
              <span className="flex shrink-0 items-center gap-2">
                <span className="h-1.5 w-3 rounded-full border border-dashed border-sky-300/60" />
                <span className="text-white/65">Predicted P10</span>
              </span>
              <span className="min-w-0 text-right font-mono text-white/80">{hoverPoint.p10Mw.toLocaleString()} MW</span>
            </div>
            <div className="flex items-start justify-between gap-2 py-0.5">
              <span className="flex shrink-0 items-center gap-2">
                <span className="h-1.5 w-3 rounded-full bg-sky-300" />
                <span className="text-white/65">Predicted P50</span>
              </span>
              <span className="min-w-0 text-right font-mono font-semibold text-white">{hoverPoint.p50Mw.toLocaleString()} MW</span>
            </div>
            <div className="flex items-start justify-between gap-2 py-0.5">
              <span className="flex shrink-0 items-center gap-2">
                <span className="h-1.5 w-3 rounded-full border border-dashed border-sky-300/60" />
                <span className="text-white/65">Predicted P90</span>
              </span>
              <span className="min-w-0 text-right font-mono text-white/80">{hoverPoint.p90Mw.toLocaleString()} MW</span>
            </div>
          </m.div>
          </div>
        )}
      </AnimatePresence>

      <p className="mt-2 flex items-center gap-1.5 text-[11px] text-white/40">
        <Info className="h-3 w-3" />
        A real walk-forward re-forecast of the currently-served model against real actual demand
        — not a live forecast. Both series end at the model&apos;s own most recent real origin.
      </p>
    </div>
  );
}
