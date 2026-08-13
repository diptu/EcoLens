/**
 * Overview data layer for ecoLens.
 *
 * Generates deterministic, realistic data for the /dashboard/overview
 * page. The data is intentionally consistent across the app:
 *   - Demand numbers come from the same region profiles as `forecast.ts`
 *   - Emissions numbers come from the same emission factors as
 *     `emissions.ts`
 *   - Trends, alerts, and goals are derived from the same synthetic
 *     PRNG seed so the page is reproducible across reloads
 *
 * In production, replace each function's body with `fetch(...)` calls
 * to the appropriate service. The shapes here match the API contracts
 * already established by `ecoLens_forecast_api.py` and
 * `ecoLens_emissions_api.py`.
 */
import {
  ALL_EMISSION_REGIONS,
  EMISSION_FACTORS,
  formatIntensity,
  formatTco2e,
  type EmissionRegion,
} from "./emissions";

// ────────────────────────────────────────────────────────────────────
// Region profiles (matches emissions.ts and forecast.ts)
// ────────────────────────────────────────────────────────────────────
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

const ALL_REGION_LIST: EmissionRegion[] = [
  "NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM",
];

// ────────────────────────────────────────────────────────────────────
// Mulberry32 PRNG (consistent with the rest of the app)
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

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}
function round0(n: number): number {
  return Math.round(n);
}

// ────────────────────────────────────────────────────────────────────
// Top-level KPIs (the "at a glance" row)
// ────────────────────────────────────────────────────────────────────
export type OverviewKpi = {
  id: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  trend?: "up" | "down" | "flat";
  trendPct?: number;
  /** If true, a "down" trend is good (used for emissions). */
  invertTrend?: boolean;
  /** Color token from the brand palette. */
  color?: "lime" | "emerald" | "sky" | "rose" | "amber" | "purple";
};

