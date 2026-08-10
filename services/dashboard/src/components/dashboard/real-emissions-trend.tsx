/**
 * RealEmissionsTrend — Executive Dashboard emissions trend chart.
 *
 * Replaces `EmissionsTrendV2` (2026-08-10) -- that component was
 * explicitly, deliberately mock (a seeded generator reproducing a
 * reference screenshot, see its own header comment). This is the real
 * replacement: `GET /v1/emissions/timeseries` for the real actual
 * history and `GET /v1/emissions/forecast` (demand-forecast x current
 * intensity) for the real P10/P50/P90 band, both fetched per the
 * selected real region (NEM aggregate + the 5 NEM regions the backend
 * actually serves -- WEM excluded, its own different native cadence was
 * never in scope for the demand model's region training).
 *
 * **Real, disclosed data-freshness gap, not glossed over**: unlike a
 * synthetic generator, the real forecast's own point timestamps don't
 * necessarily reach into the future from wall-clock "now" -- they're
 * anchored to the model's own last-observed lookback window, which can
 * lag live ingestion by an honest, real amount (confirmed live,
 * 2026-08-10: the forecast's own latest point was ~17h behind wall-clock
 * "now"). Rather than repositioning points to *pretend* the forecast
 * starts at "now", every point renders at its own real `ts` on one
 * shared time axis, and a caption below the chart states the real lag
 * whenever the forecast's latest point is behind current time -- a
 * genuine, useful signal (serving/ingestion is behind), not a bug to
 * hide from the chart.
 *
 * No fabricated P10-P90 band on the *actual* segment either -- a
 * measured historical reading has no real uncertainty to show; only the
 * forecast segment (a real prediction) has one.
 *
 * **7D/30D/90D actual-range toggle (2026-08-10)**: `fetchEmissionsForecast`
 * is near-term only by design (its own docstring: "a few hours", not a
 * multi-day projection) -- there is no real multi-day forecast anywhere
 * in this platform to back a 30D/90D *prediction*. So the range toggle
 * below only widens the real **actual** window (`GET /v1/emissions/
 * timeseries`); the real P10-P90 band still only ever covers its own
 * real near-term horizon, same as before, regardless of which range is
 * selected. A caption makes that explicit rather than letting a wide
 * "90D" selection imply a 90-day-out prediction that doesn't exist.
 * 7D keeps hourly buckets (matches the model's own native cadence); 30D
 * and 90D switch to daily buckets -- 30-90 days of hourly points would
 * be both an unreadable chart and needless payload for a trend view.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { m, AnimatePresence, useReducedMotion } from "framer-motion";
import { Globe, Info, ArrowUpRight } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  fetchEmissionsTimeseries,
  fetchEmissionsForecast,
  type EmissionsForecast,
} from "@/lib/emissions";

export type TrendRegion = "NEM" | "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1";

const REGIONS: Array<{ value: TrendRegion; label: string }> = [
  { value: "NEM", label: "NEM (all 5 regions)" },
  { value: "NSW1", label: "NSW1" },
  { value: "QLD1", label: "QLD1" },
  { value: "VIC1", label: "VIC1" },
  { value: "SA1", label: "SA1" },
  { value: "TAS1", label: "TAS1" },
];

export type RangeDays = 7 | 30 | 90;

const RANGES: Array<{ value: RangeDays; label: string }> = [
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
  { value: 90, label: "90D" },
];

const DEFAULT_RANGE_DAYS: RangeDays = 7;

/** 7D matches the model's own native hourly cadence; 30D/90D would be
 * 720-2160 hourly points -- unreadable and unnecessary for a trend
 * view, so those switch to daily buckets (backend-supported, see
 * `fetchEmissionsTimeseries`'s own `bucket` param). */
function bucketFor(days: RangeDays): "hour" | "day" {
  return days <= 7 ? "hour" : "day";
}

export type TrendPoint = {
  ts: string;
  tMs: number;
  label: string;
  fullLabel: string;
  segment: "actual" | "forecast";
  actualTco2e: number | null;
  p10Tco2e: number | null;
  p50Tco2e: number | null;
  p90Tco2e: number | null;
};

