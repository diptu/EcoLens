/**
 * Emissions client + mock generator for the ecoLens dashboard.
 *
 * In production this would call the emissions-api:
 *   fetch(`${EMISSIONS_API_URL}/v1/emissions/...`)
 *
 * For the demo (no emissions-api service attached yet) we generate
 * deterministic, realistic data with a seeded PRNG so the page is
 * reproducible across reloads and SSR/CSR matches.
 *
 * Why a mock instead of just static data?
 *   - The chart and table have to be dynamic (different regions
 *     and time ranges show different shapes)
 *   - We need the SAME shape as the API response so we can
 *     swap the implementation later without changing the UI
 *
 * The shape matches the API's response exactly — when the service
 * is deployed, replacing `generateMockEmissions()` with a real
 * `fetch()` call is a one-line change per function.
 */
import type { User } from "./auth";

export type EmissionRegion = "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1" | "WEM";
export const ALL_EMISSION_REGIONS: EmissionRegion[] = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"];

export type EmissionScope = "scope1" | "scope2" | "all";

export type TimeBucket = "hour" | "day" | "month" | "year";

/** A single region's emissions for a period. */
export type RegionEmission = {
  region: EmissionRegion | "NEM";
  since: string;
  until: string;
  scope: EmissionScope;
  n_obs: number;
  energy_mwh: number;
  scope2_kgco2e: number | null;
  scope1_kgco2e: number | null;
  intensity_kgco2e_per_mwh: number | null;
};

/** National (NEM-wide) rollup. */
export type NationalEmission = {
  since: string;
  until: string;
  scope: EmissionScope;
  regions: RegionEmission[];
  total_scope2_kgco2e: number;
  total_scope1_kgco2e: number;
  total_kgco2e: number;
  total_energy_mwh: number;
  intensity_kgco2e_per_mwh: number | null;
};

/** Fuel breakdown for a region. */
export type FuelItem = {
  fuel: string;
  kgco2e: number;
  percent: number;
};
export type FuelBreakdown = {
  region: EmissionRegion;
  since: string;
  until: string;
  by: "fuel";
  items: FuelItem[];
  total_kgco2e: number;
};

/** Forecast projection (kgCO2e over the next N hours). */
export type EmissionForecast = {
  region: EmissionRegion;
  as_of: string;
  horizon_hours: number;
  source: "forecast-api" | "baseline";
  n_steps: number;
  total_kgco2e: number;
  total_tco2e: number;
  points: {
    ts: string;
    demand_mw: number;
    intensity_kgco2e_per_mwh: number;
    kgco2e: number;
  }[];
};

// ────────────────────────────────────────────────────────────────────
// Static emission factors (kgCO2e / MWh) — mirrors the API's
// published factors. Kept in sync so the mock matches the API.
// ────────────────────────────────────────────────────────────────────
export const EMISSION_FACTORS: Record<string, number> = {
  coal_black_mw: 820,
  coal_brown_mw: 1200,
  gas_ccgt_mw: 370,
  gas_ocgt_mw: 520,
  wind_mw: 10,
  solar_utility_mw: 30,
  solar_rooftop_mw: 40,
  battery_discharge_mw: 50,
  hydro_mw: 5,
  biomass_mw: 50,
  nem_grid_avg: 660,
  wem_grid_avg: 580,
};

// Region profiles (typical demand + intensity)
const REGION_PROFILES: Record<
  EmissionRegion,
  { mean_mw: number; intensity: number; renewable_pct: number }
> = {
  NSW1: { mean_mw: 7800, intensity: 640, renewable_pct: 0.32 },
  QLD1: { mean_mw: 6100, intensity: 720, renewable_pct: 0.28 },
  VIC1: { mean_mw: 5400, intensity: 580, renewable_pct: 0.36 },
  SA1:  { mean_mw: 1600, intensity: 380, renewable_pct: 0.58 },
  TAS1: { mean_mw: 1100, intensity: 120, renewable_pct: 0.85 },
  WEM:  { mean_mw: 2300, intensity: 540, renewable_pct: 0.34 },
};

