/**
 * /analytics-forecast — Analytics & Forecast.
 *
 * Combines the three real data sources the Forecast Explorer, Carbon
 * Intelligence, and Energy Analytics pages already use into one
 * consolidated view — every number here is real, fetched from the same
 * `forecast-api` endpoints those pages call directly (no new mock data,
 * same "no fabricated numbers, honest empty state on failure" policy
 * every page in this dashboard already follows).
 *
 * **Demand Forecast dates are relabeled relative to now, not the
 * model's own real lookback anchor** (2026-09-09, explicit user
 * request): the model's real 48-step horizon is anchored to its own
 * real lookback data, not to `generated_at`, and that anchor currently
 * runs well behind live (real AEMO archive-publishing lag) —
 * independently of `actual`'s own fresher OE-sourced data, so most of
 * the model's real 48 steps would otherwise already be covered by real
 * actual readings, leaving only a few genuinely future hours to show.
 * Per an explicit request to always show a full "now + 48h" line here,
 * `forecastChartPoints` keeps the model's real P10/P50/P90 values
 * unchanged but re-timestamps each step as `actualEndMs + step ×
 * interval` instead of the model's own real dates — the one place in
 * this codebase that deliberately overrides the "never reposition
 * dates to fake a forward-looking window" convention `DemandForecast
 * Chart`'s own header comment still documents and still enforces for
 * every other caller (the Executive Dashboard's identical chart
 * included). Disclosed explicitly as a caption under the chart: the
 * *values* are real, the *dates* are not.
 *
 * Ported from a reference design (`Analytics and Forecasting.png`) --
 * three things in it don't correspond to anything this platform
 * actually has and are honestly re-scoped rather than faked to match
 * pixel-for-pixel:
 *   - "Generation Mix (Forecast)" -- there's no generation-mix
 *     *forecast* endpoint (only real historical/period mix,
 *     `GET /v1/generation-mix`). Labeled "Generation Mix" here, backed
 *     by the same real period-scoped mix the "Fuel Mix (detailed)"
 *     panel and the Per-Region table's totals already use -- one real
 *     fetch, three honest views of it, not three different numbers.
 *   - "MW / %" toggle on the Demand Forecast chart -- no second real
 *     unit exists for a demand forecast (unlike, say, emissions vs.
 *     intensity); the chart is MW throughout, like Forecast Explorer's.
 *   - "Model Comparison" (LSTM vs TFT vs Seasonal Naive) -- built from
 *     each architecture's own real walk-forward evaluation
 *     (`GET /v1/model/versions/{v}/evaluation`, `RegionEvaluation.
 *     candidate` -- real values are `"{model_name}_v{version}"` (e.g.
 *     `"lstm_demand_v5"`) and `"seasonal_naive"`, confirmed live against
 *     forecast-api's own `evaluate.py`), n_origins-weighted across
 *     whichever real regions each architecture has been evaluated on.
 *     `null` (an honest "not evaluated yet" state, not a placeholder
 *     row) when a version has never had `evaluate` run against it --
 *     a deliberate, occasional CLI run, not automatic on every train.
 *
 * "View Model Details" (the reference design's link into a dedicated
 * model-registry page) is omitted -- `/dashboard/models` is disabled
 * (see that route's own page.tsx), and every field it would have shown
 * is already inline in the Model Details panel below.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Cloud,
  Gauge as GaugeIcon,
  Info,
  Leaf,
  Radio,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DonutChart } from "@/components/dashboard/charts";
import { Sparkline } from "@/components/dashboard/fan-chart";
import {
  DemandForecastChart,
  type DemandActualPoint,
  type DemandForecastPoint,
} from "@/components/dashboard/demand-forecast-chart";
import { RecentBacktestChart, type RecentBacktestPoint } from "@/components/dashboard/recent-backtest-chart";
import { RealEmissionsTrend } from "@/components/dashboard/real-emissions-trend";
import { cn } from "@/lib/utils";
import { getCached, setCached } from "@/lib/local-cache";
import { ALL_REGIONS, summarize, type Forecast, type Region } from "@/lib/forecast";
import {
  ALL_EMISSION_REGIONS,
  fetchCurrentEmissions,
  fetchDemandForecast,
  fetchDemandSummary,
  fetchEmissionsTimeseries,
  fetchGenerationMix,
  fetchModelEvaluation,
  fetchModelInfo,
  fetchModelVersions,
  fetchRecentBacktest,
  formatEnergy,
  formatFuelType,
  formatTco2e,
  fuelColor,
  type CurrentEmissions,
  type DemandForecast,
  type DemandSummary,
  type EmissionRegion,
  type EvaluationSummary,
  type GenerationMix,
  type ModelInfo,
  type ModelVersion,
  type RecentBacktest,
  type RegionEvaluation,
} from "@/lib/emissions";

const RECENT_BACKTEST_DAYS = 7;
const CACHE_MAX_AGE_MS = 2 * 60 * 60 * 1000;

type Period = "24h" | "7d" | "30d";
const PERIODS: { value: Period; label: string; days: number }[] = [
  { value: "24h", label: "Last 24 Hours", days: 1 },
  { value: "7d",  label: "Last 7 Days",   days: 7 },
  { value: "30d", label: "Last 30 Days",  days: 30 },
];

const TFT_MODEL_NAME = "lstm_demand_tft";
const LSTM_MODEL_NAME = "lstm_demand";

// Real fallback chain for "the" accuracy number -- same priority order
// `performance/page.tsx` already established (a live evaluate run's
// number if one exists, else the training-time test split, never a
// validation-only number presented as if it were held-out).
const MAPE_KEYS = ["eval_mape", "test_mape", "corrected_test_mape", "val_mape"];
const MAE_KEYS = ["eval_mae", "test_mae", "val_mae"];
const RMSE_KEYS = ["eval_rmse", "test_rmse", "val_rmse"];
const COVERAGE_KEYS = ["eval_coverage", "test_coverage_calibrated", "test_coverage_raw"];

function firstMetric(metrics: Record<string, number>, keys: string[]): number | null {
  for (const k of keys) {
    if (typeof metrics[k] === "number") return metrics[k];
  }
  return null;
}

/** Picks the version this page treats as "the" candidate for an
 * architecture: current Production, else the newest registered --
 * same fallback `training/page.tsx`'s own version pickers already use. */
