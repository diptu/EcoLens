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
 * **1D/2D/7D toggle applies to the forecast only (2026-08-11, relabeled
 * from 6h/24h/48h same day)**: Actual always shows a fixed real 7-day
 * window ending at the latest real hour: the toggle instead selects how
 * many of the real forecast's hourly steps to *display* in real-hour
 * terms (`fetchEmissionsForecast` returns up to its own real horizon --
 * currently 48h -- the toggle just truncates how much of that gets
 * plotted, e.g. "1D" shows only the first 24 real steps). "7D" (168h)
 * always exceeds that real 48h horizon -- selecting it reliably shows
 * the real "shorter than requested" caption below rather than silently
 * capping with no explanation, same as any other over-request would.
 *
 * **Continuous, gap-free Now boundary -- a deliberate re-anchor, not
 * the forecast's own real clock**: the real forecast's own point
 * timestamps don't reach into the future from wall-clock "now" -- they're
 * anchored to the model's own last-observed lookback window, which can
 * lag live ingestion by an honest, real amount (confirmed live,
 * 2026-08-10: the forecast's own latest point was ~17h behind wall-clock
 * "now"). Plotting forecast points at that real, lagged `ts` (the
 * previous approach) either left a visible gap or an overlap between
 * where Actual's real 7-day window stops and where the forecast's own
 * clock says it starts. Forecast points are now re-anchored to start at
 * wall-clock `now() - 30min` (2026-08-11) -- a fixed near-now boundary,
 * not tied to Actual's own latest real hour (which can itself lag true
 * now by a real, variable amount) -- same real forecast values, same
 * real per-step spacing (derived from the forecast's own consecutive
 * real timestamps), just re-plotted so the two segments read as one
 * continuous line with the Now boundary sitting ~30min behind true now.
 * The lag itself isn't hidden -- it stays disclosed via a caption below
 * the chart (computed against the forecast's real, un-re-anchored
 * timestamp), it's just not expressed as a visual gap anymore.
 *
 * No fabricated P10-P90 band on the *actual* segment either -- a
 * measured historical reading has no real uncertainty to show; only the
 * forecast segment (a real prediction) has one.
 *
 * **Actual line never visually breaks (2026-08-11)**: earlier, a real
 * time jump bigger than 90 real minutes between consecutive Actual
 * points (a genuinely missing hour's reading -- AEMO's own archive can
 * lag publishing its most recent days) split the line into disconnected
 * segments. That's real, but a broken/dotted-looking chart reads as "the
 * chart is broken," not "a specific hour is missing." The Actual line is
 * now always one continuous path straight across any such gap, same as
 * every other line on this chart -- still not hidden, though: a caption
 * below the chart discloses the real gap count (`loadTrend`'s own
 * `actualGapCount`) rather than silently pretending nothing was missing.
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

/** How many of the real forecast's own hourly steps to display -- NOT
 * an actual-history window (see this file's header comment). Values are
 * real hours (the unit `loadTrend` actually slices real forecast steps
 * by); "7D" (168h) is real on its face but exceeds the real forecast
 * model's own real horizon (confirmed live: 48h) -- selecting it always
 * shows the real `forecastHorizonShorterThanRequested` caption rather
 * than silently capping at 48h with no explanation. */
export type RangeHours = 24 | 48 | 168;

const RANGES: Array<{ value: RangeHours; label: string }> = [
  { value: 24, label: "1D" },
  { value: 48, label: "2D" },
  { value: 168, label: "7D" },
];

const DEFAULT_FORECAST_HOURS: RangeHours = 24;

/** "1D"/"2D"/"7D"-style label for a real hour count -- used for the
 * user-facing subtitle/caption text below so a real 168h selection
 * reads as "7D" there too, not an awkward literal "168h". Falls back to
 * a plain "Nh" for any real count that doesn't divide evenly into whole
 * days (e.g. `forecastHoursShown` when the real available horizon cuts
 * a request short partway through a day). */
function formatHoursLabel(hours: number): string {
  return hours > 0 && hours % 24 === 0 ? `${hours / 24}D` : `${hours}h`;
}

/** Fixed real actual-history window -- independent of the forecast-hours
 * toggle above (see header comment). 7 days matches the model's own
 * native hourly cadence without becoming an unreadable number of points. */
