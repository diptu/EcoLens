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
 *
 * `fetchYtdEmissions()` below is the first of those real calls: it
 * hits `forecast-api`'s `GET /v1/emissions/ytd` (services/forecast-api's
 * all-region rollup from `raw_marts.fct_carbon_intensity`) for the
 * Executive Dashboard's "Total CO2e (YTD)" KPI. Same static-export /
 * client-side-fetch reasoning as `lib/auth.ts`.
 */
import { FORECAST_API_URL } from "./env";

export type EmissionRegion = "NSW1" | "QLD1" | "VIC1" | "SA1" | "TAS1" | "WEM";
export const ALL_EMISSION_REGIONS: EmissionRegion[] = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"];

/** Shape of forecast-api's `EmissionsYtdResponse`
 * (services/forecast-api/app/schemas/emissions/ytd.py). */
export type YtdEmissions = {
  since: string;
  until: string;
  total_generation_mwh: number | null;
  total_emissions_kgco2e: number | null;
  total_emissions_tco2e: number | null;
  intensity_kgco2e_per_mwh: number | null;
  factors_version: string | null;
  method: "live_mix_weighted";
};

/** Live call to `GET /v1/emissions/ytd` — throws on any non-2xx or
 * network failure so callers (e.g. the Executive Dashboard KPI) can
 * fall back to a placeholder rather than show a wrong number. */