// ────────────────────────────────────────────────────────────────────
// Mulberry32 PRNG (deterministic, mirrors src/lib/forecast.ts)
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
function seedFor(...parts: (string | number)[]): number {
  let h = 0;
  const s = parts.join("|");
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h) || 1;
}

// ────────────────────────────────────────────────────────────────────
// Mock generators
// ────────────────────────────────────────────────────────────────────
/** Region emissions for a given period. */
export function generateMockRegionEmissions(
  region: EmissionRegion,
  sinceIso: string,
  untilIso: string,
  scope: EmissionScope = "scope2",
): RegionEmission {
  const since = new Date(sinceIso);
  const until = new Date(untilIso);
  const hours = Math.max(1, (until.getTime() - since.getTime()) / 3_600_000);
  const n_obs = Math.floor(hours * 2); // 30-min steps
  const profile = REGION_PROFILES[region];
  const rand = mulberry32(seedFor(region, sinceIso, untilIso, "region"));

  // Energy served (MWh) over the period
  const base_energy = profile.mean_mw * hours;
  const noise = (rand() - 0.5) * 0.05;
  const energy_mwh = base_energy * (1 + noise);

  // Scope 2 (location-based): demand × intensity
  const intensity = profile.intensity;
  const scope2_kgco2e = energy_mwh * intensity;

  // Scope 1 (fuel-attributed): a bit higher than location-based because
  // it includes upstream + transmission losses for fossil generation.
  // For our region profiles, scope1 is roughly 1.05-1.15× scope2
  const scope1_factor = region === "TAS1" ? 1.02 : region === "SA1" ? 1.05 : 1.12;
  const scope1_kgco2e = scope2_kgco2e * scope1_factor;

  return {
    region,
    since: sinceIso,
    until: untilIso,
    scope,
    n_obs,
    energy_mwh: round1(energy_mwh),
    scope2_kgco2e: scope === "scope2" || scope === "all" ? round1(scope2_kgco2e) : null,
    scope1_kgco2e: scope === "scope1" || scope === "all" ? round1(scope1_kgco2e) : null,
    intensity_kgco2e_per_mwh: intensity,
  };
}

/** National rollup. */
export function generateMockNationalEmissions(
  sinceIso: string,
  untilIso: string,
  scope: EmissionScope = "scope2",
): NationalEmission {
  const regions: RegionEmission[] = ALL_EMISSION_REGIONS.map((r) =>
    generateMockRegionEmissions(r, sinceIso, untilIso, scope),
  );
  const total_s2 = regions.reduce((s, r) => s + (r.scope2_kgco2e ?? 0), 0);
  const total_s1 = regions.reduce((s, r) => s + (r.scope1_kgco2e ?? 0), 0);
  const total_energy = regions.reduce((s, r) => s + r.energy_mwh, 0);
  const total = total_s2 + (scope === "all" ? total_s1 : 0);
  return {
    since: sinceIso,
    until: untilIso,
    scope,
    regions,
    total_scope2_kgco2e: round1(total_s2),
    total_scope1_kgco2e: round1(total_s1),
    total_kgco2e: round1(total),
    total_energy_mwh: round1(total_energy),
    intensity_kgco2e_per_mwh: total_energy > 0 ? round1(total / total_energy) : null,
  };
}

