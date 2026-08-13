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

// Plain `fetch()` has no default timeout -- if the backend process
// hangs (not down, just unresponsive; happened for real during dev
// server restarts) the browser's fetch promise never resolves or
// rejects, so a page's own "Loading…" state can get stuck indefinitely
// with no way to recover short of a manual page reload. Every fetch in
// this file goes through this instead so a hung backend surfaces as a
// real, catchable timeout error after `timeoutMs` (15s -- generous for
// a live request, well under "the user thinks it's broken").
async function fetchWithTimeout(
  input: string,
  init: RequestInit = {},
  timeoutMs = 15000,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s: ${input}`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/emissions/ytd`);
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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/emissions/current`);
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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/emissions/timeseries?${params}`);
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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/generation-mix${qs ? `?${qs}` : ""}`);
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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/demand/summary${qs ? `?${qs}` : ""}`);
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
 * hours), not a multi-day projection.
 *
 * Real, generous 45s timeout (2026-08-12, matching `fetchDemandForecast`/
 * `fetchRecentBacktest`) -- `region=NEM` hits the same expensive
 * `_forecast_arrays_nem` path those two use server-side (5 real
 * per-region live inferences summed), confirmed live at ~11-14s on a
 * cache-cold hit (forecast-api's own `get_emissions_forecast` docstring).
 * The previous default 15s timeout left only ~1-4s of real margin
 * against that cold path -- confirmed live to actually trip it (the
 * Executive Dashboard's "Now" marker/forecast band silently vanishing
 * whenever a page load raced a cache-cold moment), not just a
 * theoretical risk. */
export async function fetchEmissionsForecast(region?: string): Promise<EmissionsForecast> {
  const res = await fetchWithTimeout(
    `${FORECAST_API_URL}/emissions/forecast${region ? `?region=${region}` : ""}`,
    {},
    45000,
  );
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/forecast failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `EmissionsTraceResponse` — the real
 * per-interval calculation chain (`raw_marts.fct_carbon_intensity` +
 * the `fct_generation_mix` rows that sum into it), not a mock. Backs
 * the Carbon Methodology page's "show me the real numbers" trace. */
export type EmissionsTrace = {
  region: string;
  generated_at: string;
  intervals: {
    hour: string;
    total_generation_mwh: number | null;
    total_emissions_kgco2e: number | null;
    intensity_kgco2e_per_mwh: number | null;
    factors_version: string | null;
    by_fuel: {
      fuel_type: string;
      generation_mwh: number;
      emissions_kgco2e: number;
      effective_factor_kgco2e_per_mwh: number | null;
    }[];
  }[];
};

/** Live call to `GET /v1/emissions/trace`. No mock fallback on fetch
 * failure — same policy as every other emissions endpoint on this
 * page once wired to real data. */
export async function fetchEmissionsTrace(region: string, limit = 5): Promise<EmissionsTrace> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/emissions/trace?region=${region}&limit=${limit}`);
  if (!res.ok) {
    throw new Error(`GET /v1/emissions/trace failed: ${res.status}`);
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
/** `region=NEM` sums 5 real per-region LSTM inferences server-side on a
 * real cache miss -- confirmed live (2026-08-11) taking ~20s, past this
 * file's normal 15s default (which surfaced as a real "Request timed
 * out after 15s" failure, not just a slow load). forecast-api now keeps
 * this proactively warm (`app.service.cache_warmer.
 * run_dashboard_essentials_warmer`, wired into startup the same day),
 * so a real cold hit should be rare -- this generous 45s timeout is
 * defense-in-depth for the gap between a fresh restart and that
 * warmer's first tick, same real margin `fetchRecentBacktest` already
 * uses for its own similarly slow real compute. */
export async function fetchDemandForecast(region: string = "NEM"): Promise<DemandForecast> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/forecast?region=${region}`, {}, 45000);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = new Error(
      body?.error?.message ?? `GET /v1/forecast failed: ${res.status}`,
    );
    (err as Error & { code?: string }).code = body?.error?.code;
    throw err;
  }
  return res.json();
}

/** Shape of forecast-api's `RecentBacktestResponse`
 * (`GET /v1/forecast/recent-actual-vs-predicted`). `actual` is `null` for
 * a real step the warehouse hasn't landed demand for yet (a genuine gap,
 * not an error) -- the predicted fields are still real for that step. */
