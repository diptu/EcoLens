/**
 * Insights data layer for ecoLens.
 *
 * Generates deterministic, realistic data for the /dashboard/insights
 * page. The page surfaces three categories of insight:
 *
 *   1. **Trends** — period-over-period deltas, with the magnitude and
 *      direction of change.
 *   2. **Anomalies** — points in time where the metric was statistically
 *      far from its expected value (>=2σ).
 *   3. **Opportunities** — ranked reduction opportunities with the
 *      estimated impact (tCO₂e/yr) and effort/ROI tags.
 *
 * In production, anomalies would be detected by the data-pipeline's
 * `forecasting/mlops/drift.py` (PSI + KS test). Here we synthesize
 * anomalies from the same PRNG used elsewhere so the page is
 * reproducible across reloads.
 */
import {
  ALL_EMISSION_REGIONS,
  type EmissionRegion,
} from "./emissions";

const ALL_REGION_LIST: EmissionRegion[] = [
  "NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM",
];

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
// KPI strip (4 quick numbers)
// ────────────────────────────────────────────────────────────────────
export type InsightKpi = {
  id: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  trend?: "up" | "down" | "flat";
  trendPct?: number;
  invertTrend?: boolean;     // if true, "up" is bad (e.g. emissions)
  color?: "lime" | "emerald" | "sky" | "rose" | "amber" | "purple";
};