function pointLabel(ts: string, bucket: "hour" | "day"): string {
  const d = new Date(ts);
  return bucket === "day"
    ? d.toLocaleDateString([], { month: "short", day: "numeric" })
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fullLabel(ts: string, bucket: "hour" | "day"): string {
  return new Date(ts).toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(bucket === "hour" ? { hour: "2-digit" as const, minute: "2-digit" as const } : {}),
  });
}

type LoadedTrend = {
  points: TrendPoint[];
  bucket: "hour" | "day";
  latestActualTco2e: number | null;
  forecastP50AvgTco2e: number | null;
  forecastP10AvgTco2e: number | null;
  forecastP90AvgTco2e: number | null;
  forecastHorizonLabel: string;
  forecastLagHours: number | null;
};

async function loadTrend(region: TrendRegion, rangeDays: RangeDays): Promise<LoadedTrend> {
  const regionParam = region === "NEM" ? undefined : region;
  const bucket = bucketFor(rangeDays);
  const [actual, forecast] = await Promise.all([
    fetchEmissionsTimeseries(bucket, rangeDays, regionParam),
    fetchEmissionsForecast(regionParam).catch((): EmissionsForecast | null => null),
  ]);

  const actualPoints: TrendPoint[] = actual.points
    .filter((p) => p.total_emissions_kgco2e !== null)
    .map((p) => ({
      ts: p.bucket,
      tMs: new Date(p.bucket).getTime(),
      label: pointLabel(p.bucket, bucket),
      fullLabel: fullLabel(p.bucket, bucket),
      segment: "actual" as const,
      actualTco2e: p.total_emissions_kgco2e! / 1000,
      p10Tco2e: null,
      p50Tco2e: null,
      p90Tco2e: null,
    }));

  // Real "Latest Actual" stat -- from the FULL, untrimmed actual
  // history (below, `points` only keeps what's *plotted*, which is
  // trimmed to end at the forecast's own real start -- see that
  // trimming's own comment for why). This stat isn't tied to a specific
  // chart pixel, so it stays the honestly-most-recent real hour
  // regardless of where the chart itself stops drawing.
  const lastActual = [...actualPoints].reverse()[0] ?? null;

  let forecastP50AvgTco2e: number | null = null;
  let forecastP10AvgTco2e: number | null = null;
  let forecastP90AvgTco2e: number | null = null;
  let forecastHorizonLabel = "unavailable";
  let forecastLagHours: number | null = null;
  const forecastPoints: TrendPoint[] = [];

  if (forecast && forecast.points.length > 0) {
    for (const p of forecast.points) {
      forecastPoints.push({
        ts: p.ts,
        tMs: new Date(p.ts).getTime(),
        label: pointLabel(p.ts, "hour"),
        fullLabel: fullLabel(p.ts, "hour"),
        segment: "forecast",
        actualTco2e: null,
        p10Tco2e: p.p10_kgco2e / 1000,
        p50Tco2e: p.p50_kgco2e / 1000,
        p90Tco2e: p.p90_kgco2e / 1000,
      });
    }
    const p50s = forecast.points.map((p) => p.p50_kgco2e / 1000);
    const p10s = forecast.points.map((p) => p.p10_kgco2e / 1000);
    const p90s = forecast.points.map((p) => p.p90_kgco2e / 1000);
    const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
    forecastP50AvgTco2e = avg(p50s);
    forecastP10AvgTco2e = avg(p10s);
    forecastP90AvgTco2e = avg(p90s);
    forecastHorizonLabel = forecast.horizon;
    const lastForecastMs = new Date(forecast.points[forecast.points.length - 1].ts).getTime();
    const lagMs = Date.now() - lastForecastMs;
    forecastLagHours = lagMs > 0 ? lagMs / 3_600_000 : null;
  }

  // Two distinct, non-overlapping regions -- "Actual" ending exactly
  // where the real forecast begins, not wherever wall-clock "now"
  // happens to fall. Real forecast serving lag (observed, up to ~21h)
  // means the forecast's own real timestamps sit *within* the actual
  // history's own span, not cleanly after it -- sorting both by real ts
  // on one shared axis (the previous approach) let the forecast band
  // visually cut into the middle of the actual line instead of sitting
  // after a single "Now" boundary. Trimming actual to end at the
  // forecast's own first real point (same real-boundary-alignment fix
  // `DemandForecastChart`, services/dashboard's executive page, already
  // uses) fixes *where the two regions sit relative to each other*,
  // not what's real -- the lag itself stays disclosed separately via
  // `forecastLagHours` above, computed against true wall-clock time.
  const forecastStartMs = forecastPoints.length > 0 ? forecastPoints[0].tMs : null;
  const trimmedActualPoints =
    forecastStartMs !== null ? actualPoints.filter((p) => p.tMs < forecastStartMs) : actualPoints;

  const points = [...trimmedActualPoints, ...forecastPoints].sort((a, b) => a.tMs - b.tMs);

  return {
    points,
    bucket,
    latestActualTco2e: lastActual?.actualTco2e ?? null,
    forecastP50AvgTco2e,
    forecastP10AvgTco2e,
    forecastP90AvgTco2e,
    forecastHorizonLabel,
    forecastLagHours,
  };
}