/** Fuel breakdown for a region (proportion of scope1 emissions). */
export function generateMockFuelBreakdown(
  region: EmissionRegion,
  sinceIso: string,
  untilIso: string,
): FuelBreakdown {
  const since = new Date(sinceIso);
  const until = new Date(untilIso);
  const hours = Math.max(1, (until.getTime() - since.getTime()) / 3_600_000);
  const profile = REGION_PROFILES[region];

  // Mix of fuels by region (approximating the NEM reality)
  const mixes: Record<EmissionRegion, { coal_black: number; coal_brown: number; gas_ccgt: number; gas_ocgt: number; wind: number; solar_u: number; solar_r: number; hydro: number; battery: number; biomass: number }> = {
    NSW1:  { coal_black: 0.45, coal_brown: 0.02, gas_ccgt: 0.10, gas_ocgt: 0.03, wind: 0.15, solar_u: 0.10, solar_r: 0.08, hydro: 0.05, battery: 0.01, biomass: 0.01 },
    QLD1:  { coal_black: 0.55, coal_brown: 0.01, gas_ccgt: 0.13, gas_ocgt: 0.04, wind: 0.10, solar_u: 0.10, solar_r: 0.05, hydro: 0.01, battery: 0.01, biomass: 0.00 },
    VIC1:  { coal_black: 0.10, coal_brown: 0.40, gas_ccgt: 0.15, gas_ocgt: 0.02, wind: 0.18, solar_u: 0.06, solar_r: 0.06, hydro: 0.02, battery: 0.01, biomass: 0.00 },
    SA1:   { coal_black: 0.02, coal_brown: 0.01, gas_ccgt: 0.30, gas_ocgt: 0.08, wind: 0.35, solar_u: 0.10, solar_r: 0.08, hydro: 0.01, battery: 0.04, biomass: 0.01 },
    TAS1:  { coal_black: 0.01, coal_brown: 0.00, gas_ccgt: 0.03, gas_ocgt: 0.01, wind: 0.18, solar_u: 0.02, solar_r: 0.04, hydro: 0.70, battery: 0.00, biomass: 0.01 },
    WEM:   { coal_black: 0.30, coal_brown: 0.00, gas_ccgt: 0.30, gas_ocgt: 0.05, wind: 0.18, solar_u: 0.10, solar_r: 0.05, hydro: 0.00, battery: 0.01, biomass: 0.01 },
  };
  const m = mixes[region];
  const energy_mwh = profile.mean_mw * hours;
  const items: FuelItem[] = [
    { fuel: "coal_black",   kgco2e: m.coal_black * energy_mwh * EMISSION_FACTORS.coal_black_mw,   percent: m.coal_black * 100 },
    { fuel: "coal_brown",   kgco2e: m.coal_brown * energy_mwh * EMISSION_FACTORS.coal_brown_mw,   percent: m.coal_brown * 100 },
    { fuel: "gas_ccgt",     kgco2e: m.gas_ccgt   * energy_mwh * EMISSION_FACTORS.gas_ccgt_mw,     percent: m.gas_ccgt * 100 },
    { fuel: "gas_ocgt",     kgco2e: m.gas_ocgt   * energy_mwh * EMISSION_FACTORS.gas_ocgt_mw,     percent: m.gas_ocgt * 100 },
    { fuel: "wind",         kgco2e: m.wind       * energy_mwh * EMISSION_FACTORS.wind_mw,         percent: m.wind * 100 },
    { fuel: "solar_u",      kgco2e: m.solar_u    * energy_mwh * EMISSION_FACTORS.solar_utility_mw, percent: m.solar_u * 100 },
    { fuel: "solar_r",      kgco2e: m.solar_r    * energy_mwh * EMISSION_FACTORS.solar_rooftop_mw, percent: m.solar_r * 100 },
    { fuel: "hydro",        kgco2e: m.hydro      * energy_mwh * EMISSION_FACTORS.hydro_mw,        percent: m.hydro * 100 },
    { fuel: "battery",      kgco2e: m.battery    * energy_mwh * EMISSION_FACTORS.battery_discharge_mw, percent: m.battery * 100 },
    { fuel: "biomass",      kgco2e: m.biomass    * energy_mwh * EMISSION_FACTORS.biomass_mw,      percent: m.biomass * 100 },
  ];
  // Normalize percents to sum to 100 (with rounding errors)
  const total_pct = items.reduce((s, i) => s + i.percent, 0);
  for (const i of items) i.percent = round1((i.percent / total_pct) * 100);
  items.sort((a, b) => b.kgco2e - a.kgco2e);
  return {
    region,
    since: sinceIso,
    until: untilIso,
    by: "fuel",
    items,
    total_kgco2e: round1(items.reduce((s, i) => s + i.kgco2e, 0)),
  };
}

