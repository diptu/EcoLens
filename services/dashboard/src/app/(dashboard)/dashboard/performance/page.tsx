/**
 * /dashboard/performance — ML Platform → Performance → Model Performance.
 *
 * Restructured 2026-08-10 into the tabbed layout a design reference
 * (Overview / Accuracy / Calibration / Residuals / Feature Impact /
 * Model Drifts / Logs) called for -- redistributes this page's own prior
 * flat-scroll real content into those tabs rather than discarding it, and
 * adds several genuinely new real sections the reference asked for that
 * this page's existing fetches didn't previously surface:
 *
 *   - Bias (ME) / MAE / Prediction interval width -- real, but required a
 *     small backend extension (`ml/evaluate.py`'s `EvaluationReport`
 *     didn't compute them before this pass; `GET /v1/model/versions/
 *     {version}/evaluation`'s `RegionEvaluationOut` didn't expose them).
 *     `null` for any evaluation run logged before this field existed --
 *     not backfilled/fabricated, a real "predates this metric" state.
 *   - Accuracy by horizon (1H/3H/6H/12H/24H/36H/48H) -- real, from a new
 *     `step_hours` field on `GET /v1/forecast/recent-actual-vs-predicted`
 *     (`RecentBacktestPoint.step_hours`, added alongside this page) --
 *     that endpoint's own per-step points already carried this
 *     information internally, it just wasn't returned before.
 *   - Error distribution -- real histogram, binned client-side from the
 *     same recent-backtest points' real `(actual - p50)` errors. Not a
 *     separate backend endpoint -- computing a histogram from points
 *     already on the page is a client-side reduction, same as several
 *     other real derived stats already here (`errorHealth`, etc.).
 *   - Model vs Benchmark -- real, fetches all 3 real architectures'
 *     (LSTM/TFT/TimesFM) Production evaluations in parallel (previously
 *     this page only ever showed one architecture at a time via the
 *     LSTM/TFT/TimesFM tab toggle). "Score" is a disclosed formula over
 *     real inputs, same spirit as the existing Model health score.
 *   - Feature Impact -- real, from `services/ingestion`'s
 *     `GET /v1/features/rebuild/runs` (`meta._feature_selection_log`'s
 *     persisted `result.feature_scores` -- real mutual-information +
 *     RandomForest + permutation-importance output, not a placeholder).
 *     This is the last *completed offline* feature-selection pass, not
 *     live per-prediction SHAP attribution -- no such thing exists
 *     anywhere in this platform, and this tab says so rather than
 *     pretending otherwise.
 *   - Recent Alerts & Events -- real, built from this page's own already-
 *     computed alert-condition trigger states + the latest real training
 *     run, not the reference's illustrative sample event text.
 *
 * Everything else (MLflow registry, walk-forward evaluation per region,
 * training/validation loss curves, concept drift PSI/KS, training-run
 * log) is the same real data this page already had, just moved under a
 * tab. `IllustrativeBadge` still marks the few things with no real
 * backend concept at all (batch-count tracking, historical drift
 * persistence, alert paging) -- this page's long-standing "no silently
 * fabricated dashboards" convention is unchanged.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, Box,
  CheckCircle2, ChevronRight, Cpu, Database, FileText, Gauge, GitBranch, Info,
  Radar, RefreshCw, Rocket, Sliders, Target, TrendingUp, Workflow, Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { BarChart, LineChart } from "@/components/dashboard/charts";
import { ArcGauge } from "@/components/dashboard/gauge";
import { IllustrativeBadge } from "@/components/dashboard/illustrative-badge";
import { cn } from "@/lib/utils";
import { ALL_REGIONS } from "@/lib/forecast";
import {
  fetchDrift,
  fetchLossCurve,
  fetchModelEvaluation,
  fetchModelEvaluationHistory,
  fetchModelVersions,
  fetchRecentBacktest,
  type DriftReport,
  type EvaluationHistory,
  type EvaluationSummary,
  type LossCurve,
  type ModelVersion,
  type RecentBacktest,
} from "@/lib/emissions";
import {
  fetchFeatureRebuildRuns,
  fetchTrainingRuns,
  formatRelativeTime,
  type FeatureRebuildRun,
  type TrainingRunLog,
} from "@/lib/ingestion";

// `Settings.conformal_alpha = 0.2` (data-pipeline) -- a fixed training-time
// config value, not something any API currently exposes live. Documented
// here as a known real fact (same pattern `PERFORMANCE_ARCHITECTURES`
// below uses for a hardcoded-but-real list), not an invented number.
const CONFORMAL_ALPHA = 0.2;
const TARGET_COVERAGE_PCT = (1 - CONFORMAL_ALPHA) * 100;

// This page's own architecture list, deliberately narrower than
// `lib/emissions.ts`'s shared `MODEL_ARCHITECTURES` (which also backs
// `models/page.tsx`/`training/page.tsx` and includes
// `energy_forecast_multi_task`) -- Performance is scoped to the three
// forecasting architectures the product description names (LSTM, TFT,
// TimesFM), not the separate carbon-insights model.
//
// TimesFM's real registrable model is `timesfm_demand_correction`
// (`service/ml/timesfm_correction.py`), NOT `lstm_demand_timesfm` --
// that string is only a evaluation-run *tag* (`ml/evaluate.py`'s own
// comment on it: "a label for evaluation runs to tag themselves with,
// not an MLflow Model Registry entry"), so querying it here always
// 404s/returns empty regardless of real registry state. Raw zero-shot
// TimesFM itself genuinely has no trainable weights to register, but
// `timesfm_correction.py`'s Ridge-regression residual-correction layer
// on top of it does -- real MLflow versions/metrics, same as LSTM/TFT.
const PERFORMANCE_ARCHITECTURES = [
  { modelName: "lstm_demand", label: "LSTM" },
  { modelName: "lstm_demand_tft", label: "TFT" },
  { modelName: "timesfm_demand_correction", label: "TimesFM" },
] as const;

// Candidate metric keys, in priority order -- training runs log different
// keys depending on whether a live-evaluation gate ran (`eval_*`) or only
// the training-time test split did (`test_*`). No key is guaranteed.
const MAPE_KEYS = ["eval_mape", "test_mape", "corrected_test_mape"];
const RMSE_KEYS = ["eval_rmse"];
const COVERAGE_KEYS = [
  "eval_coverage",
  "test_coverage_calibrated",
  "test_coverage_raw",
  "corrected_test_coverage_calibrated",
  "corrected_test_coverage_raw",
];

// Real horizon steps this page's new "Accuracy by Horizon" chart groups
// `GET /v1/forecast/recent-actual-vs-predicted`'s real per-step points
// by -- matches the currently-served model's real fixed 48h horizon (see
// `RecentBacktestPoint.step_hours`'s own docstring), not an arbitrary
// choice; every one of these is a real step_hours value every scored
// origin actually produces.
const HORIZON_BUCKETS_H = [1, 3, 6, 12, 24, 36, 48] as const;

const REGION_FILTER_OPTIONS = ["NEM", ...ALL_REGIONS] as const;

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "accuracy", label: "Accuracy" },
  { key: "calibration", label: "Calibration" },
  { key: "residuals", label: "Residuals" },
  { key: "feature-impact", label: "Feature Impact" },
  { key: "drift", label: "Model Drifts" },
  { key: "logs", label: "Logs" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

function firstMetric(metrics: Record<string, number>, keys: string[]): number | null {
  for (const k of keys) {
    if (typeof metrics[k] === "number") return metrics[k];
  }
  return null;
}

function mean(values: number[]): number | null {
  return values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

// Real "latest epoch" value + % change vs the epoch before it, from a
// per-epoch series already fetched for the chart itself -- not a
// separately-invented summary stat. `null` (not 0) when there's under 2
// real points to compare, so the stat box can honestly show "—" instead
// of a fabricated 0% delta.
function latestWithDelta(series: number[]): { value: number; deltaPct: number | null } | null {
  if (series.length === 0) return null;
  const value = series[series.length - 1];
  if (series.length < 2) return { value, deltaPct: null };
  const prev = series[series.length - 2];
  const deltaPct = prev !== 0 ? ((value - prev) / prev) * 100 : null;
  return { value, deltaPct };
}

const STAGE_COLORS: Record<string, string> = {
  Production: "bg-lime-100/15 text-lime-100 border-lime-200/30",
  Staging: "bg-sky-500/15 text-sky-200 border-sky-400/30",
  Archived: "bg-white/5 text-white/55 border-white/10",
};

type RecentPoint = RecentBacktest["points"][number];

/** Real per-horizon-step MAPE, grouped from `recentBacktest`'s own real
 * points by their real `step_hours` -- one real number per bucket, `null`
 * if that exact bucket has no real (non-null-actual) points yet. */
function horizonAccuracy(points: RecentPoint[]): Array<{ h: number; mape: number | null; n: number }> {
  return HORIZON_BUCKETS_H.map((h) => {
    const scored = points.filter((p) => p.step_hours === h && p.actual !== null && p.actual !== 0);
    if (scored.length === 0) return { h, mape: null, n: 0 };
    const errs = scored.map((p) => Math.abs((p.actual! - p.p50) / p.actual!) * 100);
    return { h, mape: mean(errs), n: scored.length };
  });
}

/** Real histogram of `(actual - p50) / actual * 100` (%) over every real
 * scored point -- bins sized to the real observed range (clamped to
 * +/-60% so one wild outlier can't blow the whole chart's scale out),
 * not a fixed hardcoded axis pretending to know the real spread in
 * advance. */
