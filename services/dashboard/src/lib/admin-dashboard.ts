/**
 * Data layer for the Emissions Trend v2 chart (`components/dashboard/
 * emissions-trend-v2.tsx`) and the shared task/KPI types the
 * Data Ingestion page's real, API-backed data conforms to
 * (`ActiveTask`/`OperationalKpi`/`TaskStatus`/`TaskType` — that page no
 * longer calls any generator here; see its own `lib/admin-dashboard.ts`
 * doc-comment references for what replaced each mock).
 *
 * Pure deterministic generators (no Date.now() in the hot path) so the
 * data is reproducible across SSR and CSR.
 */

// ────────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────────

export type TaskType =
  | "ingestion"
  | "model_training"
  | "data_quality"
  | "feature_build"
  | "forecast"
  | "report"
  | "anomaly"
  | "transform";
export type TaskStatus = "running" | "queued" | "completed" | "failed";

export interface ActiveTask {
  id: string;
  type: TaskType;
  target: string;
  triggered_by: string;
  started_at: string;
  status: TaskStatus;
  progress: number;       // 0-100
}

export interface OperationalKpi {
  label: string;
  value: number | string;
  unit?: string;
  sub: string;
  icon: string;
  tone: "ok" | "warn" | "neutral";
}

// ────────────────────────────────────────────────────────────────────
// Deterministic PRNG
// ────────────────────────────────────────────────────────────────────

function _seededRng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Was hardcoded to a fixed "2026-05-19" -- reasonable when that really
// was "today" for whoever built this mock, but it silently drifts out of
// date after: the Executive Dashboard's "Emissions Trend" (falls back to
// this mock whenever the real 8-day fetch doesn't have enough points --
// see that page's own fetch handler) kept showing a fixed mid-May window
// no matter what day it actually was. `Date.now()` at module-load time --
// this is mock/placeholder data, not something that needs to update
// live within a single page session.
const ANCHOR_DATE = Date.now();

// ────────────────────────────────────────────────────────────────────
// Emissions trend v2 -- explicitly mock, ported verbatim (module-load
// `ANCHOR_DATE` swap aside, matching this file's own established
// convention above) from the "v18x" prototype export the executive
// page's Emissions Trend section was pointed at on 2026-08-09, per
// direct request after disclosing this is 100% synthetic (a seeded
// diurnal-curve generator, not real backend data): a full 24-168h
// forecast shape, a 12h smoothstep blend at the now->forecast
// transition, and a P10-P90 band that mechanically grows 10%->45%
// with horizon.
// ────────────────────────────────────────────────────────────────────

export interface EmissionsTrendPointV2 {
  ts: string;
  label: string;
  segment: "past" | "now" | "forecast";
  actual: number | null;
  past_p10: number | null;
  past_p90: number | null;
  forecast_p50: number;
  forecast_p10: number;
  forecast_p90: number;
}

export type EmissionsTrendRegion = "all" | "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1" | "WEM";
export type EmissionsTrendHorizon = "next_24h" | "next_48h" | "next_7d";

export interface EmissionsTrendResponse {
  region: EmissionsTrendRegion;
  horizon: EmissionsTrendHorizon;
  generated_at: string;
  past_label: string;
  forecast_label: string;
  points: EmissionsTrendPointV2[];
  summary: {
    latest_actual_tco2e: number;
    latest_actual_label: string;
    forecast_p50_avg_tco2e: number;
    forecast_p10_avg_tco2e: number;
    forecast_p90_avg_tco2e: number;
    forecast_hours: number;
    granularity: "hourly";
  };
}

function hashRegion(r: EmissionsTrendRegion): number {
  let h = 0;
  for (let i = 0; i < r.length; i++) h = (h * 31 + r.charCodeAt(i)) | 0;
  return h;
}
function hashHorizon(h: EmissionsTrendHorizon): number {
  let v = 0;
  for (let i = 0; i < h.length; i++) v = (v * 17 + h.charCodeAt(i)) | 0;
  return v;
}

const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function shortDayLabel(d: Date): string {
  return `${SHORT_MONTHS[d.getUTCMonth()]} ${d.getUTCDate().toString().padStart(2, "0")}`;
}