export async function fetchYtdEmissions(): Promise<YtdEmissions> {
  const res = await fetch(`${FORECAST_API_URL}/emissions/ytd`);
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/ytd failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `EmissionsCurrentResponse`. */
export type CurrentEmissions = {
  as_of: string;
  total_generation_mwh: number | null;
  total_emissions_kgco2e: number | null;
  intensity_kgco2e_per_mwh: number | null;
  factors_version: string | null;
  method: "live_mix_weighted";
};

/** Live call to `GET /v1/emissions/current` — all-region rollup of each
 * region's own latest hour. Backs the "Carbon Intensity" KPI and the
 * "Emissions Snapshot" preview card. */
export async function fetchCurrentEmissions(): Promise<CurrentEmissions> {
  const res = await fetch(`${FORECAST_API_URL}/emissions/current`);
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/current failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `EmissionsTimeseriesResponse`. Named
 * `LiveEmissionsTimeseries` (not `EmissionsTimeseries`) -- that name is
 * already taken below by the mock generator's own type, a different
 * shape (`generateMockEmissionsTimeseries`'s `{ bucket, ts, kgco2e, mwh }`
 * points vs. this real endpoint's shape). */
export type LiveEmissionsTimeseries = {
  since: string;
  until: string;
  bucket: "hour" | "day";
  region: string | null;
  factors_version: string | null;
  points: {
    bucket: string;
    total_generation_mwh: number | null;
    total_emissions_kgco2e: number | null;
    intensity_kgco2e_per_mwh: number | null;
  }[];
};

/** Live call to `GET /v1/emissions/timeseries` — actual emissions
 * bucketed by hour or day. Backs the Executive Dashboard's "Emissions
 * Snapshot" sparkline (`bucket=hour, days=1`) and "Emissions Trend"
 * chart's actual history (`bucket=day, days=8`), and Carbon
 * Intelligence's region-filterable chart. `region` omitted aggregates
 * across all regions (NEM-wide), matching `fetchGenerationMix`'s
 * convention. */
export async function fetchEmissionsTimeseries(
  bucket: "hour" | "day",
  days: number,
  region?: string,
): Promise<LiveEmissionsTimeseries> {
  const params = new URLSearchParams({ bucket, days: String(days) });
  if (region) params.set("region", region);
  const res = await fetch(`${FORECAST_API_URL}/emissions/timeseries?${params}`);
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/timeseries failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `GenerationMixResponse`. */
export type GenerationMix = {
  since: string;
  until: string;
  region: string | null;
  total_generation_mwh: number;
  total_emissions_kgco2e: number;
  items: {
    fuel_type: string;
    category: "renewable" | "fossil" | "storage" | "interconnector";
    is_renewable: boolean;
    total_generation_mwh: number;
    total_emissions_kgco2e: number;
    pct_of_total_generation: number;
  }[];
};

/** Live call to `GET /v1/generation-mix` — per-fuel generation +
 * emissions over a period (YTD, NEM-wide, by default). Backs the
 * Executive Dashboard's "Emissions by Source" donut and Carbon
 * Intelligence's region-filterable fuel mix — this platform has no
 * Scope 1/3 data source, so there's nothing else honest to show for
 * the latter beyond grid electricity. */
export async function fetchGenerationMix(
  region?: string,
  sinceIso?: string,
  untilIso?: string,
): Promise<GenerationMix> {
  const params = new URLSearchParams();
  if (region) params.set("region", region);
  if (sinceIso) params.set("since", sinceIso);
  if (untilIso) params.set("until", untilIso);
  const qs = params.toString();
  const res = await fetch(`${FORECAST_API_URL}/generation-mix${qs ? `?${qs}` : ""}`);
  if (!res.ok) {
    throw new Error(`GET /v1/generation-mix failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `DemandSummaryResponse`. */
export type DemandSummary = {
  since: string;
  until: string;
  renewable_share_pct: number | null;
  avg_price_mwh: number | null;
  method: "mw_reading_ratio";
};

/** Live call to `GET /v1/demand/summary` — NEM-wide period aggregate
 * over `fct_energy_demand`. Backs the "Renewable Share" KPI and the
 * "Avg Wholesale Price (YTD)" KPI (the honestly-scoped replacement for
 * the old mock "Cost Savings" figure — no baseline/tariff model exists
 * anywhere in this platform to compute an actual "savings" number).
 * `sinceIso`/`untilIso` default to YTD when omitted, matching the
 * backend's own default. */
export async function fetchDemandSummary(
  sinceIso?: string,
  untilIso?: string,
): Promise<DemandSummary> {
  const params = new URLSearchParams();
  if (sinceIso) params.set("since", sinceIso);
  if (untilIso) params.set("until", untilIso);
  const qs = params.toString();
  const res = await fetch(`${FORECAST_API_URL}/demand/summary${qs ? `?${qs}` : ""}`);
  if (!res.ok) {
    throw new Error(`GET /v1/demand/summary failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `EmissionsForecastResponse`. */
export type EmissionsForecast = {
  region: string;
  generated_at: string;
  horizon: string;
  interval: string;
  intensity_kgco2e_per_mwh: number;
  factors_version: string | null;
  points: { ts: string; p10_kgco2e: number; p50_kgco2e: number; p90_kgco2e: number }[];
  method: "demand_forecast_x_current_intensity";
};

/** Live call to `GET /v1/emissions/forecast` — demand forecast x
 * current intensity, `region` defaults to the 5-region NEM aggregate
 * server-side. Near-term only (the model's native horizon — a few
 * hours), not a multi-day projection. */
export async function fetchEmissionsForecast(region?: string): Promise<EmissionsForecast> {
  const res = await fetch(
    `${FORECAST_API_URL}/emissions/forecast${region ? `?region=${region}` : ""}`,
  );
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/forecast failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `ForecastResponse` (demand, not emissions). */
export type DemandForecast = {
  region: string;
  model: string;
  generated_at: string;
  horizon: string;
  interval: string;
  points: { ts: string; p10: number; p50: number; p90: number; unit: "MW" }[];
};

/** Live call to `GET /v1/forecast` — DemandLSTM inference.
 * `region` defaults to "NEM" (the 5-NEM-region aggregate summed
 * server-side; see forecast-api's `_run_nem_aggregate_forecast`). Backs
 * the Executive Dashboard's "Demand Forecast Preview" card. */
export async function fetchDemandForecast(region: string = "NEM"): Promise<DemandForecast> {
  const res = await fetch(`${FORECAST_API_URL}/forecast?region=${region}`);
  if (!res.ok) {
    throw new Error(`GET /v1/forecast failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `ModelInfo` (`GET /v1/model`). */
export type ModelInfo = {
  status: "loaded" | "not_loaded";
  name: string;
  version: string | null;
  stage: string | null;
  run_id: string | null;
  loaded_at: string | null;
  git_sha: string | null;
  horizon: number | null;
  lookback: number | null;
  metrics: Record<string, number>;
};

/** Live call to `GET /v1/model` — the currently-served DemandLSTM's real
 * metadata (registry version/stage/run id, native horizon/lookback in
 * steps, and its last-evaluation metrics). Backs the Forecast Explorer
 * page's "Model info" sidebar card — replaces the old mock's fabricated
 * architecture specifics (layer count, hidden size, param count) with
 * only what the model registry actually reports. */
export async function fetchModelInfo(): Promise<ModelInfo> {
  const res = await fetch(`${FORECAST_API_URL}/model`);
  if (!res.ok) {
    throw new Error(`GET /v1/model failed: ${res.status}`);
  }
  return res.json();
}

/** Display labels for `raw_marts.dim_energy_mix`'s real `fuel_type`
 * vocabulary (see `GenerationMix`) — narrower than the dashboard's older
 * mock `EMISSION_FACTORS` names (no black/brown coal or CCGT/OCGT gas
 * split; the warehouse doesn't distinguish those). Falls back to the
 * raw fuel_type string for anything not listed here. */
const FUEL_LABELS: Record<string, string> = {
  coal: "Coal",
  gas: "Gas",
  hydro: "Hydro",
  wind: "Wind",
  solar_utility: "Solar (Utility)",
  solar_rooftop: "Solar (Rooftop)",
  battery_discharge: "Battery (Discharge)",
  battery_charge: "Battery (Charge)",
  pumped_hydro: "Pumped Hydro",
  biomass: "Biomass",
  distillate: "Distillate",
};

export function formatFuelType(fuelType: string): string {
  return FUEL_LABELS[fuelType] ?? fuelType;
}

const FUEL_COLORS: Record<string, string> = {
  coal: "#94a3b8",
  gas: "#fbbf24",
  hydro: "#22d3ee",
  wind: "#34d399",
  solar_utility: "#facc15",
  solar_rooftop: "#fde047",
  battery_discharge: "#a78bfa",
  battery_charge: "#818cf8",
  pumped_hydro: "#38bdf8",
  biomass: "#84cc16",
  distillate: "#f472b6",
};

export function fuelColor(fuelType: string): string {
  return FUEL_COLORS[fuelType] ?? "#64748b";
}

// ────────────────────────────────────────────────────────────────────
// Static emission factors (kgCO2e / MWh) — the dashboard's own
// published reference table (methodology page's factor citations,
// `overview.ts`'s illustrative mock). Not consumed by any real fetch
// path above; kept only as a reference constant for those two callers.
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
