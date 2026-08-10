/**
 * /dashboard/performance — ML Platform → Performance.
 *
 * Modeled on an ML-monitoring mockup (registry, error metrics, conformal
 * coverage, concept-drift, online-learning, model health, alerts,
 * automated actions, tech stack). Sections are split into real (fetched
 * from `GET /v1/model/versions`, `GET /v1/model/versions/{v}/evaluation`,
 * `GET /v1/model/training-runs`, `GET /v1/model/drift` — same convention
 * as `models/page.tsx`), real-but-computed (a disclosed, simple formula
 * over real inputs — Model health score, Alert conditions' triggered
 * state, Retraining decision guide's active row), and genuinely
 * illustrative (no backend concept exists at all yet — batch-count
 * tracking, historical/cumulative drift persistence, alert paging).
 * Every still-illustrative section keeps `IllustrativeBadge` — this
 * app's convention is no silently fabricated dashboards (see `training/
 * page.tsx` for the precedent this deliberately does NOT follow).
 *
 * 2026-08-10: added `GET /v1/model/versions/{version}/evaluation`
 * (forecast-api's `ml/registry.py`'s `get_latest_evaluation`) -- the
 * real walk-forward backtest (`ecolens-forecast evaluate`) was
 * previously computed but had no API surface at all; this page's old
 * `MAPE_KEYS = ["eval_mape", "test_mape"]` fallback could never actually
 * match `eval_mape` (it only ever existed on a separate MLflow run this
 * page never read), so "Error metrics"/"Conformal coverage" silently
 * fell back to training-time `test_mape`/`test_coverage_*` only -- which
 * can also be legitimately absent (e.g. a small-data config that shrinks
 * `test_frac` toward 0). Real per-region walk-forward numbers now back
 * a new "Walk-forward evaluation" card, the health score, and both
 * cards' fallback.
 */
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Bell, Box, Cpu, Database,
  GitBranch, Info, Radar, RefreshCw, Rocket, Sliders, Target,
  Workflow, Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { BarChart, LineChart } from "@/components/dashboard/charts";
import { ArcGauge } from "@/components/dashboard/gauge";
import { IllustrativeBadge } from "@/components/dashboard/illustrative-badge";
import { cn } from "@/lib/utils";
import {
  fetchDrift,
  fetchLossCurve,
  fetchModelEvaluation,
  fetchModelVersions,
  type DriftReport,
  type EvaluationSummary,
  type LossCurve,
  type ModelVersion,
} from "@/lib/emissions";
import { fetchTrainingRuns, formatRelativeTime, type TrainingRunLog } from "@/lib/ingestion";

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
// TimesFM's `modelName` here (`lstm_demand_timesfm`) is real but not an
// MLflow Model Registry entry -- `ml/evaluate.py`'s own comment on that
// exact constant: "a label for evaluation runs to tag themselves with,
// not an MLflow Model Registry entry." TimesFM is zero-shot (Google's
// pretrained checkpoint, evaluated via `cli.py evaluate-timesfm`) and has
// no versions of our own to register -- so every registry/error-metric/
// coverage/loss-curve card on this page will honestly show its existing
// real empty state ("No Production version yet", etc.) for this tab, not
// fabricated data. That's expected, not a bug.
const PERFORMANCE_ARCHITECTURES = [
  { modelName: "lstm_demand", label: "LSTM" },
  { modelName: "lstm_demand_tft", label: "TFT" },
  { modelName: "lstm_demand_timesfm", label: "TimesFM" },
] as const;

// Candidate metric keys, in priority order -- training runs log different
// keys depending on whether a live-evaluation gate ran (`eval_*`) or only
// the training-time test split did (`test_*`). No key is guaranteed.
const MAPE_KEYS = ["eval_mape", "test_mape"];
// `train.py`'s `train_and_register` only ever logs `test_mape`/
// `test_coverage_*` at training time -- RMSE is exclusively an
// `evaluate.py` walk-forward metric (`eval_rmse`), never a `test_*` key
// (verified 2026-08-05 -- no `test_rmse` is logged anywhere in this
// codebase). A version that's only ever been trained, not yet
// live-evaluated, honestly shows "--" here rather than a fabricated
// fallback key that would never actually be present.
const RMSE_KEYS = ["eval_rmse"];
const COVERAGE_KEYS = ["eval_coverage", "test_coverage_calibrated", "test_coverage_raw"];

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

