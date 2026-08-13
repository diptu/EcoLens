/**
 * DemandForecastChart — real "Actual" demand history (no fabricated
 * band -- a measured reading has no real uncertainty, same convention
 * `RealEmissionsTrend` uses for its own "Actual" segment) + real
 * P10/P50/P90 demand forecast, on one shared time axis, split into two
 * clean non-overlapping regions by a real "Now" boundary.
 *
 * Shared by the Executive Dashboard's "Demand Forecast Preview" and the
 * Forecast Explorer's "Actual vs Predicted" section -- extracted
 * 2026-08-10 rather than left duplicated a third time; both callers
 * pass real, region-scoped data, this component has no page-specific
 * logic of its own.
 *
 * "Actual" is expected to be `total_generation_mwh` (see call sites'
 * own comments for why that's the honest proxy this platform actually
 * has for demand, since there's no separately-metered demand time
 * series) -- this component itself doesn't care what unit-consistent
 * MW-ish reading it's given, just that it's real and comparable to the
 * forecast's own MW units.
 *
 * Two-region alignment (fixed 2026-08-10): rather than plotting `actual`
 * on a shared clock ending at wall-clock "now" (which can chronologically
 * interleave with a real forecast that's serving-lagged behind live,
 * splitting the chart into confusing fragments instead of two clean
 * regions), this component trims `actual` internally to end exactly
 * where the real forecast's own first point begins, and anchors the
 * "Now" line to that same real boundary -- not `Date.now()`. The real
 * lag itself stays disclosed separately (the caption below the chart),
 * computed against true wall-clock time, so "Now" being behind live
 * right now is never silently hidden by the realignment.
 *
 * Actual line never visually breaks (2026-08-11, same fix as
 * `RealEmissionsTrend`'s identical one): a real missing hour's reading
 * no longer splits the line into disconnected segments -- it's always
 * one continuous path straight across any such gap, with a caption
 * below the chart disclosing the real gap count instead of either
 * breaking the line or silently pretending nothing was missing.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import { Info } from "lucide-react";

export type DemandActualPoint = { ts: string; tMs: number; mw: number };
export type DemandForecastPoint = { ts: string; tMs: number; p10: number; p50: number; p90: number };

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

/** Smallest "nice" 1/2/2.5/5/10 × 10^n value that's still >= `v` with
 * ~10% headroom -- guarantees `niceY(v) >= v`, so a real peak never
 * clips off the top of the chart's SVG viewBox. */
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

