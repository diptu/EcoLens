/**
 * Methodology data layer for ecoLens.
 *
 * This is the *static, hand-curated* part of the methodology page
 * — calculation chain, data sources, emission factor citations.
 * The dynamic part (per-region / per-period trace numbers) is
 * computed on demand by the API endpoint `/v1/emissions/trace`.
 *
 * In production, the API also returns the chain + sources, so this
 * file's structure matches the API response exactly.
 */
import {
  EMISSION_FACTORS,
  formatIntensity,
  type EmissionRegion,
} from "./emissions";

// ────────────────────────────────────────────────────────────────────
// One step in the calculation chain
// ────────────────────────────────────────────────────────────────────
export type ChainStep = {
  step: number;
  name: string;
  source: string;
  output: string;
  details: string;
  /** Layer of the architecture this step belongs to. */
  layer: "ingestion" | "warehouse" | "calculation" | "presentation";
  /** How long this step typically takes. */
  typical_latency: string;
};

// ────────────────────────────────────────────────────────────────────
// The full calculation chain (data lineage)
// ────────────────────────────────────────────────────────────────────
export const CALCULATION_CHAIN: ChainStep[] = [
  {
    step: 1,
    name: "Raw data ingestion",
    source: "AEMO NEM/WEM, BoM, OpenElectricity, supplier disclosures",
    output: "MongoDB `ecolens_raw` collections",
    details:
      "Pipeline runs every 5 min; fetches AEMO dispatch + SCADA (5-min grain), BoM weather (hourly, 6 stations), supplier facility disclosures, OpenElectricity historical backfill.",
    layer: "ingestion",
    typical_latency: "1-3 min per source",
  },
  {
    step: 2,
    name: "dbt transform",
    source: "dbt 1.7 + Postgres 15",
    output: "Warehouse `fact_demand_30min` (one row per region per 30-min interval)",
    details:
      "Joins demand, generation mix (coal/gas/wind/solar/hydro/battery), weather, holidays. BRIN index on `ts_30` for fast range scans. 5-day lookback window catches late AEMO final-tier data.",
    layer: "warehouse",
    typical_latency: "2-5 min",
  },
  {
    step: 3,
    name: "Emission factors applied",
    source: "IPCC AR5 Working Group III + AEMO NGES",
    output: "Static lookup table (see /v1/emissions/factors)",
    details:
      "14 lifecycle factors for each fuel type. Coal brown is the most carbon-intensive (1,200 kgCO₂e/MWh); wind is the cleanest (10 kg/MWh). NEM grid average: 660 kg/MWh. WEM grid average: 580 kg/MWh.",
    layer: "calculation",
    typical_latency: "<1ms (lookup)",
  },
  {
    step: 4,
    name: "Per-interval calculation",
    source: "this API (`scope2_from_intensity` + `scope1_from_generation_mix`)",
    output: "kgCO₂e per 30-min interval per region",
    details:
      "Scope 2 (location-based): demand_mw × intensity × 0.5h. Scope 1 (fuel-attributed): sum of (fuel_mw × factor × 0.5h) for each fuel in the generation mix. Each interval is independent and auditable.",
    layer: "calculation",
    typical_latency: "~1ms per interval",
  },
  {
    step: 5,
    name: "Aggregation",
    source: "this API (`aggregate_by_bucket`)",
    output: "hour/day/month/year rollups + NEM totals",
    details:
      "Sums across intervals and across regions. National intensity is energy-weighted (so a region with 10× the demand of another contributes 10× the weight).",
    layer: "calculation",
    typical_latency: "~50ms per rollup",
  },
  {
    step: 6,
    name: "Dashboard rendering",
    source: "Next.js 14 dashboard",
    output: "Charts, tables, KPIs on /dashboard/emissions",
    details:
      "Reads via /v1/emissions/* endpoints. Shows total tCO₂e + kg/MWh intensity + per-region breakdown + fuel mix + forecast projection.",
    layer: "presentation",
    typical_latency: "Cache hit: 5ms · Cache miss: 80-200ms",
  },
];