function pickVersion(versions: ModelVersion[]): ModelVersion | null {
  if (versions.length === 0) return null;
  return versions.find((v) => v.stage === "Production") ?? versions[versions.length - 1];
}

function stageLabel(stage: string | null | undefined): string {
  if (stage === "Production") return "Production";
  if (stage === "Staging") return "Staging";
  return "Experimental";
}

/** n_origins-weighted mean across whatever real regions a candidate was
 * actually evaluated on -- a region an architecture hasn't been
 * evaluated for simply isn't in `regions` at all (RegionEvaluation is
 * per real logged row), not zero-filled. */
function aggregateCandidate(
  regions: RegionEvaluation[],
  candidate: string,
): { mape: number | null; mae: number | null; rmse: number | null; coverage: number | null; n_regions: number } | null {
  const rows = regions.filter((r) => r.candidate === candidate);
  if (rows.length === 0) return null;
  const wavg = (get: (r: RegionEvaluation) => number | null): number | null => {
    let sum = 0;
    let weight = 0;
    for (const r of rows) {
      const v = get(r);
      if (v == null) continue;
      sum += v * r.n_origins;
      weight += r.n_origins;
    }
    return weight > 0 ? sum / weight : null;
  };
  return {
    mape: wavg((r) => r.mape),
    mae: wavg((r) => r.mae),
    rmse: wavg((r) => r.rmse),
    coverage: wavg((r) => r.coverage),
    n_regions: rows.length,
  };
}

function toForecast(live: DemandForecast): Forecast {
  const m = /^(\d+)([mh])$/.exec(live.interval);
  const intervalMinutes = m ? (m[2] === "h" ? parseInt(m[1], 10) * 60 : parseInt(m[1], 10)) : 30;
  return {
    region: live.region as Region,
    asOf: live.generated_at,
    generatedAt: live.generated_at,
    model: live.model,
    modelVersion: 0,
    source: "api",
    intervalMinutes,
    points: live.points.map((p, i) => ({ ts: p.ts, step: i + 1, p10: p.p10, p50: p.p50, p90: p.p90 })),
  };
}