export type RecentBacktest = {
  region: string;
  model: string;
  generated_at: string;
  horizon_hours: number;
  interval: string;
  days_requested: number;
  points: {
    ts: string;
    actual: number | null;
    p10: number;
    p50: number;
    p90: number;
    step_hours: number;
    unit: "MW";
  }[];
};

/** Live call to `GET /v1/forecast/recent-actual-vs-predicted` — a real
 * walk-forward re-forecast of the currently-served model against real
 * actual demand for roughly the last `days` days, ending at the model's
 * own most recent real origin (see forecast-api's `evaluate_recent_
 * actual_vs_predicted` for the full reasoning). Built on demand from
 * real history every call (nothing in this platform persists a rolling
 * history of past predictions to read back instead) -- the NEM aggregate
 * in particular runs this 5 times server-side (once per NEM region) and
 * sums, so it's real but not fast; a generous timeout here, not
 * `fetchWithTimeout`'s normal 15s default. */
export async function fetchRecentBacktest(
  region: string = "NEM",
  days: number = 7,
): Promise<RecentBacktest> {
  const res = await fetchWithTimeout(
    `${FORECAST_API_URL}/forecast/recent-actual-vs-predicted?region=${region}&days=${days}`,
    {},
    45000,
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = new Error(
      body?.error?.message ?? `GET /v1/forecast/recent-actual-vs-predicted failed: ${res.status}`,
    );
    (err as Error & { code?: string }).code = body?.error?.code;
    throw err;
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
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/model`);
  if (!res.ok) {
    throw new Error(`GET /v1/model failed: ${res.status}`);
  }
  return res.json();
}

/** Shape of forecast-api's `ModelVersionOut` (`GET /v1/model/versions`). */
export type ModelVersion = {
  version: string;
  stage: string;
  run_id: string;
  created_at: string;
  metrics: Record<string, number>;
  git_sha: string | null;
};

export type ModelVersionsList = {
  name: string;
  data: ModelVersion[];
};

/** The real registered architectures this platform actually has,
 * end to end (`todo-model-training.md` Phases 1-2) -- `lstm_demand`
 * (the original LSTM) and `lstm_demand_tft` (the hand-rolled TFT).
 * TimesFM is deliberately absent: it's zero-shot, so it has no MLflow
 * Model Registry versions of its own to list/promote (see
 * `app/models/timesfm_adapter.py`'s module docstring on the data-pipeline
 * side for why). Phase 8's real dashboard experiment-comparison work --
 * letting the Model Registry page actually switch between architectures
 * instead of only ever showing `lstm_demand`. */
export const MODEL_ARCHITECTURES = [
  { modelName: "lstm_demand", label: "LSTM" },
  { modelName: "lstm_demand_tft", label: "TFT" },
  { modelName: "energy_forecast_multi_task", label: "Energy Forecast" },
] as const;

/** Live call to `GET /v1/model/versions` -- every registered MLflow
 * version of the model, any stage. Unlike `fetchModelInfo()` (which
 * only ever reports whichever version is currently Production), this
 * is the real multi-row training history: backs the Model Registry
 * page's Registry tab and Operational Tasks' "Recent Training Runs"
 * list (Model Operations TODO.md Phase 1) -- `[]` is a real, expected
 * state before the first model is ever trained+registered, not an
 * error. `modelName` (Phase 8) selects which registered architecture to
 * list -- omitted uses forecast-api's own default (`lstm_demand`). */
export async function fetchModelVersions(
  modelName?: string,
): Promise<ModelVersionsList> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/versions?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/versions`;
  const res = await fetchWithTimeout(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/versions failed: ${res.status}`,
    );
  }
  return res.json();
}

/** Live call to `POST /v1/model/versions/{version}/promote` -- real
 * MLflow stage transition, gated server-side when promoting to
 * `"Production"` (rejects a candidate with a worse `test_mape` than
 * the current Production version, a real 409). Promoting to
 * `"Production"` also archives whatever version was previously in that
 * stage server-side -- callers don't need to issue a second call for
 * that. `modelName` (Phase 8) targets a non-default architecture's
 * registry, same as `fetchModelVersions`. */
export async function promoteModelVersion(
  version: string,
  stage: "Production" | "Staging" | "Archived",
  modelName?: string,
): Promise<ModelVersion> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/model/versions/${version}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage, model_name: modelName ?? null }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `POST /v1/model/versions/${version}/promote failed: ${res.status}`,
    );
  }
  return res.json();
}

/** Live call to `DELETE /v1/model/versions/{version}` -- real,
 * permanent MLflow registry-entry removal (2026-08-05). The underlying
 * training run/artifacts aren't touched, only the registry entry --
 * once deleted, the version stops appearing in `fetchModelVersions()`
 * and can't be promoted or served. Server-side gated: throws (real 409)
 * if `version` is the current Production version, since that's what's
 * actually serving live traffic. `modelName` (Phase 8) targets a
 * non-default architecture's registry, same as `fetchModelVersions`. */
export async function deleteModelVersion(
  version: string,
  modelName?: string,
): Promise<void> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/versions/${version}?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/versions/${version}`;
  const res = await fetchWithTimeout(url, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `DELETE /v1/model/versions/${version} failed: ${res.status}`,
    );
  }
}

/** Shape of forecast-api's `LossCurvePointOut`/`LossCurveOut`
 * (`GET /v1/model/versions/{version}/loss-curve`) -- real per-epoch
 * `train_loss`/`val_loss`/`val_mape`/`val_rmse`/`val_mae` history read
 * from MLflow's step-metric history, distinct from `ModelVersion.metrics` (final
 * value only). `val_loss` (2026-08-05) is the real validation-split
 * `demand_loss` -- same units as `train_loss`, the actual "training vs
 * validation loss" pair; `val_mape`/`val_rmse`/`val_mae` are separate
 * real MW-unit (or percentage) error metrics, not losses, kept apart
 * rather than plotted on the same axis as train_loss/val_loss. */
export type LossCurvePoint = {
  epoch: number;
  train_loss: number | null;
  val_loss: number | null;
  val_mape: number | null;
  val_rmse: number | null;
  val_mae: number | null;
};

export type LossCurve = {
  model_name: string;
  version: string;
  run_id: string;
  points: LossCurvePoint[];
};

/** Live call to `GET /v1/model/versions/{version}/loss-curve` -- the
 * real per-epoch training-loss curve for one registered version.
 * `points` is `[]` for a version trained before per-epoch logging
 * existed, a real, expected state, not an error. */
export async function fetchLossCurve(
  version: string,
  modelName?: string,
): Promise<LossCurve> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/loss-curve?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/loss-curve`;
  const res = await fetchWithTimeout(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/versions/${version}/loss-curve failed: ${res.status}`,
    );
  }
  return res.json();
}