// ────────────────────────────────────────────────────────────────────
// Data sources (each line of input data + where it came from)
// ────────────────────────────────────────────────────────────────────
export type DataSource = {
  id: string;
  name: string;
  type: "primary" | "secondary" | "regulatory" | "reference";
  license: string;
  url: string;
  fields: string[];
  cadence: string;
  /** Plain-language note on what this source contributes. */
  note: string;
};

export const DATA_SOURCES: DataSource[] = [
  {
    id: "aemo-nem",
    name: "AEMO NEM dispatch + SCADA",
    type: "primary",
    license: "Open (CC BY 4.0)",
    url: "https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
    fields: ["demand_mw", "coal_black_mw", "coal_brown_mw", "gas_ccgt_mw", "gas_ocgt_mw", "wind_mw", "solar_utility_mw", "hydro_mw"],
    cadence: "5-minute",
    note: "Real-time + historical generation by fuel type for the 5 NEM regions. Source of truth for demand + dispatch.",
  },
  {
    id: "aemo-wem",
    name: "AEMO WEM market data",
    type: "primary",
    license: "Open",
    url: "https://aemo.com.au/energy-systems/electricity/wa-electricity-market",
    fields: ["demand_mw", "generation_mix"],
    cadence: "30-minute",
    note: "WEM is a single region (no sub-regions); 30-min settlement. Sources include Collie, Synergy, Alinta.",
  },
  {
    id: "bom-weather",
    name: "Bureau of Meteorology (BoM)",
    type: "primary",
    license: "CC BY 3.0 AU",
    url: "http://www.bom.gov.au/climate/data-services/",
    fields: ["temp_c", "humidity_pct", "wind_speed_kmh", "rain_since_9am_mm"],
    cadence: "30-minute (6 stations)",
    note: "Weather feeds demand forecasting (heating/cooling load) and BoM-derived carbon intensity. ERA5 reanalysis used for historical backfill.",
  },
  {
    id: "openelectricity",
    name: "OpenElectricity (OpenNEM)",
    type: "secondary",
    license: "CC BY 4.0",
    url: "https://openelectricity.org.au/",
    fields: ["historical demand backfill (>2 years)"],
    cadence: "30-minute",
    note: "Pre-built NEM historical aggregates. Used for backfilling before AEMO's open data archive starts (older years).",
  },
  {
    id: "ipcc-ar5",
    name: "IPCC AR5 Working Group III",
    type: "reference",
    license: "Open",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    fields: ["lifecycle emission factors"],
    cadence: "static",
    note: "Default lifecycle factors. These include direct combustion + upstream (fuel extraction, processing, transport).",
  },
  {
    id: "open-meteo-era5",
    name: "Open-Meteo ERA5 reanalysis",
    type: "secondary",
    license: "CC BY 4.0",
    url: "https://open-meteo.com/en/docs/historical-weather-api",
    fields: ["historical weather backfill (1940-present)"],
    cadence: "hourly",
    note: "ECMWF ERA5 reanalysis. Same physics as BoM, but global coverage and goes back to 1940. Used when BoM data is missing.",
  },
  {
    id: "electricity-maps",
    name: "Electricity Maps API",
    type: "secondary",
    license: "Open (CC BY 4.0)",
    url: "https://www.electricitymaps.com/",
    fields: ["carbon intensity cross-check for WA"],
    cadence: "hourly",
    note: "Cross-validates WEM carbon intensity against an independent provider.",
  },
];

// ────────────────────────────────────────────────────────────────────
// Emission factors with full source citations
// ────────────────────────────────────────────────────────────────────
export type FactorWithCitation = {
  factor: number;          // kgCO2e / MWh
  source: string;          // bibliographic reference
  url?: string;            // link to the source
  scope: "direct" | "lifecycle";  // direct = combustion only; lifecycle = includes upstream
  notes: string;
};