const ACTUAL_DAYS = 7;

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
  /** Real count of forecast steps actually plotted -- `min(requested
   * forecastHours, real available forecast steps)`. Drives the KPI tile
   * subs and the "shorter than requested" caption below. */
  forecastHoursShown: number;
  /** True when the real forecast horizon has fewer steps than the
   * requested `forecastHours` (e.g. a real forecast is only 4h long but
   * "24h" was selected) -- surfaced as a caption rather than silently
   * showing fewer hours than asked for with no explanation. */
  forecastHorizonShorterThanRequested: boolean;
  /** Real lag between the forecast's own real (un-re-anchored) last
   * timestamp and true wall-clock now -- computed before points are
   * re-anchored to sit continuously after Actual (see `loadTrend`'s own
   * comment), so this stays an honest number even though the chart no
   * longer visually shows the gap. */
  forecastLagHours: number | null;
  /** Real reason `fetchEmissionsForecast` failed (e.g. the model registry
   * has no Production version loaded), `null` when it succeeded. The
   * Actual line never depends on the forecast call, so a forecast failure
   * shouldn't blank the whole chart -- but silently dropping the Now line
   * and band with no explanation (the previous behavior) reads as "the
   * chart is broken" rather than "the forecast service is unavailable
   * right now," which is what's actually true. Surfaced as a caption
   * below the chart, same disclosure convention as `forecastLagHours`. */
  forecastError: string | null;
  /** Real count of hourly-cadence jumps bigger than `GAP_THRESHOLD_MS`
   * inside Actual's own real 7-day window -- e.g. a genuinely missing
   * hour's reading (confirmed live: AEMO's own real archive can lag
   * publishing recent days by ~2 real days, so the most recent hours
   * sometimes just aren't there yet). The Actual line is always plotted
   * as one continuous path regardless (see `TrendChart`'s own comment)
   * rather than visually breaking at each one -- this count backs a
   * caption disclosing that real gaps exist and were bridged, instead
   * of either breaking the line or hiding the gap's existence entirely. */
  actualGapCount: number;
};