export default function AnalyticsForecastPage() {
  const [period, setPeriod] = useState<Period>("7d");
  const [region, setRegion] = useState<EmissionRegion | "NEM">("NEM");
  const [architecture, setArchitecture] = useState<"lstm" | "tft">("lstm");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const periodDef = PERIODS.find((p) => p.value === period)!;
  const { since, until, prevSince, prevUntil } = useMemo(() => {
    const u = new Date();
    const s = new Date(u.getTime() - periodDef.days * 86_400_000);
    const ps = new Date(s.getTime() - periodDef.days * 86_400_000);
    return { since: s.toISOString(), until: u.toISOString(), prevSince: ps.toISOString(), prevUntil: s.toISOString() };
  }, [periodDef.days]);

  // ── Demand forecast (chart + Forecast Demand / Peak Demand KPIs) ──
  const [live, setLive] = useState<DemandForecast | null>(null);
  const [liveFailed, setLiveFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setLiveFailed(false);
    const cacheKey = `analytics-forecast:live:${region}`;
    const cached = getCached<DemandForecast>(cacheKey, CACHE_MAX_AGE_MS);
    if (cached) setLive(cached);
    fetchDemandForecast(region)
      .then((f) => {
        if (cancelled) return;
        setLive(f);
        setCached(cacheKey, f);
        setLastUpdated(new Date());
      })
      .catch(() => {
        if (!cancelled) {
          if (!cached) setLive(null);
          setLiveFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [region]);

  // Real actual demand history feeding the same "Demand Forecast" chart
  // as `live` above -- same `total_generation_mwh` proxy + same
  // `fetchEmissionsTimeseries("hour", …)` call the Executive Dashboard's
  // own "Demand Forecast Preview" already uses `DemandForecastChart`
  // with. `DemandForecastChart` anchors its "Now" boundary to `actual`'s
  // own most recent real point (see that component's own header
  // comment for why, and for the real 2026-09-09 bug this fixed: "Now"
  // used to be pinned to the forecast's own start instead, which could
  // be tens of hours behind live and, worse, made already-known real
  // actual demand render as if it were still an uncertain prediction).
  // This fetch uses a 7-day lookback (matching `RECENT_BACKTEST_DAYS`
  // already used elsewhere on this page) so real ingestion lag on the
  // *forecast* side (its own lookback anchor can run well behind
  // `actual`) never leaves the chart without enough real actual history
  // to draw right up to that real boundary.
  const [demandActual, setDemandActual] = useState<DemandActualPoint[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const cacheKey = `analytics-forecast:demand-actual:${region}`;
    const cached = getCached<DemandActualPoint[]>(cacheKey, CACHE_MAX_AGE_MS);
    if (cached) setDemandActual(cached);
    fetchEmissionsTimeseries("hour", RECENT_BACKTEST_DAYS, region === "NEM" ? undefined : region)
      .then((series) => {
        if (cancelled) return;
        const fresh = series.points
          .filter((p) => p.total_generation_mwh !== null)
          .map((p) => ({
            ts: p.bucket,
            tMs: new Date(p.bucket).getTime(),
            mw: Math.round(p.total_generation_mwh!),
          }));
        setDemandActual(fresh);
        setCached(cacheKey, fresh);
      })
      .catch(() => {
        if (!cancelled && !cached) setDemandActual(null);
      });
    return () => {
      cancelled = true;
    };
  }, [region]);

  const forecast = useMemo(() => (live ? toForecast(live) : null), [live]);
  const summary = useMemo(() => (forecast ? summarize(forecast) : null), [forecast]);
  const peakIdx = useMemo(() => {
    if (!forecast || !summary) return undefined;
    const idx = forecast.points.findIndex((p) => p.ts === summary.peak.ts);
    return idx >= 0 ? idx + 1 : undefined;
  }, [forecast, summary]);
  // Deliberately relabeled dates (2026-09-09, explicit user request,
  // overriding this app's own general "never reposition dates to fake
  // a forward-looking window" convention -- see `DemandForecastChart`'s
  // header comment, which still applies to every OTHER caller,
  // including the Executive Dashboard's identical chart): the model's
  // real 48 P10/P50/P90 values, unchanged, but re-timestamped as
  // `actualEndMs + step * interval` instead of the model's own real
  // (currently ~44h-lagged) lookback-anchored dates -- so the chart
  // reads as a genuine 48-step-ahead-of-now window the way the reference
  // design calls for, at the cost of the displayed dates no longer
  // being the model's own real ones. Disclosed explicitly in the
  // caption below the chart -- the *values* are real, the *dates*
  // are not, and that distinction is never allowed to go unstated.
  const forecastChartPoints: DemandForecastPoint[] = useMemo(() => {
    if (!live || !demandActual || demandActual.length === 0) return [];
    const actualEndMs = Math.max(...demandActual.map((p) => p.tMs));
    const m = /^(\d+)([mh])$/.exec(live.interval);
    const intervalMs = m
      ? (m[2] === "h" ? parseInt(m[1], 10) * 60 : parseInt(m[1], 10)) * 60_000
      : 60 * 60_000;
    return live.points.map((p, i) => {
      const tMs = actualEndMs + (i + 1) * intervalMs;
      return { ts: new Date(tMs).toISOString(), tMs, p10: p.p10, p50: p.p50, p90: p.p90 };
    });
  }, [live, demandActual]);

  // ── Recent backtest (Actual vs Predicted chart + Total Demand KPI) ──
  const [recentBacktest, setRecentBacktest] = useState<RecentBacktest | null>(null);
  const [recentBacktestFailed, setRecentBacktestFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setRecentBacktestFailed(false);
    const cacheKey = `analytics-forecast:backtest:${region}`;
    const cached = getCached<RecentBacktest>(cacheKey, CACHE_MAX_AGE_MS);
    if (cached) setRecentBacktest(cached);
    fetchRecentBacktest(region, RECENT_BACKTEST_DAYS)
      .then((r) => {
        if (cancelled) return;
        setRecentBacktest(r);
        setCached(cacheKey, r);
      })
      .catch(() => {
        if (!cancelled) setRecentBacktestFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [region]);

  const recentBacktestPoints: RecentBacktestPoint[] = useMemo(
    () =>
      recentBacktest
        ? recentBacktest.points.map((p) => ({
            ts: p.ts,
            tMs: new Date(p.ts).getTime(),
            actualMw: p.actual !== null ? Math.round(p.actual) : null,
            p10Mw: p.p10,
            p50Mw: p.p50,
            p90Mw: p.p90,
          }))
        : [],
    [recentBacktest],
  );
  const latestActualDemand = useMemo(() => {
    if (!recentBacktest) return null;
    for (let i = recentBacktest.points.length - 1; i >= 0; i--) {
      const p = recentBacktest.points[i];
      if (p.actual !== null) return p.actual;
    }
    return null;
  }, [recentBacktest]);
  const demandSparkline = useMemo(
    () => recentBacktest?.points.filter((p) => p.actual !== null).map((p) => p.actual!) ?? [],
    [recentBacktest],
  );

  // ── Model info (LSTM, currently served) + registry versions (both architectures) ──
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [lstmVersions, setLstmVersions] = useState<ModelVersion[]>([]);
  const [tftVersions, setTftVersions] = useState<ModelVersion[]>([]);
  useEffect(() => {
    let cancelled = false;
    const cacheKey = "analytics-forecast:model-info";
    const cached = getCached<ModelInfo>(cacheKey, CACHE_MAX_AGE_MS);
    if (cached) setModelInfo(cached);
    fetchModelInfo()
      .then((m) => {
        if (cancelled) return;
        setModelInfo(m);
        setCached(cacheKey, m);
      })
      .catch(() => {});
    fetchModelVersions(LSTM_MODEL_NAME)
      .then((r) => {
        if (!cancelled) setLstmVersions(r.data);
      })
      .catch(() => {});
    fetchModelVersions(TFT_MODEL_NAME)
      .then((r) => {
        if (!cancelled) setTftVersions(r.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const lstmVersion = useMemo(() => pickVersion(lstmVersions), [lstmVersions]);
  const tftVersion = useMemo(() => pickVersion(tftVersions), [tftVersions]);

  // ── Real walk-forward evaluation per architecture (Model Comparison table) ──
  const [lstmEval, setLstmEval] = useState<EvaluationSummary | null | undefined>(undefined);
  const [tftEval, setTftEval] = useState<EvaluationSummary | null | undefined>(undefined);
  useEffect(() => {
    if (!lstmVersion) return;
    let cancelled = false;
    fetchModelEvaluation(lstmVersion.version, LSTM_MODEL_NAME)
      .then((e) => {
        if (!cancelled) setLstmEval(e);
      })
      .catch(() => {
        if (!cancelled) setLstmEval(null);
      });
    return () => {
      cancelled = true;
    };
  }, [lstmVersion]);
  useEffect(() => {
    if (!tftVersion) return;
    let cancelled = false;
    fetchModelEvaluation(tftVersion.version, TFT_MODEL_NAME)
      .then((e) => {
        if (!cancelled) setTftEval(e);
      })
      .catch(() => {
        if (!cancelled) setTftEval(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tftVersion]);

  const comparisonRows = useMemo(() => {
    const rows: Array<{
      key: string;
      label: string;
      candidate: ReturnType<typeof aggregateCandidate>;
    }> = [];
    if (lstmEval) {
      rows.push({
        key: "lstm",
        label: `LSTM (v${lstmEval.version})`,
        candidate: aggregateCandidate(lstmEval.regions, `${lstmEval.model_name}_v${lstmEval.version}`),
      });
    }
    if (tftEval) {
      rows.push({
        key: "tft",
        label: `TFT (v${tftEval.version})`,
        candidate: aggregateCandidate(tftEval.regions, `${tftEval.model_name}_v${tftEval.version}`),
      });
    }
    const baselineSource = lstmEval ?? tftEval;
    if (baselineSource) {
      rows.push({
        key: "seasonal_naive",
        label: "Seasonal Naive",
        candidate: aggregateCandidate(baselineSource.regions, "seasonal_naive"),
      });
    }
    return rows.filter((r) => r.candidate != null);
  }, [lstmEval, tftEval]);

  // ── Generation/fuel mix: NEM-wide + all 6 regions, period-scoped ──
  const [nemMix, setNemMix] = useState<GenerationMix | null>(null);
  const [regionMixes, setRegionMixes] = useState<Record<EmissionRegion, GenerationMix> | null>(null);
  const [mixFailed, setMixFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setMixFailed(false);
    fetchGenerationMix(undefined, since, until)
      .then((mix) => {
        if (!cancelled) setNemMix(mix);
      })
      .catch(() => {
        if (!cancelled) setMixFailed(true);
      });
    Promise.all(
      ALL_EMISSION_REGIONS.map(async (r) => [r, await fetchGenerationMix(r, since, until)] as const),
    )
      .then((entries) => {
        if (!cancelled) setRegionMixes(Object.fromEntries(entries) as Record<EmissionRegion, GenerationMix>);
      })
      .catch(() => {
        if (!cancelled) setMixFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [since, until]);

  const regionRows = useMemo(() => {
    if (!regionMixes || !nemMix) return null;
    const nemAvgIntensity =
      nemMix.total_generation_mwh > 0 ? nemMix.total_emissions_kgco2e / nemMix.total_generation_mwh : null;
    return ALL_EMISSION_REGIONS.map((r) => {
      const mix = regionMixes[r];
      const intensity = mix.total_generation_mwh > 0 ? mix.total_emissions_kgco2e / mix.total_generation_mwh : null;
      let vsNemAvg: "cleaner" | "dirtier" | "even" = "even";
      if (intensity != null && nemAvgIntensity != null) {
        if (intensity < nemAvgIntensity * 0.97) vsNemAvg = "cleaner";
        else if (intensity > nemAvgIntensity * 1.03) vsNemAvg = "dirtier";
      }
      return {
        region: r,
        energy_mwh: mix.total_generation_mwh,
        emissions_kgco2e: mix.total_emissions_kgco2e,
        intensity_kgco2e_per_mwh: intensity,
        share_of_nem_pct:
          nemMix.total_emissions_kgco2e > 0 ? (mix.total_emissions_kgco2e / nemMix.total_emissions_kgco2e) * 100 : 0,
        vs_nem_avg: vsNemAvg,
      };
    });
  }, [regionMixes, nemMix]);

  const displayMix = region === "NEM" ? nemMix : (regionMixes?.[region] ?? null);

  // ── Demand summary (Renewable Share KPI, this period vs prior) ──
  const [demandSummary, setDemandSummary] = useState<DemandSummary | null>(null);
  const [prevDemandSummary, setPrevDemandSummary] = useState<DemandSummary | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchDemandSummary(since, until)
      .then((d) => {
        if (!cancelled) setDemandSummary(d);
      })
      .catch(() => {});
    fetchDemandSummary(prevSince, prevUntil)
      .then((d) => {
        if (!cancelled) setPrevDemandSummary(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [since, until, prevSince, prevUntil]);

  // ── Current emissions snapshot (Carbon Intensity KPI) ──
  const [currentEmissions, setCurrentEmissions] = useState<CurrentEmissions | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchCurrentEmissions()
      .then((c) => {
        if (!cancelled) setCurrentEmissions(c);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const renewableDeltaPct =
    demandSummary?.renewable_share_pct != null && prevDemandSummary?.renewable_share_pct != null
      ? demandSummary.renewable_share_pct - prevDemandSummary.renewable_share_pct
      : null;

  const cleanSharePct = useMemo(() => {
    if (!nemMix || nemMix.total_generation_mwh <= 0) return null;
    const clean = nemMix.items.filter((i) => i.is_renewable).reduce((s, i) => s + i.total_generation_mwh, 0);
    return (clean / nemMix.total_generation_mwh) * 100;
  }, [nemMix]);

  const topSource = useMemo(
    () => (nemMix ? [...nemMix.items].sort((a, b) => b.total_emissions_kgco2e - a.total_emissions_kgco2e)[0] : null),
    [nemMix],
  );

  // Active architecture's real model details for the Forecast Model
  // Performance panel.
  const activeVersion = architecture === "lstm" ? lstmVersion : tftVersion;
  const activeMetrics = activeVersion?.metrics ?? {};
  const activeIsServed = architecture === "lstm" && modelInfo?.status === "loaded";
  const activeMape = firstMetric(activeMetrics, MAPE_KEYS);
  const activeMae = firstMetric(activeMetrics, MAE_KEYS);
  const activeRmse = firstMetric(activeMetrics, RMSE_KEYS);
  const activeCoverage = firstMetric(activeMetrics, COVERAGE_KEYS);

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Analytics &amp; Forecast</h1>
          <p className="mt-1 text-sm text-white/55">
            Explore historical trends, model forecasts, and key energy insights — all real data
            from forecast-api, in one place.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-white/70">
            <Radio className="h-3.5 w-3.5 text-emerald-200" />
            <span className={cn("h-1.5 w-1.5 rounded-full", liveFailed ? "bg-rose-400" : "bg-emerald-300")} />
            {liveFailed ? "Unavailable" : "Live Data"}
          </div>
          <span className="text-xs text-white/40">
            Last updated{" "}
            {lastUpdated
              ? lastUpdated.toLocaleTimeString("en-AU", { timeZone: "Australia/Sydney", hour: "2-digit", minute: "2-digit" })
              : "—"}
          </span>
        </div>
      </div>

      {/* ── Period + Region selectors ──────────────────────── */}
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">Period</div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Period">
              {PERIODS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  role="tab"
                  aria-selected={p.value === period}
                  onClick={() => setPeriod(p.value)}
                  data-testid={`af-period-${p.value}`}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    p.value === period
                      ? "bg-lime-100 text-black"
                      : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">Region</div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Region">
              <button
                type="button"
                role="tab"
                aria-selected={region === "NEM"}
                onClick={() => setRegion("NEM")}
                data-testid="af-region-NEM"
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  region === "NEM"
                    ? "bg-emerald-200 text-black"
                    : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                )}
              >
                NEM (All)
              </button>
              {ALL_REGIONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  role="tab"
                  aria-selected={r === region}
                  onClick={() => setRegion(r)}
                  data-testid={`af-region-${r}`}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    r === region
                      ? "bg-emerald-200 text-black"
                      : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                  )}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Card>

      {/* ── KPI row ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi
          icon={Zap}
          label="Total Demand (Actual)"
          value={latestActualDemand != null ? `${Math.round(latestActualDemand).toLocaleString()} MW` : "—"}
          hint={recentBacktestFailed ? "unavailable" : "most recent real reading"}
          sparkline={demandSparkline}
          sparkColor="rgba(52,211,153,0.9)"
        />
        <Kpi
          icon={TrendingUp}
          label="Forecast Demand (P50)"
          value={forecast && forecast.points.length > 0 ? `${forecast.points[0].p50.toLocaleString()} MW` : "—"}
          hint={live ? `next ${live.interval}` : liveFailed ? "unavailable" : undefined}
          sparkline={forecast?.points.slice(0, 12).map((p) => p.p50)}
          sparkColor="rgba(56,189,248,0.9)"
        />
        <Kpi
          icon={ArrowUpRight}
          label="Peak Demand"
          value={summary ? `${summary.peak.value.toLocaleString()} MW` : "—"}
          hint={
            summary && forecast && peakIdx
              ? `at step ${peakIdx} of ${forecast.points.length}`
              : liveFailed
                ? "unavailable"
                : undefined
          }
        />
        <Kpi
          icon={Leaf}
          label="Renewable Share"
          value={demandSummary?.renewable_share_pct != null ? `${demandSummary.renewable_share_pct.toFixed(1)}%` : "—"}
          deltaPct={renewableDeltaPct}
          deltaIsPoints
          goodWhen="up"
          hint={`vs previous ${periodDef.days}d`}
        />
        <Kpi
          icon={GaugeIcon}
          label="Carbon Intensity"
          value={
            currentEmissions?.intensity_kgco2e_per_mwh != null
              ? `${Math.round(currentEmissions.intensity_kgco2e_per_mwh)} gCO₂e/kWh`
              : "—"
          }
          hint={currentEmissions ? `as of ${new Date(currentEmissions.as_of).toLocaleTimeString("en-AU", { timeZone: "Australia/Sydney", hour: "2-digit", minute: "2-digit" })}` : undefined}
        />
      </div>

      {/* ── Demand Forecast + Forecast Model Performance + Generation Mix ── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-200" /> Demand Forecast
            </span>
          }
          subtitle={`Actual demand history feeding into predicted demand (P50) with prediction intervals (P10–P90) — ${region}`}
        >
          {forecast ? (
            <>
              <DemandForecastChart
                actual={demandActual ?? []}
                forecast={forecastChartPoints}
                testId="af-demand-forecast-chart"
              />
              <p className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-200/80">
                <Info className="mt-px h-3 w-3 shrink-0" />
                P10/P50/P90 values are the model&apos;s real latest prediction, unchanged — the
                step dates shown are relabeled relative to the most recent real actual reading
                (not the model&apos;s own real lookback-anchored dates, currently lagged behind
                live) so this reads as a forward-looking {forecastChartPoints.length}-step window
                from now.
              </p>
            </>
          ) : (
            <p className="py-16 text-center text-sm text-white/40">
              {liveFailed ? "No forecast available — is forecast-api running, and is a model loaded?" : "Loading forecast…"}
            </p>
          )}
        </Card>

        <Card title="Forecast Model Performance">
          <div className="flex gap-1 rounded-md bg-white/5 p-1">
            <button
              type="button"
              onClick={() => setArchitecture("lstm")}
              className={cn(
                "flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors",
                architecture === "lstm" ? "bg-lime-100 text-black" : "text-white/60 hover:text-white",
              )}
            >
              LSTM {lstmVersion ? `(${stageLabel(lstmVersion.stage)})` : ""}
            </button>
            <button
              type="button"
              onClick={() => setArchitecture("tft")}
              className={cn(
                "flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors",
                architecture === "tft" ? "bg-lime-100 text-black" : "text-white/60 hover:text-white",
              )}
            >
              TFT {tftVersion ? `(${stageLabel(tftVersion.stage)})` : ""}
            </button>
          </div>
          {activeVersion ? (
            <>
              <div className="mt-3 flex items-center gap-2 text-xs">
                <span className="font-mono text-white/80">
                  {architecture === "lstm" ? "LSTM" : "TFT"} v{activeVersion.version}
                </span>
                {activeIsServed && (
                  <span className="rounded-full border border-emerald-200/30 bg-emerald-200/10 px-2 py-0.5 text-[10px] font-medium text-emerald-100">
                    Live
                  </span>
                )}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                <MiniStat label="MAPE" value={activeMape != null ? `${activeMape.toFixed(2)}%` : "—"} />
                <MiniStat label="MAE" value={activeMae != null ? `${Math.round(activeMae)} MW` : "—"} />
                <MiniStat label="RMSE" value={activeRmse != null ? `${Math.round(activeRmse)} MW` : "—"} />
                <MiniStat
                  label="Coverage"
                  value={activeCoverage != null ? `${(activeCoverage <= 1 ? activeCoverage * 100 : activeCoverage).toFixed(1)}%` : "—"}
                />
              </div>
              <dl className="mt-3 space-y-1.5 text-xs">
                <Row label="Type" value={architecture === "lstm" ? "LSTM" : "TFT"} />
                <Row
                  label="Horizon"
                  value={activeIsServed && modelInfo?.horizon != null ? `${modelInfo.horizon} steps` : "—"}
                />
                <Row label="Probabilistic output" value="P10 / P50 / P90" />
                <Row
                  label="Calibration"
                  value={activeCoverage != null ? `Conformal (${(activeCoverage <= 1 ? activeCoverage * 100 : activeCoverage).toFixed(1)}% coverage)` : "—"}
                />
                <Row label="Last trained" value={new Date(activeVersion.created_at).toLocaleDateString("en-AU", { timeZone: "Australia/Sydney" })} />
              </dl>
            </>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">No registered version yet.</p>
          )}
        </Card>

        <Card title="Generation Mix" subtitle={periodDef.label}>
          {displayMix ? (
            <div className="flex flex-col items-center">
              <DonutChart
                data={displayMix.items.map((i) => ({
                  label: formatFuelType(i.fuel_type),
                  value: i.total_generation_mwh,
                  color: fuelColor(i.fuel_type),
                }))}
                size={150}
                thickness={18}
                centerLabel={formatEnergy(displayMix.total_generation_mwh)}
                centerSub="Total generation"
                formatTooltip={(label, value) => (
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">{label}</span>
                    <span className="ml-auto font-mono font-medium text-white">{formatEnergy(value)}</span>
                  </div>
                )}
              />
              <div className="mt-3 w-full space-y-1 text-[11px]">
                {[...displayMix.items]
                  .sort((a, b) => b.total_generation_mwh - a.total_generation_mwh)
                  .map((i) => (
                    <div key={i.fuel_type} className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: fuelColor(i.fuel_type) }} />
                        <span className="text-white/70">{formatFuelType(i.fuel_type)}</span>
                      </span>
                      <span className="text-white">{i.pct_of_total_generation.toFixed(0)}%</span>
                    </div>
                  ))}
              </div>
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">
              {mixFailed ? "Unavailable — is forecast-api running?" : "Loading…"}
            </p>
          )}
        </Card>
      </div>

      {/* ── Emissions Forecast + Per-Region Emissions + Fuel Mix + Key Insights ── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="lg:col-span-2">
          <RealEmissionsTrend title="Emissions Forecast (Australia)" />
        </div>

        <Card title="Per-Region Emissions" subtitle={periodDef.label} className="lg:col-span-1">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]" data-testid="af-region-table">
              <thead>
                <tr className="border-b border-white/5 text-left text-[9px] uppercase tracking-wider text-white/40">
                  <th className="py-1.5 pr-2">Region</th>
                  <th className="py-1.5 pr-2 text-right">tCO₂e</th>
                  <th className="py-1.5 text-right">Share</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {regionRows == null ? (
                  <tr>
                    <td colSpan={3} className="py-6 text-center font-sans text-white/40">
                      {mixFailed ? "Unavailable — is forecast-api running?" : "Loading…"}
                    </td>
                  </tr>
                ) : (
                  regionRows.map((r) => (
                    <tr key={r.region} className="border-t border-white/5">
                      <td className="py-1.5 pr-2 font-sans text-white">{r.region}</td>
                      <td className="py-1.5 pr-2 text-right text-lime-100">{(r.emissions_kgco2e / 1000).toFixed(1)}</td>
                      <td className="py-1.5 text-right text-white/70">{r.share_of_nem_pct.toFixed(1)}%</td>
                    </tr>
                  ))
                )}
              </tbody>
              {nemMix && (
                <tfoot>
                  <tr className="border-t-2 border-white/10 font-sans font-semibold text-white">
                    <td className="py-2 pr-2">NEM (Total)</td>
                    <td className="py-2 pr-2 text-right font-mono text-lime-100">{formatTco2e(nemMix.total_emissions_kgco2e)}</td>
                    <td className="py-2 text-right">100%</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </Card>

        <Card title="Fuel Mix (detailed)" subtitle={periodDef.label}>
          {displayMix ? (
            <div className="flex flex-col items-center">
              <DonutChart
                data={displayMix.items.map((i) => ({
                  label: formatFuelType(i.fuel_type),
                  value: i.total_emissions_kgco2e,
                  color: fuelColor(i.fuel_type),
                }))}
                size={130}
                thickness={16}
                centerLabel={formatTco2e(displayMix.total_emissions_kgco2e)}
                formatTooltip={(label, value) => (
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">{label}</span>
                    <span className="ml-auto font-mono font-medium text-white">{formatTco2e(value)}</span>
                  </div>
                )}
              />
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">
              {mixFailed ? "Unavailable — is forecast-api running?" : "Loading…"}
            </p>
          )}
        </Card>

        <Card title="Key Insights">
          <div className="space-y-3 text-xs">
            {topSource && nemMix && (
              <Insight
                icon={Cloud}
                tone="warning"
                title={`${formatFuelType(topSource.fuel_type)} remains the largest source`}
                body={`${formatFuelType(topSource.fuel_type)} contributed ${nemMix.total_emissions_kgco2e ? Math.round((topSource.total_emissions_kgco2e / nemMix.total_emissions_kgco2e) * 100) : 0}% of emissions ${periodDef.label.toLowerCase()}.`}
              />
            )}
            {cleanSharePct != null && (
              <Insight
                icon={Sparkles}
                tone="positive"
                title="Clean energy contribution"
                body={`Renewables contributed ${cleanSharePct.toFixed(0)}% of generation ${periodDef.label.toLowerCase()}.`}
              />
            )}
            {renewableDeltaPct != null && (
              <Insight
                icon={renewableDeltaPct >= 0 ? TrendingUp : Activity}
                tone={renewableDeltaPct >= 0 ? "positive" : "negative"}
                title={`Renewable share ${renewableDeltaPct >= 0 ? "growing" : "shrinking"}`}
                body={`${renewableDeltaPct >= 0 ? "+" : ""}${renewableDeltaPct.toFixed(1)} pts vs the previous ${periodDef.label.toLowerCase()}.`}
              />
            )}
            {live && (
              <Insight
                icon={BarChart3}
                tone="default"
                title="Forecast available"
                body={`Real-time forecast covers the next ${live.horizon} for ${region}.`}
              />
            )}
            {!topSource && !cleanSharePct && !live && (
              <p className="py-6 text-center text-white/40">
                {mixFailed && liveFailed ? "Unavailable — is forecast-api running?" : "Loading…"}
              </p>
            )}
          </div>
        </Card>
      </div>

      {/* ── Actual vs Predicted + Model Comparison ─────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={`Actual vs Predicted — ${region}`}>
          <p className="mb-3 text-xs text-white/50">
            A real walk-forward re-forecast of the currently-served model: what it actually would
            have predicted (P10–P50–P90) at each of several real points over the last{" "}
            {RECENT_BACKTEST_DAYS} days, against real actual demand for those same real timestamps.
          </p>
          {recentBacktest === null ? (
            <p className="py-8 text-center text-xs text-white/40">
              {recentBacktestFailed ? "Backtest unavailable." : "Running real walk-forward backtest…"}
            </p>
          ) : (
            <RecentBacktestChart points={recentBacktestPoints} testId="analytics-forecast-actual-vs-predicted" />
          )}
        </Card>

        <Card
          title={
            <span className="flex items-center gap-2">
              Model Comparison
              <span title="n_origins-weighted mean across every real region each version has been walk-forward evaluated on (GET /v1/model/versions/{version}/evaluation).">
                <Info className="h-3.5 w-3.5 text-white/30" />
              </span>
            </span>
          }
        >
          {comparisonRows.length === 0 ? (
            <p className="py-8 text-center text-xs text-white/40">
              No real evaluation runs logged yet for either architecture — <code className="rounded bg-black/30 px-1 font-mono text-lime-100">evaluate</code> is a
              deliberate, occasional CLI run, not automatic on every training run.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/5 text-left text-[10px] uppercase tracking-wider text-white/40">
                    <th className="py-1.5 pr-2">Model</th>
                    <th className="py-1.5 pr-2 text-right">MAPE ↓</th>
                    <th className="py-1.5 pr-2 text-right">MAE ↓</th>
                    <th className="py-1.5 pr-2 text-right">RMSE ↓</th>
                    <th className="py-1.5 text-right">Coverage ↑</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {comparisonRows.map((r) => (
                    <tr key={r.key} className="border-t border-white/5">
                      <td className="py-1.5 pr-2 font-sans text-white">{r.label}</td>
                      <td className="py-1.5 pr-2 text-right text-white/80">
                        {r.candidate!.mape != null ? `${r.candidate!.mape.toFixed(2)}%` : "—"}
                      </td>
                      <td className="py-1.5 pr-2 text-right text-white/80">
                        {r.candidate!.mae != null ? Math.round(r.candidate!.mae) : "—"}
                      </td>
                      <td className="py-1.5 pr-2 text-right text-white/80">
                        {r.candidate!.rmse != null ? Math.round(r.candidate!.rmse) : "—"}
                      </td>
                      <td className="py-1.5 text-right text-emerald-100">
                        {r.candidate!.coverage != null
                          ? `${(r.candidate!.coverage <= 1 ? r.candidate!.coverage * 100 : r.candidate!.coverage).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  hint,
  deltaPct,
  deltaIsPoints,
  goodWhen,
  sparkline,
  sparkColor,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  deltaPct?: number | null;
  deltaIsPoints?: boolean;
  goodWhen?: "up" | "down";
  sparkline?: number[];
  sparkColor?: string;
}) {
  const isGood = deltaPct == null || !goodWhen ? null : goodWhen === "down" ? deltaPct <= 0 : deltaPct >= 0;
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
          <div className="mt-1 text-xl font-bold text-white">{value}</div>
          <div className="mt-0.5 flex items-center gap-1 text-[10px]">
            {deltaPct != null && (
              <span className={cn("font-medium", isGood ? "text-emerald-200" : "text-rose-300")}>
                {deltaPct >= 0 ? "↑" : "↓"} {Math.abs(deltaPct).toFixed(deltaIsPoints ? 1 : 0)}
                {deltaIsPoints ? " pts" : "%"}
              </span>
            )}
            {hint && <span className="text-white/40">{hint}</span>}
          </div>
        </div>
        <Icon className="h-4 w-4 shrink-0 text-white/40" />
      </div>
      {sparkline && sparkline.length > 1 && (
        <Sparkline values={sparkline} width={140} height={28} color={sparkColor} className="mt-2 w-full" />
      )}
    </Card>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.02] px-2 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 font-mono text-sm text-white">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-white/45">{label}</dt>
      <dd className="font-mono text-white/80">{value}</dd>
    </div>
  );
}

function Insight({
  icon: Icon,
  tone,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: "positive" | "negative" | "warning" | "default";
  title: string;
  body: string;
}) {
  const color =
    tone === "positive" ? "text-emerald-200" : tone === "negative" ? "text-rose-300" : tone === "warning" ? "text-amber-200" : "text-sky-200";
  return (
    <div className="flex gap-2">
      <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", color)} />
      <div>
        <p className={cn("font-semibold", color)}>{title}</p>
        <p className="mt-0.5 text-white/55">{body}</p>
      </div>
    </div>
  );
}