export const FACTORS_WITH_CITATIONS: Record<string, FactorWithCitation> = {
  coal_black_mw: {
    factor: EMISSION_FACTORS.coal_black_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, black coal)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Includes mining, transport, and combustion. NSW Hunter Valley coal sits at the lower end (~820); other basins can reach 1,000+.",
  },
  coal_brown_mw: {
    factor: EMISSION_FACTORS.coal_brown_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, brown/lignite coal)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Brown coal has 40-60% more carbon per unit of energy than black coal. VIC Latrobe Valley is the main source.",
  },
  gas_ccgt_mw: {
    factor: EMISSION_FACTORS.gas_ccgt_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, natural gas combined cycle)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Combined-cycle gas turbines are ~33% more efficient than open-cycle, hence the lower factor.",
  },
  gas_ocgt_mw: {
    factor: EMISSION_FACTORS.gas_ocgt_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (natural gas, peaking plant)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Open-cycle plants are typically used for peak demand. Higher emissions due to lower thermal efficiency.",
  },
  wind_mw: {
    factor: EMISSION_FACTORS.wind_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, onshore + offshore wind)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Mostly manufacturing emissions (steel, concrete, transport). Operating emissions are zero.",
  },
  solar_utility_mw: {
    factor: EMISSION_FACTORS.solar_utility_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, utility-scale PV)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Includes panel manufacturing + balance-of-system. Lower than rooftop because of better panel efficiency at scale.",
  },
  solar_rooftop_mw: {
    factor: EMISSION_FACTORS.solar_rooftop_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, distributed PV)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Slightly higher than utility due to smaller panels, less efficient inverters.",
  },
  battery_discharge_mw: {
    factor: EMISSION_FACTORS.battery_discharge_mw,
    source: "AEMO NGES + literature average",
    scope: "lifecycle",
    notes: "Hard to attribute fairly; this is the lifecycle (manufacturing) emissions per MWh of output. Real-world emissions are zero (storage only shifts demand).",
  },
  hydro_mw: {
    factor: EMISSION_FACTORS.hydro_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, hydropower)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Mostly concrete/steel in dam construction. Reservoirs can emit methane (not modeled here).",
  },
  biomass_mw: {
    factor: EMISSION_FACTORS.biomass_mw,
    source: "IPCC AR5 WG III Annex III Table A.III.2 (median, dedicated biomass)",
    url: "https://www.ipcc.ch/report/ar5/wg3/",
    scope: "lifecycle",
    notes: "Often considered carbon-neutral at the stack (CO₂ absorbed during growth). Lifecycle still has processing/transport emissions.",
  },
  nem_grid_avg: {
    factor: EMISSION_FACTORS.nem_grid_avg,
    source: "AEMO annual emissions intensity (rolling 12-month)",
    url: "https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem",
    scope: "lifecycle",
    notes: "Used as a fallback when the warehouse column `emissions_intensity_kgco2e_per_mwh` is NULL. Refreshed annually.",
  },
  wem_grid_avg: {
    factor: EMISSION_FACTORS.wem_grid_avg,
    source: "AEMO WEM annual emissions intensity",
    url: "https://aemo.com.au/energy-systems/electricity/wa-electricity-market",
    scope: "lifecycle",
    notes: "WEM is dirtier than NEM (more coal, less renewables per MWh). Used as fallback for WEM rows.",
  },
};

// ────────────────────────────────────────────────────────────────────
// Worked examples (so users can verify the math by hand)
// ────────────────────────────────────────────────────────────────────
export type WorkedExample = {
  id: string;
  title: string;
  description: string;
  scope: "scope1" | "scope2" | "whatif";
  region: EmissionRegion | "NEM";
  inputs: { label: string; value: string; unit: string }[];
  steps: { math: string; result: string }[];
  finalAnswer: string;
};