export function generateInsightKpis(): InsightKpi[] {
  return [
    {
      id: "demand",
      label: "Demand (30d)",
      value: "2,453",
      unit: "GWh",
      sub: "vs 2,354 prior 30d",
      trend: "up",
      trendPct: 4.2,
      color: "sky",
    },
    {
      id: "emissions",
      label: "Emissions (30d)",
      value: "1,541,820",
      unit: "tCO₂e",
      sub: "Scope 2 (location-based)",
      trend: "down",
      trendPct: -6.8,
      invertTrend: true,  // down is good for emissions
      color: "emerald",
    },
    {
      id: "intensity",
      label: "Grid intensity",
      value: "628",
      unit: "kg/MWh",
      sub: "vs 656 prior 30d",
      trend: "down",
      trendPct: -4.3,
      invertTrend: true,
      color: "emerald",
    },
    {
      id: "renewable",
      label: "Renewable share",
      value: "34.6",
      unit: "%",
      sub: "vs 32.1% prior 30d",
      trend: "up",
      trendPct: 2.5,
      color: "lime",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Trend data — month-over-month series
// ────────────────────────────────────────────────────────────────────
export type InsightTrend = {
  labels: string[];
  current: number[];          // current period
  prior: number[];            // same period, one year earlier
  /** Same data, normalized so current[0] = 100 (index-style chart). */
  current_indexed: number[];
  prior_indexed: number[];
  /** Total change in absolute terms (last value - first value). */
  totalDelta: number;
  /** Total change in percent. */
  totalDeltaPct: number;
};

export function generateInsightTrend(months: number = 12): InsightTrend {
  const rand = mulberry32(seedFor("insight-trend", months));
  const labels: string[] = [];
  const current: number[] = [];
  const prior: number[] = [];
  const baseMonth = new Date();
  for (let i = months - 1; i >= 0; i--) {
    const d = new Date(baseMonth.getFullYear(), baseMonth.getMonth() - i, 1);
    labels.push(d.toLocaleDateString("en-AU", { month: "short" }));
    // current: starts high, falls
    const baseCur = 2400 - i * 35 + (rand() - 0.5) * 60;
    current.push(round0(baseCur));
    // prior year: generally higher (worse) than current
    const basePrior = baseCur + 200 + (rand() - 0.5) * 80;
    prior.push(round0(basePrior));
  }
  // Indexed so first month = 100
  const first = current[0] || 1;
  const firstPrior = prior[0] || 1;
  return {
    labels,
    current,
    prior,
    current_indexed: current.map((v) => round1((v / first) * 100)),
    prior_indexed: prior.map((v) => round1((v / firstPrior) * 100)),
    totalDelta: current[current.length - 1] - current[0],
    totalDeltaPct: ((current[current.length - 1] - current[0]) / current[0]) * 100,
  };
}

// ────────────────────────────────────────────────────────────────────
// Anomaly detection — the "spikes & dips" panel
// ────────────────────────────────────────────────────────────────────
export type Anomaly = {
  id: string;
  /** When it happened (ISO). */
  ts: string;
  /** Which metric spiked. */
  metric: "demand" | "emissions" | "intensity" | "renewable" | "price";
  /** Region affected, or null for org-wide. */
  region: EmissionRegion | null;
  /** Observed value. */
  observed: number;
  /** Expected (rolling 30-day mean) value. */
  expected: number;
  /** Standard deviations from expected. */
  sigma: number;
  /** Direction. */
  direction: "spike" | "dip";
  /** Short human-readable explanation. */
  cause: string;
  /** Severity. */
  severity: "info" | "warning" | "alert";
};

export function generateAnomalies(limit: number = 8): Anomaly[] {
  const now = new Date();
  const seed = seedFor("anomalies", now.toISOString().slice(0, 10));
  const rand = mulberry32(seed);
  const daysAgo = (d: number) => new Date(now.getTime() - d * 86_400_000).toISOString();
  const pickR = () => ALL_REGION_LIST[Math.floor(rand() * ALL_REGION_LIST.length)];
  const templates: Anomaly[] = [
    {
      id: "anom-1",
      ts: daysAgo(2),
      metric: "emissions",
      region: "QLD1",
      observed: 5800,
      expected: 4400,
      sigma: 3.2,
      direction: "spike",
      cause: "Sustained coal dispatch during off-peak; possibly generator outage + low wind",
      severity: "alert",
    },
    {
      id: "anom-2",
      ts: daysAgo(4),
      metric: "intensity",
      region: "SA1",
      observed: 215,
      expected: 380,
      sigma: -2.8,
      direction: "dip",
      cause: "Record rooftop solar generation (3,200 MW peak); demand +8% met entirely by solar",
      severity: "info",
    },
    {
      id: "anom-3",
      ts: daysAgo(6),
      metric: "demand",
      region: "VIC1",
      observed: 8400,
      expected: 5500,
      sigma: 2.4,
      direction: "spike",
      cause: "Heatwave + Loy Yang unit trip; demand spiked 53% above baseline",
      severity: "warning",
    },
    {
      id: "anom-4",
      ts: daysAgo(8),
      metric: "renewable",
      region: "TAS1",
      observed: 0.92,
      expected: 0.78,
      sigma: 2.1,
      direction: "spike",
      cause: "Both Bassi Link and Musselroe at full output; hydro spilling",
      severity: "info",
    },
    {
      id: "anom-5",
      ts: daysAgo(11),
      metric: "price",
      region: "NSW1",
      observed: 412,
      expected: 88,
      sigma: 4.1,
      direction: "spike",
      cause: "5-min spot price hit $412/MWh for 12 min during a generator contingency",
      severity: "alert",
    },
    {
      id: "anom-6",
      ts: daysAgo(13),
      metric: "emissions",
      region: "VIC1",
      observed: 3100,
      expected: 3700,
      sigma: -2.3,
      direction: "dip",
      cause: "Brown coal units ramped down; wind + rooftop solar covered the gap",
      severity: "info",
    },
    {
      id: "anom-7",
      ts: daysAgo(15),
      metric: "demand",
      region: "WEM",
      observed: 3200,
      expected: 2350,
      sigma: 2.6,
      direction: "spike",
      cause: "Heatwave in Perth; AC load dominated the morning ramp",
      severity: "warning",
    },
    {
      id: "anom-8",
      ts: daysAgo(18),
      metric: "intensity",
      region: "NSW1",
      observed: 815,
      expected: 640,
      sigma: 2.9,
      direction: "spike",
      cause: "Vales Point running at max output; wind forecast bust",
      severity: "warning",
    },
    {
      id: "anom-9",
      ts: daysAgo(22),
      metric: "renewable",
      region: null,
      observed: 0.42,
      expected: 0.33,
      sigma: 2.4,
      direction: "spike",
      cause: "NEM-wide: 3 GW of new utility solar came online across QLD + VIC",
      severity: "info",
    },
  ];
  return templates.slice(0, limit);
}

// ────────────────────────────────────────────────────────────────────
// Reduction opportunities — ranked by ROI / impact
// ────────────────────────────────────────────────────────────────────
export type Opportunity = {
  id: string;
  name: string;
  description: string;
  category: "energy_efficiency" | "renewable" | "fuel_switch" | "process" | "offsets";
  /** Estimated annual reduction in tCO₂e. */
  reduction_tco2e: number;
  /** Estimated cost (negative = savings, positive = spend). */
  cost_aud: number;
  /** Effort level. */
  effort: "Low" | "Medium" | "High";
  /** 5-year ROI percentage. */
  roi_5yr_pct: number;
  /** Implementation timeline in months. */
  timeline_months: number;
  /** Priority. */
  priority: "High" | "Medium" | "Low";
  /** Region(s) this applies to. */
  regions: EmissionRegion[] | null;
  /** Status: planned / in_progress / completed / proposed. */
  status: "proposed" | "planned" | "in_progress" | "completed";
};

export function generateOpportunities(): Opportunity[] {
  return [
    {
      id: "opp-rooftop-solar",
      name: "Add 8 MW rooftop solar (4 sites)",
      description: "Deploy PV arrays on warehouses in Sydney, Brisbane, Melbourne, Adelaide. Combined roof area 62,000 m². Payback ~4.5y.",
      category: "renewable",
      reduction_tco2e: 8_400,
      cost_aud: -2_400_000,  // net savings over 5y
      effort: "Medium",
      roi_5yr_pct: 168,
      timeline_months: 12,
      priority: "High",
      regions: ["NSW1", "QLD1", "VIC1", "SA1"],
      status: "planned",
    },
    {
      id: "opp-led-retrofit",
      name: "LED + smart-controls retrofit (all sites)",
      description: "Replace 18,500 fluorescent / HID fittings with LED + occupancy/daylight sensors. Reduces lighting load ~78%.",
      category: "energy_efficiency",
      reduction_tco2e: 1_240,
      cost_aud: -680_000,
      effort: "Low",
      roi_5yr_pct: 312,
      timeline_months: 6,
      priority: "High",
      regions: null,
      status: "in_progress",
    },
    {
      id: "opp-ppa",
      name: "Sign 10y PPA for 50 GWh/year",
      description: "Lock in 50 GWh/year from a new NEM wind farm (NSW1). Underwrites ~25% of our annual demand with matched certificates.",
      category: "renewable",
      reduction_tco2e: 31_500,
      cost_aud: 1_200_000,
      effort: "Low",
      roi_5yr_pct: 84,
      timeline_months: 3,
      priority: "High",
      regions: ["NSW1"],
      status: "proposed",
    },
    {
      id: "opp-bess",
      name: "Battery storage at 3 sites (10 MWh total)",
      description: "Behind-the-meter batteries to shift demand to high-renewable hours and provide FCAS revenue. Combined 10 MWh / 5 MW.",
      category: "energy_efficiency",
      reduction_tco2e: 2_100,
      cost_aud: -1_800_000,
      effort: "Medium",
      roi_5yr_pct: 124,
      timeline_months: 9,
      priority: "Medium",
      regions: ["NSW1", "VIC1", "SA1"],
      status: "planned",
    },
    {
      id: "opp-hvac",
      name: "HVAC optimisation (12 sites)",
      description: "Tune schedules, raise setpoints 1°C in summer, lower 1°C in winter. AI-driven controls + commissioning. Comfy range preserved.",
      category: "process",
      reduction_tco2e: 3_800,
      cost_aud: -420_000,
      effort: "Low",
      roi_5yr_pct: 268,
      timeline_months: 4,
      priority: "High",
      regions: null,
      status: "proposed",
    },
    {
      id: "opp-fuel-switch",
      name: "Replace LPG forklifts with electric (8 sites)",
      description: "48 LPG forklifts across 8 distribution centres → lithium-electric. Eliminates on-site Scope 1 fuel combustion.",
      category: "fuel_switch",
      reduction_tco2e: 720,
      cost_aud: -380_000,
      effort: "Medium",
      roi_5yr_pct: 145,
      timeline_months: 18,
      priority: "Medium",
      regions: null,
      status: "proposed",
    },
    {
      id: "opp-vrms",
      name: "Voltage reduction on 3 large motors",
      description: "Install VFDs on 3 large HVAC motors (110 kW each). Energy savings 18-25% during partial load.",
      category: "energy_efficiency",
      reduction_tco2e: 480,
      cost_aud: -140_000,
      effort: "Low",
      roi_5yr_pct: 215,
      timeline_months: 2,
      priority: "High",
      regions: ["VIC1"],
      status: "planned",
    },
    {
      id: "opp-cars",
      name: "Fleet electrification (sedan segment)",
      description: "Replace 84 ICE sedans with EVs over 3 years. Charger infrastructure at HQ + 6 depots. Reduces Scope 1 fleet emissions.",
      category: "fuel_switch",
      reduction_tco2e: 1_150,
      cost_aud: 250_000,
      effort: "High",
      roi_5yr_pct: 42,
      timeline_months: 36,
      priority: "Low",
      regions: null,
      status: "proposed",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Forecast vs actual — for the model performance card
// ────────────────────────────────────────────────────────────────────
export type ForecastVsActual = {
  region: EmissionRegion;
  /** MAPE (mean absolute percentage error) for the last 30 days. */
  mape: number;
  /** Average band coverage (% of points inside P10-P90). */
  band_coverage: number;
  /** Number of forecast points evaluated. */
  n_points: number;
  /** Status derived from MAPE: <5% great, 5-10% ok, >10% needs work. */
  status: "great" | "ok" | "needs-work";
};

export function generateForecastVsActual(): ForecastVsActual[] {
  const rand = mulberry32(seedFor("fva"));
  return ALL_REGION_LIST.map((r) => {
    const mape = round1(2 + rand() * 9); // 2-11%
    const band_coverage = round1(0.74 + rand() * 0.18); // 74-92%
    return {
      region: r,
      mape,
      band_coverage,
      n_points: 1440, // 30 days × 48 obs/day
      status: mape < 5 ? "great" : mape < 8 ? "ok" : "needs-work",
    };
  });
}

// ────────────────────────────────────────────────────────────────────
// Peer benchmarking (vs industry average)
// ────────────────────────────────────────────────────────────────────
export type PeerBenchmark = {
  /** The metric being benchmarked. */
  metric: "intensity_kg_per_mwh" | "renewable_pct" | "scope1_per_revenue";
  /** Our value. */
  ours: number;
  /** Industry average. */
  industry: number;
  /** Top quartile. */
  top_quartile: number;
  /** Difference vs industry, in same units as `ours`. */
  delta_vs_industry: number;
  /** Difference vs industry, in percent. */
  delta_pct: number;
  /** Where we rank: top, above-average, average, below-average. */
  rank: "top" | "above-average" | "average" | "below-average";
};

export function generatePeerBenchmarks(): PeerBenchmark[] {
  return [
    {
      metric: "intensity_kg_per_mwh",
      ours: 628,
      industry: 720,
      top_quartile: 540,
      delta_vs_industry: -92,
      delta_pct: -12.8,
      rank: "above-average",
    },
    {
      metric: "renewable_pct",
      ours: 34.6,
      industry: 28.4,
      top_quartile: 42.1,
      delta_vs_industry: 6.2,
      delta_pct: 21.8,
      rank: "above-average",
    },
    {
      metric: "scope1_per_revenue",
      ours: 0.42,
      industry: 0.48,
      top_quartile: 0.23,
      delta_vs_industry: -0.06,
      delta_pct: -12.5,
      rank: "above-average",
    },
  ];
}

// ────────────────────────────────────────────────────────────────────
// Recommended actions (the AI / heuristic-driven summary at the top)
// ────────────────────────────────────────────────────────────────────
export type Recommendation = {
  id: string;
  title: string;
  body: string;
  category: "reduce" | "switch" | "report" | "investigate";
  impact_tco2e: number;
  effort: "Low" | "Medium" | "High";
  urgency: "now" | "this-week" | "this-month" | "this-quarter";
  href: string;
};

export function generateRecommendations(limit: number = 3): Recommendation[] {
  const all: Recommendation[] = [
    {
      id: "rec-1",
      title: "Investigate QLD1 off-peak coal dispatch",
      body: "Three nights in the last 7 days showed QLD1 grid intensity >800 kgCO₂e/MWh between 01:00-04:00. Reviewing flexible load schedules could shift 320 MWh/week to lower-intensity hours, saving ~250 tCO₂e/week.",
      category: "investigate",
      impact_tco2e: 1_000,
      effort: "Low",
      urgency: "this-week",
      href: "/dashboard/carbon/?region=QLD1",
    },
    {
      id: "rec-2",
      title: "Lock in 10y wind PPA (NSW1)",
      body: "The new Bango wind farm is offering 10y contracts at $58/MWh — 8% below current NEM average. Signing 50 GWh/year would underwrite 25% of our annual NSW demand with matched certificates and reduce emissions ~31,500 tCO₂e/yr.",
      category: "switch",
      impact_tco2e: 31_500,
      effort: "Low",
      urgency: "this-month",
      href: "/dashboard/scenarios/",
    },
    {
      id: "rec-3",
      title: "HVAC tune-up across 12 sites (low-risk quick win)",
      body: "Adjusting setpoints by 1°C and tightening schedules could cut HVAC energy ~14%. Estimated 3,800 tCO₂e/yr with payback under 18 months. All work is non-disruptive (BMS-only changes).",
      category: "reduce",
      impact_tco2e: 3_800,
      effort: "Low",
      urgency: "this-quarter",
      href: "/dashboard/actions/",
    },
  ];
  return all.slice(0, limit);
}

// ────────────────────────────────────────────────────────────────────
// Re-exports
// ────────────────────────────────────────────────────────────────────
export { ALL_EMISSION_REGIONS };
export type { EmissionRegion };