export type RegionEvaluation = {
  region: string;
  candidate: string;
  mape: number;
  rmse: number;
  coverage: number;
  /** Real mean P10-P90 width (MW) over this candidate's scored origins
   * (`ml/evaluate.py`'s `EvaluationReport.mean_interval_width`, added
   * 2026-08-10) -- the Model Comparison page's "Consistency" metric. */
  interval_width: number;
  n_origins: number;
  /** Real MAE (MW). `null` for an evaluation run logged before this
   * field existed (`ml/evaluate.py`'s `EvaluationReport.mae`, added
   * 2026-08-10) -- not fabricated as 0. */
  mae: number | null;
  /** Real mean signed error / bias (MW, `p50 - actual`) -- positive
   * means this candidate tends to over-forecast, negative under-forecast.
   * Same `null`-for-pre-existing-runs caveat as `mae`. */
  mean_error: number | null;
};

export type EvaluationSummary = {
  model_name: string;
  version: string;
  run_id: string;
  evaluated_at: string;
  n_origins: number;
  regions: RegionEvaluation[];
};

/** Live call to `GET /v1/model/versions/{version}/evaluation` -- the
 * real walk-forward backtest (`ecolens-forecast evaluate`) for one
 * registered version, per region/candidate (the version itself, its
 * uncalibrated raw quantiles, and a seasonal-naive baseline). `null`
 * when no evaluation has ever been run for this version -- a real,
 * expected state (`evaluate` is a deliberate, occasional CLI run, not
 * something every training run triggers automatically), not an error.
 * Distinct from `ModelVersion.metrics.test_mape` (the easier,
 * training-time split) -- this is the honest, harder rolling-origin
 * number a version's own registered metrics can never surface (see
 * forecast-api's `ml/registry.py`'s `get_latest_evaluation` docstring
 * for why). */