export function RealEmissionsTrend() {
  const [region, setRegion] = useState<TrendRegion>("NEM");
  const [rangeDays, setRangeDays] = useState<RangeDays>(DEFAULT_RANGE_DAYS);
  const [data, setData] = useState<LoadedTrend | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    loadTrend(region, rangeDays)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [region, rangeDays]);

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
                title={`Real ${rangeDays}-day actual (${bucketFor(rangeDays)}ly, GET /v1/emissions/timeseries) + real demand-forecast-derived P10/P50/P90 (GET /v1/emissions/forecast, near-term horizon only)`}
                aria-label="More info"
                data-testid="emissions-trend-info"
              >
                <Info className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-0.5 text-xs text-white/55">
              Real {rangeDays}-day actual + real forecast confidence band (P10-P90), region-scoped
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RangeToggle value={rangeDays} onChange={setRangeDays} />
          <PillSelect
            icon={<Globe className="h-3.5 w-3.5" />}
            value={region}
            options={REGIONS}
            onChange={setRegion}
            testId="emissions-trend-region"
          />
        </div>
      </div>

      {data === null ? (
        <p className="py-16 text-center text-xs text-white/40">
          {error ? `Unavailable — ${error}` : "Loading real emissions data…"}
        </p>
      ) : (
        <>
          <div className="mb-3 flex items-center gap-4 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 text-[11px] text-white/65">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-full bg-emerald-300" />
              Actual
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-3 rounded-full border-t-2 border-dashed border-sky-300" />
              Forecast (P50)
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-3.5 rounded-sm border border-sky-300/40 bg-sky-300/15" />
              Forecast P10-P90
            </span>
            <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-sky-300/40 bg-sky-300/10 px-2 py-0.5 text-sky-200">
              real horizon: {data.forecastHorizonLabel}
            </span>
          </div>

          <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <KpiMiniTile
              label="Latest Actual"
              value={data.latestActualTco2e !== null ? fmtKt(data.latestActualTco2e) : "—"}
              unit="tCO₂e"
              sub={`most recent real ${data.bucket}`}
            />
            <KpiMiniTile
              label="Forecast (P50) Avg"
              value={data.forecastP50AvgTco2e !== null ? fmtKt(data.forecastP50AvgTco2e) : "—"}
              unit="tCO₂e"
              sub={`real horizon: ${data.forecastHorizonLabel}`}
            />
            <KpiMiniTile
              label="Forecast Range (P10-P90) Avg"
              value={
                data.forecastP10AvgTco2e !== null && data.forecastP90AvgTco2e !== null
                  ? `${fmtKt(data.forecastP10AvgTco2e)} – ${fmtKt(data.forecastP90AvgTco2e)}`
                  : "—"
              }
              unit="tCO₂e"
              sub={`real horizon: ${data.forecastHorizonLabel}`}
            />
          </div>

          <TrendChart points={data.points} bucket={data.bucket} />

          {data.forecastLagHours !== null && data.forecastLagHours > 1 && (
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-amber-200/80">
              <Info className="h-3 w-3" />
              The &quot;Now&quot; line marks the real forecast&apos;s own start, not this instant —
              the serving model&apos;s own lookback data is ~{Math.round(data.forecastLagHours)}h
              behind live ingestion right now, not a display artifact.
            </p>
          )}
          {rangeDays > 7 && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-white/40">
              <Info className="h-3 w-3" />
              The confidence band only covers the model&apos;s real near-term horizon
              (real horizon: {data.forecastHorizonLabel}) — there is no {rangeDays}-day-out
              prediction to show, only {rangeDays} days of real actuals plus that near-term band.
            </p>
          )}
          <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-white/40">
            <Info className="h-3 w-3" />
            tCO₂e = tonnes of carbon dioxide equivalent. No band on Actual — a measured reading
            has no real uncertainty to show.
          </p>
        </>
      )}
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────────
// Chart
// ────────────────────────────────────────────────────────────────────