/** Forecast emissions for the next N hours. */
export function generateMockEmissionForecast(
  region: EmissionRegion,
  horizonHours: number,
): EmissionForecast {
  const asOf = new Date();
  const profile = REGION_PROFILES[region];
  const points = [];
  let total = 0;
  for (let h = 1; h <= horizonHours * 2; h++) {
    const ts = new Date(asOf.getTime() + h * 30 * 60_000);
    // Diurnal swing (cosine) + small noise
    const aestHour = (ts.getUTCHours() + 10) % 24;
    const radians = ((aestHour - 18) / 24) * Math.PI * 2;
    const diurnal = 0.6 + 0.4 * Math.cos(radians);
    const mw = profile.mean_mw * diurnal;
    const kg = mw * profile.intensity * 0.5; // 30 min
    total += kg;
    points.push({
      ts: ts.toISOString(),
      demand_mw: round1(mw),
      intensity_kgco2e_per_mwh: profile.intensity,
      kgco2e: round1(kg),
    });
  }
  return {
    region,
    as_of: asOf.toISOString(),
    horizon_hours: horizonHours,
    source: "baseline",
    n_steps: points.length,
    total_kgco2e: round1(total),
    total_tco2e: round1(total / 1000),
    points,
  };
}

// ────────────────────────────────────────────────────────────────────
// Time series (for the chart)
// ────────────────────────────────────────────────────────────────────
export type EmissionsTimeseries = {
  region: EmissionRegion;
  bucket: TimeBucket;
  since: string;
  until: string;
  points: { ts: string; kgco2e: number; mwh: number; n_obs: number }[];
};

export function generateMockEmissionsTimeseries(
  region: EmissionRegion,
  sinceIso: string,
  untilIso: string,
  bucket: TimeBucket,
): EmissionsTimeseries {
  const since = new Date(sinceIso);
  const until = new Date(untilIso);
  const profile = REGION_PROFILES[region];
  const rand = mulberry32(seedFor(region, sinceIso, untilIso, "ts", bucket));

  let n_buckets: number;
  let bucket_ms: number;
  let advance: (d: Date) => Date;
  if (bucket === "hour") {
    n_buckets = Math.floor((until.getTime() - since.getTime()) / 3_600_000);
    bucket_ms = 3_600_000;
    advance = (d) => new Date(d.getTime() + bucket_ms);
  } else if (bucket === "day") {
    n_buckets = Math.floor((until.getTime() - since.getTime()) / 86_400_000);
    bucket_ms = 86_400_000;
    advance = (d) => new Date(d.getTime() + bucket_ms);
  } else if (bucket === "month") {
    n_buckets = (until.getFullYear() - since.getFullYear()) * 12 + (until.getMonth() - since.getMonth()) + 1;
    bucket_ms = 0;
    advance = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 1, d.getUTCHours());
  } else {
    n_buckets = until.getFullYear() - since.getFullYear() + 1;
    bucket_ms = 0;
    advance = (d) => new Date(d.getFullYear() + 1, 0, 1);
  }
  n_buckets = Math.max(1, n_buckets);
  const points: EmissionsTimeseries["points"] = [];
  let cursor = new Date(since);
  for (let i = 0; i < n_buckets; i++) {
    const noise = (rand() - 0.5) * 0.08;
    // Hour/day: 2-obs per hour or 48 per day → compute energy from profile
    // Month: 30 days × 24 hours
    // Year: 365 days × 24 hours
    let mwh: number;
    if (bucket === "hour")        mwh = profile.mean_mw * 1 * (1 + noise);
    else if (bucket === "day")    mwh = profile.mean_mw * 24 * (1 + noise);
    else if (bucket === "month")  mwh = profile.mean_mw * 24 * 30 * (1 + noise);
    else                          mwh = profile.mean_mw * 24 * 365 * (1 + noise);
    const kg = mwh * profile.intensity;
    const n_obs = bucket === "hour" ? 2 : bucket === "day" ? 48 : bucket === "month" ? 1440 : 17520;
    points.push({
      ts: cursor.toISOString(),
      kgco2e: round1(kg),
      mwh: round1(mwh),
      n_obs,
    });
    cursor = advance(cursor);
  }
  return { region, bucket, since: sinceIso, until: untilIso, points };
}