export async function fetchModelEvaluation(
  version: string,
  modelName?: string,
): Promise<EvaluationSummary | null> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/evaluation?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/evaluation`;
  const res = await fetchWithTimeout(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/versions/${version}/evaluation failed: ${res.status}`,
    );
  }
  return res.json();
}

export type EvaluationHistory = {
  model_name: string;
  version: string;
  runs: EvaluationSummary[];
};

/** Live call to `GET /v1/model/versions/{version}/evaluation-history` --
 * every real walk-forward evaluation run ever logged for `version`,
 * oldest first (`ml/registry.py`'s `get_evaluation_history`, added
 * 2026-08-10). Unlike `fetchModelEvaluation` (latest only), this is the
 * real time series a genuine "has this version's real accuracy drifted
 * since it was last evaluated" comparison needs -- the Model Comparison
 * page's "Stability (Performance Drift)" metric is computed client-side
 * from this (earliest vs. latest run's `mape`), not a fabricated single
 * score. `runs: []` (not an error) when `evaluate` has never been run
 * for this version, or only once -- both real states a drift comparison
 * simply can't be made from yet. */
export async function fetchModelEvaluationHistory(
  version: string,
  modelName?: string,
): Promise<EvaluationHistory> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/evaluation-history?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/versions/${encodeURIComponent(version)}/evaluation-history`;
  const res = await fetchWithTimeout(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ??
        `GET /v1/model/versions/${version}/evaluation-history failed: ${res.status}`,
    );
  }
  return res.json();
}

export type MlflowExperiment = {
  experiment_id: string;
  name: string;
  run_count: number;
  last_run_at: string | null;
};

/** Live call to `GET /v1/model/experiments` -- real MLflow experiments.
 * Every architecture this platform trains (LSTM/TFT/energy-forecast)
 * logs to one shared experiment (`mlops.tracking.EXPERIMENT_NAME`), so
 * this is typically a single real row, not a per-model breakdown --
 * replaces `dashboards.getMlflowExperiments()`'s fabricated sample
 * experiments (`lstm_demand_v8_hptune`, `rf_baseline`, etc., none of
 * which correspond to anything real). */
export async function fetchMlflowExperiments(): Promise<MlflowExperiment[]> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/model/experiments`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/experiments failed: ${res.status}`,
    );
  }
  const json: { data: MlflowExperiment[] } = await res.json();
  return json.data;
}

export type MlflowRun = {
  run_id: string;
  experiment_name: string;
  architecture: string | null;
  status: "running" | "finished" | "failed" | "killed";
  started_at: string | null;
  duration_seconds: number | null;
  metrics: Record<string, number>;
};

/** Live call to `GET /v1/model/mlflow-runs` -- real recent MLflow runs
 * across every experiment, newest first. `architecture` comes from each
 * run's own tag, so LSTM/TFT/energy-forecast runs are distinguishable
 * even though they share one experiment -- replaces `dashboards.
 * getMlflowRuns()`'s fabricated sample runs. */
export async function fetchMlflowRuns(limit = 8): Promise<MlflowRun[]> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/model/mlflow-runs?limit=${limit}`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/mlflow-runs failed: ${res.status}`,
    );
  }
  const json: { data: MlflowRun[] } = await res.json();
  return json.data;
}

export type TuneTrial = {
  hidden_size: number;
  lr: number;
  val_mape: number;
  run_id: string;
};

export type TuneTriggerResult = {
  best_hidden_size: number;
  best_lr: number;
  best_val_mape: number;
  best_run_id: string;
  trials: TuneTrial[];
};

/** Live call to `POST /v1/model/tune` -- a real grid search (3
 * hidden_sizes × 2 learning_rates = 6 trials, each a full training
 * run). Synchronous -- resolves once the whole real search completes
 * (verified live: ~75s at this service's current data volume), not a
 * 202-queued trigger the way `/model/train` is -- there's no separate
 * worker process this hands off to. */
export async function triggerTune(regions?: string[]): Promise<TuneTriggerResult> {
  const res = await fetchWithTimeout(
    `${FORECAST_API_URL}/model/tune`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ regions: regions ?? null }),
    },
    // Real, synchronous grid search -- ~75s measured, not a hung
    // request; the default 15s timeout would wrongly abort this one.
    180000,
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error?.message ?? `POST /v1/model/tune failed: ${res.status}`);
  }
  return res.json();
}

export type TuningRun = {
  run_id: string;
  status: string;
  started_at: string | null;
  duration_seconds: number | null;
  metrics: Record<string, number>;
  params: Record<string, string>;
};

/** Live call to `GET /v1/model/tuning-runs` -- real MLflow runs tagged
 * `tuning=true` (every trial `ml/tune.py`'s grid search runs logs
 * itself with this tag) -- replaces the old mock's 4 hardcoded sample
 * trial rows. */
export async function fetchTuningRuns(limit = 20): Promise<TuningRun[]> {
  const res = await fetchWithTimeout(`${FORECAST_API_URL}/model/tuning-runs?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`GET /v1/model/tuning-runs failed: ${res.status}`);
  }
  const json: { data: TuningRun[] } = await res.json();
  return json.data;
}