export function generateOverviewKpis(): OverviewKpi[] {
  return [
    {
      id: "energy",
      label: "Total energy (30d)",
      value: "2,453",
      unit: "GWh",
      sub: "across all regions",
      trend: "up",
      trendPct: 4.2,
      color: "lime",
    },
    {
      id: "emissions",
      label: "Total emissions (30d)",
      value: "1,541,820",
      unit: "tCO₂e",
      sub: "Scope 2, location-based",
      trend: "down",
      trendPct: -6.8,
      color: "emerald",
    },
    {
      id: "intensity",
      label: "Avg grid intensity",
      value: "628",
      unit: "kg/MWh",
      sub: "weighted by energy",
      trend: "down",
      trendPct: -2.1,
      color: "emerald",
    },
    {
      id: "renewable",
      label: "Renewable share",
      value: "34.6",
      unit: "%",
      sub: "vs 32.1% prior period",
      trend: "up",
      trendPct: 2.5,
      color: "lime",
    },
    {
      id: "cost",
      label: "Energy cost (30d)",
      value: "$487,250",
      sub: "estimated",
      trend: "up",
      trendPct: 3.1,
      color: "amber",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Headline trends (3 series: demand, emissions, renewable share)
// ────────────────────────────────────────────────────────────────────
export type OverviewTrend = {
  labels: string[];
  demand_gwh: number[];      // GWh per period
  emissions_kt: number[];    // kt CO2e per period
  renewable_pct: number[];   // % per period
  /** Average $/MWh spot price per period (AUD). */
  price_aud_per_mwh: number[];
};

export function generateOverviewTrend(months: number = 12): OverviewTrend {
  const rand = mulberry32(seedFor("trend", months));
  const labels: string[] = [];
  const demand: number[] = [];
  const emissions: number[] = [];
  const renewable: number[] = [];
  const price: number[] = [];
  const baseMonth = new Date();
  for (let i = months - 1; i >= 0; i--) {
    const d = new Date(baseMonth.getFullYear(), baseMonth.getMonth() - i, 1);
    labels.push(d.toLocaleDateString("en-AU", { month: "short" }));
    // Demand oscillates seasonally (higher in summer/winter for heating/cooling)
    const month = d.getMonth();
    const seasonal = 1 + 0.08 * Math.cos(((month - 6) / 12) * Math.PI * 2);
    const trend = 1 + (months - 1 - i) * 0.005; // slight upward trend
    const noise = (rand() - 0.5) * 0.04;
    demand.push(round0(2050 * seasonal * trend * (1 + noise)));
    // Emissions follow demand but with renewable share improving
    const ren = 0.30 + (months - 1 - i) * 0.004 + (rand() - 0.5) * 0.02;
    renewable.push(round1(Math.max(0.15, Math.min(0.55, ren)) * 100));
    const intensity = 660 - (months - 1 - i) * 4; // gradual decarbonization
    emissions.push(round1(demand[demand.length - 1] * 1000 * intensity * (1 - ren) / 1_000_000));
    // Spot price: random in $40-180/MWh range
    price.push(round0(60 + rand() * 120));
  }
  return {
    labels,
    demand_gwh: demand,
    emissions_kt: emissions,
    renewable_pct: renewable,
    price_aud_per_mwh: price,
  };
}

// ────────────────────────────────────────────────────────────────────
// Region breakdown (for the regional map / table)
// ────────────────────────────────────────────────────────────────────
export type RegionStat = {
  region: EmissionRegion | "NEM";
  state: string;
  energy_mwh: number;
  emissions_tco2e: number;
  intensity_kg_per_mwh: number;
  renewable_pct: number;
  population: number | null;
  status: "ok" | "warning" | "alert";
  /** Year-over-year change in renewable share (percentage points). */
  renewable_yoy: number;
};

const REGION_STATE: Record<EmissionRegion, { state: string; population: number }> = {
  NSW1: { state: "NSW", population: 8_200_000 },
  QLD1: { state: "QLD", population: 5_200_000 },
  VIC1: { state: "VIC", population: 6_700_000 },
  SA1:  { state: "SA",  population: 1_820_000 },
  TAS1: { state: "TAS", population:   570_000 },
  WEM:  { state: "WA",  population: 2_700_000 },
};

export function generateRegionStats(period: "7d" | "30d" | "90d" | "365d" = "30d"): RegionStat[] {
  const rand = mulberry32(seedFor("regions", period));
  const hours = period === "7d" ? 24 * 7 : period === "30d" ? 24 * 30 : 24 * 90;
  const regions: RegionStat[] = ALL_REGION_LIST.map((r) => {
    const profile = REGION_PROFILES[r];
    const meta = REGION_STATE[r];
    const energy_mwh = profile.mean_mw * hours * (1 + (rand() - 0.5) * 0.03);
    const emissions = energy_mwh * profile.intensity;
    const noise = (rand() - 0.5) * 0.05;
    const renewable_pct = Math.max(0.15, Math.min(0.92, profile.renewable_pct + noise));
    // Status: warning for high intensity, alert for very high
    const status: "ok" | "warning" | "alert" =
      profile.intensity > 700 ? "alert" :
      profile.intensity > 500 ? "warning" : "ok";
    return {
      region: r,
      state: meta.state,
      energy_mwh: round0(energy_mwh),
      emissions_tco2e: round1(emissions / 1000),
      intensity_kg_per_mwh: profile.intensity,
      renewable_pct: round1(renewable_pct * 100),
      population: meta.population,
      status,
      renewable_yoy: round1((rand() - 0.3) * 8), // bias slightly positive
    };
  });
  // NEM (national) row
  const total_energy = regions.reduce((s, r) => s + r.energy_mwh, 0);
  const total_emissions = regions.reduce((s, r) => s + r.emissions_tco2e, 0);
  const weighted_intensity = (total_emissions * 1000) / total_energy;
  const weighted_renewable = regions.reduce(
    (s, r) => s + r.renewable_pct * r.energy_mwh, 0,
  ) / total_energy;
  regions.push({
    region: "NEM",
    state: "AU",
    energy_mwh: round0(total_energy),
    emissions_tco2e: round1(total_emissions),
    intensity_kg_per_mwh: round0(weighted_intensity),
    renewable_pct: round1(weighted_renewable),
    population: null,
    status: "ok",
    renewable_yoy: round1(regions.reduce((s, r) => s + r.renewable_yoy * r.energy_mwh, 0) / total_energy),
  });
  return regions;
}

// ────────────────────────────────────────────────────────────────────
// Recent alerts (for the "needs attention" card)
// ────────────────────────────────────────────────────────────────────
export type OverviewAlert = {
  id: string;
  severity: "info" | "warning" | "alert";
  category: "emissions" | "demand" | "weather" | "regulatory" | "anomaly";
  title: string;
  body: string;
  /** When this happened (ISO). */
  ts: string;
  /** Region affected, or null for org-wide. */
  region: EmissionRegion | null;
  /** Optional actionable CTA. */
  cta?: { label: string; href: string };
};

export function generateOverviewAlerts(limit: number = 5): OverviewAlert[] {
  const now = new Date();
  const seed = seedFor("alerts", now.toISOString().slice(0, 10));
  const rand = mulberry32(seed);
  const pick = <T,>(arr: T[]) => arr[Math.floor(rand() * arr.length)];
  const minutesAgo = (m: number) => new Date(now.getTime() - m * 60_000).toISOString();
  const templates: OverviewAlert[] = [
    {
      id: "alert-1",
      severity: "alert",
      category: "emissions",
      title: "QLD1 emissions intensity 18% above 30-day baseline",
      body: "Sustained coal generation during off-peak hours pushed QLD1's grid intensity to 850 kgCO₂e/MWh between 02:00 and 04:00 AEST. Consider shifting flexible load to midday.",
      ts: minutesAgo(47),
      region: "QLD1",
      cta: { label: "View QLD1 detail →", href: "/dashboard/carbon/?region=QLD1" },
    },
    {
      id: "alert-2",
      severity: "warning",
      category: "weather",
      title: "Heatwave forecast for NSW1, SA1 (3 consecutive days >38°C)",
      body: "BoM forecast: Sydney 39°C, Adelaide 42°C. Expected demand uplift of +12% Wed-Fri. Pre-cooling recommended for facilities in these regions.",
      ts: minutesAgo(120),
      region: null,
      cta: { label: "View forecast →", href: "/dashboard/forecast/" },
    },
    {
      id: "alert-3",
      severity: "info",
      category: "anomaly",
      title: "TAS1 wind generation hit record daily average (78% of demand)",
      body: "Bassi Link and Musselroe both at full output. Spot prices fell to -$8/MWh for 4 hours. Battery storage captured 142 MWh of excess.",
      ts: minutesAgo(245),
      region: "TAS1",
    },
    {
      id: "alert-4",
      severity: "warning",
      category: "regulatory",
      title: "Q2 disclosure deadline in 14 days",
      body: "Scope 1+2 facility-level data must be lodged by Aug 7. Last 2 facilities still need manual verification of natural gas consumption.",
      ts: minutesAgo(420),
      region: null,
      cta: { label: "View report →", href: "/dashboard/reports/" },
    },
    {
      id: "alert-5",
      severity: "alert",
      category: "demand",
      title: "VIC1 demand spike detected (2.3σ above 30-day average)",
      body: "Unexpected +1,800 MW spike at 18:47 AEST — possibly due to a Loy Yang unit trip. Spot price hit $412/MWh for 15 minutes. No action required; flagged for review.",
      ts: minutesAgo(720),
      region: "VIC1",
    },
    {
      id: "alert-6",
      severity: "info",
      category: "emissions",
      title: "Monthly emissions target met (4.2% under trajectory)",
      body: "Cumulative YTD emissions: 18,420 tCO₂e vs target 19,225 tCO₂e. On track for FY target of 32,500 tCO₂e.",
      ts: minutesAgo(1_440),
      region: null,
    },
  ];
  return templates.slice(0, limit);
}

// ────────────────────────────────────────────────────────────────────
// Goals (for the progress card)
// ────────────────────────────────────────────────────────────────────
export type Goal = {
  id: string;
  /** Title of the goal. */
  title: string;
  /** Detailed description. */
  description: string;
  /** Current value. */
  current: number;
  /** Target value. */
  target: number;
  /** Unit label. */
  unit: string;
  /** "lower" means we want current < target; "higher" means current > target. */
  direction: "lower" | "higher";
  /** When this goal is due (ISO). */
  due: string;
  /** Annualized progress (0-1). */
  progressPct: number;
  /** Time elapsed in the goal period (0-1). */
  timeProgressPct: number;
  /** Status: on-track, behind, ahead, achieved. */
  status: "on-track" | "behind" | "ahead" | "achieved";
};

export function generateGoals(): Goal[] {
  return [
    {
      id: "g-2030-net-zero",
      title: "Net-zero Scope 1+2 by 2030",
      description: "Reduce absolute Scope 1+2 emissions 50% by 2030 vs 2020 baseline (40,200 tCO₂e).",
      current: 18_420,
      target: 20_100,        // 50% of baseline
      unit: "tCO₂e (YTD)",
      direction: "lower",
      due: "2030-06-30",
      progressPct: 54.2,     // (baseline - current) / (baseline - target) = (40200-18420)/(40200-20100) ≈ 0.542
      timeProgressPct: 36.4, // ~4.4y of 12y elapsed
      status: "ahead",
    },
    {
      id: "g-2026-renewables",
      title: "60% renewable electricity by 2026",
      description: "Increase renewable share of electricity consumption to 60% by end of FY2026.",
      current: 34.6,
      target: 60.0,
      unit: "%",
      direction: "higher",
      due: "2026-06-30",
      progressPct: 21.4,     // (34.6 - 22) / (60 - 22) — using 22% as the implicit start
      timeProgressPct: 28.0,
      status: "behind",
    },
    {
      id: "g-2025-intensity",
      title: "Reduce grid intensity 25% by 2025",
      description: "Drop weighted-average grid intensity from 800 to 600 kgCO₂e/MWh by end of 2025.",
      current: 628,
      target: 600,
      unit: "kg/MWh",
      direction: "lower",
      due: "2025-12-31",
      progressPct: 86.0,     // (800-628)/(800-600) = 86%
      timeProgressPct: 87.5, // 10.5/12 months
      status: "on-track",
    },
    {
      id: "g-2027-rooftop",
      title: "Install 50 MW rooftop solar by 2027",
      description: "Deploy on-site solar across 24 facilities.",
      current: 31,
      target: 50,
      unit: "MW",
      direction: "higher",
      due: "2027-12-31",
      progressPct: 62.0,
      timeProgressPct: 50.0,
      status: "on-track",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Re-exports
// ────────────────────────────────────────────────────────────────────
export { formatIntensity, formatTco2e, EMISSION_FACTORS };
export type { EmissionRegion };