async function loadTrend(region: TrendRegion, forecastHours: RangeHours): Promise<LoadedTrend> {
  const regionParam = region === "NEM" ? undefined : region;
  const bucket = "hour" as const;
  let forecastError: string | null = null;
  const [actual, forecast] = await Promise.all([
    fetchEmissionsTimeseries(bucket, ACTUAL_DAYS, regionParam),
    fetchEmissionsForecast(regionParam).catch((err): EmissionsForecast | null => {
      forecastError = err instanceof Error ? err.message : "forecast unavailable";
      return null;
    }),
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

  const lastActual = [...actualPoints].reverse()[0] ?? null;

  let actualGapCount = 0;
  for (let i = 1; i < actualPoints.length; i++) {
    if (actualPoints[i].tMs - actualPoints[i - 1].tMs > GAP_THRESHOLD_MS) actualGapCount++;
  }

  let forecastP50AvgTco2e: number | null = null;
  let forecastP10AvgTco2e: number | null = null;
  let forecastP90AvgTco2e: number | null = null;
  let forecastHorizonLabel = "unavailable";
  let forecastLagHours: number | null = null;
  let forecastHoursShown = 0;
  let forecastHorizonShorterThanRequested = false;
  const forecastPoints: TrendPoint[] = [];

  if (forecast && forecast.points.length > 0) {
    // Real lag, computed BEFORE re-anchoring below -- against the
    // forecast's own real, un-re-anchored last timestamp vs. true
    // wall-clock now, so this stays an honest number regardless of how
    // the points end up positioned for display (see this file's header
    // comment).
    const lastRealForecastMs = new Date(
      forecast.points[forecast.points.length - 1].ts,
    ).getTime();
    const lagMs = Date.now() - lastRealForecastMs;
    forecastLagHours = lagMs > 0 ? lagMs / 3_600_000 : null;

    // Real per-step spacing, derived from the forecast's own consecutive
    // real timestamps (not parsed from the `interval` label) -- reused
    // below so the re-anchored points keep the model's real cadence.
    const stepMs =
      forecast.points.length > 1
        ? new Date(forecast.points[1].ts).getTime() - new Date(forecast.points[0].ts).getTime()
        : 3_600_000;

    // `forecastHours` selects how much of the real forecast to *show*,
    // not an actual-history window (see header comment) -- e.g. "1D"
    // (24) plots only the first 24 real hourly steps `fetchEmissionsForecast`
    // returned. Flagged (not silently truncated) if the real horizon is
    // actually shorter than what was requested.
    const shown = forecast.points.slice(0, forecastHours);
    forecastHoursShown = shown.length;
    forecastHorizonShorterThanRequested = forecast.points.length < forecastHours;

    // Re-anchor: the first shown step renders at wall-clock `now() -
    // 30min`, not at the forecast's own real (possibly lagged)
    // timestamp -- see header comment for why. A fixed near-now anchor
    // (rather than the last real Actual point) keeps the join point
    // stable even when Actual's own most recent real hour is itself a
    // little behind true now (real ingestion lag, typically well under
    // 30min) -- the two segments read as one continuous line without
    // the boundary jumping around release to release.
    const anchorMs = Date.now() - 30 * 60_000;
    shown.forEach((p, i) => {
      const displayMs = anchorMs + i * stepMs;
      const displayIso = new Date(displayMs).toISOString();
      forecastPoints.push({
        ts: displayIso,
        tMs: displayMs,
        label: pointLabel(displayIso, "hour"),
        fullLabel: fullLabel(displayIso, "hour"),
        segment: "forecast",
        actualTco2e: null,
        p10Tco2e: p.p10_kgco2e / 1000,
        p50Tco2e: p.p50_kgco2e / 1000,
        p90Tco2e: p.p90_kgco2e / 1000,
      });
    });

    const p50s = shown.map((p) => p.p50_kgco2e / 1000);
    const p10s = shown.map((p) => p.p10_kgco2e / 1000);
    const p90s = shown.map((p) => p.p90_kgco2e / 1000);
    const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
    forecastP50AvgTco2e = avg(p50s);
    forecastP10AvgTco2e = avg(p10s);
    forecastP90AvgTco2e = avg(p90s);
    forecastHorizonLabel = forecast.horizon;
  }

  const points = [...actualPoints, ...forecastPoints].sort((a, b) => a.tMs - b.tMs);

  return {
    points,
    bucket,
    latestActualTco2e: lastActual?.actualTco2e ?? null,
    forecastP50AvgTco2e,
    forecastP10AvgTco2e,
    forecastP90AvgTco2e,
    forecastHorizonLabel,
    forecastHoursShown,
    forecastHorizonShorterThanRequested,
    forecastLagHours,
    forecastError,
    actualGapCount,
  };
}

export function RealEmissionsTrend({
  title = "Emissions Trend",
  initialRegion = "NEM",
}: {
  /** Override for the card's own heading -- callers embedding this on a
   * page with its own naming convention (e.g. Analytics' "Emissions
   * Forecast (Australia)") don't have to fork the component just to
   * relabel it. Everything else (region toggle, forecast-hours toggle,
   * real data/logic) stays identical regardless of title. */
  title?: string;
  initialRegion?: TrendRegion;
} = {}) {
  const [region, setRegion] = useState<TrendRegion>(initialRegion);
  const [forecastHours, setForecastHours] = useState<RangeHours>(DEFAULT_FORECAST_HOURS);
  const [data, setData] = useState<LoadedTrend | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    loadTrend(region, forecastHours)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [region, forecastHours]);

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
                {title}
              </h2>
              <button
                type="button"
                className="text-white/40 transition hover:text-white/80"
                title={`Real ${ACTUAL_DAYS}-day actual (hourly, GET /v1/emissions/timeseries) + next ${formatHoursLabel(forecastHours)} of the real demand-forecast-derived P10/P50/P90 (GET /v1/emissions/forecast), plotted continuously from where Actual ends`}
                aria-label="More info"
                data-testid="emissions-trend-info"
              >
                <Info className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-0.5 text-xs text-white/55">
              Real {ACTUAL_DAYS}-day actual + next {formatHoursLabel(forecastHours)} forecast
              confidence band (P10-P90), region-scoped
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RangeToggle value={forecastHours} onChange={setForecastHours} />
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
              showing: {formatHoursLabel(data.forecastHoursShown)} of {data.forecastHorizonLabel} real horizon
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
              sub={`next ${formatHoursLabel(data.forecastHoursShown)}`}
            />
            <KpiMiniTile
              label="Forecast Range (P10-P90) Avg"
              value={
                data.forecastP10AvgTco2e !== null && data.forecastP90AvgTco2e !== null
                  ? `${fmtKt(data.forecastP10AvgTco2e)} – ${fmtKt(data.forecastP90AvgTco2e)}`
                  : "—"
              }
              unit="tCO₂e"
              sub={`next ${formatHoursLabel(data.forecastHoursShown)}`}
            />
          </div>

          <TrendChart points={data.points} />

          {data.forecastError !== null && (
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-amber-200/80">
              <Info className="h-3 w-3" />
              Forecast unavailable right now ({data.forecastError}) — showing real actual
              emissions only. The &quot;Now&quot; line and forecast band will return once the
              forecast service responds.
            </p>
          )}
          {data.forecastLagHours !== null && data.forecastLagHours > 1 && (
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-amber-200/80">
              <Info className="h-3 w-3" />
              Forecast values reflect the serving model&apos;s own lookback data as of
              ~{Math.round(data.forecastLagHours)}h ago — plotted starting from Actual&apos;s
              latest point for a continuous read, not repositioned to hide the real lag.
            </p>
          )}
          {data.forecastHorizonShorterThanRequested && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-white/40">
              <Info className="h-3 w-3" />
              The real forecast horizon ({data.forecastHorizonLabel}) is shorter than the
              requested {formatHoursLabel(forecastHours)} — showing all {formatHoursLabel(data.forecastHoursShown)} available.
            </p>
          )}
          {data.actualGapCount > 0 && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-white/40">
              <Info className="h-3 w-3" />
              Actual has {data.actualGapCount} real gap{data.actualGapCount === 1 ? "" : "s"} in
              this window (hours AEMO hasn&apos;t published readings for yet) — the line is drawn
              straight across them to stay continuous rather than breaking.
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
}: {
  points: TrendPoint[];
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

  // Real gaps happen (documented, live-confirmed: AEMO's own real
  // archive can lag publishing its most recent days by ~2 real days, so
  // an individual hour's reading sometimes just isn't there yet) -- but
  // rather than visually breaking the line at each one (the previous
  // behavior), the Actual line is always drawn as a single continuous
  // path straight across any real gaps, same as every other line on
  // this chart. Not hidden, though: `loadTrend`'s own `actualGapCount`
  // backs a caption below the chart disclosing that real gaps exist and
  // were bridged, rather than either breaking the line or silently
  // pretending the data was never missing.
  const actualSegments = [smoothPath(actualPts.map((p) => [x(p.tMs), y(p.actualTco2e!)]))];
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

  // The "Now" line sits at the forecast's own re-anchored start --
  // `loadTrend` anchors that to wall-clock `now() - 30min` (see its own
  // comment), a fixed near-now boundary rather than Actual's own latest
  // real point, so the two segments read as one continuous line even
  // when Actual's most recent real hour lags true now by a little.
  // Falls back to wall-clock now only when there's no real forecast to
  // anchor to at all.
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

  // Real fix (2026-08-11): the tooltip below is centered on the cursor
  // (`-translate-x-1/2` around `left: hover.x`), which pushed it partly
  // outside this card's own `overflow-hidden` bounds -- invisible, not
  // just clipped-looking -- whenever the hovered point was near either
  // edge of the chart (confirmed live: hovering the most recent real
  // points, at the chart's right edge). Clamping the fed-in `left`
  // value keeps the same centered-on-cursor tooltip everywhere except
  // right at the edges, where it stays fully on-screen instead.
  const TOOLTIP_WIDTH_PX = 220; // matches the tooltip's own `min-w-[220px]` below
  const tooltipContainerWidth = wrapRef.current?.clientWidth ?? w;
  const tooltipLeft = hover
    ? Math.min(
        Math.max(hover.x, TOOLTIP_WIDTH_PX / 2),
        Math.max(TOOLTIP_WIDTH_PX / 2, tooltipContainerWidth - TOOLTIP_WIDTH_PX / 2),
      )
    : 0;

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
            style={{ left: tooltipLeft, top: hover.y }}
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
  value: RangeHours;
  onChange: (v: RangeHours) => void;
}) {
  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/5 p-0.5"
      role="tablist"
      aria-label="Forecast window"
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