export function getEmissionsTrendV2(
  region: EmissionsTrendRegion = "all",
  horizon: EmissionsTrendHorizon = "next_48h",
): EmissionsTrendResponse {
  const rng = _seededRng((0x4EC0 << 16) ^ hashRegion(region) ^ hashHorizon(horizon));

  const regionScale = region === "all" ? 1.0 : 0.22;
  const dailyMean = 12_000 * regionScale;
  const pastPoints: EmissionsTrendPointV2[] = [];
  const nowAnchor = ANCHOR_DATE;
  let actualAtNow = 0;

  for (let d = 6; d >= 0; d--) {
    const dayFactor = 0.85 + rng() * 0.3;
    for (let h = 0; h < 24; h++) {
      const ts = new Date(nowAnchor - d * 86_400_000 + (h - 12) * 3_600_000);
      const hourAngle = ((h - 4 + 24) % 24) / 24;
      const diurnal = 0.65 + 0.8 * Math.sin(hourAngle * Math.PI);
      const actual = Math.round(dailyMean * dayFactor * diurnal);
      const spread = actual * (0.14 + rng() * 0.10);
      const pastP10 = Math.max(0, Math.round(actual - spread));
      const pastP90 = Math.round(actual + spread);
      const isNow = d === 0 && h === 14;
      const point: EmissionsTrendPointV2 = {
        ts: ts.toISOString(),
        label: d === 0 ? `${h.toString().padStart(2, "0")}:00` : shortDayLabel(ts),
        segment: isNow ? "now" : "past",
        actual,
        past_p10: pastP10,
        past_p90: pastP90,
        forecast_p10: isNow ? pastP10 : 0,
        forecast_p50: isNow ? actual : 0,
        forecast_p90: isNow ? pastP90 : 0,
      };
      pastPoints.push(point);
      if (isNow) actualAtNow = actual;
    }
  }

  const nowPoint = pastPoints.find((p) => p.segment === "now")!;
  const anchorValue = nowPoint.actual!;

  const forecastHours = horizon === "next_24h" ? 24 : horizon === "next_48h" ? 48 : 168;
  const forecastStartTs = new Date(nowAnchor + 3 * 3_600_000);
  const forecastPoints: EmissionsTrendPointV2[] = [];
  for (let h = 0; h < forecastHours; h++) {
    const ts = new Date(forecastStartTs.getTime() + h * 3_600_000);
    const hourAngle = ((ts.getUTCHours() - 4 + 24) % 24) / 24;
    const naturalDiurnal = 0.7 + 0.85 * Math.sin(hourAngle * Math.PI);
    const naturalFc = dailyMean * 1.55 * naturalDiurnal;

    const blendHours = 12;
    const t = Math.min(1, (h + 1) / blendHours);
    const blendWeight = t * t * (3 - 2 * t);
    const flatMean = anchorValue;
    const blendedFc = flatMean * (1 - blendWeight) + naturalFc * blendWeight;
    const fcMean = blendedFc;

    const baseSpreadPct = 0.10 + blendWeight * 0.35;
    const fcP50 = Math.round(fcMean);
    const fcSpread = fcP50 * (baseSpreadPct + rng() * 0.05);
    forecastPoints.push({
      ts: ts.toISOString(),
      label: h < 24 ? `${ts.getUTCHours().toString().padStart(2, "0")}:00` : shortDayLabel(ts),
      segment: "forecast",
      actual: null,
      past_p10: null,
      past_p90: null,
      forecast_p10: Math.max(0, Math.round(fcP50 - fcSpread)),
      forecast_p50: fcP50,
      forecast_p90: Math.round(fcP50 + fcSpread),
    });
  }

  const fcP50s = forecastPoints.map((p) => p.forecast_p50);
  const fcP10s = forecastPoints.map((p) => p.forecast_p10);
  const fcP90s = forecastPoints.map((p) => p.forecast_p90);
  const avg = (arr: number[]) => Math.round(arr.reduce((a, b) => a + b, 0) / arr.length);

  return {
    region,
    horizon,
    generated_at: new Date(nowAnchor).toISOString(),
    past_label: "Past (Actual)",
    forecast_label: `Forecast (${horizon.replace("_", " ")})`,
    points: [...pastPoints, ...forecastPoints],
    summary: {
      latest_actual_tco2e: actualAtNow,
      latest_actual_label: `Today, 14:00`,
      forecast_p50_avg_tco2e: avg(fcP50s),
      forecast_p10_avg_tco2e: avg(fcP10s),
      forecast_p90_avg_tco2e: avg(fcP90s),
      forecast_hours: forecastHours,
      granularity: "hourly",
    },
  };
}