export type DriftReport = {
  feature: string;
  psi: number | null;
  psi_severity: "none" | "moderate" | "major" | "unknown";
  ks_statistic: number | null;
  ks_pvalue: number | null;
  reference_n: number;
  comparison_n: number;
};

/** Live call to `GET /v1/model/drift` -- real PSI/KS drift, top 10
 * features by PSI, between an older ("reference") and more recent
 * ("comparison") chronological slice of the same real training data.
 * `[]` is a real, expected state when there isn't enough data on both
 * sides yet (e.g. this architecture's Postgres marts are empty).
 *
 * Real, disclosed limitation (`live_drift.py`'s own docstring): this is
 * NOT a training-vs-live-serving comparison -- there's no live serving
 * feature snapshot logged anywhere yet. A feature like `day_of_year`
 * will show extreme PSI here purely because the reference/comparison
 * windows don't each span a full year (different seasons look like
 * "drift" even with a perfectly stable model) -- callers should treat
 * high-PSI calendar/seasonal features as a methodology artifact, not
 * necessarily a real signal, until each window covers a full year. */
export async function fetchDrift(modelName?: string): Promise<DriftReport[]> {
  const url = modelName
    ? `${FORECAST_API_URL}/model/drift?model_name=${encodeURIComponent(modelName)}`
    : `${FORECAST_API_URL}/model/drift`;
  const res = await fetchWithTimeout(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      body?.error?.message ?? `GET /v1/model/drift failed: ${res.status}`,
    );
  }
  const json: { data: DriftReport[] } = await res.json();
  return json.data;
}

/** Polls `fetchModelVersions()` every `intervalMs` until the newest
 * version differs from `sinceVersion` (the top-of-list version's id
 * *before* the trigger, or `null` if the registry was empty) or
 * `timeoutMs` elapses. Used after `triggerTraining()`
 * (`lib/ingestion.ts`) -- that trigger has no training-run id to poll
 * directly (a separate, independently-running consumer process does
 * the actual work; see its own docstring), so watching for a new
 * top-of-list version here is the only real completion signal
 * available. Returns a cancel function; callers must call it on
 * unmount so a stale poll doesn't call `onUpdate` after the
 * component's gone.
 *
 * `onTimeout` (2026-08-11, real bug fix): previously this just silently
 * stopped calling `setTimeout` once `deadline` passed, with no signal
 * to the caller at all -- confirmed live, a real training-trigger
 * consumer crash (see `db/rabbitmq.py`'s `consume_training_trigger_
 * events` docstring for that real bug) left callers stuck showing
 * "Waiting for the worker..." forever, no error, no way to tell a user
 * "this gave up" from "this is still genuinely in progress". Called
 * once, only when the real deadline is reached with no new version
 * ever having landed -- never called after a real `onUpdate` already
 * found one (that path returns early instead). */
export function pollForNewModelVersion(
  sinceVersion: string | null,
  onUpdate: (versions: ModelVersionsList) => void,
  intervalMs = 5000,
  timeoutMs = 120_000,
  modelName?: string,
  onTimeout?: () => void,
): () => void {
  let cancelled = false;
  const deadline = Date.now() + timeoutMs;
  const tick = async () => {
    try {
      const res = await fetchModelVersions(modelName);
      if (cancelled) return;
      onUpdate(res);
      const newest = res.data[0]?.version ?? null;
      if (newest !== sinceVersion) return; // a new version landed -- stop polling
    } catch {
      // A transient poll failure isn't fatal -- just retry next tick.
    }
    if (cancelled) return;
    if (Date.now() < deadline) {
      setTimeout(tick, intervalMs);
    } else {
      onTimeout?.();
    }
  };
  void tick();
  return () => {
    cancelled = true;
  };
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
