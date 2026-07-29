/**
 * Forecast data layer for ecoLens.
 *
 * In production this would be:
 *   fetch(`${FORECAST_API_URL}/v1/forecast/${region}?horizon=${steps}`)
 *     .then(r => r.json())
 *
 * For the dashboard demo (no forecast-api service attached yet)
 * we generate deterministic, realistic-looking NEM demand
 * forecasts with a seeded PRNG so the chart is reproducible
 * across reloads and SSR/CSR.
 *
 * Realism:
 *  - Each region has a characteristic demand profile (mean + amplitude)
 *  - Two daily peaks: morning ramp (~7-9am) and evening peak (~6-8pm)
 *  - Weekday/weekend offset
 *  - P10/P90 bands widen with horizon (uncertainty grows)
 *  - Bands are asymmetric (P90-P50 > P50-P10 for peaks)
 *
 * Pure functions only — no fetch, no I/O. The page component
 * decides whether to use this generator or call the real API.
 */

import type { User } from "./auth";

export type Region = "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1" | "WEM";

export const ALL_REGIONS: Region[] = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"];

export type Horizon = 4 | 8 | 12 | 24 | 48 | 96 | 168 | 336;
export const ALL_HORIZONS: { steps: Horizon; label: string; hours: number }[] = [
  { steps: 4,   label: "2h",   hours: 2 },
  { steps: 8,   label: "4h",   hours: 4 },
  { steps: 12,  label: "6h",   hours: 6 },
  { steps: 24,  label: "12h",  hours: 12 },
  { steps: 48,  label: "24h",  hours: 24 },
  { steps: 96,  label: "2d",   hours: 48 },
  { steps: 168, label: "3.5d", hours: 84 },
  { steps: 336, label: "1wk",  hours: 168 },
];

/** One forecast point. */
export type ForecastPoint = {
  ts: string;          // ISO 8601 UTC
  step: number;        // horizon step, 1-indexed
  p10: number;         // MW
  p50: number;         // MW
  p90: number;         // MW
};

/** A full forecast series for one region. */
export type Forecast = {
  region: Region;
  /** Reference time the forecast is "as of". */
  asOf: string;
  /** When this forecast was generated (real or simulated). */
  generatedAt: string;
  /** Which model produced it. */
  model: string;
  /** Model version (0 for the baseline / mock). */
  modelVersion: number;
  /** Minutes between each step. */
  intervalMinutes: number;
  /** Data source marker — useful for the UI to show "(mock)" badge. */
  source: "mock" | "api";
  points: ForecastPoint[];
};

// ────────────────────────────────────────────────────────────────────
// Region profiles (typical NEM demand magnitudes; in MW)
// ────────────────────────────────────────────────────────────────────
const REGION_PROFILES: Record<
  Region,
  { mean: number; amplitude: number; peakHourLocal: number; weekendDrop: number }
> = {
  NSW1: { mean: 7800,  amplitude: 2200, peakHourLocal: 18, weekendDrop: 0.10 },
  QLD1: { mean: 6100,  amplitude: 1900, peakHourLocal: 18, weekendDrop: 0.08 },
  VIC1: { mean: 5400,  amplitude: 1700, peakHourLocal: 18, weekendDrop: 0.12 },
  SA1:  { mean: 1600,  amplitude: 600,  peakHourLocal: 19, weekendDrop: 0.09 },
  TAS1: { mean: 1100,  amplitude: 280,  peakHourLocal: 17, weekendDrop: 0.10 },
  WEM:  { mean: 2300,  amplitude: 700,  peakHourLocal: 17, weekendDrop: 0.07 },
};