export function DemandForecastChart({
  actual,
  forecast,
  maxActualPoints = 24,
  testId = "forecast-sparkline",
}: {
  actual: DemandActualPoint[];
  forecast: DemandForecastPoint[];
  /** How many real actual-history points (closest to the "Now"
   * boundary) to display -- callers can fetch a wider real window than
   * this to guarantee enough history precedes a laggy forecast (see
   * this module's own header comment), without that wider fetch also
   * cluttering the chart with more days than a "preview" needs. Default
   * (24) matches the Executive Dashboard's own prior fixed behavior. */
  maxActualPoints?: number;
  /** Distinct testids per page -- the Executive Dashboard and Forecast
   * Explorer both render this component on their own separate page, so
   * a repeated default is fine (Playwright scopes to whichever page is
   * loaded), but a caller can override if it ever needs two on one
   * page at once. */
  testId?: string;
}) {
  const reduced = useReducedMotion();
  const w = 1200, h = 300, padL = 50, padR = 16, padT = 20, padB = 40;
  const innerW = w - padL - padR, innerH = h - padT - padB;

  type DemandChartPoint = {
    tMs: number;
    label: string;
    fullLabel: string;
    segment: "actual" | "forecast";
    actualMw: number | null;
    p10Mw: number | null;
    p50Mw: number | null;
    p90Mw: number | null;
  };

  // Trim `actual` to end exactly where the real forecast begins (see
  // this module's own header comment for why) -- done here, not by the
  // caller, so every caller gets a correctly two-region chart without
  // needing to remember the alignment step itself.
  const forecastStartMs = forecast.length > 0 ? forecast[0].tMs : null;
  const trimmedActual = (
    forecastStartMs !== null ? actual.filter((p) => p.tMs < forecastStartMs) : actual
  ).slice(-maxActualPoints);

  const points: DemandChartPoint[] = [
    ...trimmedActual.map((p) => ({
      tMs: p.tMs,
      label: hourLabel(p.ts),
      fullLabel: fullLabel(p.ts),
      segment: "actual" as const,
      actualMw: p.mw,
      p10Mw: null,
      p50Mw: null,
      p90Mw: null,
    })),
    ...forecast.map((p) => ({
      tMs: p.tMs,
      label: hourLabel(p.ts),
      fullLabel: fullLabel(p.ts),
      segment: "forecast" as const,
      actualMw: null,
      p10Mw: p.p10,
      p50Mw: p.p50,
      p90Mw: p.p90,
    })),
  ].sort((a, b) => a.tMs - b.tMs);

  const yMaxRaw = Math.max(1, ...points.map((p) => Math.max(p.actualMw ?? 0, p.p90Mw ?? 0)));
  const yMax = niceY(yMaxRaw);

  const tMin = points.length ? points[0].tMs : Date.now();
  const tMax = points.length ? points[points.length - 1].tMs : Date.now();
  const tSpan = Math.max(1, tMax - tMin);
  const x = (tMs: number) => padL + ((tMs - tMin) / tSpan) * innerW;
  const y = (v: number) => padT + innerH * (1 - v / yMax);

  const actualPts = points.filter((p) => p.segment === "actual" && p.actualMw !== null);
  const fcPts = points.filter((p) => p.segment === "forecast" && p.p50Mw !== null);

  // Real gaps happen (a genuinely missing hour's reading -- same real
  // cause `RealEmissionsTrend`'s own Actual line can hit, see that
  // component's header comment). Always drawn as a single continuous
  // path straight across any such gap rather than visually breaking
  // the line -- not hidden, though: `actualGapCount` below backs a
  // caption disclosing that real gaps exist and were bridged.
  const actualSegments = [smoothPath(actualPts.map((p) => [x(p.tMs), y(p.actualMw!)]))];
  let actualGapCount = 0;
  for (let i = 1; i < actualPts.length; i++) {
    if (actualPts[i].tMs - actualPts[i - 1].tMs > GAP_THRESHOLD_MS) actualGapCount++;
  }
  const fcP50Segments = splitOnGaps(fcPts).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.p50Mw!)])),
  );
  const fcBandSegments = splitOnGaps(fcPts).map((seg) =>
    smoothBandPath(
      seg.map((p) => [x(p.tMs), y(p.p90Mw!)]),
      seg.map((p) => [x(p.tMs), y(p.p10Mw!)]),
    ),
  );

  // The "Now" line marks the real boundary between the two regions, not
  // literally `Date.now()` at render time -- see this module's own
  // header comment.
  const nowMs = fcPts.length > 0 ? fcPts[0].tMs : Date.now();
  const nowInRange = nowMs >= tMin && nowMs <= tMax;

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || points.length === 0) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const svgX = (mx / rect.width) * w;
      const svgY = (my / rect.height) * h;
      let nearest = 0;
      let best = Infinity;
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        const py = p.segment === "actual" ? y(p.actualMw!) : y(p.p50Mw!);
        const d = (x(p.tMs) - svgX) ** 2 + (py - svgY) ** 2;
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
  }, [points.length, tMin, tSpan, innerW]);

  const hoverPoint = hover ? points[hover.idx] : null;

  if (points.length === 0) {
    return <p className="py-16 text-center text-xs text-white/40">No real data yet.</p>;
  }

  const yLabels = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: padT + (1 - f) * innerH,
    label: fmtMwLabel(f * yMax),
  }));
  const labelEvery = points.length > 30 ? 4 : points.length > 16 ? 2 : 1;

  // Real, disclosed lag vs. TRUE wall-clock time (deliberately
  // `Date.now()` here, not the chart's own `nowMs` boundary above,
  // which is anchored to the forecast's own start and would make this
  // always read ~0).
  const forecastLagHours =
    fcPts.length > 0 ? Math.max(0, (Date.now() - fcPts[fcPts.length - 1].tMs) / 3_600_000) : null;

  return (
    <div ref={wrapRef} className="relative" data-testid={testId}>
      {/* `aspect-ratio` (not a fixed height class) -- with
          `preserveAspectRatio="none"`, any real mismatch between this
          box's rendered aspect and the `${w}/${h}` viewBox non-uniformly
          scales x vs y, which visibly distorts text (confirmed live: the
          "Now" label rendered as an illegible diagonal sliver before
          this fix). */}
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

        {fcBandSegments.map((d, i) => (
          <m.path
            key={`band-${i}`}
            d={d}
            fill="rgba(52,211,153,0.10)"
            stroke="none"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.3 }}
          />
        ))}
        {fcP50Segments.map((d, i) => (
          <m.path
            key={`p50-${i}`}
            d={d}
            fill="none"
            stroke="#34d399"
            strokeWidth={2}
            strokeDasharray="6 3"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1, delay: 0.5, ease: "easeInOut" }}
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
          />
        ))}
        {fcPts.map((p, i) => (
          <m.circle
            key={`fcdot-${i}`}
            cx={x(p.tMs)}
            cy={y(p.p50Mw!)}
            r={3}
            fill="#0a1410"
            stroke="#34d399"
            strokeWidth={1.5}
            initial={reduced ? false : { scale: 0 }}
            animate={{ scale: 1 }}
            transition={{
              type: "spring",
              stiffness: 280,
              damping: 22,
              delay: reduced ? 0 : 0.7 + (i / fcPts.length) * 0.3,
            }}
          />
        ))}

        {nowInRange && (
          <g data-testid="forecast-now-marker">
            <line
              x1={x(nowMs)} x2={x(nowMs)} y1={padT} y2={padT + innerH}
              stroke="rgba(255,255,255,0.18)" strokeWidth={0.7} strokeDasharray="3 3"
            />
            <text x={x(nowMs)} y={padT - 6} textAnchor="middle" fontSize="10" fontWeight={600} fill="rgba(255,255,255,0.7)">
              Now
            </text>
          </g>
        )}

        {points.map(
          (p, i) =>
            (i % labelEvery === 0 || i === points.length - 1) && (
              <text key={`xlbl-${i}`} x={x(p.tMs)} y={h - 12} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.45)">
                {p.label}
              </text>
            ),
        )}
        <g>
          <text x={padL} y={h - 2} fontSize="9" fill="rgba(255,255,255,0.5)">
            {new Date(points[0].tMs).toLocaleDateString([], { month: "short", day: "numeric" })}
          </text>
          <text x={w - padR} y={h - 2} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.5)">
            {new Date(points[points.length - 1].tMs).toLocaleDateString([], { month: "short", day: "numeric" })}
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
            {hoverPoint.p50Mw !== null && (
              <circle cx={x(hoverPoint.tMs)} cy={y(hoverPoint.p50Mw)} r={4} fill="#0a1410" stroke="#34d399" strokeWidth={2} />
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
            className="pointer-events-none absolute z-20 min-w-[180px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
            style={{ left: hover.x, top: hover.y }}
            data-testid={`${testId}-tooltip`}
          >
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
              {hoverPoint.fullLabel}
            </div>
            {hoverPoint.actualMw !== null && (
              <div className="flex items-center gap-2 py-0.5">
                <span className="h-1.5 w-3 rounded-full bg-white" />
                <span className="text-white/65">Actual</span>
                <span className="ml-auto font-mono font-semibold text-white">
                  {hoverPoint.actualMw.toLocaleString()} MW
                </span>
              </div>
            )}
            {hoverPoint.p50Mw !== null && (
              <>
                <div className="flex items-center gap-2 py-0.5">
                  <span className="h-1.5 w-3 rounded-full border border-dashed border-emerald-100/50" />
                  <span className="text-white/65">P10</span>
                  <span className="ml-auto font-mono text-white/80">{hoverPoint.p10Mw!.toLocaleString()} MW</span>
                </div>
                <div className="flex items-center gap-2 py-0.5">
                  <span className="h-1.5 w-3 rounded-full bg-emerald-300" />
                  <span className="text-white/65">P50</span>
                  <span className="ml-auto font-mono font-semibold text-white">{hoverPoint.p50Mw.toLocaleString()} MW</span>
                </div>
                <div className="flex items-center gap-2 py-0.5">
                  <span className="h-1.5 w-3 rounded-full border border-dashed border-emerald-100/50" />
                  <span className="text-white/65">P90</span>
                  <span className="ml-auto font-mono text-white/80">{hoverPoint.p90Mw!.toLocaleString()} MW</span>
                </div>
              </>
            )}
          </m.div>
        )}
      </AnimatePresence>

      {forecastLagHours !== null && forecastLagHours > 1 && (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-200/80">
          <Info className="h-3 w-3" />
          The &quot;Now&quot; line marks the real forecast&apos;s own start, not this instant — the
          serving model&apos;s own lookback data is ~{Math.round(forecastLagHours)}h behind live
          ingestion right now, not a display artifact.
        </p>
      )}
      {actualGapCount > 0 && (
        <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-white/40">
          <Info className="h-3 w-3" />
          Actual has {actualGapCount} real gap{actualGapCount === 1 ? "" : "s"} in this window
          (hours with no real reading yet) — the line is drawn straight across them to stay
          continuous rather than breaking.
        </p>
      )}
    </div>
  );
}