function errorHistogram(points: RecentPoint[], bins = 15) {
  const errs = points
    .filter((p) => p.actual !== null && p.actual !== 0)
    .map((p) => ((p.actual! - p.p50) / p.actual!) * 100);
  if (errs.length === 0) return { buckets: [] as { mid: number; count: number }[], meanPct: null as number | null, stdPct: null as number | null };
  const maxAbs = Math.min(60, Math.max(...errs.map((e) => Math.abs(e)), 5));
  const lo = -maxAbs;
  const hi = maxAbs;
  const width = (hi - lo) / bins;
  const buckets = Array.from({ length: bins }, (_, i) => ({ mid: lo + width * (i + 0.5), count: 0 }));
  for (const e of errs) {
    const clamped = Math.max(lo, Math.min(hi - 1e-9, e));
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((clamped - lo) / width)));
    buckets[idx].count += 1;
  }
  const meanPct = mean(errs);
  const variance = meanPct !== null ? mean(errs.map((e) => (e - meanPct) ** 2)) : null;
  return { buckets, meanPct, stdPct: variance !== null ? Math.sqrt(variance) : null };
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

export default function PerformancePage() {
  const [tab, setTab] = useState<TabKey>("overview");
  const [architecture, setArchitecture] = useState<string>(
    PERFORMANCE_ARCHITECTURES[0].modelName,
  );
  const [region, setRegion] = useState<(typeof REGION_FILTER_OPTIONS)[number]>("NEM");
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [runs, setRuns] = useState<TrainingRunLog[] | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [lossCurve, setLossCurve] = useState<LossCurve | null>(null);
  const [lossCurveLoaded, setLossCurveLoaded] = useState(false);
  const [selectedLossCurveVersion, setSelectedLossCurveVersion] = useState<string | null>(
    null,
  );
  const [drift, setDrift] = useState<DriftReport[] | null>(null);
  const [driftLoaded, setDriftLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    // A version picked for one architecture's registry doesn't exist in
    // another's -- reset back to the default (Production, falling back
    // to newest) whenever the LSTM/TFT toggle changes.
    setSelectedLossCurveVersion(null);
    Promise.all([fetchModelVersions(architecture), fetchTrainingRuns(20)])
      .then(([v, r]) => {
        if (cancelled) return;
        setVersions(v.data);
        setRuns(r.data);
      })
      .catch(() => {
        if (cancelled) return;
        setVersions([]);
        setRuns([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture]);

  useEffect(() => {
    let cancelled = false;
    setDriftLoaded(false);
    fetchDrift(architecture)
      .then((reports) => {
        if (cancelled) return;
        setDrift(reports);
      })
      .catch(() => {
        if (cancelled) return;
        setDrift([]);
      })
      .finally(() => {
        if (!cancelled) setDriftLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture]);

  const production = versions?.find((v) => v.stage === "Production") ?? null;
  const staging = versions?.filter((v) => v.stage === "Staging") ?? [];
  const recentForChart = (versions ?? []).slice(0, 8).reverse();

  // Real walk-forward evaluation for the Production version specifically
  // -- kept separate from the version-picker-linked `evaluation` state
  // below (which follows whatever the loss-curve dropdown has selected)
  // because several cards' own subtitles promise "the Production
  // version's logged eval" -- they shouldn't silently start describing a
  // different version just because an operator picked one in the
  // loss-curve dropdown further down the page.
  const [productionEvaluation, setProductionEvaluation] = useState<EvaluationSummary | null>(
    null,
  );
  useEffect(() => {
    let cancelled = false;
    if (!production) {
      setProductionEvaluation(null);
      return;
    }
    fetchModelEvaluation(production.version, architecture)
      .then((summary) => {
        if (!cancelled) setProductionEvaluation(summary);
      })
      .catch(() => {
        if (!cancelled) setProductionEvaluation(null);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture, production?.version]);
  const productionCalibratedEvalAll = (productionEvaluation?.regions ?? []).filter(
    (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
  );
  // Real client-side region filter -- "ALL"/"NEM" keeps every region's
  // row, a specific region narrows every downstream real stat on this
  // page to just that one, same real per-region rows either way.
  const productionCalibratedEval =
    region === "NEM"
      ? productionCalibratedEvalAll
      : productionCalibratedEvalAll.filter((r) => r.region === region);
  const productionNaiveMapeByRegion = new Map(
    (productionEvaluation?.regions ?? [])
      .filter((r) => r.candidate === "seasonal_naive")
      .map((r) => [r.region, r.mape]),
  );

  // Loss curve is per-version training history. Defaults to whichever
  // version the rest of this page treats as "the" version (Production,
  // falling back to the newest if nothing's Production yet) -- but a
  // manual pick (the version dropdown below) always wins.
  const defaultLossCurveVersion = production ?? versions?.[0] ?? null;
  const lossCurveVersion = selectedLossCurveVersion
    ? (versions?.find((v) => v.version === selectedLossCurveVersion) ?? defaultLossCurveVersion)
    : defaultLossCurveVersion;
  useEffect(() => {
    let cancelled = false;
    if (!lossCurveVersion) {
      setLossCurve(null);
      setLossCurveLoaded(true);
      return;
    }
    setLossCurveLoaded(false);
    fetchLossCurve(lossCurveVersion.version, architecture)
      .then((curve) => {
        if (cancelled) return;
        setLossCurve(curve);
      })
      .catch(() => {
        if (cancelled) return;
        setLossCurve(null);
      })
      .finally(() => {
        if (!cancelled) setLossCurveLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture, lossCurveVersion?.version]);

  // Real walk-forward backtest (`ecolens-forecast evaluate`) for
  // whichever version the loss-curve picker above is showing.
  const [evaluation, setEvaluation] = useState<EvaluationSummary | null>(null);
  const [evaluationLoaded, setEvaluationLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!lossCurveVersion) {
      setEvaluation(null);
      setEvaluationLoaded(true);
      return;
    }
    setEvaluationLoaded(false);
    fetchModelEvaluation(lossCurveVersion.version, architecture)
      .then((summary) => {
        if (cancelled) return;
        setEvaluation(summary);
      })
      .catch(() => {
        if (cancelled) return;
        setEvaluation(null);
      })
      .finally(() => {
        if (!cancelled) setEvaluationLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture, lossCurveVersion?.version]);

  const evalRegionsAll = evaluation?.regions ?? [];
  const calibratedEvalAll = evalRegionsAll.filter(
    (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
  );
  const calibratedEval =
    region === "NEM" ? calibratedEvalAll : calibratedEvalAll.filter((r) => r.region === region);
  const naiveEval = evalRegionsAll.filter((r) => r.candidate === "seasonal_naive");
  const naiveMapeByRegion = new Map(naiveEval.map((r) => [r.region, r.mape]));

  const walkForwardMape = mean(calibratedEval.map((r) => r.mape));
  const walkForwardBaselineMape = mean(
    calibratedEval.map((r) => naiveMapeByRegion.get(r.region)).filter((v): v is number => v != null),
  );
  const walkForwardCoverage = mean(calibratedEval.map((r) => r.coverage));
  const walkForwardRmse = mean(calibratedEval.map((r) => r.rmse));
  const walkForwardMae = mean(
    calibratedEval.map((r) => r.mae).filter((v): v is number => v != null),
  );
  const walkForwardBias = mean(
    calibratedEval.map((r) => r.mean_error).filter((v): v is number => v != null),
  );
  const walkForwardIntervalWidth = mean(calibratedEval.map((r) => r.interval_width));

  // Real chronological history of every `evaluate` run ever logged for
  // this version.
  const [evalHistory, setEvalHistory] = useState<EvaluationHistory | null>(null);
  const [evalHistoryLoaded, setEvalHistoryLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!lossCurveVersion) {
      setEvalHistory(null);
      setEvalHistoryLoaded(true);
      return;
    }
    setEvalHistoryLoaded(false);
    fetchModelEvaluationHistory(lossCurveVersion.version, architecture)
      .then((h) => {
        if (!cancelled) setEvalHistory(h);
      })
      .catch(() => {
        if (!cancelled) setEvalHistory(null);
      })
      .finally(() => {
        if (!cancelled) setEvalHistoryLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture, lossCurveVersion?.version]);

  const evalHistoryPoints = (evalHistory?.runs ?? [])
    .map((run) => {
      const calibrated = run.regions.filter(
        (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
      );
      return {
        evaluatedAt: run.evaluated_at,
        mape: mean(calibrated.map((r) => r.mape)),
        coverage: mean(calibrated.map((r) => r.coverage)),
      };
    })
    .filter((p): p is { evaluatedAt: string; mape: number; coverage: number | null } => p.mape !== null);

  // Real "Stability" -- variance of this version's own real walk-forward
  // MAPE across every real `evaluate` run logged for it (lower = a more
  // consistent, less noisy real accuracy signal over time). Real,
  // disclosed formula: `100 - min(100, stddev-as-%-of-mean * 4)` --
  // arbitrary scaling constant (4), same "weights are a policy choice,
  // shown not hidden" honesty the Model health score card already uses.
  const mapeHistoryValues = evalHistoryPoints.map((p) => p.mape);
  const mapeHistoryMean = mean(mapeHistoryValues);
  const stabilityHealth =
    mapeHistoryValues.length >= 2 && mapeHistoryMean !== null && mapeHistoryMean > 0
      ? Math.max(
          0,
          100 -
            Math.min(
              100,
              (Math.sqrt(mean(mapeHistoryValues.map((v) => (v - mapeHistoryMean) ** 2)) ?? 0) /
                mapeHistoryMean) *
                100 *
                4,
            ),
        )
      : null;

  const lossCurvePoints = lossCurve?.points ?? [];
  const lossCurveLabels = lossCurvePoints.map((p) => `${p.epoch}`);
  const trainLossSeries = lossCurvePoints.map((p) => p.train_loss ?? 0);
  const valLossSeries = lossCurvePoints.map((p) => p.val_loss ?? 0);
  const hasTrainLoss = lossCurvePoints.some((p) => p.train_loss !== null);
  const hasValLoss = lossCurvePoints.some((p) => p.val_loss !== null);
  const valRmseSeries = lossCurvePoints.map((p) => p.val_rmse ?? 0);
  const valMaeSeries = lossCurvePoints.map((p) => p.val_mae ?? 0);
  const trainLossLatest = hasTrainLoss ? latestWithDelta(trainLossSeries) : null;
  const valLossLatest = hasValLoss ? latestWithDelta(valLossSeries) : null;
  const hasValRmseMae = lossCurvePoints.some(
    (p) => p.val_rmse !== null && p.val_mae !== null,
  );
  const valRmseLatest = hasValRmseMae ? latestWithDelta(valRmseSeries) : null;
  const valMaeLatest = hasValRmseMae ? latestWithDelta(valMaeSeries) : null;

  const productionBaselineMape = mean(
    productionCalibratedEval
      .map((r) => productionNaiveMapeByRegion.get(r.region))
      .filter((v): v is number => v != null),
  );
  const mape =
    (production ? firstMetric(production.metrics, MAPE_KEYS) : null) ??
    mean(productionCalibratedEval.map((r) => r.mape));
  const rmse =
    (production ? firstMetric(production.metrics, RMSE_KEYS) : null) ??
    mean(productionCalibratedEval.map((r) => r.rmse));
  const coverage =
    (production ? firstMetric(production.metrics, COVERAGE_KEYS) : null) ??
    mean(productionCalibratedEval.map((r) => r.coverage));
  const productionWalkForwardMape = mean(productionCalibratedEval.map((r) => r.mape));
  const productionMae = mean(
    productionCalibratedEval.map((r) => r.mae).filter((v): v is number => v != null),
  );
  const productionBias = mean(
    productionCalibratedEval.map((r) => r.mean_error).filter((v): v is number => v != null),
  );
  const productionIntervalWidth = mean(productionCalibratedEval.map((r) => r.interval_width));

  const mapeSeries = recentForChart
    .map((v) => firstMetric(v.metrics, MAPE_KEYS))
    .filter((v): v is number => v !== null);
  const mapeLabels = recentForChart
    .filter((v) => firstMetric(v.metrics, MAPE_KEYS) !== null)
    .map((v) => `v${v.version}`);

  const now = Date.now();
  const last24h = (runs ?? []).filter(
    (r) => now - new Date(r.started_at).getTime() < 24 * 60 * 60 * 1000,
  );
  const lastRun = runs?.[0] ?? null;

  const mapeChangePct =
    mapeSeries.length >= 2 && mapeSeries[mapeSeries.length - 2] !== 0
      ? ((mapeSeries[mapeSeries.length - 1] - mapeSeries[mapeSeries.length - 2]) /
          mapeSeries[mapeSeries.length - 2]) *
        100
      : null;
  const top3Psi = drift ? drift.slice(0, 3).find((r) => r.psi !== null)?.psi ?? null : null;

  // ── NEW: real recent walk-forward re-forecast (region/NEM-scoped),
  // backing Accuracy-by-horizon + the error histogram/Bias-by-window
  // below. `GET /v1/forecast/recent-actual-vs-predicted` -- always
  // reflects the currently-served Production model (not version-
  // selectable, unlike the loss-curve dropdown above), same as the
  // Forecast Explorer page's identical use of this endpoint.
  const [recentBacktest, setRecentBacktest] = useState<RecentBacktest | null>(null);
  const [recentBacktestFailed, setRecentBacktestFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setRecentBacktest(null);
    setRecentBacktestFailed(false);
    fetchRecentBacktest(region, 7)
      .then((r) => {
        if (!cancelled) setRecentBacktest(r);
      })
      .catch(() => {
        if (!cancelled) setRecentBacktestFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [region]);
  const recentPoints = recentBacktest?.points ?? [];
  const horizonAcc = useMemo(() => horizonAccuracy(recentPoints), [recentPoints]);
  const errHist = useMemo(() => errorHistogram(recentPoints), [recentPoints]);

  // ── NEW: real feature-importance from the last completed offline
  // feature-selection pass (`services/ingestion`) -- see this file's own
  // header comment for why this isn't live per-prediction attribution.
  const [featureRuns, setFeatureRuns] = useState<FeatureRebuildRun[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchFeatureRebuildRuns(5)
      .then((r) => {
        if (!cancelled) setFeatureRuns(r.data);
      })
      .catch(() => {
        if (!cancelled) setFeatureRuns([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const latestFeatureRun = (featureRuns ?? []).find((r) => r.status === "success" && r.result?.feature_scores) ?? null;
  const featureScoreRows = latestFeatureRun?.result?.feature_scores
    ? Object.entries(latestFeatureRun.result.feature_scores).sort((a, b) => b[1] - a[1])
    : [];

  // ── NEW: real cross-architecture comparison -- fetches all 3 real
  // architectures' Production versions + evaluations in parallel,
  // independent of the LSTM/TFT/TimesFM toggle above (that toggle picks
  // which architecture the REST of the page drills into; this table
  // always shows all 3 side by side, the way "vs Benchmark" implies).
  type BenchmarkRow = {
    label: string;
    modelName: string;
    version: string | null;
    mape: number | null;
    rmse: number | null;
    mae: number | null;
    bias: number | null;
    coverage: number | null;
    score: number | null;
  };
  const [benchmarkRows, setBenchmarkRows] = useState<BenchmarkRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    setBenchmarkRows(null);
    Promise.all(
      PERFORMANCE_ARCHITECTURES.map(async (arch) => {
        const versionsResp = await fetchModelVersions(arch.modelName).catch(() => ({ data: [] as ModelVersion[] }));
        const prod = versionsResp.data.find((v) => v.stage === "Production") ?? null;
        if (!prod) return { label: arch.label, modelName: arch.modelName, version: null } as BenchmarkRow;
        const evalSummary = await fetchModelEvaluation(prod.version, arch.modelName).catch(() => null);
        const calib = (evalSummary?.regions ?? []).filter(
          (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
        );
        const naiveByRegion = new Map(
          (evalSummary?.regions ?? [])
            .filter((r) => r.candidate === "seasonal_naive")
            .map((r) => [r.region, r.mape]),
        );
        const archMape = mean(calib.map((r) => r.mape));
        const archBaseline = mean(
          calib.map((r) => naiveByRegion.get(r.region)).filter((v): v is number => v != null),
        );
        const archCoverage = mean(calib.map((r) => r.coverage));
        // Real, disclosed 2-component score (same methodology as the
        // Model health score card further down: real inputs, weights
        // shown, reweighted across whichever components are actually
        // available -- just without that card's drift component, since
        // computing 3 architectures' own drift snapshots here too would
        // triple this fetch's real cost for a comparison table that's
        // primarily about accuracy/calibration).
        const errorComponent =
          archBaseline != null && archMape != null && archBaseline > 0
            ? clamp01(archBaseline / archMape)
            : null;
        const coverageComponent =
          archCoverage != null
            ? clamp01(1 - Math.abs(archCoverage * 100 - TARGET_COVERAGE_PCT) / TARGET_COVERAGE_PCT)
            : null;
        const scoreParts = [
          { v: errorComponent, w: 0.7 },
          { v: coverageComponent, w: 0.3 },
        ].filter((p): p is { v: number; w: number } => p.v != null);
        const scoreWeight = scoreParts.reduce((s, p) => s + p.w, 0);
        const score = scoreWeight > 0 ? scoreParts.reduce((s, p) => s + p.v * p.w, 0) / scoreWeight : null;
        return {
          label: arch.label,
          modelName: arch.modelName,
          version: prod.version,
          mape: archMape,
          rmse: mean(calib.map((r) => r.rmse)),
          mae: mean(calib.map((r) => r.mae).filter((v): v is number => v != null)),
          bias: mean(calib.map((r) => r.mean_error).filter((v): v is number => v != null)),
          coverage: archCoverage,
          score,
        } as BenchmarkRow;
      }),
    )
      .then((rows) => {
        if (!cancelled) setBenchmarkRows(rows);
      })
      .catch(() => {
        if (!cancelled) setBenchmarkRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // Real naive baseline row, from whichever architecture's own
  // evaluation happened to log it (all 3 score against the exact same
  // seasonal-naive implementation, `ml/evaluate.py`'s `BaselineForecaster`
  // -- picking the first available real one is not a fabricated row).
  const naiveBenchmarkMape =
    walkForwardBaselineMape ?? mean(calibratedEvalAll.map((r) => naiveMapeByRegion.get(r.region)).filter((v): v is number => v != null));

  const errorHealth =
    productionBaselineMape != null && productionWalkForwardMape != null && productionBaselineMape > 0
      ? Math.min(1, productionBaselineMape / productionWalkForwardMape) * 100
      : null;
  const coverageHealth =
    coverage != null
      ? Math.max(
          0,
          100 -
            (Math.abs(coverage * (coverage <= 1 ? 100 : 1) - TARGET_COVERAGE_PCT) /
              TARGET_COVERAGE_PCT) *
              100,
        )
      : null;
  const driftHealth = top3Psi != null ? Math.max(0, 100 - Math.min(1, top3Psi / 0.5) * 100) : null;
  const healthComponents = [
    { label: "Accuracy", value: errorHealth, weight: 0.4 },
    { label: "Calibration", value: coverageHealth, weight: 0.2 },
    { label: "Drift", value: driftHealth, weight: 0.2 },
    { label: "Stability", value: stabilityHealth, weight: 0.2 },
  ];
  const healthComponentsAvailable = healthComponents.filter(
    (c): c is { label: string; value: number; weight: number } => c.value != null,
  );
  const healthTotalWeight = healthComponentsAvailable.reduce((sum, c) => sum + c.weight, 0);
  const healthScore =
    healthTotalWeight > 0
      ? Math.round(
          healthComponentsAvailable.reduce((sum, c) => sum + c.value * c.weight, 0) / healthTotalWeight,
        )
      : null;

  // ── NEW: real "Recent Alerts & Events" -- built from this page's own
  // already-computed real states (alert-condition triggers, the latest
  // real training run), not the reference mockup's illustrative sample
  // text.
  const coverageTriggered = coverage !== null ? coverage * (coverage <= 1 ? 100 : 1) < 75 : null;
  const mapeTriggered = mapeChangePct !== null ? mapeChangePct > 15 : null;
  const driftTriggered = top3Psi !== null ? top3Psi > 0.5 : null;
  type EventRow = { icon: React.ComponentType<{ className?: string }>; tone: "good" | "warn"; title: string; detail: string; at: string | null };
  const rawEvents: Array<EventRow | null> = [
    lastRun
      ? {
          icon: RefreshCw,
          tone: "good",
          title: "Model retrained",
          detail: `${lastRun.model_name} — ${lastRun.status === "success" ? "completed successfully" : lastRun.status}`,
          at: lastRun.finished_at ?? lastRun.started_at,
        }
      : null,
    coverageTriggered !== null
      ? {
          icon: coverageTriggered ? AlertTriangle : CheckCircle2,
          tone: coverageTriggered ? "warn" : "good",
          title: coverageTriggered ? "Under-coverage detected" : "Coverage within target",
          detail: `Coverage (P10–P90) is ${(coverage! * (coverage! <= 1 ? 100 : 1)).toFixed(1)}%, target ${TARGET_COVERAGE_PCT.toFixed(0)}%.`,
          at: productionEvaluation?.evaluated_at ?? null,
        }
      : null,
    mapeTriggered !== null
      ? {
          icon: mapeTriggered ? AlertTriangle : CheckCircle2,
          tone: mapeTriggered ? "warn" : "good",
          title: mapeTriggered ? "MAPE regression vs last version" : "MAPE stable vs last version",
          detail: `${mapeChangePct! >= 0 ? "+" : ""}${mapeChangePct!.toFixed(1)}% change in logged MAPE.`,
          at: null,
        }
      : null,
    driftTriggered !== null
      ? {
          icon: driftTriggered ? AlertTriangle : CheckCircle2,
          tone: driftTriggered ? "warn" : "good",
          title: driftTriggered ? "Significant drift detected" : "No significant drift detected",
          detail: `Top-3-feature PSI is ${top3Psi!.toFixed(2)}.`,
          at: null,
        }
      : null,
  ];
  const events: EventRow[] = rawEvents.filter((e): e is EventRow => e !== null);

  return (
    <div className="space-y-6">
      {/* ── Breadcrumb + header ─────────────────────────────── */}
      <div className="flex items-center gap-1.5 text-xs text-white/40">
        <Link href="/dashboard/executive" className="hover:text-white/70">Home</Link>
        <ChevronRight className="h-3 w-3" />
        <span>Dashboard</span>
        <ChevronRight className="h-3 w-3" />
        <span className="text-white/60">Performance</span>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Model Performance</h1>
          <p className="mt-1 text-sm text-white/55">
            Evaluate and monitor the real predictive performance of the demand-forecasting model
            across key metrics — every section below is either live data or clearly marked as not.
          </p>
        </div>
      </div>

      {/* ── Filter bar (real Model/Region; Horizon/Target are real,
          fixed facts about this model, not adjustable -- disclosed
          rather than faked as interactive) ────────────────────── */}
      <Card noPadding>
        <div className="flex flex-wrap items-center gap-4 p-4 text-xs">
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">Model</div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Model architecture">
              {PERFORMANCE_ARCHITECTURES.map((arch) => (
                <button
                  key={arch.modelName}
                  type="button"
                  role="tab"
                  aria-selected={architecture === arch.modelName}
                  onClick={() => setArchitecture(arch.modelName)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                    architecture === arch.modelName
                      ? "bg-lime-100 text-black"
                      : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                  )}
                >
                  {arch.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">Region</div>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value as (typeof REGION_FILTER_OPTIONS)[number])}
              className="rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] text-white/80"
            >
              {REGION_FILTER_OPTIONS.map((r) => (
                <option key={r} value={r} className="bg-[#0a1410]">
                  {r === "NEM" ? "NEM (all 5 regions)" : r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">Horizon</div>
            <div className="rounded-md border border-white/5 bg-white/[0.02] px-2.5 py-1 text-white/60" title="This model's real fixed forecast horizon -- not user-adjustable, v0 doesn't resample to an arbitrary requested horizon (same real limitation the Forecast Explorer page discloses).">
              48h (native, fixed)
            </div>
          </div>
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">Target</div>
            <div className="rounded-md border border-white/5 bg-white/[0.02] px-2.5 py-1 text-white/60" title="This platform only ever forecasts demand -- no other real target exists to select.">
              Total Demand (MW)
            </div>
          </div>
          <div className="ml-auto text-right text-[11px] text-white/40">
            {productionEvaluation ? (
              <>
                <div>real eval window ending</div>
                <div className="font-mono text-white/70">
                  {new Date(productionEvaluation.evaluated_at).toLocaleString()}
                </div>
              </>
            ) : (
              <span>No real walk-forward eval logged yet for the Production version.</span>
            )}
          </div>
        </div>
      </Card>

      {/* ── Tabs ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-1 border-b border-white/5 pb-2" role="tablist" aria-label="Performance section">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              tab === t.key
                ? "bg-emerald-200/15 text-emerald-100"
                : "text-white/55 hover:bg-white/5 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ═══════════════════════ OVERVIEW ═══════════════════════ */}
      {tab === "overview" && (
        <div className="space-y-6">
          {/* KPI row */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
            <KpiTile icon={Target} label="Overall Accuracy (wMAPE)" value={walkForwardMape != null ? `${walkForwardMape.toFixed(2)}%` : "—"} sub={walkForwardBaselineMape != null ? `naive baseline: ${walkForwardBaselineMape.toFixed(2)}%` : undefined} />
            <KpiTile icon={Gauge} label="Bias (ME)" value={walkForwardBias != null ? `${walkForwardBias >= 0 ? "+" : ""}${walkForwardBias.toFixed(0)} MW` : "—"} sub={walkForwardBias == null ? "not logged for this eval run yet" : walkForwardBias >= 0 ? "tends to over-forecast" : "tends to under-forecast"} />
            <KpiTile icon={Activity} label="RMSE" value={walkForwardRmse != null ? `${Math.round(walkForwardRmse).toLocaleString()} MW` : "—"} sub={walkForwardMae != null ? `MAE: ${Math.round(walkForwardMae).toLocaleString()} MW` : undefined} />
            <KpiTile icon={Radar} label="Coverage (P10–P90)" value={walkForwardCoverage != null ? `${(walkForwardCoverage * 100).toFixed(1)}%` : "—"} sub={`target ${TARGET_COVERAGE_PCT.toFixed(0)}%`} />
            <KpiTile icon={TrendingUp} label="Prediction Interval Width" value={walkForwardIntervalWidth != null ? `${Math.round(walkForwardIntervalWidth).toLocaleString()} MW` : "—"} sub="mean P90−P10" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Accuracy by horizon */}
            <Card
              title="Accuracy by Horizon"
              subtitle={`Real weighted MAPE (%) across real horizon steps, ${region} — GET /v1/forecast/recent-actual-vs-predicted`}
            >
              {recentBacktest === null ? (
                <p className="py-14 text-center text-xs text-white/40">{recentBacktestFailed ? "Unavailable." : "Loading real backtest…"}</p>
              ) : horizonAcc.every((b) => b.mape === null) ? (
                <p className="py-14 text-center text-xs text-white/40">No real scored steps yet for {region}.</p>
              ) : (
                <BarChart
                  data={horizonAcc.map((b) => b.mape ?? 0)}
                  labels={horizonAcc.map((b) => `${b.h}H`)}
                  height={200}
                  color="rgba(163,230,53,0.85)"
                  formatTooltip={(label, value) => {
                    const b = horizonAcc.find((x) => `${x.h}H` === label);
                    return (
                      <div>
                        <div className="flex items-center gap-2 py-0.5">
                          <span className="text-white/65">MAPE</span>
                          <span className="ml-auto font-mono font-medium text-white">{value.toFixed(2)}%</span>
                        </div>
                        <div className="text-[10px] text-white/35">n={b?.n ?? 0} real scored steps</div>
                      </div>
                    );
                  }}
                />
              )}
            </Card>

            {/* Accuracy by region */}
            <Card
              title="Accuracy by Region"
              subtitle="Real walk-forward MAPE (%), full horizon — this model vs. real seasonal-naive baseline"
            >
              {!evaluationLoaded ? (
                <p className="py-14 text-center text-xs text-white/40">Loading…</p>
              ) : calibratedEvalAll.length === 0 ? (
                <p className="py-14 text-center text-xs text-white/40">No real evaluate run logged yet.</p>
              ) : (
                <div className="space-y-2">
                  {calibratedEvalAll.map((row) => {
                    const baseline = naiveMapeByRegion.get(row.region);
                    const maxVal = Math.max(row.mape, baseline ?? row.mape, 1) * 1.15;
                    return (
                      <div key={row.region} className="flex items-center gap-2 text-xs">
                        <span className="w-12 shrink-0 text-white/60">{row.region}</span>
                        <div className="relative h-4 flex-1 overflow-hidden rounded bg-white/5">
                          <div className="h-full rounded bg-lime-200/80" style={{ width: `${Math.min(100, (row.mape / maxVal) * 100)}%` }} />
                          {baseline != null && (
                            <div
                              className="absolute top-0 h-full w-0.5 bg-white/50"
                              style={{ left: `${Math.min(100, (baseline / maxVal) * 100)}%` }}
                              title={`Benchmark (naive): ${baseline.toFixed(2)}%`}
                            />
                          )}
                        </div>
                        <span className="w-14 shrink-0 text-right font-mono text-white/80">{row.mape.toFixed(2)}%</span>
                      </div>
                    );
                  })}
                  <p className="pt-1 text-[10px] text-white/35">
                    Lime bar = this model&apos;s real MAPE; white tick = the real seasonal-naive baseline for that region.
                  </p>
                </div>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Calibration gauge */}
            <Card title="Forecast Reliability (Calibration)" subtitle="How well the real prediction intervals capture real actual demand">
              {coverage !== null ? (
                <div className="flex flex-col items-center">
                  <ArcGauge
                    value={coverage * (coverage <= 1 ? 100 : 1)}
                    max={100}
                    label={`${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%`}
                    sub="Coverage (P10–P90)"
                    targetValue={TARGET_COVERAGE_PCT}
                    targetLabel={`Target ${TARGET_COVERAGE_PCT.toFixed(0)}%`}
                    color="rgba(56,189,248,0.9)"
                  />
                  {(() => {
                    const deltaPp = coverage * (coverage <= 1 ? 100 : 1) - TARGET_COVERAGE_PCT;
                    return (
                      <p className="mt-1 text-center text-xs">
                        <span className={cn("font-semibold", Math.abs(deltaPp) <= 3 ? "text-emerald-200" : "text-amber-200")}>
                          {deltaPp >= 0 ? "+" : ""}
                          {deltaPp.toFixed(1)}pp
                        </span>{" "}
                        <span className="text-white/40">vs target</span>
                      </p>
                    );
                  })()}
                </div>
              ) : (
                <p className="py-10 text-center text-xs text-white/40">No coverage metric available.</p>
              )}
            </Card>

            {/* Error distribution */}
            <Card
              title="Error Distribution"
              subtitle={`Real histogram of (actual − forecast) / actual, ${region}, last 7 real days`}
              actions={
                errHist.meanPct != null ? (
                  <div className="flex gap-4 text-right text-[11px]">
                    <div>
                      <div className="text-white/40">Mean (ME)</div>
                      <div className="font-mono font-semibold text-white">{errHist.meanPct >= 0 ? "+" : ""}{errHist.meanPct.toFixed(2)}%</div>
                    </div>
                    <div>
                      <div className="text-white/40">Std Dev</div>
                      <div className="font-mono font-semibold text-white">{errHist.stdPct?.toFixed(1) ?? "—"}%</div>
                    </div>
                  </div>
                ) : undefined
              }
            >
              {recentBacktest === null ? (
                <p className="py-14 text-center text-xs text-white/40">{recentBacktestFailed ? "Unavailable." : "Loading…"}</p>
              ) : errHist.buckets.length === 0 ? (
                <p className="py-14 text-center text-xs text-white/40">No real scored points with actual data yet.</p>
              ) : (
                <BarChart
                  data={errHist.buckets.map((b) => b.count)}
                  labels={errHist.buckets.map((b) => `${b.mid >= 0 ? "+" : ""}${b.mid.toFixed(0)}%`)}
                  height={180}
                  color="rgba(163,230,53,0.7)"
                  formatTooltip={(label, value) => (
                    <div className="flex items-center gap-2 py-0.5">
                      <span className="text-white/65">Real points</span>
                      <span className="ml-auto font-mono font-medium text-white">{value}</span>
                    </div>
                  )}
                />
              )}
            </Card>
          </div>

          {/* Model vs Benchmark */}
          <Card title="Model vs Benchmark" subtitle="Real Production evaluation for each real architecture, plus the real seasonal-naive baseline">
            {benchmarkRows === null ? (
              <p className="py-10 text-center text-xs text-white/40">Loading real per-architecture evaluations…</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <thead className="border-b border-white/5 text-[10px] uppercase tracking-wide text-white/40">
                    <tr>
                      <th className="py-2 pr-3">Model</th>
                      <th className="py-2 pr-3">wMAPE ↓</th>
                      <th className="py-2 pr-3">RMSE (MW) ↓</th>
                      <th className="py-2 pr-3">MAE (MW) ↓</th>
                      <th className="py-2 pr-3">Bias (ME) ↓</th>
                      <th className="py-2 pr-3">Coverage (P10–P90) ↑</th>
                      <th className="py-2">Score ↑</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-white/85">
                    {benchmarkRows.map((row) => (
                      <tr key={row.modelName} className={row.modelName === architecture ? "bg-white/[0.03]" : undefined}>
                        <td className="py-2 pr-3">
                          <span className="font-medium">{row.label}</span>
                          {row.version && <span className="ml-1.5 rounded-md border border-white/10 bg-white/5 px-1 py-0.5 text-[9px] text-white/50">v{row.version}</span>}
                          {row.modelName === architecture && <span className="ml-1.5 rounded-md border border-lime-200/30 bg-lime-100/10 px-1 py-0.5 text-[9px] text-lime-100">Selected</span>}
                        </td>
                        <td className="py-2 pr-3 font-mono">{row.mape != null ? `${row.mape.toFixed(2)}%` : "—"}</td>
                        <td className="py-2 pr-3 font-mono">{row.rmse != null ? Math.round(row.rmse).toLocaleString() : "—"}</td>
                        <td className="py-2 pr-3 font-mono">{row.mae != null ? Math.round(row.mae).toLocaleString() : "—"}</td>
                        <td className="py-2 pr-3 font-mono">{row.bias != null ? `${row.bias >= 0 ? "+" : ""}${row.bias.toFixed(0)}%`.replace("%", "") : "—"}</td>
                        <td className="py-2 pr-3 font-mono">{row.coverage != null ? `${(row.coverage * 100).toFixed(1)}%` : "—"}</td>
                        <td className="py-2">
                          {row.score != null ? (
                            <div className="flex items-center gap-2">
                              <span className="font-mono">{row.score.toFixed(2)}</span>
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/5">
                                <div className="h-full rounded-full bg-lime-200" style={{ width: `${row.score * 100}%` }} />
                              </div>
                            </div>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                    {naiveBenchmarkMape != null && (
                      <tr className="text-white/50">
                        <td className="py-2 pr-3">Naive (baseline)</td>
                        <td className="py-2 pr-3 font-mono">{naiveBenchmarkMape.toFixed(2)}%</td>
                        <td className="py-2 pr-3">—</td>
                        <td className="py-2 pr-3">—</td>
                        <td className="py-2 pr-3">—</td>
                        <td className="py-2 pr-3">—</td>
                        <td className="py-2">—</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="mt-3 text-[10px] text-white/35">
                  Score = 70% (real baseline MAPE ÷ this model&apos;s real MAPE, capped at 1) + 30% (real coverage-vs-target closeness) — a disclosed formula over real inputs, reweighted across whichever component is available; not a product-approved ranking.
                </p>
              </div>
            )}
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Performance over time */}
            <Card title="Performance Over Time" subtitle={`Real avg walk-forward MAPE per evaluate run, ${architecture}${lossCurveVersion ? ` v${lossCurveVersion.version}` : ""}`}>
              {!evalHistoryLoaded ? (
                <p className="py-10 text-center text-xs text-white/40">Loading…</p>
              ) : evalHistoryPoints.length < 2 ? (
                <p className="py-10 text-center text-xs text-white/40">
                  {evalHistoryPoints.length === 0 ? "No evaluate runs logged yet." : "Only one evaluate run logged so far — needs 2+ to chart a trend."}
                </p>
              ) : (
                <LineChart
                  series={[
                    { name: "This model", data: evalHistoryPoints.map((p) => p.mape), color: "rgba(163,230,53,0.95)", fill: true },
                    ...(walkForwardBaselineMape != null
                      ? [{ name: "Benchmark (best)", data: evalHistoryPoints.map(() => walkForwardBaselineMape), color: "rgba(255,255,255,0.4)", dashed: true }]
                      : []),
                  ]}
                  labels={evalHistoryPoints.map((p) => new Date(p.evaluatedAt).toLocaleDateString([], { month: "short", day: "2-digit" }))}
                  height={200}
                  formatTooltip={(label, values) => (
                    <div>
                      <div className="mb-1 text-white/50">{label}</div>
                      {values.map((v) => (
                        <div key={v.name} className="flex items-center gap-2 py-0.5">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                          <span className="text-white/65">{v.name}</span>
                          <span className="ml-auto font-mono font-medium text-white">{v.value.toFixed(2)}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                />
              )}
            </Card>

            {/* Model health score */}
            <Card title="Model Health Score" subtitle="Real, computed from this page's own real inputs — formula disclosed below">
              <div className="flex flex-col items-center sm:flex-row sm:items-start sm:justify-around">
                {healthScore != null ? (
                  <ArcGauge
                    value={healthScore}
                    max={100}
                    label={`${healthScore}/100`}
                    sub="Computed score"
                    color={healthScore >= 90 ? "rgba(163,230,53,0.9)" : healthScore >= 70 ? "rgba(250,204,21,0.85)" : "rgba(244,63,94,0.85)"}
                  />
                ) : (
                  <p className="py-10 text-center text-xs text-white/40">Not enough real inputs yet.</p>
                )}
                <div className="mt-3 w-full max-w-[220px] space-y-1.5 text-xs sm:mt-0">
                  {healthComponents.map((c) => (
                    <div key={c.label} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] px-2.5 py-1.5">
                      <span className="text-white/65">{c.label}</span>
                      {c.value == null ? (
                        <span className="text-[10px] text-white/30">no data</span>
                      ) : (
                        <span className={cn("rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase", c.value >= 90 ? "border-lime-200/30 bg-lime-100/10 text-lime-100" : c.value >= 70 ? "border-amber-300/30 bg-amber-300/10 text-amber-200" : "border-rose-400/30 bg-rose-400/10 text-rose-200")}>
                          {c.value >= 90 ? "Good" : c.value >= 70 ? "Moderate" : "Poor"}
                        </span>
                      )}
                    </div>
                  ))}
                  <div className="flex items-center justify-between rounded-md border border-dashed border-white/10 bg-white/[0.01] px-2.5 py-1.5">
                    <span className="text-white/40">Data Quality</span>
                    <IllustrativeBadge label="Not tracked yet" />
                  </div>
                </div>
              </div>
              <p className="mt-3 text-center text-[10px] text-white/40">
                40% accuracy (vs. naive baseline) + 20% calibration (coverage vs. target) + 20% drift (top-3 PSI) + 20% stability (MAPE variance across real evaluate runs) — reweighted across whichever components have a real value.
              </p>
            </Card>
          </div>

          {/* Recent alerts & events */}
          <Card
            title="Recent Alerts & Events"
            subtitle="Built from this page's own real computed states — not sample text"
            actions={
              <button type="button" onClick={() => setTab("logs")} className="flex items-center gap-1 text-xs text-emerald-100 hover:underline">
                View all alerts <ArrowRight className="h-3 w-3" />
              </button>
            }
          >
            {events.length === 0 ? (
              <p className="py-10 text-center text-xs text-white/40">Not enough real data yet to compute any event.</p>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {events.map((ev, i) => (
                  <div key={i} className={cn("rounded-md border p-3", ev.tone === "warn" ? "border-amber-300/25 bg-amber-300/5" : "border-emerald-300/20 bg-emerald-300/5")}>
                    <div className="flex items-center justify-between">
                      <ev.icon className={cn("h-4 w-4", ev.tone === "warn" ? "text-amber-300" : "text-emerald-300")} />
                      {ev.at && <span className="text-[9px] text-white/35">{formatRelativeTime(ev.at)}</span>}
                    </div>
                    <p className="mt-1.5 text-xs font-medium text-white/85">{ev.title}</p>
                    <p className="mt-0.5 text-[10px] text-white/45">{ev.detail}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════ ACCURACY ═══════════════════════ */}
      {tab === "accuracy" && (
        <div className="space-y-6">
          <Card
            title="Walk-forward evaluation"
            subtitle={
              <>
                <span>
                  Real rolling-origin backtest for {architecture}
                  {lossCurveVersion ? ` v${lossCurveVersion.version} (${lossCurveVersion.stage})` : ""}, per region, vs. a seasonal-naive baseline
                </span>
                <br />
                <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/evaluation</span>
              </>
            }
          >
            {!evaluationLoaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : calibratedEval.length === 0 ? (
              <p className="py-10 text-center text-xs text-white/40">
                No <code className="rounded bg-black/20 px-1 py-0.5 font-mono">evaluate</code> run logged yet for v{lossCurveVersion?.version ?? "?"}.
              </p>
            ) : (
              <>
                <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                  <Stat label="Mean MAPE" value={walkForwardMape != null ? `${walkForwardMape.toFixed(2)}%` : "—"} />
                  <Stat label="Naive MAPE" value={walkForwardBaselineMape != null ? `${walkForwardBaselineMape.toFixed(2)}%` : "—"} />
                  <Stat label="Mean RMSE" value={walkForwardRmse != null ? Math.round(walkForwardRmse).toLocaleString() : "—"} />
                  <Stat label="Mean MAE" value={walkForwardMae != null ? Math.round(walkForwardMae).toLocaleString() : "—"} />
                  <Stat label="Mean bias (ME)" value={walkForwardBias != null ? `${walkForwardBias >= 0 ? "+" : ""}${walkForwardBias.toFixed(0)}` : "—"} />
                  <Stat label="Mean coverage" value={walkForwardCoverage != null ? `${(walkForwardCoverage * 100).toFixed(1)}%` : "—"} />
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {calibratedEval.map((row) => {
                    const baselineMape = naiveMapeByRegion.get(row.region);
                    const beatsBaseline = baselineMape != null && row.mape <= baselineMape;
                    const maxVal = Math.max(row.mape, baselineMape ?? row.mape, 1);
                    return (
                      <div key={row.region} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                        <div className="mb-1.5 flex items-center justify-between text-xs">
                          <span className="font-medium text-white/80">{row.region}</span>
                          <span className={cn("rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase", beatsBaseline ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200" : "border-rose-400/30 bg-rose-400/10 text-rose-200")}>
                            {beatsBaseline ? "beats naive" : "below naive"}
                          </span>
                        </div>
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="w-20 shrink-0 text-[10px] text-white/45">This version</span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                              <div className="h-full rounded-full bg-emerald-300" style={{ width: `${Math.min(100, (row.mape / maxVal) * 100)}%` }} />
                            </div>
                            <span className="w-14 shrink-0 text-right font-mono text-[10px] text-white/70">{row.mape.toFixed(2)}%</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="w-20 shrink-0 text-[10px] text-white/45">Naive baseline</span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                              <div className="h-full rounded-full bg-white/25" style={{ width: `${baselineMape != null ? Math.min(100, (baselineMape / maxVal) * 100) : 0}%` }} />
                            </div>
                            <span className="w-14 shrink-0 text-right font-mono text-[10px] text-white/50">{baselineMape != null ? `${baselineMape.toFixed(2)}%` : "—"}</span>
                          </div>
                          <div className="flex items-center justify-between pt-0.5 text-[10px] text-white/35">
                            <span>MAE {row.mae != null ? `${Math.round(row.mae)} MW` : "—"}</span>
                            <span>Bias {row.mean_error != null ? `${row.mean_error >= 0 ? "+" : ""}${row.mean_error.toFixed(0)} MW` : "—"}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-[10px] text-white/35">
                  n_origins={evaluation?.n_origins ?? "—"} rolling origins per region · evaluated{" "}
                  {evaluation?.evaluated_at ? new Date(evaluation.evaluated_at).toLocaleString() : "—"} · run {evaluation?.run_id.slice(0, 8) ?? "—"}
                </p>
              </>
            )}
          </Card>

          <Card title="Accuracy by Horizon (detail)" subtitle={`Real weighted MAPE (%) across every real horizon step, ${region}`}>
            {recentBacktest === null ? (
              <p className="py-14 text-center text-xs text-white/40">{recentBacktestFailed ? "Unavailable." : "Loading…"}</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                {horizonAcc.map((b) => (
                  <div key={b.h} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-white/40">{b.h}H ahead</div>
                    <div className="mt-1 text-lg font-bold text-white">{b.mape != null ? `${b.mape.toFixed(1)}%` : "—"}</div>
                    <div className="text-[9px] text-white/30">n={b.n}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Training vs validation loss"
            subtitle={
              <>
                <span>Real per-epoch train_loss/val_loss for {architecture}{lossCurveVersion ? ` v${lossCurveVersion.version} (${lossCurveVersion.stage})` : ""}</span>
                <br />
                <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/loss-curve</span>
              </>
            }
            actions={
              <div className="flex items-center gap-2">
                {(trainLossLatest || valLossLatest) && (
                  <div className="flex gap-2">
                    <MetricStatBox label="Train Loss" value={trainLossLatest?.value ?? null} deltaPct={trainLossLatest?.deltaPct ?? null} color="rgba(132,204,22,0.95)" />
                    <MetricStatBox label="Val Loss" value={valLossLatest?.value ?? null} deltaPct={valLossLatest?.deltaPct ?? null} color="rgba(56,189,248,0.95)" />
                  </div>
                )}
                {versions && versions.length > 1 && (
                  <select
                    value={lossCurveVersion?.version ?? ""}
                    onChange={(e) => setSelectedLossCurveVersion(e.target.value || null)}
                    className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-white/70 hover:bg-white/10"
                  >
                    {versions.map((v) => (
                      <option key={v.version} value={v.version} className="bg-[#0a1410]">
                        v{v.version} ({v.stage})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            }
          >
            {!lossCurveLoaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : !lossCurveVersion ? (
              <p className="py-10 text-center text-xs text-white/40">No registered version yet.</p>
            ) : !hasTrainLoss ? (
              <p className="py-10 text-center text-xs text-white/40">v{lossCurveVersion.version} has no per-epoch history logged.</p>
            ) : (
              <>
                <LineChart
                  series={[
                    { name: "train_loss", data: trainLossSeries, color: "rgba(132,204,22,0.95)", fill: true },
                    ...(hasValLoss ? [{ name: "val_loss", data: valLossSeries, color: "rgba(56,189,248,0.95)", dashed: true }] : []),
                  ]}
                  labels={lossCurveLabels}
                  height={200}
                  formatTooltip={(label, values) => (
                    <div>
                      <div className="mb-1 text-white/50">Epoch {label}</div>
                      {values.map((v) => (
                        <div key={v.name} className="flex items-center gap-2 py-0.5">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                          <span className="text-white/65">{v.name}</span>
                          <span className="ml-auto font-mono font-medium text-white">{v.value.toFixed(3)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                />
                {!hasValLoss && <p className="mt-2 text-center text-[10px] text-white/35">v{lossCurveVersion.version} has no val_loss logged — showing train_loss only.</p>}
              </>
            )}
          </Card>

          <Card
            title="Validation RMSE & MAE"
            subtitle={
              <>
                <span>Real per-epoch val_rmse/val_mae (MW) for {architecture}{lossCurveVersion ? ` v${lossCurveVersion.version}` : ""}</span>
                <br />
                <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/loss-curve</span>
              </>
            }
            actions={
              (valRmseLatest || valMaeLatest) && (
                <div className="flex gap-2">
                  <MetricStatBox label="RMSE" value={valRmseLatest?.value ?? null} deltaPct={valRmseLatest?.deltaPct ?? null} decimals={2} color="rgba(244,63,94,0.9)" />
                  <MetricStatBox label="MAE" value={valMaeLatest?.value ?? null} deltaPct={valMaeLatest?.deltaPct ?? null} decimals={2} color="rgba(250,204,21,0.9)" />
                </div>
              )
            }
          >
            {!lossCurveLoaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : !hasValRmseMae ? (
              <p className="py-10 text-center text-xs text-white/40">No val_rmse/val_mae logged for this version.</p>
            ) : (
              <LineChart
                series={[
                  { name: "val_rmse", data: valRmseSeries, color: "rgba(244,63,94,0.9)", fill: true },
                  { name: "val_mae", data: valMaeSeries, color: "rgba(250,204,21,0.9)", fill: true },
                ]}
                labels={lossCurveLabels}
                height={200}
                formatTooltip={(label, values) => (
                  <div>
                    <div className="mb-1 text-white/50">Epoch {label}</div>
                    {values.map((v) => (
                      <div key={v.name} className="flex items-center gap-2 py-0.5">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                        <span className="text-white/65">{v.name}</span>
                        <span className="ml-auto font-mono font-medium text-white">{v.value.toFixed(1)} MW</span>
                      </div>
                    ))}
                  </div>
                )}
              />
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════ CALIBRATION ═══════════════════════ */}
      {tab === "calibration" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Forecast Reliability (Calibration)" subtitle="Target from Settings.conformal_alpha (fixed); actual from the Production version's real walk-forward eval">
              {coverage !== null ? (
                <div className="flex flex-col items-center">
                  <ArcGauge
                    value={coverage * (coverage <= 1 ? 100 : 1)}
                    max={100}
                    label={`${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%`}
                    sub="Actual coverage"
                    targetValue={TARGET_COVERAGE_PCT}
                    targetLabel={`Target ${TARGET_COVERAGE_PCT.toFixed(0)}% (P10–P90)`}
                    color="rgba(56,189,248,0.9)"
                  />
                </div>
              ) : (
                <p className="py-10 text-center text-xs text-white/40">No coverage metric available.</p>
              )}
            </Card>
            <Card title="Prediction Interval Width" subtitle="Real mean P90−P10 width, MW — narrower for the same coverage is genuinely more confident">
              <div className="flex h-full flex-col items-center justify-center py-6">
                <div className="text-4xl font-bold text-white">{walkForwardIntervalWidth != null ? Math.round(walkForwardIntervalWidth).toLocaleString() : "—"}</div>
                <div className="mt-1 text-xs text-white/45">MW, mean over scored real origins</div>
              </div>
            </Card>
          </div>

          <Card title="Coverage Over Time" subtitle="Real mean coverage per evaluate run, chronological">
            {!evalHistoryLoaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : evalHistoryPoints.filter((p) => p.coverage != null).length < 2 ? (
              <p className="py-10 text-center text-xs text-white/40">Not enough real evaluate runs with coverage logged yet.</p>
            ) : (
              <LineChart
                series={[
                  { name: "Coverage", data: evalHistoryPoints.map((p) => (p.coverage ?? 0) * 100), color: "rgba(56,189,248,0.95)", fill: true },
                  { name: "Target", data: evalHistoryPoints.map(() => TARGET_COVERAGE_PCT), color: "rgba(255,255,255,0.4)", dashed: true },
                ]}
                labels={evalHistoryPoints.map((p) => new Date(p.evaluatedAt).toLocaleDateString([], { month: "short", day: "2-digit" }))}
                height={200}
                formatTooltip={(label, values) => (
                  <div>
                    <div className="mb-1 text-white/50">{label}</div>
                    {values.map((v) => (
                      <div key={v.name} className="flex items-center gap-2 py-0.5">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.color }} />
                        <span className="text-white/65">{v.name}</span>
                        <span className="ml-auto font-mono font-medium text-white">{v.value.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              />
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════ RESIDUALS ═══════════════════════ */}
      {tab === "residuals" && (
        <div className="space-y-6">
          <Card
            title="Error Distribution"
            subtitle={`Real histogram of (actual − forecast) / actual, ${region}, last 7 real days — GET /v1/forecast/recent-actual-vs-predicted`}
            actions={
              errHist.meanPct != null ? (
                <div className="flex gap-4 text-right text-[11px]">
                  <div>
                    <div className="text-white/40">Mean (ME)</div>
                    <div className="font-mono font-semibold text-white">{errHist.meanPct >= 0 ? "+" : ""}{errHist.meanPct.toFixed(2)}%</div>
                  </div>
                  <div>
                    <div className="text-white/40">Std Dev</div>
                    <div className="font-mono font-semibold text-white">{errHist.stdPct?.toFixed(1) ?? "—"}%</div>
                  </div>
                </div>
              ) : undefined
            }
          >
            {recentBacktest === null ? (
              <p className="py-14 text-center text-xs text-white/40">{recentBacktestFailed ? "Unavailable." : "Loading…"}</p>
            ) : errHist.buckets.length === 0 ? (
              <p className="py-14 text-center text-xs text-white/40">No real scored points yet.</p>
            ) : (
              <BarChart
                data={errHist.buckets.map((b) => b.count)}
                labels={errHist.buckets.map((b) => `${b.mid >= 0 ? "+" : ""}${b.mid.toFixed(0)}%`)}
                height={220}
                color="rgba(163,230,53,0.7)"
              />
            )}
          </Card>

          <Card title="Actual vs Predicted (real scored points)" subtitle={`Every real (actual, predicted) pair behind the histogram above, ${region}, last 7 real days`}>
            {recentBacktest === null ? (
              <p className="py-14 text-center text-xs text-white/40">Loading…</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-[11px]">
                  <thead className="border-b border-white/5 text-[9px] uppercase tracking-wide text-white/40">
                    <tr>
                      <th className="py-1.5 pr-3">Timestamp</th>
                      <th className="py-1.5 pr-3">Step</th>
                      <th className="py-1.5 pr-3">Actual (MW)</th>
                      <th className="py-1.5 pr-3">Predicted P50 (MW)</th>
                      <th className="py-1.5">Error</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-white/75">
                    {recentPoints.slice(-30).reverse().map((p, i) => {
                      const errPct = p.actual !== null && p.actual !== 0 ? ((p.actual - p.p50) / p.actual) * 100 : null;
                      return (
                        <tr key={`${p.ts}-${i}`}>
                          <td className="py-1 pr-3 font-mono">{new Date(p.ts).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
                          <td className="py-1 pr-3">{p.step_hours}h</td>
                          <td className="py-1 pr-3 font-mono">{p.actual != null ? Math.round(p.actual).toLocaleString() : "—"}</td>
                          <td className="py-1 pr-3 font-mono">{Math.round(p.p50).toLocaleString()}</td>
                          <td className={cn("py-1 font-mono", errPct == null ? "text-white/30" : Math.abs(errPct) > 15 ? "text-rose-300" : "text-white/60")}>
                            {errPct != null ? `${errPct >= 0 ? "+" : ""}${errPct.toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="mt-2 text-[10px] text-white/35">Most recent 30 of {recentPoints.length} real scored points.</p>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════ FEATURE IMPACT ═══════════════════════ */}
      {tab === "feature-impact" && (
        <div className="space-y-6">
          <Card
            title="Feature Impact"
            subtitle="Real, offline feature-selection output — mutual information + RandomForest + permutation importance, min-max normalized"
            actions={
              latestFeatureRun && (
                <span className="text-[10px] text-white/40">
                  run {latestFeatureRun.id.slice(0, 8)} · {latestFeatureRun.finished_at ? formatRelativeTime(latestFeatureRun.finished_at) : "—"}
                </span>
              )
            }
          >
            {featureRuns === null ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : !latestFeatureRun ? (
              <p className="py-10 text-center text-xs text-white/40">
                No completed feature-selection run yet. Trigger &quot;Rebuild Features&quot; from Operational Tasks → System Commands.
              </p>
            ) : (
              <>
                <p className="mb-3 rounded-md border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-[11px] text-amber-100/80">
                  This is the last completed <em>offline</em> feature-selection pass, not live per-prediction attribution (no SHAP/live
                  attribution exists anywhere in this platform — a materially larger, separate feature). Real sklearn output, not a
                  placeholder.
                </p>
                <div className="space-y-1.5">
                  {featureScoreRows.slice(0, 25).map(([feature, score]) => {
                    const selected = latestFeatureRun.result?.selected_features?.includes(feature) ?? false;
                    return (
                      <div key={feature} className="flex items-center gap-2 text-xs">
                        <span className={cn("w-48 shrink-0 truncate font-mono", selected ? "text-white/85" : "text-white/45")}>{feature}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                          <div className={cn("h-full rounded-full", selected ? "bg-lime-200/80" : "bg-white/15")} style={{ width: `${Math.min(100, score * 100)}%` }} />
                        </div>
                        <span className="w-12 text-right font-mono text-white/60">{score.toFixed(3)}</span>
                        {selected && <span className="rounded-md border border-lime-200/30 bg-lime-100/10 px-1 py-0.5 text-[8px] uppercase text-lime-100">Selected</span>}
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-[10px] text-white/35">
                  {latestFeatureRun.n_selected ?? latestFeatureRun.result?.selected_features?.length ?? "—"} of {featureScoreRows.length} candidate
                  features selected · target: <code className="font-mono">{latestFeatureRun.result?.target ?? "—"}</code>
                </p>
              </>
            )}
          </Card>
        </div>
      )}

      {/* ═══════════════════════ MODEL DRIFTS ═══════════════════════ */}
      {tab === "drift" && (
        <div className="space-y-6">
          <Card title="Concept drift tracking" subtitle="Real per-feature PSI/KS from GET /v1/model/drift — chronological split of real training data, top 10 features by PSI">
            {!driftLoaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : !drift || drift.length === 0 ? (
              <p className="py-10 text-center text-xs text-white/40">Not enough real data yet to split into reference/comparison windows for {architecture}.</p>
            ) : (
              <>
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">Impact-ranked drift features</div>
                <div className="space-y-1.5">
                  {drift.map((row) => (
                    <div key={row.feature} className="flex items-center gap-2 text-xs">
                      <span className="w-40 truncate text-white/60">{row.feature}</span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                        <div
                          className={cn("h-full rounded-full", row.psi_severity === "major" ? "bg-rose-400/60" : row.psi_severity === "moderate" ? "bg-amber-300/50" : row.psi_severity === "unknown" ? "bg-white/15" : "bg-emerald-300/40")}
                          style={{ width: `${row.psi !== null ? Math.min(100, (row.psi / 0.5) * 100) : 0}%` }}
                        />
                      </div>
                      <span className="w-10 text-right font-mono text-white/50">{row.psi !== null ? row.psi.toFixed(2) : "—"}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-[10px] text-white/35">
                  Not a training-vs-live-serving comparison — compares an older vs. a more recent chronological slice of the same training data.
                </p>
              </>
            )}
          </Card>

          <Card title="Online learning & adaptation" subtitle="Update counts are real (meta._training_log); batch-count/cumulative-drift tracking is illustrative">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Stat label="Updates (last 24h)" value={loaded ? String(last24h.length) : "—"} />
              <Stat label="Last update" value={lastRun ? formatRelativeTime(lastRun.finished_at ?? lastRun.started_at) : "—"} />
              <div className="rounded-md border border-dashed border-amber-300/30 bg-amber-300/5 p-3 text-center">
                <div className="text-[9px] font-semibold uppercase tracking-wider text-amber-200/70">Batches processed</div>
                <div className="mt-1 text-lg font-bold text-white/70">—</div>
                <IllustrativeBadge label="Not tracked yet" />
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ═══════════════════════ LOGS ═══════════════════════ */}
      {tab === "logs" && (
        <div className="space-y-6">
          <Card
            title="MLflow registry"
            subtitle="Real data from GET /v1/model/versions"
            actions={<Link href="/dashboard/models" className="text-xs text-emerald-100 hover:underline">View all runs →</Link>}
          >
            <div className="grid grid-cols-2 gap-2 text-center">
              <Stat label="Registered" value={loaded ? String(versions?.length ?? 0) : "—"} />
              <Stat label="Staging" value={loaded ? String(staging.length) : "—"} />
            </div>
            {production && (
              <div className="mt-3 flex items-center gap-2 rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs">
                <span className="font-mono text-white">v{production.version}</span>
                <span className={cn("rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase", STAGE_COLORS.Production)}>Production</span>
              </div>
            )}
          </Card>

          <Card title="Training run log" subtitle="Real rows from meta._training_log (GET /v1/model/training-runs)">
            {!loaded ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : !runs || runs.length === 0 ? (
              <p className="py-10 text-center text-xs text-white/40">No training runs logged yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-left text-[11px]">
                  <thead className="border-b border-white/5 text-[9px] uppercase tracking-wide text-white/40">
                    <tr>
                      <th className="py-1.5 pr-3">Model</th>
                      <th className="py-1.5 pr-3">Status</th>
                      <th className="py-1.5 pr-3">Started</th>
                      <th className="py-1.5">Triggered by</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-white/75">
                    {runs.slice(0, 20).map((r) => (
                      <tr key={r.id}>
                        <td className="py-1 pr-3 font-mono">{r.model_name}</td>
                        <td className="py-1 pr-3">
                          <span className={cn("rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase", r.status === "success" ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200" : r.status === "failed" ? "border-rose-400/30 bg-rose-400/10 text-rose-200" : "border-amber-300/30 bg-amber-300/10 text-amber-200")}>
                            {r.status}
                          </span>
                        </td>
                        <td className="py-1 pr-3 text-white/50">{formatRelativeTime(r.started_at)}</td>
                        <td className="py-1 text-white/50">{r.triggered_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Feature-selection run log" subtitle="Real rows from meta._feature_selection_log (GET /v1/features/rebuild/runs)">
            {featureRuns === null ? (
              <p className="py-10 text-center text-xs text-white/40">Loading…</p>
            ) : featureRuns.length === 0 ? (
              <p className="py-10 text-center text-xs text-white/40">No feature-selection runs logged yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-left text-[11px]">
                  <thead className="border-b border-white/5 text-[9px] uppercase tracking-wide text-white/40">
                    <tr>
                      <th className="py-1.5 pr-3">Status</th>
                      <th className="py-1.5 pr-3">Started</th>
                      <th className="py-1.5 pr-3">n_selected</th>
                      <th className="py-1.5">Triggered by</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-white/75">
                    {featureRuns.map((r) => (
                      <tr key={r.id}>
                        <td className="py-1 pr-3">
                          <span className={cn("rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase", r.status === "success" ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200" : r.status === "failed" ? "border-rose-400/30 bg-rose-400/10 text-rose-200" : "border-amber-300/30 bg-amber-300/10 text-amber-200")}>
                            {r.status}
                          </span>
                        </td>
                        <td className="py-1 pr-3 text-white/50">{formatRelativeTime(r.started_at)}</td>
                        <td className="py-1 pr-3 font-mono">{r.n_selected ?? "—"}</td>
                        <td className="py-1 text-white/50">{r.triggered_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Actions" subtitle={undefined}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Link href="/dashboard/models" className="flex flex-col items-center gap-1.5 rounded-md border border-lime-200/30 bg-lime-100/10 px-3 py-3 text-center text-xs text-lime-100 hover:bg-lime-100/20">
                <Sliders className="h-4 w-4" /> Trigger fine-tune
                <span className="text-[10px] text-lime-100/60">Opens Model Registry → Fine-tune tab</span>
              </Link>
              <Link href="/dashboard/models" className="flex flex-col items-center gap-1.5 rounded-md border border-sky-400/20 bg-sky-500/10 px-3 py-3 text-center text-xs text-sky-200 hover:bg-sky-500/20">
                <Rocket className="h-4 w-4" /> Trigger full retrain
                <span className="text-[10px] text-sky-200/60">Opens Model Registry → Train tab</span>
              </Link>
              <button type="button" disabled title="Not wired to a real endpoint yet" className="flex flex-col items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-3 text-center text-xs text-white/40 opacity-60 cursor-not-allowed">
                <GitBranch className="h-4 w-4" /> Recalibrate conformal model
              </button>
              <button type="button" disabled title="Not wired to a real endpoint yet" className="flex flex-col items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-3 text-center text-xs text-white/40 opacity-60 cursor-not-allowed">
                <Bell className="h-4 w-4" /> Notify team
              </button>
            </div>
          </Card>

          <Card title="Alert conditions" subtitle="Thresholds are a policy choice, not fetched data — each condition's TRIGGERED/OK state is computed live from real numbers">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { label: "Coverage < 75%", current: coverage !== null ? `${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%` : "—", triggered: coverageTriggered },
                { label: "MAPE increase > 15% vs last version", current: mapeChangePct !== null ? `${mapeChangePct >= 0 ? "+" : ""}${mapeChangePct.toFixed(1)}%` : "— (needs 2+ versions)", triggered: mapeTriggered },
                { label: "PSI (top 3 features) > 0.5", current: top3Psi !== null ? top3Psi.toFixed(2) : "—", triggered: driftTriggered },
                { label: "Error plateau detected", current: "— (no plateau-detection formula defined yet)", triggered: null },
              ].map((cond) => (
                <div key={cond.label} className={cn("rounded-md border p-3", cond.triggered === true ? "border-rose-400/30 bg-rose-400/5" : "border-white/5 bg-white/[0.02]")}>
                  <div className="flex items-center justify-between">
                    <AlertTriangle className={cn("h-3.5 w-3.5", cond.triggered === true ? "text-rose-300" : "text-amber-300/70")} />
                    {cond.triggered !== null && (
                      <span className={cn("rounded-md border px-1.5 py-0.5 text-[8px] font-medium uppercase", cond.triggered ? "border-rose-400/30 bg-rose-400/10 text-rose-200" : "border-emerald-300/30 bg-emerald-300/10 text-emerald-200")}>
                        {cond.triggered ? "Triggered" : "OK"}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[11px] text-white/70">{cond.label}</p>
                  <p className="mt-1 text-[10px] text-white/40">Current: {cond.current}</p>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Tech stack" subtitle={undefined}>
            <div className="flex flex-wrap items-center gap-4 text-xs text-white/60">
              {[
                { icon: Box, label: "MLflow" },
                { icon: Workflow, label: "Prefect" },
                { icon: Activity, label: "Prometheus" },
                { icon: Cpu, label: "Grafana" },
                { icon: Database, label: "PostgreSQL" },
                { icon: FileText, label: "dbt" },
              ].map((t) => (
                <span key={t.label} className="inline-flex items-center gap-1.5">
                  <t.icon className="h-3.5 w-3.5 text-white/40" /> {t.label}
                </span>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.02] p-3">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 text-lg font-bold text-white">{value}</div>
    </div>
  );
}

/** KPI card matching the reference design's top row -- icon chip, label,
 * value, real optional sub-caption (a comparison or a "not logged yet"
 * disclosure, never a fabricated placeholder). */
function KpiTile({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-300/10">
          <Icon className="h-3.5 w-3.5 text-emerald-200" />
        </span>
        <span className="text-[10px] font-medium uppercase tracking-wide text-white/45">{label}</span>
      </div>
      <div className="mt-2 text-xl font-bold text-white">{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-white/40">{sub}</div>}
    </div>
  );
}

/** "<Label> (latest)" stat box with a real per-epoch % change vs the
 * previous epoch -- every metric this backs (loss/RMSE/MAE) is "lower is
 * better", so a decrease is shown green/down and an increase red/up. */
function MetricStatBox({
  label,
  value,
  deltaPct,
  decimals = 4,
  color,
}: {
  label: string;
  value: number | null;
  deltaPct: number | null;
  decimals?: number;
  color: string;
}) {
  const improved = deltaPct !== null && deltaPct < 0;
  const worsened = deltaPct !== null && deltaPct > 0;
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-white/50">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
        {label} (latest)
      </div>
      <div className="mt-0.5 text-base font-bold text-white">{value !== null ? value.toFixed(decimals) : "—"}</div>
      {deltaPct !== null && (
        <div className={cn("mt-0.5 flex items-center gap-0.5 text-[10px] font-medium", improved ? "text-emerald-300" : worsened ? "text-rose-300" : "text-white/40")}>
          {improved ? <ArrowDownRight className="h-3 w-3" /> : worsened ? <ArrowUpRight className="h-3 w-3" /> : null}
          {Math.abs(deltaPct).toFixed(1)}%
        </div>
      )}
    </div>
  );
}
