/**
 * /dashboard/performance — ML Platform → Performance.
 *
 * Modeled on an ML-monitoring mockup (registry, error metrics, conformal
 * coverage, concept-drift, online-learning, model health, alerts,
 * automated actions, tech stack). Sections are split strictly into real
 * (fetched from `GET /v1/model/versions`, `GET /v1/model/training-runs`,
 * and `GET /v1/model/drift` — same convention as `models/page.tsx`) and
 * illustrative (no backend concept exists yet — there is no rolling error
 * time-series, no health-score formula, no alert policy). Every
 * illustrative section carries `IllustrativeBadge` — this app's
 * convention is no silently fabricated dashboards (see `training/
 * page.tsx` for the precedent this deliberately does NOT follow).
 */
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity, AlertTriangle, Bell, Box, Cpu, Database,
  GitBranch, Radar, RefreshCw, Rocket, Sliders, Target,
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
  fetchModelVersions,
  type DriftReport,
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
  const hasValRmseMae = lossCurvePoints.some(
    (p) => p.val_rmse !== null && p.val_mae !== null,
  );

  const mape = production ? firstMetric(production.metrics, MAPE_KEYS) : null;
  const rmse = production ? firstMetric(production.metrics, RMSE_KEYS) : null;
  const coverage = production ? firstMetric(production.metrics, COVERAGE_KEYS) : null;

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
          subtitle="Across recent model versions — no daily time-series exists yet, so this is per-version, not a rolling window"
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
          subtitle="Target from Settings.conformal_alpha (fixed); actual from the Production version's logged eval"
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
              No coverage metric logged for the Production version yet.
            </p>
          )}
        </Card>
      </div>

      {/* ── Training vs validation loss (real) ──────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-200" /> Training vs validation loss
          </span>
        }
        subtitle={
          lossCurveVersion
            ? `Real per-epoch train_loss/val_loss for ${architecture} v${lossCurveVersion.version} (${lossCurveVersion.stage}) -- GET /v1/model/versions/{version}/loss-curve`
            : "Real per-epoch train_loss/val_loss, once a version exists -- GET /v1/model/versions/{version}/loss-curve"
        }
        actions={
          // Version deletion lives on the Model Registry page only
          // (/dashboard/models) -- this page is a read-only training
          // diagnostic view, not where destructive registry actions
          // belong.
          versions && versions.length > 1 ? (
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
          ) : undefined
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
            <Target className="h-4 w-4 text-emerald-200" /> Validation RMSE & MAE
          </span>
        }
        subtitle={
          lossCurveVersion
            ? `Real per-epoch val_rmse/val_mae (MW) for ${architecture} v${lossCurveVersion.version} (${lossCurveVersion.stage}) -- GET /v1/model/versions/{version}/loss-curve`
            : "Real per-epoch val_rmse/val_mae (MW), once a version exists -- GET /v1/model/versions/{version}/loss-curve"
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
                dashed: true,
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
        <div className="mt-4 rounded-lg border border-dashed border-amber-300/20 bg-white/[0.01] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-white/70">
              Cumulative drift / diminishing-returns tracking
            </span>
            <IllustrativeBadge />
          </div>
          <p className="text-xs text-white/45">
            Would show cumulative drift since the last full retrain and
            whether online updates are still improving accuracy. No such
            computation exists in the pipeline yet — see TODO.md.
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

      {/* ── Model health score (illustrative) ──────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card
          title={
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-200" /> Model health score
            </span>
          }
          subtitle="No scoring formula exists in this codebase yet — inventing one from real inputs would look more authoritative than it is"
          badge={<IllustrativeBadge />}
        >
          <div className="flex justify-center">
            <ArcGauge value={63} max={100} label="63/100" sub="Sample value" color="rgba(244,63,94,0.85)" />
          </div>
          <p className="mt-2 text-center text-xs text-white/45">
            Would combine error-vs-baseline, feature drift, and coverage
            health into one score once a real formula is defined and
            product-approved.
          </p>
        </Card>

        <Card
          title="Retraining decision guide"
          subtitle="Sample thresholds — no retraining policy is wired to real alerts yet"
          badge={<IllustrativeBadge />}
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
              <tr className="border-t border-white/5">
                <td className="py-1.5">90 – 100</td>
                <td className="py-1.5 text-lime-100">Stable</td>
                <td className="py-1.5">No action needed</td>
              </tr>
              <tr className="border-t border-white/5">
                <td className="py-1.5">70 – 89</td>
                <td className="py-1.5 text-amber-200">Monitor</td>
                <td className="py-1.5">Continue online learning</td>
              </tr>
              <tr className="border-t border-white/5">
                <td className="py-1.5">&lt; 70</td>
                <td className="py-1.5 text-rose-300">Critical</td>
                <td className="py-1.5">Full retrain</td>
              </tr>
            </tbody>
          </table>
        </Card>
      </div>

      {/* ── Alert conditions (illustrative) ─────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-amber-200" /> Alert conditions
          </span>
        }
        subtitle="Sample thresholds only — no alert policy or paging integration exists yet"
        badge={<IllustrativeBadge />}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Coverage < 75%", current: coverage !== null ? `${(coverage * (coverage <= 1 ? 100 : 1)).toFixed(1)}%` : "—" },
            { label: "MAPE increase > 15% vs last version", current: mapeChangePct !== null ? `${mapeChangePct >= 0 ? "+" : ""}${mapeChangePct.toFixed(1)}%` : "— (needs 2+ versions with logged MAPE)" },
            { label: "PSI (top 3 features) > 0.5", current: top3Psi !== null ? top3Psi.toFixed(2) : "—" },
            { label: "Error plateau detected", current: "— (no plateau-detection formula defined yet)" },
          ].map((cond) => (
            <div key={cond.label} className="rounded-md border border-white/5 bg-white/[0.02] p-3">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-300/70" />
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