function TrendChart({
  points,
  bucket,
}: {
  points: TrendPoint[];
  bucket: "hour" | "day";
}) {
  const reduced = useReducedMotion();
  const w = 1200, h = 360;
  const padL = 70, padR = 24, padT = 28, padB = 40;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const yMaxRaw = Math.max(
    1,
    ...points.map((p) => Math.max(p.actualTco2e ?? 0, p.p90Tco2e ?? 0)),
  );
  const yMax = niceY(yMaxRaw);

  const tMin = points.length ? points[0].tMs : Date.now();
  const tMax = points.length ? points[points.length - 1].tMs : Date.now();
  const tSpan = Math.max(1, tMax - tMin);
  const x = (tMs: number) => padL + ((tMs - tMin) / tSpan) * innerW;
  const y = (v: number) => padT + innerH * (1 - v / yMax);

  const actualPts = points.filter((p) => p.segment === "actual" && p.actualTco2e !== null);
  const fcPts = points.filter((p) => p.segment === "forecast" && p.p50Tco2e !== null);

  // Real gaps happen (documented, live-confirmed: ~29h missing entirely
  // from `GET /v1/emissions/timeseries` on 2026-08-10, not a rounding
  // artifact) -- a single continuous smoothed path across a real 29h gap
  // draws a plausible-looking curve through a span with zero real data,
  // which is worse than no line at all. Splitting on any real time jump
  // bigger than 1.5 real steps (of whichever bucket this range actually
  // fetched -- an hourly 7D or a daily 30D/90D) breaks the line there
  // instead. Using the fixed hourly threshold for a daily-bucketed
  // range would treat every single real ~24h step as a "gap" and never
  // draw a connected line at all.
  const actualGapThresholdMs = bucket === "day" ? 36 * 60 * 60 * 1000 : GAP_THRESHOLD_MS;
  const actualSegments = splitOnGaps(actualPts, actualGapThresholdMs).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.actualTco2e!)])),
  );
  const fcP50Segments = splitOnGaps(fcPts).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.p50Tco2e!)])),
  );
  const fcBandSegments = splitOnGaps(fcPts).map((seg) =>
    smoothBandPath(
      seg.map((p) => [x(p.tMs), y(p.p90Tco2e!)]),
      seg.map((p) => [x(p.tMs), y(p.p10Tco2e!)]),
    ),
  );
  // Explicit P10/P90 edge lines -- the real interval is often narrow
  // relative to the chart's y-range (actual emissions swing far more
  // than the forecast's own uncertainty), so a fill alone can shrink to
  // a near-invisible sliver. Tracing both edges keeps the band legible
  // as a band even when it's only a few px tall.
  const fcP10Segments = splitOnGaps(fcPts).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.p10Tco2e!)])),
  );
  const fcP90Segments = splitOnGaps(fcPts).map((seg) =>
    smoothPath(seg.map((p) => [x(p.tMs), y(p.p90Tco2e!)])),
  );

  // The "Now" line marks the real boundary between the two regions --
  // where the trimmed real actual history stops and the real forecast
  // begins (see `loadTrend`'s own comment) -- not literally
  // `Date.now()` at render time, which the real forecast can lag well
  // behind (disclosed separately via the caption below `TrendChart`,
  // which *does* compare against true wall-clock time). Falls back to
  // `Date.now()` only when there's no forecast to anchor to at all.
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
      // 2D pixel distance, not just nearest-by-time -- the real actual
      // and forecast segments can genuinely overlap in time (the
      // disclosed forecast-lag quirk: the forecast's own real
      // timestamps aren't guaranteed to be the chronologically-latest
      // points), so nearest-by-time alone could pick a point from the
      // series the cursor isn't actually pointing at. Comparing full
      // (x, y) position picks whichever line the cursor is visually
      // closest to, same as any normal chart hover.
      let nearest = 0;
      let best = Infinity;
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        const py = p.segment === "actual" ? y(p.actualTco2e!) : y(p.p50Tco2e!);
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
  }, [points, tMin, tSpan, innerW]);

  const hoverPoint = hover ? points[hover.idx] : null;

  if (points.length === 0) {
    return <p className="py-16 text-center text-xs text-white/40">No real data for this region yet.</p>;
  }

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

        {fcBandSegments.map((d, i) => (
          <m.path
            key={`fcband-${i}`}
            d={d}
            fill="rgba(56,189,248,0.22)"
            stroke="none"
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.4 }}
            data-testid="emissions-trend-forecast-band"
          />
        ))}
        {fcP90Segments.map((d, i) => (
          <path key={`fcp90-${i}`} d={d} fill="none" stroke="rgba(125,211,252,0.5)" strokeWidth={1} strokeDasharray="3 3" />
        ))}
        {fcP10Segments.map((d, i) => (
          <path key={`fcp10-${i}`} d={d} fill="none" stroke="rgba(125,211,252,0.5)" strokeWidth={1} strokeDasharray="3 3" />
        ))}
        {fcP50Segments.map((d, i) => (
          <m.path
            key={`fcline-${i}`}
            d={d}
            fill="none"
            stroke="#7dd3fc"
            strokeWidth={2}
            strokeDasharray="8 4"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1, delay: 0.6, ease: "easeInOut" }}
            data-testid="emissions-trend-forecast-line"
          />
        ))}
        {actualSegments.map((d, i) => (
          <m.path
            key={`actual-${i}`}
            d={d}
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
        ))}

        {nowInRange && (
          <g data-testid="emissions-trend-now-marker">
            <line x1={x(nowMs)} x2={x(nowMs)} y1={padT} y2={padT + innerH} stroke="rgba(255,255,255,0.20)" strokeWidth={1} strokeDasharray="4 4" />
            <text x={x(nowMs)} y={padT - 10} textAnchor="middle" fontSize="10" fontWeight={600} fill="rgba(255,255,255,0.55)">
              Now
            </text>
          </g>
        )}

        {hover && hoverPoint && (
          <m.g initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.1 }}>
            <line
              x1={x(hoverPoint.tMs)}
              x2={x(hoverPoint.tMs)}
              y1={padT}
              y2={padT + innerH}
              stroke={hoverPoint.segment === "forecast" ? "rgba(125,211,252,0.4)" : "rgba(52,211,153,0.4)"}
              strokeWidth={0.5}
              strokeDasharray="2 2"
            />
            {hoverPoint.actualTco2e !== null && (
              <circle cx={x(hoverPoint.tMs)} cy={y(hoverPoint.actualTco2e)} r={5} fill="#34d399" stroke="#0a1410" strokeWidth={1.5} />
            )}
            {hoverPoint.p50Tco2e !== null && (
              <circle cx={x(hoverPoint.tMs)} cy={y(hoverPoint.p50Tco2e)} r={5} fill="#0a1410" stroke="#7dd3fc" strokeWidth={2} />
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
              {hoverPoint.fullLabel}
            </div>
            {hoverPoint.actualTco2e !== null && (
              <TooltipRow color="bg-emerald-300" label="Actual" value={`${hoverPoint.actualTco2e.toLocaleString(undefined, { maximumFractionDigits: 0 })} tCO₂e`} bold />
            )}
            {hoverPoint.p50Tco2e !== null && (
              <>
                <TooltipRow color="bg-sky-300" label="Forecast P50" value={`${hoverPoint.p50Tco2e.toLocaleString(undefined, { maximumFractionDigits: 0 })} tCO₂e`} bold />
                <TooltipRow
                  color="border border-sky-300/40"
                  label="Forecast P10-P90"
                  value={`${hoverPoint.p10Tco2e!.toLocaleString(undefined, { maximumFractionDigits: 0 })} – ${hoverPoint.p90Tco2e!.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                />
              </>
            )}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Small bits
// ────────────────────────────────────────────────────────────────────

function RangeToggle({
  value,
  onChange,
}: {
  value: RangeDays;
  onChange: (v: RangeDays) => void;
}) {
  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/5 p-0.5"
      role="tablist"
      aria-label="Actual history range"
      data-testid="emissions-trend-range"
    >
      {RANGES.map((r) => (
        <button
          key={r.value}
          type="button"
          role="tab"
          aria-selected={value === r.value}
          onClick={() => onChange(r.value)}
          data-testid={`emissions-trend-range-${r.value}`}
          className={cn(
            "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
            value === r.value
              ? "bg-emerald-200/15 text-emerald-100"
              : "text-white/60 hover:text-white",
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

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
  label, value, unit, sub,
}: {
  label: string;
  value: string;
  unit: string;
  sub: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5">
        <ArrowUpRight className="h-4 w-4 text-emerald-100" />
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

function TooltipRow({ color, label, value, bold }: { color: string; label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <span className={cn("h-1.5 w-3 rounded-full", color)} />
      <span className="text-white/65">{label}</span>
      <span className={cn("ml-auto font-mono", bold ? "font-semibold text-white" : "text-white/80")}>{value}</span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// SVG helpers
// ────────────────────────────────────────────────────────────────────

// Real data is nominally hourly -- a jump bigger than 1.5 real hours
// between consecutive points is a genuine gap (see `TrendChart`'s own
// comment for the live-confirmed ~29h example), not clock jitter.
const GAP_THRESHOLD_MS = 90 * 60 * 1000;

function splitOnGaps<T extends { tMs: number }>(pts: T[], thresholdMs = GAP_THRESHOLD_MS): T[][] {
  if (pts.length === 0) return [];
  const segments: T[][] = [[pts[0]]];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].tMs - pts[i - 1].tMs > thresholdMs) {
      segments.push([pts[i]]);
    } else {
      segments[segments.length - 1].push(pts[i]);
    }
  }
  return segments;
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

function smoothBandPath(topPts: Array<[number, number]>, botPts: Array<[number, number]>, tension: number = 0.35): string {
  if (topPts.length === 0 || botPts.length === 0 || topPts.length !== botPts.length) return "";
  const top = smoothPath(topPts, tension);
  const bottomReversed = smoothPath([...botPts].reverse(), tension).replace(/^M/, "L");
  return `${top} ${bottomReversed} Z`;
}

/** Smallest "nice" 1/2/2.5/5/10 × 10^n value that's still >= `v` with
 * ~10% headroom -- guarantees `niceY(v) >= v`, unlike the old formula's
 * `Math.ceil(norm) * mag * (step / 10)`, which for most real peak
 * values (e.g. 17,000 -> 4,400) returned a ceiling *below* the actual
 * max, clipping the line off the top of the chart's SVG viewBox. */
function niceY(v: number): number {
  if (v <= 0) return 1000;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = (v / mag) * 1.1;
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (norm <= step) return step * mag;
  }
  return 10 * mag;
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