// ────────────────────────────────────────────────────────────────────
// Deterministic PRNG (Mulberry32) — same shape as the one in data.ts
// ────────────────────────────────────────────────────────────────────
function mulberry32(seed: number) {
  let s = seed >>> 0;
  return function next() {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Seed a PRNG from a region + asOf + horizon — gives the same
 *  forecast every time for the same inputs. */
function seedFor(region: Region, asOfIso: string, steps: number): number {
  let h = 0;
  const s = `${region}|${asOfIso}|${steps}`;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h) || 1;
}

/**
 * Build a single demand value at `stepMinutes` minutes after `asOf`.
 * Combines:
 *  - diurnal pattern (24h cosine, peak at peakHourLocal AEST)
 *  - 7-day seasonality (weekday vs weekend)
 *  - a small random walk on top so the curve isn't perfectly smooth
 *  - uncertainty that grows with horizon (for the P10/P90 bands)
 */
function demandAt(
  region: Region,
  stepMinutes: number,
  asOfMs: number,
  peakHourLocal: number,
  weekendDrop: number,
  rand: () => number,
): { p50: number; p10: number; p90: number } {
  const profile = REGION_PROFILES[region];
  // Convert step → AEST hour. AU is UTC+10 in winter (AEST), UTC+11 in summer (AEDT).
  // For simplicity, hardcode AEST (UTC+10) — accurate enough for a demo.
  const tsMs = asOfMs + stepMinutes * 60_000;
  const date = new Date(tsMs);
  const aestHour = (date.getUTCHours() + 10) % 24;
  const dayOfWeek = date.getUTCDay(); // 0=Sun, 6=Sat
  const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;

  // Diurnal: 1.0 at peak hour, ~0.5 at trough
  const radians = ((aestHour - peakHourLocal) / 24) * Math.PI * 2;
  const diurnal = 0.5 + 0.5 * Math.cos(radians);

  // Small noise so the line isn't a perfect cosine
  const noise = (rand() - 0.5) * 0.04;

  // Build the median
  const weekendFactor = isWeekend ? 1 - weekendDrop : 1;
  const p50 = profile.mean * (0.4 + 0.6 * diurnal) * weekendFactor * (1 + noise);

  // Bands widen with horizon (sigma grows ~sqrt(h))
  const horizon = stepMinutes / 30; // in 30-min steps
  const sigma = profile.amplitude * 0.05 * Math.sqrt(horizon);

  // Asymmetric: P90-P50 is slightly wider than P50-P10 (peak uncertainty > trough)
  const p10 = Math.max(0, p50 - sigma * 1.05);
  const p90 = p50 + sigma * 0.95;

  return { p50, p10, p90 };
}

/**
 * Generate a deterministic forecast for the given region + horizon.
 *
 * The result is reproducible: same inputs → same output. The seed
 * is derived from (region, asOf, steps) so two pages rendering the
 * same forecast get byte-identical numbers.
 */
export function generateMockForecast(
  region: Region,
  steps: Horizon,
  asOfIso?: string,
): Forecast {
  const asOf = asOfIso ?? new Date().toISOString();
  const asOfMs = Date.parse(asOf);
  const rand = mulberry32(seedFor(region, asOf, steps));
  const profile = REGION_PROFILES[region];

  const points: ForecastPoint[] = [];
  for (let i = 1; i <= steps; i++) {
    const stepMinutes = i * 30; // NEM 30-min settlement
    const { p50, p10, p90 } = demandAt(
      region,
      stepMinutes,
      asOfMs,
      profile.peakHourLocal,
      profile.weekendDrop,
      rand,
    );
    points.push({
      ts: new Date(asOfMs + stepMinutes * 60_000).toISOString(),
      step: i,
      p10: round1(p10),
      p50: round1(p50),
      p90: round1(p90),
    });
  }

  return {
    region,
    asOf,
    generatedAt: new Date().toISOString(),
    model: "ecolens_lstm_demand",
    modelVersion: 0,
    intervalMinutes: 30,
    source: "mock",
    points,
  };
}

/** Round to 1 decimal place. Forecasts in MW are 1dp-precise enough. */
function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

// ────────────────────────────────────────────────────────────────────
// Summary stats (used by the KPI row above the chart)
// ────────────────────────────────────────────────────────────────────
export type ForecastSummary = {
  peak: { ts: string; value: number };
  trough: { ts: string; value: number };
  mean: number;
  total: number;
  uncertaintyAtPeak: number;       // (p90-p10)/2 at the peak step
  uncertaintyGrowth: number;        // (sigma at last step) / (sigma at first step)
};

export function summarize(forecast: Forecast): ForecastSummary {
  const { points } = forecast;
  if (points.length === 0) {
    return {
      peak: { ts: "", value: 0 },
      trough: { ts: "", value: 0 },
      mean: 0,
      total: 0,
      uncertaintyAtPeak: 0,
      uncertaintyGrowth: 0,
    };
  }
  let peak = points[0];
  let trough = points[0];
  let sum = 0;
  for (const p of points) {
    if (p.p50 > peak.p50) peak = p;
    if (p.p50 < trough.p50) trough = p;
    sum += p.p50;
  }
  const mean = sum / points.length;
  const total = sum * (forecast.intervalMinutes / 60); // MWh
  const firstBand = (points[0].p90 - points[0].p10) / 2;
  const lastBand = (points[points.length - 1].p90 - points[points.length - 1].p10) / 2;
  const peakBand = (peak.p90 - peak.p10) / 2;
  return {
    peak: { ts: peak.ts, value: peak.p50 },
    trough: { ts: trough.ts, value: trough.p50 },
    mean: round1(mean),
    total: Math.round(total),
    uncertaintyAtPeak: round1(peakBand),
    uncertaintyGrowth: firstBand > 0 ? round1(lastBand / firstBand) : 0,
  };
}

/** Format a 30-min step's timestamp as "14:30 AEST" or "Sat 09:00". */
export function formatStepLabel(tsIso: string, stepIndex: number, total: number): string {
  const d = new Date(tsIso);
  // Show time for short horizons, date for long ones
  if (total <= 48) {
    const aest = new Date(d.getTime() + 10 * 60 * 60 * 1000);
    const hh = aest.getUTCHours().toString().padStart(2, "0");
    const mm = aest.getUTCMinutes().toString().padStart(2, "0");
    // Only label every ~6th step to keep it sparse
    return stepIndex === 1 || stepIndex === total || stepIndex % Math.max(1, Math.floor(total / 6)) === 0
      ? `${hh}:${mm}`
      : "";
  }
  // Long horizons: show date
  if (stepIndex === 1 || stepIndex === total || stepIndex % Math.max(1, Math.floor(total / 8)) === 0) {
    const aest = new Date(d.getTime() + 10 * 60 * 60 * 1000);
    return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][aest.getUTCDay()]} ${aest.getUTCDate()}/${aest.getUTCMonth() + 1}`;
  }
  return "";
}

// Re-export for pages that already import the User type from auth
export type { User };