export const WORKED_EXAMPLES: WorkedExample[] = [
  {
    id: "ex-scope2-basic",
    title: "Scope 2: 1 hour of NSW1 demand",
    description: "How much location-based Scope 2 emissions does 1 hour of NSW1 demand produce, given the region's average grid intensity?",
    scope: "scope2",
    region: "NSW1",
    inputs: [
      { label: "Average demand",  value: "7,800",     unit: "MW"   },
      { label: "Grid intensity",   value: "640",       unit: "kgCO₂e/MWh" },
      { label: "Duration",         value: "1",         unit: "hour" },
    ],
    steps: [
      {
        math: "energy_served = demand × hours = 7,800 × 1",
        result: "7,800 MWh",
      },
      {
        math: "scope2 = energy × intensity = 7,800 × 640",
        result: "4,992,000 kgCO₂e",
      },
      {
        math: "scope2_tonnes = 4,992,000 ÷ 1,000",
        result: "4,992 tCO₂e",
      },
    ],
    finalAnswer: "1 hour of average NSW1 demand produces ~4,992 tCO₂e (Scope 2).",
  },
  {
    id: "ex-scope1-mix",
    title: "Scope 1: 30 min of brown-coal-heavy generation",
    description: "How much Scope 1 emissions does 30 minutes of VIC1 generation produce, when the mix is heavy on brown coal?",
    scope: "scope1",
    region: "VIC1",
    inputs: [
      { label: "Coal (brown)",   value: "2,000",   unit: "MW × 0.5h = 1,000 MWh" },
      { label: "Gas (CCGT)",     value: "1,000",   unit: "MW × 0.5h = 500 MWh"   },
      { label: "Wind",           value: "500",     unit: "MW × 0.5h = 250 MWh"   },
      { label: "Interval",       value: "30",      unit: "minutes"                 },
    ],
    steps: [
      {
        math: "coal_brown   = 1,000 MWh × 1,200 kg/MWh = 1,200,000 kgCO₂e",
        result: "1,200,000 kg",
      },
      {
        math: "gas_ccgt     =   500 MWh ×   370 kg/MWh =   185,000 kgCO₂e",
        result: "185,000 kg",
      },
      {
        math: "wind         =   250 MWh ×    10 kg/MWh =     2,500 kgCO₂e",
        result: "2,500 kg",
      },
      {
        math: "total        = 1,200,000 + 185,000 + 2,500",
        result: "1,387,500 kgCO₂e (1,387.5 tCO₂e)",
      },
    ],
    finalAnswer: "30 min of that mix produces 1,387.5 tCO₂e. Brown coal alone is 87% of it.",
  },
  {
    id: "ex-whatif-100",
    title: "What-if: hitting 100 kgCO₂e/MWh intensity",
    description: "If our grid intensity drops to 100 kgCO₂e/MWh (a 90% renewable scenario), what would our annual emissions look like?",
    scope: "whatif",
    region: "NEM",
    inputs: [
      { label: "Target intensity",  value: "100",        unit: "kgCO₂e/MWh" },
      { label: "Annual demand",     value: "26,300,000", unit: "MWh (2,453 GWh × 30 days × 12 mo ÷ 12 for avg)" },
    ],
    steps: [
      {
        math: "implied_kgco2e = 26,300,000 × 100",
        result: "2,630,000,000 kgCO₂e",
      },
      {
        math: "implied_tco2e = 2,630,000,000 ÷ 1,000",
        result: "2,630,000 tCO₂e",
      },
      {
        math: "current_actual ≈ 1,541,820 tCO₂e (last 30d × 12)",
        result: "~18,502,000 tCO₂e / yr (current trajectory)",
      },
      {
        math: "savings_pct = (18,502,000 − 2,630,000) ÷ 18,502,000",
        result: "85.8% reduction",
      },
    ],
    finalAnswer: "Hitting 100 kg/MWh intensity would cut our annual emissions by ~86%.",
  },
];

// ────────────────────────────────────────────────────────────────────
// Re-exports
// ────────────────────────────────────────────────────────────────────
export { EMISSION_FACTORS, formatIntensity };
export type { EmissionRegion };