export default function PerformancePage() {
  const [architecture, setArchitecture] = useState<string>(
    PERFORMANCE_ARCHITECTURES[0].modelName,
  );
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
  // because the "Error metrics"/"Conformal coverage" cards' own
  // subtitles promise "the Production version's logged eval" -- they
  // shouldn't silently start describing a different version just
  // because an operator picked one in the loss-curve dropdown further
  // down the page.
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
  const productionCalibratedEval = (productionEvaluation?.regions ?? []).filter(
    (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
  );
  const productionNaiveMapeByRegion = new Map(
    (productionEvaluation?.regions ?? [])
      .filter((r) => r.candidate === "seasonal_naive")
      .map((r) => [r.region, r.mape]),
  );

  // Loss curve is per-version training history. Defaults to whichever
  // version the rest of this page treats as "the" version (Production,
  // falling back to the newest if nothing's Production yet) -- but a
  // manual pick (the version dropdown below) always wins, since the
  // whole point of a picker is letting an operator look at a specific
  // run's training curve regardless of its registry stage (e.g. a
  // freshly-trained challenger that hasn't been promoted).
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
  // whichever version the loss-curve picker above is showing -- the
  // honest, harder rolling-origin MAPE against a real seasonal-naive
  // baseline, per region. `null` is a real, expected state (no
  // `evaluate` run has ever been logged for this version), not a
  // loading/error placeholder -- `evaluationLoaded` distinguishes that
  // from "still fetching".
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

  // Splits the flat per-`(region, candidate)` rows into the three real
  // candidates `evaluate_and_log` always scores together: the version's
  // own calibrated quantiles, its uncalibrated raw quantiles (`_raw`),
  // and the seasonal-naive baseline (`ml/evaluate.py`'s own fixed
  // `"seasonal_naive"` name) -- not string-matched against the model
  // name/version (which would break if a candidate name format ever
  // changes), just against the two fixed markers that are actually
  // stable across every real evaluation run.
  const evalRegions = evaluation?.regions ?? [];
  const calibratedEval = evalRegions.filter(
    (r) => r.candidate !== "seasonal_naive" && !r.candidate.endsWith("_raw"),
  );
  const naiveEval = evalRegions.filter((r) => r.candidate === "seasonal_naive");
  const naiveMapeByRegion = new Map(naiveEval.map((r) => [r.region, r.mape]));

  // Real, simple, unweighted mean across regions -- every region counts
  // equally regardless of its own demand volume, same convention the
  // dashboard's other cross-region aggregates (e.g. `/dashboard/
  // forecast`'s NEM tab) already use.
  const walkForwardMape = mean(calibratedEval.map((r) => r.mape));
  const walkForwardBaselineMape = mean(
    calibratedEval.map((r) => naiveMapeByRegion.get(r.region)).filter((v): v is number => v != null),
  );
  const walkForwardCoverage = mean(calibratedEval.map((r) => r.coverage));

  const lossCurvePoints = lossCurve?.points ?? [];
  const lossCurveLabels = lossCurvePoints.map((p) => `${p.epoch}`);
  const trainLossSeries = lossCurvePoints.map((p) => p.train_loss ?? 0);
  const valLossSeries = lossCurvePoints.map((p) => p.val_loss ?? 0);
  const hasTrainLoss = lossCurvePoints.some((p) => p.train_loss !== null);
  // `val_loss` was only added 2026-08-05 -- a version registered before
  // that (or a warm-started incremental run that skipped it) has real
  // train_loss but no val_loss at all. Checked separately so the chart
  // can honestly fall back to a train-loss-only line instead of
  // plotting a fabricated flat-zero "validation" series.
  const hasValLoss = lossCurvePoints.some((p) => p.val_loss !== null);
  // `val_rmse`/`val_mae` (2026-08-05, "Validation RMSE & MAE" chart) --
  // real MW-unit error metrics, same per-epoch/per-version-age caveat
  // as val_loss above (only present for versions trained after this
  // field existed).
  const valRmseSeries = lossCurvePoints.map((p) => p.val_rmse ?? 0);
  const valMaeSeries = lossCurvePoints.map((p) => p.val_mae ?? 0);
  const trainLossLatest = hasTrainLoss ? latestWithDelta(trainLossSeries) : null;
  const valLossLatest = hasValLoss ? latestWithDelta(valLossSeries) : null;
  const hasValRmseMae = lossCurvePoints.some(
    (p) => p.val_rmse !== null && p.val_mae !== null,
  );
  const valRmseLatest = hasValRmseMae ? latestWithDelta(valRmseSeries) : null;
  const valMaeLatest = hasValRmseMae ? latestWithDelta(valMaeSeries) : null;

  // Training-time metrics first (cheaper, already on `production.
  // metrics`), falling back to the real walk-forward mean when absent --
  // `test_mape`/`test_coverage_*` are only logged when the training run
  // actually had a non-empty `test` split (`ml/train.py`'s own comment:
  // `test`/`test_mape` are optional, `val`/`cal` are what's required),
  // which isn't guaranteed (e.g. a small-data region config that
  // deliberately shrinks `test_frac` toward 0 to give `val`/`cal` more
  // room -- a real, current example, not a hypothetical). `eval_mape` in
  // the old `MAPE_KEYS` list could never match anything here (that key
  // only ever exists on the SEPARATE evaluation run `productionEvaluation`
  // now reads) -- kept in `MAPE_KEYS` only because `mapeSeries` below
  // still uses it against `production.metrics` for the same reason.
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
  // Real walk-forward MAPE specifically (not the training-time-first
  // `mape` above) -- the "is this actually beating naive" question only
  // the harder, honest backtest can answer; training-time `test_mape` is
  // an easier, in-distribution split that can look fine while still
  // losing to naive on fresh out-of-sample data (this model family's
  // own real, measured history -- see `TODO.md`).
  const productionWalkForwardMape = mean(productionCalibratedEval.map((r) => r.mape));

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

  // Real % change between the two most recent versions' MAPE (mapeSeries
  // is already chronological, real, per-version data fetched above) --
  // matches what the "MAPE increase > 15% vs last version" alert
  // condition actually asks, unlike just echoing the raw Production MAPE.
  const mapeChangePct =
    mapeSeries.length >= 2 && mapeSeries[mapeSeries.length - 2] !== 0
      ? ((mapeSeries[mapeSeries.length - 1] - mapeSeries[mapeSeries.length - 2]) /
          mapeSeries[mapeSeries.length - 2]) *
        100
      : null;
  // Real max PSI among the top 3 drift-ranked features -- `drift` is
  // already sorted descending by PSI (live_drift.py), so this is just
  // the top feature's PSI, not a new computation invented for this card.
  const top3Psi = drift ? drift.slice(0, 3).find((r) => r.psi !== null)?.psi ?? null : null;

  // Real, transparent health score -- NOT a fabricated placeholder.
  // Built entirely from real inputs already fetched on this page
  // (walk-forward MAPE-vs-baseline, conformal coverage-vs-target, top
  // drift PSI), each mapped to a 0-100 "how healthy is this dimension"
  // score, then averaged with the weights below. A component is left
  // out of the average (not zeroed) when its real input isn't available
  // yet, so a version simply missing a walk-forward eval doesn't get
  // punished as if it scored 0 on that dimension. Disclosed here and in
  // the card's subtitle -- deliberately simple and real rather than
  // "looking more authoritative than it is" (this page's own prior
  // stance on this exact card, which this replaces): weights and
  // formula are visible, not a black box.
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
    { value: errorHealth, weight: 0.5 },
    { value: coverageHealth, weight: 0.25 },
    { value: driftHealth, weight: 0.25 },
  ].filter((c): c is { value: number; weight: number } => c.value != null);
  const healthTotalWeight = healthComponents.reduce((sum, c) => sum + c.weight, 0);
  const healthScore =
    healthTotalWeight > 0
      ? Math.round(
          healthComponents.reduce((sum, c) => sum + c.value * c.weight, 0) / healthTotalWeight,
        )
      : null;

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold text-white">Model performance</h1>
        <p className="mt-1 text-sm text-white/55">
          End-to-end monitoring of the demand-forecast model — registry,
          error metrics, and calibration are live; sections without a real
          backend signal yet are clearly marked.
        </p>
      </div>

      {/* ── Data flow strip (real, static) ─────────────────── */}
      <Card noPadding>
        <div className="flex flex-wrap items-center justify-center gap-2 overflow-x-auto p-4 text-xs">
          {[
            { icon: Database, label: "Ingestion" },
            { icon: Activity, label: "Forecast model" },
            { icon: Target, label: "P10 / P50 / P90" },
            { icon: Box, label: "MLflow registry" },
            { icon: Bell, label: "Serving & alerts" },
          ].map((step, i, arr) => (
            <div key={step.label} className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-white/70">
                <step.icon className="h-3.5 w-3.5 text-emerald-200" />
                {step.label}
              </div>
              {i < arr.length - 1 && <span className="text-white/20">→</span>}
            </div>
          ))}
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Model architecture">
        {PERFORMANCE_ARCHITECTURES.map((arch) => (
          <button
            key={arch.modelName}
            type="button"
            role="tab"
            aria-selected={architecture === arch.modelName}
            onClick={() => setArchitecture(arch.modelName)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              architecture === arch.modelName
                ? "bg-lime-100 text-black"
                : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
            )}
          >
            {arch.label}
          </button>
        ))}
      </div>

      {/* ── Registry + error metrics + conformal ───────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-1"
          title={
            <span className="flex items-center gap-2">
              <Box className="h-4 w-4 text-emerald-200" /> MLflow registry
            </span>
          }
          subtitle="Real data from GET /v1/model/versions"
        >
          <div className="grid grid-cols-2 gap-2 text-center">
            <Stat label="Registered" value={loaded ? String(versions?.length ?? 0) : "—"} />
            <Stat label="Staging" value={loaded ? String(staging.length) : "—"} />
          </div>
          <div className="mt-3 rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Production
            </div>
            {production ? (
              <div className="mt-1 flex items-center gap-2">
                <span className="font-mono text-sm text-white">v{production.version}</span>
                <span className={cn(
                  "rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase",
                  STAGE_COLORS.Production,
                )}>
                  Production
                </span>
              </div>
            ) : (
              <p className="mt-1 text-white/45">
                {loaded ? "No Production version yet." : "Loading…"}
              </p>
            )}
          </div>
          <Link
            href="/dashboard/models"
            className="mt-3 block text-center text-xs text-emerald-100 hover:underline"
          >
            View all runs →
          </Link>
        </Card>

        <Card
          className="lg:col-span-1"
          title={
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-200" /> Error metrics
            </span>
          }
          subtitle="Training-time test split when logged, else the real walk-forward mean (see the Walk-forward card below) — per-version, not a rolling window"
        >
          <div className="grid grid-cols-2 gap-2 text-center">
            <Stat label="MAPE (Production)" value={mape !== null ? `${mape.toFixed(2)}%` : "—"} />
            <Stat label="RMSE (Production)" value={rmse !== null ? rmse.toFixed(2) : "—"} />
          </div>
          <div className="mt-3">
            {mapeSeries.length >= 2 ? (
              <BarChart data={mapeSeries} labels={mapeLabels} height={140} />
            ) : (
              <p className="py-6 text-center text-xs text-white/40">
                Not enough versions with a logged MAPE to chart yet.
              </p>
            )}
          </div>
        </Card>

        <Card
          className="lg:col-span-1"
          title={
            <span className="flex items-center gap-2">
              <Target className="h-4 w-4 text-emerald-200" /> Conformal coverage
            </span>
          }
          subtitle="Target from Settings.conformal_alpha (fixed); actual from the Production version's training-time split, or its real walk-forward eval when that's absent"
        >
          {coverage !== null ? (
            <ArcGauge
              value={coverage * (coverage <= 1 ? 100 : 1)}
              max={100}
              label={`${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%`}
              sub="Actual coverage"
              targetValue={TARGET_COVERAGE_PCT}
              targetLabel={`Target ${TARGET_COVERAGE_PCT.toFixed(0)}% (P10–P90)`}
              color="rgba(56,189,248,0.9)"
            />
          ) : (
            <p className="py-10 text-center text-xs text-white/40">
              No coverage metric logged or walk-forward-evaluated for the Production version yet.
            </p>
          )}
        </Card>
      </div>

      {/* ── Walk-forward evaluation (real) ──────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <TitleIcon icon={Target} /> Walk-forward evaluation
          </span>
        }
        subtitle={
          <>
            <span>
              Real rolling-origin backtest for {architecture}
              {lossCurveVersion ? ` v${lossCurveVersion.version} (${lossCurveVersion.stage})` : ""},
              per region, vs. a seasonal-naive baseline — the honest, harder number
              training-time <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-lime-100">test_mape</code>{" "}
              doesn&apos;t capture
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
            No <code className="rounded bg-black/20 px-1 py-0.5 font-mono">evaluate</code> run
            logged yet for v{lossCurveVersion?.version ?? "?"} — run{" "}
            <code className="rounded bg-black/20 px-1 py-0.5 font-mono">
              ecolens-forecast evaluate --version {lossCurveVersion?.version ?? "?"}
            </code>{" "}
            to populate this.
          </p>
        ) : (
          <>
            {(walkForwardMape != null || walkForwardCoverage != null) && (
              <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                <Stat
                  label="Mean MAPE (this version)"
                  value={walkForwardMape != null ? `${walkForwardMape.toFixed(2)}%` : "—"}
                />
                <Stat
                  label="Mean MAPE (naive baseline)"
                  value={walkForwardBaselineMape != null ? `${walkForwardBaselineMape.toFixed(2)}%` : "—"}
                />
                <Stat
                  label="Mean coverage"
                  value={walkForwardCoverage != null ? `${(walkForwardCoverage * 100).toFixed(1)}%` : "—"}
                />
              </div>
            )}
            <div className="space-y-1.5">
              {calibratedEval.map((row) => {
                const baselineMape = naiveMapeByRegion.get(row.region);
                const beatsBaseline = baselineMape != null && row.mape <= baselineMape;
                return (
                  <div
                    key={row.region}
                    className="flex items-center gap-2 rounded-md border border-white/5 bg-white/[0.02] px-2 py-1.5 text-xs"
                  >
                    <span className="w-14 shrink-0 text-white/70">{row.region}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                      <div
                        className={cn("h-full rounded-full", beatsBaseline ? "bg-emerald-300/50" : "bg-rose-400/50")}
                        style={{ width: `${Math.min(100, (row.mape / Math.max(row.mape, baselineMape ?? row.mape, 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="w-16 shrink-0 text-right font-mono text-white/60">
                      {row.mape.toFixed(2)}%
                    </span>
                    <span className="w-24 shrink-0 text-right text-[10px] text-white/35">
                      naive {baselineMape != null ? `${baselineMape.toFixed(2)}%` : "—"}
                    </span>
                    <span
                      className={cn(
                        "w-20 shrink-0 rounded-md border px-1.5 py-0.5 text-center text-[9px] font-medium uppercase",
                        beatsBaseline
                          ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-200"
                          : "border-rose-400/30 bg-rose-400/10 text-rose-200",
                      )}
                    >
                      {beatsBaseline ? "beats naive" : "below naive"}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-[10px] text-white/35">
              n_origins={evaluation?.n_origins ?? "—"} rolling origins per region · evaluated{" "}
              {evaluation?.evaluated_at ? new Date(evaluation.evaluated_at).toLocaleString() : "—"} ·
              run {evaluation?.run_id.slice(0, 8) ?? "—"}
            </p>
          </>
        )}
      </Card>

      {/* ── Training vs validation loss (real) ──────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <TitleIcon icon={Activity} /> Training vs validation loss
          </span>
        }
        subtitle={
          <>
            <span>
              Real per-epoch train_loss/val_loss for {architecture}
              {lossCurveVersion ? ` v${lossCurveVersion.version} (${lossCurveVersion.stage})` : ""}
            </span>
            <br />
            <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/loss-curve</span>
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            {(trainLossLatest || valLossLatest) && (
              <div className="flex gap-2">
                <MetricStatBox
                  label="Train Loss"
                  value={trainLossLatest?.value ?? null}
                  deltaPct={trainLossLatest?.deltaPct ?? null}
                  color="rgba(132,204,22,0.95)"
                />
                <MetricStatBox
                  label="Val Loss"
                  value={valLossLatest?.value ?? null}
                  deltaPct={valLossLatest?.deltaPct ?? null}
                  color="rgba(56,189,248,0.95)"
                />
              </div>
            )}
            {/* Version deletion lives on the Model Registry page only
                (/dashboard/models) -- this page is a read-only training
                diagnostic view, not where destructive registry actions
                belong. */}
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
          <p className="py-10 text-center text-xs text-white/40">
            No registered version yet -- train one from Model Registry to see its loss curve here.
          </p>
        ) : !hasTrainLoss ? (
          <p className="py-10 text-center text-xs text-white/40">
            v{lossCurveVersion.version} has no per-epoch history logged (trained before
            step-metric logging existed, or a warm-started incremental run that only
            logs a final metric).
          </p>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between text-[10px] text-white/40">
              <span>Loss</span>
              <span>Epoch</span>
            </div>
            <LineChart
              series={[
                {
                  name: "train_loss",
                  data: trainLossSeries,
                  color: "rgba(132,204,22,0.95)",
                  fill: true,
                },
                ...(hasValLoss
                  ? [
                      {
                        name: "val_loss",
                        data: valLossSeries,
                        color: "rgba(56,189,248,0.95)",
                        dashed: true,
                      },
                    ]
                  : []),
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
                      <span className="ml-auto font-mono font-medium text-white">
                        {v.value.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            />
            <div className="mt-3 flex items-center justify-center gap-4 text-[11px] text-white/60">
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-3 rounded-full bg-lime-100" /> Train Loss
              </span>
              {hasValLoss && (
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-0.5 w-4 border-t-2 border-dashed" style={{ borderColor: "rgba(56,189,248,0.95)" }} /> Validation Loss
                </span>
              )}
            </div>
            {!hasValLoss && (
              <p className="mt-2 text-center text-[10px] text-white/35">
                v{lossCurveVersion.version} has no val_loss logged (trained before
                2026-08-05, when per-epoch validation loss was added) -- showing
                train_loss only, not a fabricated validation line.
              </p>
            )}
          </>
        )}
      </Card>

      {/* ── Validation RMSE & MAE (real) ────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <TitleIcon icon={Target} /> Validation RMSE & MAE
          </span>
        }
        subtitle={
          <>
            <span>
              Real per-epoch val_rmse/val_mae (MW) for {architecture}
              {lossCurveVersion ? ` v${lossCurveVersion.version} (${lossCurveVersion.stage})` : ""}
            </span>
            <br />
            <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/loss-curve</span>
          </>
        }
        actions={
          (valRmseLatest || valMaeLatest) && (
            <div className="flex gap-2">
              <MetricStatBox
                label="RMSE"
                value={valRmseLatest?.value ?? null}
                deltaPct={valRmseLatest?.deltaPct ?? null}
                decimals={2}
                color="rgba(244,63,94,0.9)"
              />
              <MetricStatBox
                label="MAE"
                value={valMaeLatest?.value ?? null}
                deltaPct={valMaeLatest?.deltaPct ?? null}
                decimals={2}
                color="rgba(250,204,21,0.9)"
              />
            </div>
          )
        }
      >
        {!lossCurveLoaded ? (
          <p className="py-10 text-center text-xs text-white/40">Loading…</p>
        ) : !lossCurveVersion ? (
          <p className="py-10 text-center text-xs text-white/40">
            No registered version yet -- train one from Model Registry to see this chart here.
          </p>
        ) : !hasValRmseMae ? (
          <p className="py-10 text-center text-xs text-white/40">
            v{lossCurveVersion.version} has no val_rmse/val_mae logged (trained before
            2026-08-05, when these per-epoch error metrics were added).
          </p>
        ) : (
          <>
            <div className="mb-1 flex items-center justify-between text-[10px] text-white/40">
              <span>MW</span>
              <span>Epoch</span>
            </div>
            <LineChart
              series={[
                {
                  name: "val_rmse",
                  data: valRmseSeries,
                  color: "rgba(244,63,94,0.9)",
                  fill: true,
                },
                {
                  name: "val_mae",
                  data: valMaeSeries,
                  color: "rgba(250,204,21,0.9)",
                  fill: true,
                },
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
                      <span className="ml-auto font-mono font-medium text-white">
                        {v.value.toFixed(1)} MW
                      </span>
                    </div>
                  ))}
                </div>
              )}
            />
            <div className="mt-3 flex items-center justify-between text-[11px] text-white/60">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-3 rounded-full" style={{ background: "rgba(244,63,94,0.9)" }} /> RMSE (MW)
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-3 rounded-full" style={{ background: "rgba(250,204,21,0.9)" }} /> MAE (MW)
                </span>
              </div>
              <span className="flex items-center gap-1 text-white/35" title="Lower RMSE/MAE means smaller real forecast error">
                Lower is better <Info className="h-3 w-3" />
              </span>
            </div>
          </>
        )}
      </Card>

      {/* ── Online learning (mixed real/illustrative) ──────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4 text-emerald-200" /> Online learning & adaptation
          </span>
        }
        subtitle="Update counts are real (meta._training_log); drift/returns tracking below is illustrative"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Stat label="Updates (last 24h)" value={loaded ? String(last24h.length) : "—"} />
          <Stat
            label="Last update"
            value={lastRun ? formatRelativeTime(lastRun.finished_at ?? lastRun.started_at) : "—"}
          />
          <div className="rounded-md border border-dashed border-amber-300/30 bg-amber-300/5 p-3 text-center">
            <div className="text-[9px] font-semibold uppercase tracking-wider text-amber-200/70">
              Batches processed
            </div>
            <div className="mt-1 text-lg font-bold text-white/70">—</div>
            <IllustrativeBadge label="Not tracked yet" />
          </div>
        </div>
        <div className="mt-4 rounded-lg border border-white/5 bg-white/[0.01] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-white/70">Current drift snapshot</span>
            {top3Psi != null && (
              <span
                className={cn(
                  "rounded-md border px-1.5 py-0.5 text-[9px] font-medium uppercase",
                  top3Psi > 0.5
                    ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                    : top3Psi > 0.25
                      ? "border-amber-300/30 bg-amber-300/10 text-amber-200"
                      : "border-emerald-300/30 bg-emerald-300/10 text-emerald-200",
                )}
              >
                top PSI {top3Psi.toFixed(2)}
              </span>
            )}
          </div>
          <p className="text-xs text-white/45">
            {top3Psi != null
              ? `Real, current top-3-feature PSI from GET /v1/model/drift (reference vs. comparison chronological split of ${architecture}'s own training data) — same number the Concept drift tracking card and Alert conditions below use.`
              : "No real drift snapshot available yet for this architecture (needs 200+ rows on each side of the split)."}
          </p>
          <p className="mt-2 text-[10px] text-amber-200/60">
            Still illustrative: a real trend *since the last full retrain* (cumulative drift over
            time, whether online updates are still improving accuracy) needs historical drift
            snapshots persisted somewhere — this only ever computes the CURRENT snapshot on
            demand, nothing is stored between page loads yet. See TODO.md.
          </p>
        </div>
      </Card>

      {/* ── Concept drift (real) ─────────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Radar className="h-4 w-4 text-emerald-200" /> Concept drift tracking
          </span>
        }
        subtitle="Real per-feature PSI/KS from GET /v1/model/drift — chronological split of real training data, top 10 features by PSI"
      >
        {!driftLoaded ? (
          <p className="py-10 text-center text-xs text-white/40">Loading…</p>
        ) : !drift || drift.length === 0 ? (
          <p className="py-10 text-center text-xs text-white/40">
            Not enough real data yet to split into reference/comparison windows
            for {architecture} (needs 200+ rows on each side).
          </p>
        ) : (
          <>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Impact-ranked drift features (reference vs. comparison window)
            </div>
            <div className="space-y-1.5">
              {drift.map((row) => (
                <div key={row.feature} className="flex items-center gap-2 text-xs">
                  <span className="w-40 truncate text-white/60">{row.feature}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        row.psi_severity === "major"
                          ? "bg-rose-400/60"
                          : row.psi_severity === "moderate"
                            ? "bg-amber-300/50"
                            : row.psi_severity === "unknown"
                              ? "bg-white/15"
                              : "bg-emerald-300/40",
                      )}
                      style={{
                        width: `${row.psi !== null ? Math.min(100, (row.psi / 0.5) * 100) : 0}%`,
                      }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono text-white/50">
                    {row.psi !== null ? row.psi.toFixed(2) : "—"}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[10px] text-white/35">
              Not a training-vs-live-serving comparison — there's no live
              serving feature snapshot logged yet. This compares an older vs.
              a more recent chronological slice of the same training data, so
              a calendar/seasonal feature can read as high-PSI purely because
              the two windows don't each span a full year, not because
              anything is actually wrong.
            </p>
          </>
        )}
      </Card>

      {/* ── Model health score (real, disclosed formula) ────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          title={
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-200" /> Model health score
            </span>
          }
          subtitle="Real, computed from this page's own real inputs -- not product-approved policy, just a disclosed formula (weights shown below), for the Production version"
        >
          <div className="flex justify-center">
            {healthScore != null ? (
              <ArcGauge
                value={healthScore}
                max={100}
                label={`${healthScore}/100`}
                sub="Computed score"
                color={
                  healthScore >= 90
                    ? "rgba(163,230,53,0.9)"
                    : healthScore >= 70
                      ? "rgba(250,204,21,0.85)"
                      : "rgba(244,63,94,0.85)"
                }
              />
            ) : (
              <p className="py-10 text-center text-xs text-white/40">
                Not enough real inputs yet (needs at least one of: a walk-forward eval, a logged
                coverage metric, or a drift snapshot for the Production version).
              </p>
            )}
          </div>
          <p className="mt-2 text-center text-[10px] text-white/40">
            50% error-vs-naive-baseline (walk-forward) + 25% coverage-vs-{TARGET_COVERAGE_PCT.toFixed(0)}%-target
            + 25% top-3-feature drift (PSI-vs-0.5) — reweighted across whichever components have
            a real value; none are fabricated when missing.
          </p>
        </Card>

        <Card
          title="Retraining decision guide"
          subtitle="Thresholds are a policy choice (not fetched data) — the highlighted row reflects the real score above"
        >
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-white/40">
                <th className="pb-2 font-medium">Health score</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="text-white/70">
              {[
                { range: "90 – 100", label: "Stable", action: "No action needed", active: healthScore != null && healthScore >= 90, tone: "text-lime-100" },
                { range: "70 – 89", label: "Monitor", action: "Continue online learning", active: healthScore != null && healthScore >= 70 && healthScore < 90, tone: "text-amber-200" },
                { range: "< 70", label: "Critical", action: "Full retrain", active: healthScore != null && healthScore < 70, tone: "text-rose-300" },
              ].map((row) => (
                <tr
                  key={row.range}
                  className={cn(
                    "border-t border-white/5",
                    row.active && "bg-white/[0.04] outline outline-1 -outline-offset-1 outline-white/10",
                  )}
                >
                  <td className="py-1.5">
                    {row.range}
                    {row.active && <span className="ml-1.5 text-[9px] text-white/40">← current</span>}
                  </td>
                  <td className={cn("py-1.5", row.tone)}>{row.label}</td>
                  <td className="py-1.5">{row.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      {/* ── Alert conditions (real trigger state; no paging yet) ─ */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-amber-200" /> Alert conditions
          </span>
        }
        subtitle="Thresholds are a policy choice, not fetched data — but each condition's TRIGGERED/OK state below is computed live from this page's real numbers. No paging/notification integration exists yet (see Actions → Notify team)."
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              label: "Coverage < 75%",
              current: coverage !== null ? `${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%` : "—",
              triggered: coverage !== null ? coverage * (coverage <= 1 ? 100 : 1) < 75 : null,
            },
            {
              label: "MAPE increase > 15% vs last version",
              current: mapeChangePct !== null ? `${mapeChangePct >= 0 ? "+" : ""}${mapeChangePct.toFixed(1)}%` : "— (needs 2+ versions with logged MAPE)",
              triggered: mapeChangePct !== null ? mapeChangePct > 15 : null,
            },
            {
              label: "PSI (top 3 features) > 0.5",
              current: top3Psi !== null ? top3Psi.toFixed(2) : "—",
              triggered: top3Psi !== null ? top3Psi > 0.5 : null,
            },
            {
              label: "Error plateau detected",
              current: "— (no plateau-detection formula defined yet)",
              triggered: null,
            },
          ].map((cond) => (
            <div
              key={cond.label}
              className={cn(
                "rounded-md border p-3",
                cond.triggered === true
                  ? "border-rose-400/30 bg-rose-400/5"
                  : "border-white/5 bg-white/[0.02]",
              )}
            >
              <div className="flex items-center justify-between">
                <AlertTriangle
                  className={cn(
                    "h-3.5 w-3.5",
                    cond.triggered === true ? "text-rose-300" : "text-amber-300/70",
                  )}
                />
                {cond.triggered !== null && (
                  <span
                    className={cn(
                      "rounded-md border px-1.5 py-0.5 text-[8px] font-medium uppercase",
                      cond.triggered
                        ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                        : "border-emerald-300/30 bg-emerald-300/10 text-emerald-200",
                    )}
                  >
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

      {/* ── Automated actions (mixed) ────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-emerald-200" /> Actions
          </span>
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Link
            href="/dashboard/models"
            className="flex flex-col items-center gap-1.5 rounded-md border border-lime-200/30 bg-lime-100/10 px-3 py-3 text-center text-xs text-lime-100 hover:bg-lime-100/20"
          >
            <Sliders className="h-4 w-4" /> Trigger fine-tune
            <span className="text-[10px] text-lime-100/60">Opens Model Registry → Fine-tune tab</span>
          </Link>
          <Link
            href="/dashboard/models"
            className="flex flex-col items-center gap-1.5 rounded-md border border-sky-400/20 bg-sky-500/10 px-3 py-3 text-center text-xs text-sky-200 hover:bg-sky-500/20"
          >
            <Rocket className="h-4 w-4" /> Trigger full retrain
            <span className="text-[10px] text-sky-200/60">Opens Model Registry → Train tab</span>
          </Link>
          <button
            type="button"
            disabled
            title="Not wired to a real endpoint yet"
            className="flex flex-col items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-3 text-center text-xs text-white/40 opacity-60 cursor-not-allowed"
          >
            <GitBranch className="h-4 w-4" /> Recalibrate conformal model
          </button>
          <button
            type="button"
            disabled
            title="Not wired to a real endpoint yet"
            className="flex flex-col items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-3 py-3 text-center text-xs text-white/40 opacity-60 cursor-not-allowed"
          >
            <Bell className="h-4 w-4" /> Notify team
          </button>
        </div>
      </Card>

      {/* ── Tech stack (real, static) ────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Workflow className="h-4 w-4 text-emerald-200" /> Tech stack
          </span>
        }
      >
        <div className="flex flex-wrap items-center gap-4 text-xs text-white/60">
          {[
            { icon: Box, label: "MLflow" },
            { icon: Workflow, label: "Prefect" },
            { icon: Activity, label: "Prometheus" },
            { icon: Cpu, label: "Grafana" },
            { icon: Database, label: "PostgreSQL" },
          ].map((t) => (
            <span key={t.label} className="inline-flex items-center gap-1.5">
              <t.icon className="h-3.5 w-3.5 text-white/40" /> {t.label}
            </span>
          ))}
        </div>
      </Card>
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

/** Icon in a small colored rounded-square box, for a card title. */
function TitleIcon({ icon: Icon }: { icon: React.ComponentType<{ className?: string }> }) {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-300/10">
      <Icon className="h-3.5 w-3.5 text-emerald-200" />
    </span>
  );
}

/** "<Label> (latest)" stat box with a real per-epoch % change vs the
 * previous epoch -- every metric this backs (loss/RMSE/MAE) is "lower is
 * better", so a decrease is shown green/down and an increase red/up,
 * the opposite convention a KPI like "revenue" would use. `deltaPct
 * === null` (fewer than 2 real epochs to compare, or a same-value
 * baseline) shows no arrow/delta rather than a fabricated 0%. */
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
      <div className="mt-0.5 text-base font-bold text-white">
        {value !== null ? value.toFixed(decimals) : "—"}
      </div>
      {deltaPct !== null && (
        <div
          className={cn(
            "mt-0.5 flex items-center gap-0.5 text-[10px] font-medium",
            improved ? "text-emerald-300" : worsened ? "text-rose-300" : "text-white/40",
          )}
        >
          {improved ? (
            <ArrowDownRight className="h-3 w-3" />
          ) : worsened ? (
            <ArrowUpRight className="h-3 w-3" />
          ) : null}
          {Math.abs(deltaPct).toFixed(1)}%
        </div>
      )}
    </div>
  );
}