// ────────────────────────────────────────────────────────────────────
// Summary KPIs (aggregated metrics for the hero row)
// ────────────────────────────────────────────────────────────────────
export type EmissionsSummary = {
  period: string;
  energyMWh: number;
  totalTco2e: number;
  intensityKgPerMwh: number;
  renewablePct: number;
  /** Change vs previous equivalent period (%). Positive = worse. */
  vsPriorPct: number;
  /** Peak hour of the period (with the most emissions). */
  peakHour: { ts: string; kgco2e: number };
  /** Trough hour (lowest emissions). */
  troughHour: { ts: string; kgco2e: number };
};

export function summarizeEmissions(national: NationalEmission, timeseries: EmissionsTimeseries): EmissionsSummary {
  const since = new Date(national.since);
  const until = new Date(national.until);
  const days = (until.getTime() - since.getTime()) / 86_400_000;
  const period =
    days <= 1 ? "Last 24h" :
    days <= 8 ? "Last 7d"  :
    days <= 32 ? "Last 30d" :
    days <= 95 ? "Last 90d" :
    `Last ${Math.round(days)}d`;

  const totalTco2e = national.total_kgco2e / 1000;
  const intensityKgPerMwh = national.intensity_kgco2e_per_mwh ?? 0;
  const renewablePct = 100 - (intensityKgPerMwh / 800) * 100; // very rough

  let peak = timeseries.points[0];
  let trough = timeseries.points[0];
  for (const p of timeseries.points) {
    if (p.kgco2e > peak.kgco2e) peak = p;
    if (p.kgco2e < trough.kgco2e) trough = p;
  }
  // Mock "vs prior" - depends on region intensity
  const vsPriorPct = intensityKgPerMwh > 700 ? 4.2 : -2.8;

  return {
    period,
    energyMWh: national.total_energy_mwh,
    totalTco2e: round1(totalTco2e),
    intensityKgPerMwh: round1(intensityKgPerMwh),
    renewablePct: Math.max(0, Math.min(100, Math.round(renewablePct))),
    vsPriorPct,
    peakHour: { ts: peak.ts, kgco2e: round1(peak.kgco2e) },
    troughHour: { ts: trough.ts, kgco2e: round1(trough.kgco2e) },
  };
}

// ────────────────────────────────────────────────────────────────────
// Formatting helpers
// ────────────────────────────────────────────────────────────────────
export function formatTco2e(kg: number | null | undefined): string {
  if (kg == null) return "—";
  if (Math.abs(kg) >= 1_000_000_000) return `${(kg / 1_000_000_000).toFixed(2)} Gt`;
  if (Math.abs(kg) >= 1_000_000)     return `${(kg / 1_000_000).toFixed(2)} kt`;
  if (Math.abs(kg) >= 1_000)         return `${(kg / 1_000).toFixed(1)} t`;
  return `${kg.toFixed(0)} kg`;
}

export function formatIntensity(intensity: number | null | undefined): string {
  if (intensity == null) return "—";
  return `${Math.round(intensity)} kg/MWh`;
}

export function formatEnergy(mwh: number | null | undefined): string {
  if (mwh == null) return "—";
  if (mwh >= 1_000_000) return `${(mwh / 1_000_000).toFixed(2)} TWh`;
  if (mwh >= 1_000)     return `${(mwh / 1_000).toFixed(1)} GWh`;
  return `${Math.round(mwh).toLocaleString()} MWh`;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export type { User };
