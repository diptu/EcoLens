/**
 * /dashboard/admin/models — model registry, training, fine-tuning.
 *
 * Lists all model versions with their stage + metrics. Lets the
 * admin (diptu) start a full retrain, a fine-tune job, promote a
 * Staging model to Production, or permanently delete a version
 * (2026-08-05 -- gated server-side against deleting the current
 * Production version, see `deleteModelVersion`'s own docstring).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import {
  Box,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Info,
  Minus,
  PlayCircle,
  Rocket,
  Scale,
  Sliders,
  Star,
  Trash2,
  TrendingDown,
  TrendingUp,
  Trophy,
  Upload,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { LineChart, PALETTE, RadarChart } from "@/components/dashboard/charts";
import { ArcGauge } from "@/components/dashboard/gauge";
import { cn } from "@/lib/utils";
import {
  deleteModelVersion,
  fetchLossCurve,
  fetchModelEvaluation,
  fetchModelEvaluationHistory,
  fetchModelVersions,
  importModelBundle,
  importOnnxBundle,
  promoteModelVersion,
  type LossCurve,
  type ModelImportResult,
  type ModelVersion,
  type RegionEvaluation,
} from "@/lib/emissions";
import {
  formatRelativeTime,
  pollForTrainingRun,
  triggerTraining,
  type TrainingRunLog,
  type TrainTrigger,
} from "@/lib/ingestion";

type Tab = "registry" | "comparison" | "train" | "fine-tune" | "import";

// This page's own architecture list, deliberately narrower than
// `lib/emissions.ts`'s shared `MODEL_ARCHITECTURES` (which also backs
// `training/page.tsx` and includes `energy_forecast_multi_task`) --
// Model Registry is scoped to the three forecasting architectures the
// product description names (LSTM, TFT, TimesFM), not the separate
// carbon-insights model.
//
// TimesFM's real registrable model is `timesfm_demand_correction`
// (`service/ml/timesfm_correction.py`) -- a genuinely trainable Ridge-
// regression residual-correction layer on top of frozen zero-shot
// TimesFM, with its own MLflow registry entries/versions/metrics, NOT
// `lstm_demand_timesfm` (that string is only a evaluation-run *tag*,
// `ml/evaluate.py`'s own comment on it: "not an MLflow Model Registry
// entry" -- querying it here always 404s/returns empty, which is why
// this tab used to always show "No registered version for TimesFM
// yet." regardless of real registry state). Fixed 2026-08-10 -- see
// this file's git history for the stale `lstm_demand_timesfm` version
// of this comment if the reasoning above needs re-checking.
//
// Train tab still honest for TimesFM: it's permanently disabled
// regardless of architecture (raw zero-shot TimesFM itself has nothing
// to retrain -- only its correction layer does, via the Fine-tune tab
// below).
//
// Fine-tune tab (fixed 2026-08-11): `POST /v1/model/train`
// (`triggerTraining`) now takes a real `architecture` parameter --
// `service/model/actions.py`'s `_build_and_publish_training_trigger`
// used to hardcode `"architecture": "lstm"` server-side regardless of
// which tab was selected client-side, so selecting TFT or TimesFM and
// clicking "Start fine-tune" silently fine-tuned LSTM instead. See
// `TRAIN_TRIGGER_ARCHITECTURE` below for the modelName -> training-
// trigger-architecture-code mapping `FineTuneForm` now sends.
const MODEL_ARCHITECTURES = [
  { modelName: "lstm_demand", label: "LSTM" },
  { modelName: "lstm_demand_tft", label: "TFT" },
  { modelName: "timesfm_demand_correction", label: "TimesFM" },
] as const;

// `MODEL_ARCHITECTURES[*].modelName` (a real MLflow registry name) ->
// the short code `training_worker.handle_training_trigger`'s
// `payload["architecture"]` actually switches on (`service/
// training_worker.py`, `service/ml/timesfm_correction.py`'s
// `TIMESFM_CORRECTION_MODEL_NAME`). Two different vocabularies for the
// same three architectures -- this is the one place that translates
// between them for the Fine-tune form.
const TRAIN_TRIGGER_ARCHITECTURE: Record<string, string> = {
  lstm_demand: "lstm",
  lstm_demand_tft: "tft",
  timesfm_demand_correction: "timesfm_correction",
};

export default function AdminModelsPage() {
  const [tab, setTab] = useState<Tab>("registry");
  const [architecture, setArchitecture] = useState<string>(
    MODEL_ARCHITECTURES[0].modelName,
  );
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [expandedVersion, setExpandedVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    fetchModelVersions(architecture)
      .then((r) => {
        if (!cancelled) {
          setVersions(r.data);
          setModelName(r.name);
          setExpandedVersion(r.data[0]?.version ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVersions([]);
          setModelName(architecture);
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture]);

  function refreshVersions(fresh: ModelVersion[]) {
    setVersions(fresh);
    setExpandedVersion(fresh[0]?.version ?? null);
  }

  const [promoting, setPromoting] = useState<string | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  function handlePromote(version: string, stage: "Production" | "Staging" | "Archived") {
    setPromoting(version);
    setPromoteError(null);
    promoteModelVersion(version, stage, architecture)
      .then(() => fetchModelVersions(architecture))
      .then((r) => refreshVersions(r.data))
      .catch((err) => {
        setPromoteError(err instanceof Error ? err.message : "promotion failed");
      })
      .finally(() => setPromoting(null));
  }

  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function handleDelete(version: string) {
    // Client-side confirm too, not just the server-side Production
    // gate -- this is permanent (the registry entry, not the
    // underlying run/artifacts, but still irreversible from the UI's
    // point of view: a deleted version can't be promoted or served
    // again without re-registering it from the run directly).
    if (
      !window.confirm(
        `Permanently delete v${version}? This removes it from the registry -- it can't be promoted or served again.`,
      )
    ) {
      return;
    }
    setDeleting(version);
    setDeleteError(null);
    deleteModelVersion(version, architecture)
      .then(() => fetchModelVersions(architecture))
      .then((r) => refreshVersions(r.data))
      .catch((err) => {
        setDeleteError(err instanceof Error ? err.message : "deletion failed");
      })
      .finally(() => setDeleting(null));
  }

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold text-white">Model registry</h1>
        <p className="mt-1 text-sm text-white/55">
          Manage the MLflow registry. Train new versions, fine-tune the
          current production model, and promote Staging → Production.
        </p>
      </div>

      {/* ── Tabs ────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Models tabs">
        <TabButton active={tab === "registry"}  onClick={() => setTab("registry")}  data-testid="tab-registry">
          <Box className="h-3.5 w-3.5" /> Registry
        </TabButton>
        <TabButton active={tab === "comparison"} onClick={() => setTab("comparison")} data-testid="tab-comparison">
          <Scale className="h-3.5 w-3.5" /> Comparison
        </TabButton>
        <TabButton active={tab === "train"}     onClick={() => setTab("train")}     data-testid="tab-train">
          <Rocket className="h-3.5 w-3.5" /> Train
        </TabButton>
        <TabButton active={tab === "fine-tune"} onClick={() => setTab("fine-tune")} data-testid="tab-fine-tune">
          <Sliders className="h-3.5 w-3.5" /> Fine-tune
        </TabButton>
        <TabButton active={tab === "import"} onClick={() => setTab("import")} data-testid="tab-import">
          <Upload className="h-3.5 w-3.5" /> Import
        </TabButton>
      </div>

      {/* ── Registry tab ────────────────────────────────────── */}
      {tab === "registry" && (
        <Card
          title={
            <span className="flex items-center gap-2">
              <Box className="h-4 w-4 text-emerald-200" />
              {modelName ?? architecture}
              {versions ? ` · ${versions.length} version${versions.length === 1 ? "" : "s"}` : ""}
            </span>
          }
          actions={
            <span className="text-[10px] text-white/40">
              real data from GET /v1/model/versions — click a row to expand
            </span>
          }
        >
          <div
            className="mb-3 flex flex-wrap gap-1"
            role="tablist"
            aria-label="Model architecture"
            data-testid="architecture-selector"
          >
            {MODEL_ARCHITECTURES.map((arch) => (
              <TabButton
                key={arch.modelName}
                active={architecture === arch.modelName}
                onClick={() => setArchitecture(arch.modelName)}
                data-testid={`architecture-${arch.modelName}`}
              >
                {arch.label}
              </TabButton>
            ))}
          </div>
          {promoteError && (
            <p className="mb-2 text-xs text-rose-300">{promoteError}</p>
          )}
          {deleteError && (
            <p className="mb-2 text-xs text-rose-300">{deleteError}</p>
          )}
          <div className="space-y-2" data-testid="model-registry">
            <RealModelVersions
              versions={versions}
              loaded={loaded}
              expandedVersion={expandedVersion}
              onToggle={(v) => setExpandedVersion(expandedVersion === v ? null : v)}
              onPromote={handlePromote}
              promoting={promoting}
              onDelete={handleDelete}
              deleting={deleting}
            />
          </div>
        </Card>
      )}

      {/* ── Comparison tab ──────────────────────────────────── */}
      {tab === "comparison" && <ComparisonTab />}

      {/* ── Train tab ────────────────────────────────────────── */}
      {tab === "train" && (
        <div className="space-y-3">
          <div
            className="flex flex-wrap gap-1"
            role="tablist"
            aria-label="Model to train"
            data-testid="train-architecture-selector"
          >
            {MODEL_ARCHITECTURES.map((arch) => (
              <TabButton
                key={arch.modelName}
                active={architecture === arch.modelName}
                onClick={() => setArchitecture(arch.modelName)}
                data-testid={`train-architecture-${arch.modelName}`}
              >
                {arch.label}
              </TabButton>
            ))}
          </div>
          <TrainForm
            architecture={architecture}
            architectureLabel={
              MODEL_ARCHITECTURES.find((a) => a.modelName === architecture)?.label ?? architecture
            }
            // Unlike Fine-tune, deliberately does NOT switch to the
            // Registry tab on success -- this tab's own "Training vs
            // validation loss" card below the form is the whole reason
            // to stay here and see the run that was just triggered.
            onNewVersion={(fresh) => refreshVersions(fresh)}
          />
        </div>
      )}

      {/* ── Fine-tune tab ───────────────────────────────────── */}
      {tab === "fine-tune" && (
        <div className="space-y-3">
          <div
            className="flex flex-wrap gap-1"
            role="tablist"
            aria-label="Model to fine-tune"
            data-testid="finetune-architecture-selector"
          >
            {MODEL_ARCHITECTURES.map((arch) => (
              <TabButton
                key={arch.modelName}
                active={architecture === arch.modelName}
                onClick={() => setArchitecture(arch.modelName)}
                data-testid={`finetune-architecture-${arch.modelName}`}
              >
                {arch.label}
              </TabButton>
            ))}
          </div>
          <FineTuneForm
            architecture={architecture}
            architectureLabel={
              MODEL_ARCHITECTURES.find((a) => a.modelName === architecture)?.label ?? architecture
            }
            onNewVersion={(fresh) => {
              refreshVersions(fresh);
              setTab("registry");
            }}
          />
        </div>
      )}

      {/* ── Import tab ──────────────────────────────────────── */}
      {tab === "import" && (
        <ImportForm
          onImported={(newModelName, fresh) => {
            // The bundle's own manifest.json decides architecture (LSTM
            // vs TFT), not a client-side selector -- switch the shared
            // `architecture` state to whatever the server actually
            // registered against, so the Registry tab shows the version
            // that was just imported rather than whichever architecture
            // happened to be selected before this tab was opened.
            setArchitecture(newModelName);
            refreshVersions(fresh);
            setTab("registry");
          }}
        />
      )}
    </div>
  );
}

function TabButton({
  active, onClick, children, ...rest
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  "data-testid"?: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-lime-100 text-black"
          : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────
// Comparison tab -- real Model Comparison view (2026-08-10). Every
// number here traces to a real forecast-api read: `GET /v1/model/
// versions` (registry metadata + training-time `test_*` metrics),
// `GET .../evaluation` (the harder walk-forward backtest, preferred
// when it exists), and `GET .../evaluation-history` (the real time
// series a genuine "has this version's accuracy drifted" comparison
// needs). No metric here is fabricated -- a candidate whose evaluation
// has never been run falls back to its training-time split honestly
// labeled `metricsSource: "training"`, and Stability stays `null`
// (rendered as "not enough evaluation history yet") until `evaluate`
// has actually been run at least twice for that version.
//
// Each side independently picks an architecture *and* a version
// (2026-08-11) -- both sides can be the same architecture, so this
// covers "LSTM v7 vs v8" as well as "LSTM vs TFT". Leaving a side's
// version on "Auto" keeps the original default (current Production,
// else the newest registered version).
// ────────────────────────────────────────────────────────────────────

type ComparisonCandidate = {
  modelName: string;
  label: string;
  version: ModelVersion | null;
  primaryCandidateName: string | null;
  accuracyMape: number | null;
  reliabilityCoverage: number | null;
  consistencyWidthMw: number | null;
  metricsSource: "evaluation" | "training" | null;
  driftDeltaMapePp: number | null;
  driftRunCount: number;
};

/** `candidate.label` alone is ambiguous once both comparison sides can
 * be the same architecture (e.g. LSTM v7 vs LSTM v8) -- used anywhere
 * the two candidates are named side by side outside their own score
 * cards (which already show version separately). */
function candidateDisplayName(candidate: ComparisonCandidate | null): string {
  if (!candidate) return "—";
  return candidate.version ? `${candidate.label} v${candidate.version.version}` : candidate.label;
}

function average(values: number[]): number | null {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return null;
  return finite.reduce((a, b) => a + b, 0) / finite.length;
}

/** Real registry version list for one architecture -- split out from
 * `loadComparisonCandidate` (2026-08-11) so `ComparisonTab` can
 * populate a per-side version picker *before* deciding which version's
 * metrics to load, letting a user compare two versions of the *same*
 * architecture (e.g. LSTM v7 vs v8), not just two different
 * architectures. `[]` on a failed/empty fetch, same as the old inline
 * try/catch. */
async function fetchComparisonVersions(modelName: string): Promise<ModelVersion[]> {
  try {
    return (await fetchModelVersions(modelName)).data;
  } catch {
    return [];
  }
}

async function loadComparisonCandidate(
  modelName: string,
  label: string,
  versions: ModelVersion[],
  /** A specific version string to compare, or `null`/`""` for the old
   * default (current Production, else the newest registered). Passing
   * an explicit version lets the two sides of the comparison be the
   * same architecture at different versions. */
  selectedVersion: string | null,
): Promise<ComparisonCandidate> {
  const base: ComparisonCandidate = {
    modelName,
    label,
    version: null,
    primaryCandidateName: null,
    accuracyMape: null,
    reliabilityCoverage: null,
    consistencyWidthMw: null,
    metricsSource: null,
    driftDeltaMapePp: null,
    driftRunCount: 0,
  };

  if (versions.length === 0) return base;

  const version =
    (selectedVersion ? versions.find((v) => v.version === selectedVersion) : null) ??
    versions.find((v) => v.stage === "Production") ??
    versions[0];
  base.version = version;
  const primaryCandidateName = `${modelName}_v${version.version}`;
  base.primaryCandidateName = primaryCandidateName;

  const byPrimary = (regions: RegionEvaluation[]) =>
    regions.filter((r) => r.candidate === primaryCandidateName);

  try {
    const evaluation = await fetchModelEvaluation(version.version, modelName);
    const rows = evaluation ? byPrimary(evaluation.regions) : [];
    if (rows.length > 0) {
      base.accuracyMape = average(rows.map((r) => r.mape));
      base.reliabilityCoverage = average(rows.map((r) => r.coverage));
      base.consistencyWidthMw = average(rows.map((r) => r.interval_width));
      base.metricsSource = "evaluation";
    }
  } catch {
    // Real evaluation read can fail (e.g. registry unreachable) -- fall
    // through to the training-time split below rather than surfacing a
    // hard error for what's an optional, "harder" number.
  }

  if (base.metricsSource === null) {
    const m = version.metrics;
    // `timesfm_demand_correction` (`service/ml/timesfm_correction.py`)
    // logs its training-time test split under its own `corrected_*`
    // key names (`raw_test_mape`/`corrected_test_mape`/etc, not the
    // LSTM/TFT `train_and_register`'s `test_*` names) -- real numbers,
    // just a different real key, so this checks both rather than
    // showing "no test metrics" for a version that actually has them.
    // No calibrated-interval-width equivalent is logged for the
    // correction model, so Consistency honestly stays "—" for it.
    const hasAny =
      m.test_mape !== undefined ||
      m.test_coverage_calibrated !== undefined ||
      m.test_interval_width_calibrated_mw !== undefined ||
      m.corrected_test_mape !== undefined ||
      m.corrected_test_coverage_calibrated !== undefined;
    if (hasAny) {
      base.accuracyMape = m.test_mape ?? m.corrected_test_mape ?? null;
      base.reliabilityCoverage = m.test_coverage_calibrated ?? m.corrected_test_coverage_calibrated ?? null;
      base.consistencyWidthMw = m.test_interval_width_calibrated_mw ?? null;
      base.metricsSource = "training";
    }
  }

  try {
    const history = await fetchModelEvaluationHistory(version.version, modelName);
    const perRunMape = history.runs
      .map((run) => average(byPrimary(run.regions).map((r) => r.mape)))
      .filter((v): v is number => v !== null);
    base.driftRunCount = perRunMape.length;
    if (perRunMape.length >= 2) {
      base.driftDeltaMapePp = perRunMape[perRunMape.length - 1] - perRunMape[0];
    }
  } catch {
    // Real history read can fail -- Stability stays "not enough data".
  }

  return base;
}

/** Bounded to [0, 100] -- a MAPE over 100% (a real possibility for a bad
 * model on a volatile series) would otherwise drive this negative. */
function accuracyScore(mape: number | null): number | null {
  if (mape === null) return null;
  return Math.max(0, Math.min(100, 100 - mape));
}

function reliabilityScore(coverage: number | null): number | null {
  if (coverage === null) return null;
  return Math.max(0, Math.min(100, coverage * 100));
}

/** Relative, not absolute -- there's no universal "good" MW interval
 * width across regions of very different scale (TAS1 vs NSW1), so this
 * scores the narrower of the *two candidates actually being compared*
 * higher, explicitly disclosed as relative in the UI caption below. */
function consistencyScores(
  widthA: number | null,
  widthB: number | null,
): [number | null, number | null] {
  if (widthA === null || widthB === null) return [null, null];
  const worst = Math.max(widthA, widthB);
  if (worst === 0) return [100, 100];
  return [100 * (1 - widthA / worst), 100 * (1 - widthB / worst)];
}

// Sensitivity factor for `stabilityScore` -- how many points a 1
// percentage-point rise in real backtested MAPE (between a version's
// earliest and most recent `evaluate` run) costs. A bare `10` here would
// be an undocumented magic number with no stated rationale; naming it
// makes explicit that it's a deliberate product choice (harsher than a
// 1:1 point-per-pp penalty), not a value derived from any calibration
// study -- tune it here if that choice ever needs revisiting, and the
// `ScoreCalculationTooltip` breakdown below picks up the change
// automatically rather than drifting out of sync with a hardcoded copy.
const STABILITY_PENALTY_PER_PP = 10;

/** Absolute, disclosed formula: every 1 percentage-point rise in this
 * version's own real backtested MAPE between its earliest and most
 * recent `evaluate` run costs `STABILITY_PENALTY_PER_PP` points, bounded
 * to [0, 100] -- an improvement is capped at 100, not rewarded beyond
 * it, and a large-enough regression floors at 0 rather than going
 * negative. */
function stabilityScore(deltaPp: number | null): number | null {
  if (deltaPp === null) return null;
  return Math.max(0, Math.min(100, 100 - Math.max(0, deltaPp) * STABILITY_PENALTY_PER_PP));
}

function overallScore(scores: Array<number | null>): number | null {
  const present = scores.filter((s): s is number => s !== null);
  if (present.length === 0) return null;
  return present.reduce((a, b) => a + b, 0) / present.length;
}

function ComparisonTab() {
  const [modelNameA, setModelNameA] = useState<string>(MODEL_ARCHITECTURES[1].modelName); // TFT
  const [modelNameB, setModelNameB] = useState<string>(MODEL_ARCHITECTURES[0].modelName); // LSTM
  // "" = auto (current Production, else newest) -- same default the old
  // hardcoded pick used, now just expressed as "no explicit choice".
  const [selectedVersionA, setSelectedVersionA] = useState<string>("");
  const [selectedVersionB, setSelectedVersionB] = useState<string>("");
  const [versionsA, setVersionsA] = useState<ModelVersion[]>([]);
  const [versionsB, setVersionsB] = useState<ModelVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [candA, setCandA] = useState<ComparisonCandidate | null>(null);
  const [candB, setCandB] = useState<ComparisonCandidate | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const labelA = MODEL_ARCHITECTURES.find((a) => a.modelName === modelNameA)?.label ?? modelNameA;
    const labelB = MODEL_ARCHITECTURES.find((a) => a.modelName === modelNameB)?.label ?? modelNameB;
    Promise.all([fetchComparisonVersions(modelNameA), fetchComparisonVersions(modelNameB)])
      .then(([vA, vB]) => {
        if (cancelled) return null;
        setVersionsA(vA);
        setVersionsB(vB);
        return Promise.all([
          loadComparisonCandidate(modelNameA, labelA, vA, selectedVersionA),
          loadComparisonCandidate(modelNameB, labelB, vB, selectedVersionB),
        ]);
      })
      .then((result) => {
        if (!cancelled && result) {
          setCandA(result[0]);
          setCandB(result[1]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [modelNameA, modelNameB, selectedVersionA, selectedVersionB]);

  const accA = accuracyScore(candA?.accuracyMape ?? null);
  const accB = accuracyScore(candB?.accuracyMape ?? null);
  const relA = reliabilityScore(candA?.reliabilityCoverage ?? null);
  const relB = reliabilityScore(candB?.reliabilityCoverage ?? null);
  const [consA, consB] = consistencyScores(
    candA?.consistencyWidthMw ?? null,
    candB?.consistencyWidthMw ?? null,
  );
  const stabA = stabilityScore(candA?.driftDeltaMapePp ?? null);
  const stabB = stabilityScore(candB?.driftDeltaMapePp ?? null);
  const overallA = overallScore([accA, relA, consA, stabA]);
  const overallB = overallScore([accB, relB, consB, stabB]);

  const leading =
    overallA !== null && (overallB === null || overallA >= overallB) ? "A" : overallB !== null ? "B" : null;

  return (
    <div className="space-y-6" data-testid="comparison-tab">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr_320px]">
        <ComparisonPicker
          value={modelNameA}
          onChange={(v) => {
            setModelNameA(v);
            setSelectedVersionA("");
          }}
          versionValue={selectedVersionA}
          onVersionChange={setSelectedVersionA}
          versions={versionsA}
          testId="comparison-select-a"
        />
        <ComparisonPicker
          value={modelNameB}
          onChange={(v) => {
            setModelNameB(v);
            setSelectedVersionB("");
          }}
          versionValue={selectedVersionB}
          onVersionChange={setSelectedVersionB}
          versions={versionsB}
          testId="comparison-select-b"
        />
        <div />
      </div>

      {loading ? (
        <Card><p className="py-8 text-center text-xs text-white/40">Loading real registry + evaluation data…</p></Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr_320px]">
          <ComparisonScoreCard
            candidate={candA}
            overall={overallA}
            accuracyScore={accA}
            reliabilityScore={relA}
            consistencyScore={consA}
            stabilityScore={stabA}
            leading={leading === "A"}
            color={PALETTE.green}
            side="a"
          />
          <ComparisonScoreCard
            candidate={candB}
            overall={overallB}
            accuracyScore={accB}
            reliabilityScore={relB}
            consistencyScore={consB}
            stabilityScore={stabB}
            leading={leading === "B"}
            color={PALETTE.sky}
            side="b"
          />
          <RecommendationPanel
            candA={candA}
            candB={candB}
            accA={accA}
            relA={relA}
            consA={consA}
            stabA={stabA}
            accB={accB}
            relB={relB}
            consB={consB}
            stabB={stabB}
            overallA={overallA}
            overallB={overallB}
            leading={leading}
          />
        </div>
      )}

      {!loading && (candA?.metricsSource || candB?.metricsSource) && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
          <KeyMetricsTable candA={candA} candB={candB} />
          <Card title="Model at a Glance">
            <RadarChart
              axes={["Accuracy", "Reliability", "Consistency", "Stability"]}
              maxValue={100}
              series={[
                { name: candidateDisplayName(candA), color: PALETTE.green, values: [accA ?? 0, relA ?? 0, consA ?? 0, stabA ?? 0] },
                { name: candidateDisplayName(candB), color: PALETTE.sky, values: [accB ?? 0, relB ?? 0, consB ?? 0, stabB ?? 0] },
              ]}
            />
            <p className="mt-3 text-[10px] leading-relaxed text-white/40">
              Each axis is a real metric normalized 0-100 (higher = better). Consistency is
              relative between these two candidates (narrower interval wins); Stability needs
              &ge;2 real <code className="font-mono">evaluate</code> runs for this version to be
              computed, and reads as "no data" (axis at 0) until then.
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}

function ComparisonPicker({
  value, onChange, versionValue, onVersionChange, versions, testId,
}: {
  value: string;
  onChange: (v: string) => void;
  versionValue: string;
  onVersionChange: (v: string) => void;
  versions: ModelVersion[];
  testId: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
        Compare
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testId}
        className="rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
      >
        {MODEL_ARCHITECTURES.map((a) => (
          <option key={a.modelName} value={a.modelName} className="bg-[#0a1410]">
            {a.label}
          </option>
        ))}
      </select>
      {/* Same architecture on both sides is a valid comparison now
          (e.g. LSTM v7 vs v8) -- this select just picks which of that
          architecture's real registered versions to load. */}
      <select
        value={versionValue}
        onChange={(e) => onVersionChange(e.target.value)}
        data-testid={`${testId}-version`}
        className="rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
      >
        <option value="" className="bg-[#0a1410]">Auto (Production)</option>
        {versions.map((v) => (
          <option key={v.version} value={v.version} className="bg-[#0a1410]">
            v{v.version} ({v.stage})
          </option>
        ))}
      </select>
    </div>
  );
}

function MetricRow({
  label, score, display, color,
}: {
  label: string;
  score: number | null;
  display: string;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-white/55">{label}</span>
        <span className="font-mono font-semibold text-white">{display}</span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full"
          style={{ width: `${score ?? 0}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function ComparisonScoreCard({
  candidate, overall, accuracyScore: accS, reliabilityScore: relS, consistencyScore: consS,
  stabilityScore: stabS, leading, color, side,
}: {
  candidate: ComparisonCandidate | null;
  overall: number | null;
  accuracyScore: number | null;
  reliabilityScore: number | null;
  consistencyScore: number | null;
  stabilityScore: number | null;
  leading: boolean;
  color: string;
  /** Disambiguates the two card testids -- both sides can now be the
   * same architecture (and, in the degenerate case, the same version)
   * since a user can compare LSTM v7 vs v8. */
  side: "a" | "b";
}) {
  if (!candidate || !candidate.version) {
    return (
      <Card>
        <p className="py-8 text-center text-xs text-white/40">
          {candidate ? `No registered version for ${candidate.label} yet.` : ""}
        </p>
      </Card>
    );
  }
  const { version } = candidate;
  return (
    <Card
      noPadding
      className={leading ? "border-lime-200/25 bg-lime-100/[0.03]" : undefined}
      data-testid={`comparison-card-${side}-${candidate.modelName}-v${version.version}`}
    >
      <div className="flex items-start justify-between gap-2 p-5 pb-0">
        <div>
          {leading && (
            <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-lime-200">
              <Trophy className="h-3 w-3" /> Leading model
            </div>
          )}
          <h3 className="text-lg font-bold text-white">{candidate.label}</h3>
          <p className="mt-0.5 text-[11px] text-white/45">
            v{version.version} · {formatRelativeTime(version.created_at)}
          </p>
        </div>
        <span className={cn(
          "rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
          STAGE_COLORS[version.stage] ?? "border-white/10 bg-white/5 text-white/55",
        )}>
          {version.stage}
        </span>
      </div>
      <div className="flex items-center gap-4 p-5">
        <div className="flex flex-col items-center gap-1.5">
          <ArcGauge value={overall ?? 0} max={100} label={overall === null ? "—" : overall.toFixed(0)} sub="/ 100" size={128} color={color} />
          <ScoreCalculationTooltip
            overall={overall}
            accS={accS}
            relS={relS}
            consS={consS}
            stabS={stabS}
            candidate={candidate}
          />
        </div>
        <div className="flex-1 space-y-2.5">
          <MetricRow
            label="Accuracy (MAPE)"
            score={accS}
            color={color}
            display={candidate.accuracyMape === null ? "—" : `${candidate.accuracyMape.toFixed(2)}%`}
          />
          <MetricRow
            label="Reliability (Coverage)"
            score={relS}
            color={color}
            display={candidate.reliabilityCoverage === null ? "—" : `${(candidate.reliabilityCoverage * 100).toFixed(1)}%`}
          />
          <MetricRow
            label="Consistency (Interval Width)"
            score={consS}
            color={color}
            display={candidate.consistencyWidthMw === null ? "—" : `${candidate.consistencyWidthMw.toFixed(0)} MW`}
          />
          <MetricRow
            label="Stability (Perf. Drift)"
            score={stabS}
            color={color}
            display={candidate.driftDeltaMapePp === null ? `— (${candidate.driftRunCount}/2 eval runs)` : `${candidate.driftDeltaMapePp >= 0 ? "+" : ""}${candidate.driftDeltaMapePp.toFixed(2)}pp`}
          />
        </div>
      </div>
      <div className="border-t border-white/5 px-5 py-3 text-[11px] text-white/45">
        {candidate.metricsSource === "evaluation"
          ? "Accuracy/Reliability/Consistency from a real walk-forward evaluate run."
          : candidate.metricsSource === "training"
            ? "No evaluate run logged yet -- showing this version's training-time test split instead."
            : "No test metrics logged for this version yet."}
      </div>
    </Card>
  );
}

/**
 * ScoreCalculationTooltip — hover-only breakdown of how the composite
 * "overall" score (and each of its 4 sub-scores) is actually computed,
 * with this candidate's own real numbers plugged into each formula.
 *
 * Deliberately hover-on-a-fixed-icon, not a floating mouse-tracked
 * tooltip with an interactive button inside (the "View details" pattern
 * `RealEmissionsTrend`'s tooltip used to have, removed 2026-08-10
 * because a mouse-tracked tooltip relocates out from under the cursor
 * before a click can land) -- this one is read-only and anchored to a
 * static target, so hovering it is enough; there's nothing inside that
 * needs to be clicked.
 */
function ScoreCalculationTooltip({
  overall, accS, relS, consS, stabS, candidate,
}: {
  overall: number | null;
  accS: number | null;
  relS: number | null;
  consS: number | null;
  stabS: number | null;
  candidate: ComparisonCandidate;
}) {
  const fmt = (v: number | null) => (v === null ? "no data" : v.toFixed(1));
  return (
    <div className="group relative">
      <span className="flex cursor-help items-center gap-1 text-[10px] text-white/40 hover:text-white/70">
        <Info className="h-3 w-3" /> How calculated?
      </span>
      <div className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 w-72 -translate-x-1/2 rounded-md border border-white/10 bg-[#0a1410]/95 p-3 text-[11px] leading-relaxed text-white/70 opacity-0 shadow-2xl backdrop-blur transition-opacity duration-150 group-hover:opacity-100">
        <p className="mb-1.5 font-semibold text-white">
          Overall = average of the scores below (each normalized 0-100, higher = better)
        </p>
        <ul className="space-y-1">
          <li>
            <span className="text-white/90">Accuracy</span> = 100 − MAPE →{" "}
            {candidate.accuracyMape === null
              ? "no data"
              : `100 − ${candidate.accuracyMape.toFixed(2)} = ${fmt(accS)}`}
          </li>
          <li>
            <span className="text-white/90">Reliability</span> = Coverage × 100 →{" "}
            {candidate.reliabilityCoverage === null
              ? "no data"
              : `${(candidate.reliabilityCoverage * 100).toFixed(1)} → ${fmt(relS)}`}
          </li>
          <li>
            <span className="text-white/90">Consistency</span> = 100 × (1 − this width ÷ the
            wider of the two compared models&apos; widths) -- relative, not absolute → {fmt(consS)}
          </li>
          <li>
            <span className="text-white/90">Stability</span> = 100 − {STABILITY_PENALTY_PER_PP} × the
            MAPE increase between this version&apos;s earliest and latest real{" "}
            <code className="font-mono">evaluate</code> run (0 if it improved) → {fmt(stabS)}
          </li>
        </ul>
        <p className="mt-1.5 border-t border-white/10 pt-1.5 text-white/50">
          Overall = mean of whichever scores above have data ={" "}
          {overall === null ? "—" : overall.toFixed(1)}
        </p>
        <p className="mt-1 text-white/40">
          {candidate.metricsSource === "evaluation"
            ? "Accuracy/Reliability/Consistency come from this version's real walk-forward evaluate run."
            : candidate.metricsSource === "training"
              ? "No evaluate run logged yet -- using this version's training-time test split instead."
              : "No test metrics logged for this version yet."}
        </p>
      </div>
    </div>
  );
}

function RecommendationPanel({
  candA, candB, overallA, overallB, accA, relA, consA, stabA, accB, relB, consB, stabB, leading,
}: {
  candA: ComparisonCandidate | null;
  candB: ComparisonCandidate | null;
  overallA: number | null;
  overallB: number | null;
  accA: number | null;
  relA: number | null;
  consA: number | null;
  stabA: number | null;
  accB: number | null;
  relB: number | null;
  consB: number | null;
  stabB: number | null;
  leading: "A" | "B" | null;
}) {
  const [promoting, setPromoting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (leading === null) {
    return (
      <Card title="Recommendation">
        <p className="py-4 text-xs text-white/45">
          Not enough real data to recommend a model yet -- neither candidate has a
          training-time test split or an evaluate run logged.
        </p>
      </Card>
    );
  }

  const winner = leading === "A" ? candA : candB;
  const other = leading === "A" ? candB : candA;
  const winnerOverall = leading === "A" ? overallA : overallB;
  const otherOverall = leading === "A" ? overallB : overallA;
  const winnerAcc = leading === "A" ? accA : accB;
  const winnerRel = leading === "A" ? relA : relB;
  const winnerCons = leading === "A" ? consA : consB;
  const winnerStab = leading === "A" ? stabA : stabB;
  const improvementPct =
    otherOverall !== null && otherOverall > 0 && winnerOverall !== null
      ? ((winnerOverall - otherOverall) / otherOverall) * 100
      : null;
  const alreadyProduction = winner?.version?.stage === "Production";

  async function handlePromote() {
    if (!winner?.version) return;
    if (
      !window.confirm(
        `Promote ${winner.label} v${winner.version.version} to Production? This archives whatever is currently in Production for ${winner.modelName}.`,
      )
    ) {
      return;
    }
    setPromoting(true);
    setError(null);
    try {
      await promoteModelVersion(winner.version.version, "Production", winner.modelName);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "promotion failed");
    } finally {
      setPromoting(false);
    }
  }

  return (
    <Card title="Recommendation" data-testid="recommendation-panel">
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-lime-200/30 bg-lime-100/10">
            <Star className="h-4 w-4 text-lime-200" />
          </span>
          <div>
            <p className="text-sm font-semibold text-white">
              {alreadyProduction
                ? `${candidateDisplayName(winner)} is already in Production`
                : `Promote ${candidateDisplayName(winner)} to Production`}
            </p>
            {winner && other && (
              <p className="mt-0.5 text-[11px] text-white/50">
                {candidateDisplayName(winner)} ({winner.metricsSource ?? "no data"}) scores higher than{" "}
                {candidateDisplayName(other)} on available metrics.
              </p>
            )}
          </div>
        </div>
        <dl className="space-y-1.5 text-xs">
          <div className="flex justify-between">
            <dt className="flex items-center gap-1.5 text-white/45">
              Overall score
              {winner && (
                <ScoreCalculationTooltip
                  overall={winnerOverall}
                  accS={winnerAcc}
                  relS={winnerRel}
                  consS={winnerCons}
                  stabS={winnerStab}
                  candidate={winner}
                />
              )}
            </dt>
            <dd className="font-mono text-white">{winnerOverall !== null ? `${winnerOverall.toFixed(0)}/100` : "—"}</dd>
          </div>
          <div className="flex justify-between"><dt className="text-white/45">vs. other candidate</dt><dd className="font-mono text-white">{improvementPct !== null ? `${improvementPct >= 0 ? "+" : ""}${improvementPct.toFixed(0)}%` : "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-white/45">Ready for production</dt><dd className="font-mono text-white">{winner?.version ? "Yes" : "No"}</dd></div>
        </dl>
        {error && <p className="text-[11px] text-rose-300">{error}</p>}
        {done ? (
          <p className="rounded-md border border-lime-200/30 bg-lime-100/10 px-3 py-2 text-[11px] text-lime-100">
            Promoted -- reload the Registry tab to see it reflected.
          </p>
        ) : !alreadyProduction && winner?.version ? (
          <button
            type="button"
            onClick={handlePromote}
            disabled={promoting}
            data-testid="promote-recommended"
            className="flex w-full items-center justify-center gap-1.5 rounded-md bg-lime-100 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-50"
          >
            <Rocket className="h-3.5 w-3.5" /> {promoting ? "Promoting…" : `Promote ${candidateDisplayName(winner)} to Production`}
          </button>
        ) : null}
      </div>
    </Card>
  );
}

function KeyMetricsTable({
  candA, candB,
}: {
  candA: ComparisonCandidate | null;
  candB: ComparisonCandidate | null;
}) {
  type Row = {
    label: string;
    lowerIsBetter: boolean;
    valueA: number | null;
    valueB: number | null;
    fmt: (v: number) => string;
  };
  const rows: Row[] = [
    { label: "Accuracy (MAPE)", lowerIsBetter: true, valueA: candA?.accuracyMape ?? null, valueB: candB?.accuracyMape ?? null, fmt: (v) => `${v.toFixed(2)}%` },
    { label: "Reliability (Coverage)", lowerIsBetter: false, valueA: candA?.reliabilityCoverage ?? null, valueB: candB?.reliabilityCoverage ?? null, fmt: (v) => `${(v * 100).toFixed(1)}%` },
    { label: "Consistency (Interval Width)", lowerIsBetter: true, valueA: candA?.consistencyWidthMw ?? null, valueB: candB?.consistencyWidthMw ?? null, fmt: (v) => `${v.toFixed(0)} MW` },
    { label: "Stability (Perf. Drift)", lowerIsBetter: true, valueA: candA?.driftDeltaMapePp ?? null, valueB: candB?.driftDeltaMapePp ?? null, fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}pp` },
  ];
  return (
    <Card title="Key Metrics Comparison" noPadding>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-white/5 text-[10px] uppercase tracking-wider text-white/40">
              <th className="px-4 py-2.5 font-medium">Metric</th>
              <th className="px-4 py-2.5 font-medium">{candidateDisplayName(candA)}</th>
              <th className="px-4 py-2.5 font-medium">{candidateDisplayName(candB)}</th>
              <th className="px-4 py-2.5 font-medium">Difference</th>
              <th className="px-4 py-2.5 font-medium">Better</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const both = row.valueA !== null && row.valueB !== null;
              const better = !both ? null : row.lowerIsBetter
                ? (row.valueA! <= row.valueB! ? "A" : "B")
                : (row.valueA! >= row.valueB! ? "A" : "B");
              const diff = both ? row.valueA! - row.valueB! : null;
              return (
                <tr key={row.label} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-2.5 text-white/70">{row.label}</td>
                  <td className="px-4 py-2.5 font-mono text-white">{row.valueA !== null ? row.fmt(row.valueA) : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-white">{row.valueB !== null ? row.fmt(row.valueB) : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-white/60">{diff !== null ? row.fmt(diff) : "—"}</td>
                  <td className="px-4 py-2.5">
                    {better === null ? (
                      <span className="text-white/30">—</span>
                    ) : diff === 0 ? (
                      <span className="inline-flex items-center gap-1 text-white/40">
                        <Minus className="h-3 w-3" /> Tie
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-emerald-200">
                        {row.lowerIsBetter === (diff! < 0) ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                        {better === "A" ? candidateDisplayName(candA) : candidateDisplayName(candB)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** There's exactly one real model in this system (`ecolens_lstm_demand`)
 * and `GET /v1/model` only ever reports whichever version is currently
 * `Production` (`registry.py`'s `load_bundle` hardcodes that stage) — so
 * unlike the old mock's fake 7-version expandable list, this renders
 * one real row (or an honest "not loaded yet" state). Phase 1's
 * `GET /v1/model/versions` will bring back a real multi-row list with
 * Staging/Archived versions too. */
const STAGE_COLORS: Record<string, string> = {
  Production: "bg-lime-100/15 text-lime-100 border-lime-200/30",
  Staging: "bg-sky-500/15 text-sky-200 border-sky-400/30",
  Archived: "bg-white/5 text-white/55 border-white/10",
};

/** Real multi-row training history from `GET /v1/model/versions` --
 * supersedes Phase 0's single-row placeholder (`fetchModelInfo()` only
 * ever reports the current Production version). `[]` is a real,
 * expected state before the first model is ever trained+registered,
 * not an error -- rendered as an honest empty state rather than a
 * fabricated list. */
function RealModelVersions({
  versions, loaded, expandedVersion, onToggle, onPromote, promoting, onDelete, deleting,
}: {
  versions: ModelVersion[] | null;
  loaded: boolean;
  expandedVersion: string | null;
  onToggle: (version: string) => void;
  onPromote: (version: string, stage: "Production" | "Staging" | "Archived") => void;
  promoting: string | null;
  onDelete: (version: string) => void;
  deleting: string | null;
}) {
  if (!loaded) {
    return <p className="px-1 py-6 text-center text-xs text-white/40">Loading model versions…</p>;
  }
  if (!versions || versions.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-white/[0.02] px-4 py-6 text-center text-xs text-white/50">
        No model has been trained and registered yet.
      </div>
    );
  }
  return (
    <>
      {versions.map((v) => (
        <RealModelVersionRow
          key={v.version}
          version={v}
          expanded={expandedVersion === v.version}
          onToggle={() => onToggle(v.version)}
          onPromote={onPromote}
          promoting={promoting === v.version}
          onDelete={onDelete}
          deleting={deleting === v.version}
        />
      ))}
    </>
  );
}

function RealModelVersionRow({
  version, expanded, onToggle, onPromote, promoting, onDelete, deleting,
}: {
  version: ModelVersion;
  expanded: boolean;
  onToggle: () => void;
  onPromote: (version: string, stage: "Production" | "Staging" | "Archived") => void;
  promoting: boolean;
  onDelete: (version: string) => void;
  deleting: boolean;
}) {
  return (
    <div
      className="rounded-lg border border-white/5 bg-white/[0.02] transition-colors hover:border-white/10"
      data-testid={`model-row-${version.version}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-white/45" /> : <ChevronRight className="h-3.5 w-3.5 text-white/45" />}
          <span className="font-mono text-base font-semibold text-white">v{version.version}</span>
          <span className={cn(
            "rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
            STAGE_COLORS[version.stage] ?? "border-white/10 bg-white/5 text-white/55",
          )}>
            {version.stage}
          </span>
        </div>
        <span className="text-[10px] text-white/40">{formatRelativeTime(version.created_at)}</span>
      </button>
      {expanded && (
        <div className="border-t border-white/5 px-4 py-3 text-xs">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Field label="Run ID" value={version.run_id} />
            <Field label="Git SHA" value={version.git_sha ?? "—"} />
            <Field label="Created" value={new Date(version.created_at).toLocaleString("en-AU")} />
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            {Object.keys(version.metrics).length === 0 ? (
              <span className="text-[11px] text-white/40">No test metrics logged for this run.</span>
            ) : (
              Object.entries(version.metrics).map(([key, value]) => (
                <Field key={key} label={key.replace(/_/g, " ")} value={value.toFixed(4)} />
              ))
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {version.stage !== "Production" && (
              <button
                type="button"
                onClick={() => onPromote(version.version, "Production")}
                disabled={promoting}
                data-testid={`promote-${version.version}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-lime-200/30 bg-lime-100/10 px-2.5 py-1 text-[11px] font-semibold text-lime-100 hover:bg-lime-100/20 disabled:opacity-50"
              >
                <Rocket className="h-3 w-3" /> {promoting ? "Promoting…" : "Promote to Production"}
              </button>
            )}
            {version.stage !== "Staging" && (
              <button
                type="button"
                onClick={() => onPromote(version.version, "Staging")}
                disabled={promoting}
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
              >
                <GitBranch className="h-3 w-3" /> Move to Staging
              </button>
            )}
            {version.stage !== "Archived" && (
              <button
                type="button"
                onClick={() => onPromote(version.version, "Archived")}
                disabled={promoting}
                className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:bg-white/10 disabled:opacity-50"
              >
                <XCircle className="h-3 w-3" /> Archive
              </button>
            )}
            {/* Production is never offered here at all -- the server
             * rejects it (409) regardless, but hiding it client-side is
             * more honest than showing a button that's guaranteed to
             * fail. Staging/Archived/None-stage versions delete freely,
             * matching delete_model_version's own real gate. */}
            {version.stage !== "Production" && (
              <button
                type="button"
                onClick={() => onDelete(version.version)}
                disabled={deleting}
                data-testid={`delete-${version.version}`}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-rose-400/20 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-200 hover:bg-rose-500/20 disabled:opacity-50"
              >
                <Trash2 className="h-3 w-3" /> {deleting ? "Deleting…" : "Delete"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-white/5 bg-white/[0.02] px-2 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 truncate font-mono text-white/85" title={value}>{value}</div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Train form
// ────────────────────────────────────────────────────────────────────
/** Submission is deliberately disabled -- there is no real endpoint to
 * call yet (`POST /v1/model/train` lands in Phase 2; see TODO.md's
 * Model Operations section). The old mock faked a "queued" success
 * message via `setTimeout` with no backend behind it at all; showing
 * that fake success would just lie about a job having started. This
 * form is kept as a preview of the real request shape. */
/** Real, wired to `POST /v1/model/train` with `full_retrain: true`
 * (2026-08-11 -- previously this tab had no trigger endpoint at all,
 * just a disabled preview button whose epochs/batch-size/hidden-size/
 * layers/dropout fields didn't correspond to anything the backend
 * actually accepted). `training_worker.handle_training_trigger`
 * dispatches `full_retrain: true` to the real from-scratch trainer
 * (`ml.train.train_and_register`/`ml.train_tft.train_and_register_tft`
 * -- the same functions `ecolens-forecast train`/`train-tft` already
 * use from the CLI) instead of the incremental warm-start path the
 * Fine-tune tab's identical-looking trigger uses. Only exposes
 * `regions`/`window_hours` -- same "don't fabricate knobs the endpoint
 * doesn't accept" reasoning `FineTuneForm`'s own docstring states; a
 * from-scratch retrain still doesn't take epoch count, batch size, or
 * architecture hyperparameters over HTTP, those stay `Settings`-level
 * (`model_train_epochs` etc.), tunable only via direct config/CLI. */
function TrainForm({
  architecture,
  architectureLabel,
  onNewVersion,
}: {
  architecture: string;
  architectureLabel: string;
  onNewVersion: (versions: ModelVersion[]) => void;
}) {
  const [regionsInput, setRegionsInput] = useState("");
  // Real, much wider than Fine-tune's own 336h (14-day) default -- "full
  // retrain" is meant to be comprehensive, not a small recent nudge.
  // 8760h (365 days) safely exceeds every real region's current total
  // warehouse history (WEM, the longest, is ~44 real days as of
  // 2026-08-11), so this behaves like "use everything available" today
  // without needing a separate "unlimited" sentinel/code path -- see
  // `handle_training_trigger`'s own comment on why `full_retrain`
  // reuses the exact same `window_hours` mechanism Fine-tune uses.
  const [windowHours, setWindowHours] = useState(8760);
  const [status, setStatus] = useState<FineTuneState>({ state: "idle" });
  const cancelPoll = useRef<(() => void) | null>(null);

  useEffect(() => {
    cancelPoll.current?.();
    setStatus({ state: "idle" });
    return () => {
      cancelPoll.current?.();
    };
  }, [architecture]);

  // Real "current latest version" for this architecture -- backs the
  // loss-curve card below so it shows *something* real (whichever
  // version is currently Production, else the newest) even before this
  // session ever clicks "Start training", not just after.
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchModelVersions(architecture)
      .then((res) => {
        if (cancelled) return;
        const v = res.data.find((v) => v.stage === "Production") ?? res.data[0];
        setLatestVersion(v?.version ?? null);
      })
      .catch(() => {
        if (!cancelled) setLatestVersion(null);
      });
    return () => {
      cancelled = true;
    };
  }, [architecture]);

  // Once this session's own trigger actually succeeds, show *that*
  // fresh version's curve instead of the (now stale) previous latest --
  // `status.run.model_version` is the real version `log_and_register_run`
  // just registered.
  const lossCurveVersion =
    status.state === "success" ? status.run.model_version : latestVersion;

  const [lossCurve, setLossCurve] = useState<LossCurve | null>(null);
  const [lossCurveLoaded, setLossCurveLoaded] = useState(false);
  useEffect(() => {
    if (!lossCurveVersion) {
      setLossCurve(null);
      setLossCurveLoaded(true);
      return;
    }
    let cancelled = false;
    setLossCurveLoaded(false);
    fetchLossCurve(lossCurveVersion, architecture)
      .then((curve) => {
        if (!cancelled) setLossCurve(curve);
      })
      .catch(() => {
        if (!cancelled) setLossCurve(null);
      })
      .finally(() => {
        if (!cancelled) setLossCurveLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [lossCurveVersion, architecture]);

  const lossCurvePoints = lossCurve?.points ?? [];
  const lossCurveLabels = lossCurvePoints.map((p) => `${p.epoch}`);
  const trainLossSeries = lossCurvePoints.map((p) => p.train_loss ?? 0);
  const valLossSeries = lossCurvePoints.map((p) => p.val_loss ?? 0);
  const hasTrainLoss = lossCurvePoints.some((p) => p.train_loss !== null);
  const hasValLoss = lossCurvePoints.some((p) => p.val_loss !== null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const regions = regionsInput
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

    cancelPoll.current?.();
    setStatus({ state: "idle" });
    triggerTraining({
      regions: regions.length ? regions : undefined,
      windowHours,
      architecture: TRAIN_TRIGGER_ARCHITECTURE[architecture] ?? "lstm",
      fullRetrain: true,
    })
      .then((trigger) => {
        setStatus({ state: "queued", trigger });
        cancelPoll.current = pollForTrainingRun(
          architecture,
          trigger.triggered_by,
          trigger.queued_at,
          (match) => {
            if (match.state === "waiting") return;
            if (match.state === "running") {
              setStatus({ state: "running", trigger, run: match.run });
            } else if (match.state === "success") {
              setStatus({ state: "success", run: match.run });
              fetchModelVersions(architecture)
                .then((fresh) => onNewVersion(fresh.data))
                .catch(() => {});
            } else {
              setStatus({
                state: "error",
                message: match.run.error_message
                  ? `Training run failed: ${match.run.error_message}`
                  : "Training run failed (no error message logged).",
              });
            }
          },
          3000,
          // A from-scratch retrain over more real history genuinely
          // takes longer than an incremental fine-tune -- 4 minutes,
          // not Fine-tune's 2, before surfacing the same "worker may not
          // be running" real error instead of an unexplained spinner.
          240_000,
          () => {
            setStatus({
              state: "error",
              message:
                "No training run registered within 4 minutes. The training worker may not be " +
                "running, or the trigger event never reached it -- check Recent Training Runs " +
                "or the training-trigger dead-letter queue.",
            });
          },
        );
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "training trigger failed";
        setStatus({ state: "error", message });
      });
  }

  const submitting = status.state === "queued" || status.state === "running";

  return (
    <div className="space-y-4">
    <Card
      title={
        <span className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-emerald-200" />
          Train {architectureLabel} from scratch
        </span>
      }
      subtitle={
        architecture === "timesfm_demand_correction"
          ? "Publishes a real training-trigger event -- refits TimesFM's Ridge correction layer fresh on the selected window. Same real behavior as the Fine-tune tab for this architecture: frozen zero-shot TimesFM has no weights to warm-start from, so there's no separate 'from scratch' path to distinguish here."
          : "Publishes a real training-trigger event -- app.service.training_worker's consumer picks it up and trains a brand new version completely from scratch (fresh random init, not warm-started from the current Production/Staging version)."
      }
    >
      <form onSubmit={submit} className="space-y-4" data-testid="train-form">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Regions (optional)
            </label>
            <input
              type="text"
              value={regionsInput}
              onChange={(e) => setRegionsInput(e.target.value)}
              placeholder="e.g. NSW1, QLD1 -- blank uses the server default"
              data-testid="train-regions"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
            />
          </div>
          <div>
            <NumberField label="Window" unit="hours" value={windowHours} onChange={setWindowHours} min={1} max={87600} />
            {architecture !== "timesfm_demand_correction" && windowHours < 240 && (
              <p className="mt-1 text-[10px] text-amber-300/80">
                LSTM/TFT need roughly ~230+ real hours of history to build even one
                train/val/calibration window at this platform&apos;s current lookback/horizon --
                a window this short will likely fail with "not enough history".
              </p>
            )}
          </div>
        </div>
        {status.state === "queued" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200">
            <PlayCircle className="mr-1 inline h-3.5 w-3.5 animate-pulse" />
            Queued — {status.trigger.regions.join(", ")}, window {new Date(status.trigger.window_since).toLocaleString("en-AU")} → {new Date(status.trigger.window_until).toLocaleString("en-AU")}. Waiting for the training worker to pick it up…
          </div>
        )}
        {status.state === "running" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200" data-testid="train-progress">
            <div className="flex items-center gap-1.5">
              <PlayCircle className="h-3.5 w-3.5 animate-pulse" />
              Training run in progress — <ElapsedSince iso={status.run.started_at} /> elapsed.
            </div>
            <div className="mt-1 text-white/50">
              Regions: {status.run.regions.join(", ")} · window {formatRelativeTime(status.run.window_start)} → {formatRelativeTime(status.run.window_end)}
            </div>
          </div>
        )}
        {status.state === "success" && (
          <div className="rounded-md border border-emerald-200/30 bg-emerald-200/5 p-3 text-xs text-emerald-100" data-testid="train-success">
            Done — v{status.run.model_version ?? "?"} registered
            {status.run.finished_at
              ? ` in ${formatDurationBetween(status.run.started_at, status.run.finished_at)}`
              : ""}
            . See its training vs validation loss below, or check the Registry tab.
          </div>
        )}
        {status.state === "error" && (
          <p className="text-xs text-rose-300" data-testid="train-error">{status.message}</p>
        )}
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting}
            data-testid="start-train"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-semibold",
              submitting
                ? "cursor-not-allowed bg-white/10 text-white/40"
                : "bg-lime-100 text-black hover:bg-lime-100",
            )}
          >
            <PlayCircle className="h-3.5 w-3.5" /> Start training
          </button>
          <p className="text-[11px] text-white/45">
            Runs in <code className="rounded bg-black/30 px-1 font-mono">forecast-api</code>'s
            train-worker process, from scratch. The new version is registered in MLflow on completion.
          </p>
        </div>
      </form>
    </Card>

    <Card
      title="Training vs validation loss"
      subtitle={
        <>
          <span>
            Real per-epoch train_loss/val_loss for {architectureLabel}
            {lossCurveVersion ? ` v${lossCurveVersion}` : ""}
            {status.state === "success"
              ? " (just trained)"
              : lossCurveVersion
                ? " (current latest version)"
                : ""}
          </span>
          <br />
          <span className="font-mono text-white/35">GET /v1/model/versions/&#123;version&#125;/loss-curve</span>
        </>
      }
    >
      {!lossCurveLoaded ? (
        <p className="py-10 text-center text-xs text-white/40">Loading…</p>
      ) : !lossCurveVersion ? (
        <p className="py-10 text-center text-xs text-white/40">No registered version yet -- train one above.</p>
      ) : !hasTrainLoss ? (
        <p className="py-10 text-center text-xs text-white/40">v{lossCurveVersion} has no per-epoch history logged.</p>
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
          {!hasValLoss && (
            <p className="mt-2 text-center text-[10px] text-white/35">
              v{lossCurveVersion} has no val_loss logged — showing train_loss only.
            </p>
          )}
        </>
      )}
    </Card>
    </div>
  );
}

/** Real progress states, backed by `GET /v1/model/training-runs`
 * (`pollForTrainingRun`) -- `"running"`/`"success"` carry the actual
 * `meta._training_log` row so the UI can show real elapsed/duration
 * time instead of an undifferentiated spinner. */
type FineTuneState =
  | { state: "idle" }
  | { state: "queued"; trigger: TrainTrigger }
  | { state: "running"; trigger: TrainTrigger; run: TrainingRunLog }
  | { state: "success"; run: TrainingRunLog }
  | { state: "error"; message: string };

function formatDurationBetween(startIso: string, endIso: string): string {
  const totalSeconds = Math.max(
    0,
    Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000),
  );
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Ticks once a second off the real `startIso` timestamp -- not a
 * fabricated progress bar (there's no epoch/step count this platform's
 * training code reports), just an honest "how long has this actually
 * been running" clock. */
function ElapsedSince({ iso }: { iso: string }) {
  const [, forceTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => forceTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return <>{m}m {s}s</>;
}

/** Real, wired to `POST /v1/model/train` (Model Operations TODO.md
 * Phase 2), now sending the selected `architecture` too (fixed
 * 2026-08-11 -- see `TRAIN_TRIGGER_ARCHITECTURE` above). Only exposes
 * the fields that endpoint actually accepts -- `regions`/`window_hours`
 * -- not a base-version picker, learning rate, or epoch count: LSTM/TFT
 * fine-tune from whatever the current Production/Staging version is
 * (`train_and_register_incremental`/`_tft_incremental`) and always use
 * `Settings.incremental_train_epochs`/`incremental_train_lr`; TimesFM
 * instead re-fits its Ridge correction layer fresh on the selected
 * window each time (`service/ml/timesfm_correction.py` -- there's no
 * "previous version" to warm-start a plain Ridge regression from the
 * way there is for a neural net's weights). Neither path exposes
 * per-trigger tuning knobs -- fabricating those controls (like the old
 * mock did) would suggest a precision this endpoint doesn't have. */
function FineTuneForm({
  architecture,
  architectureLabel,
  onNewVersion,
}: {
  architecture: string;
  architectureLabel: string;
  onNewVersion: (versions: ModelVersion[]) => void;
}) {
  const [regionsInput, setRegionsInput] = useState("");
  // Real bug, confirmed live 2026-08-11: this used to default to 24,
  // matching forecast-api's own old (also-fixed) `Settings.
  // incremental_train_window_hours` default -- both guaranteed
  // `train_model`'s "not enough history to build train/val/calibration
  // windows" error every time for LSTM/TFT (lookback=24, horizon=48
  // needs ~196+ real hourly rows across train/val/cal; 24h of calendar
  // time is at most 24 rows). 336h (14 days) matches forecast-api's new
  // default -- see that field's own docstring for the full math.
  const [windowHours, setWindowHours] = useState(336);
  const [status, setStatus] = useState<FineTuneState>({ state: "idle" });
  const cancelPoll = useRef<(() => void) | null>(null);

  // Switching which model to fine-tune mid-poll would otherwise leave a
  // stale "queued"/"polling"/"error" status from the *previous*
  // architecture's trigger showing under the newly-selected one --
  // cancel that poll and reset to idle so the form always reflects the
  // currently-selected architecture only.
  useEffect(() => {
    cancelPoll.current?.();
    setStatus({ state: "idle" });
    return () => {
      cancelPoll.current?.();
    };
  }, [architecture]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const regions = regionsInput
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

    cancelPoll.current?.();
    setStatus({ state: "idle" });
    triggerTraining({
      regions: regions.length ? regions : undefined,
      windowHours,
      architecture: TRAIN_TRIGGER_ARCHITECTURE[architecture] ?? "lstm",
    })
      .then((trigger) => {
        setStatus({ state: "queued", trigger });
        cancelPoll.current = pollForTrainingRun(
          architecture,
          trigger.triggered_by,
          trigger.queued_at,
          (match) => {
            if (match.state === "waiting") return; // still queued, no row yet -- keep showing "queued"
            if (match.state === "running") {
              setStatus({ state: "running", trigger, run: match.run });
            } else if (match.state === "success") {
              setStatus({ state: "success", run: match.run });
              fetchModelVersions(architecture)
                .then((fresh) => onNewVersion(fresh.data))
                .catch(() => {}); // registry refresh is best-effort -- the success message above is already real
            } else {
              setStatus({
                state: "error",
                message: match.run.error_message
                  ? `Training run failed: ${match.run.error_message}`
                  : "Training run failed (no error message logged).",
              });
            }
          },
          3000,
          120_000,
          // Real bug fix (2026-08-11): previously nothing ever left this
          // form stuck on "Waiting for the worker..." forever if the
          // real training-trigger consumer crashed or the real run
          // genuinely failed (e.g. a real window too short to build a
          // train/val/cal split). Surfaced as a real error now instead
          // of an unexplained stuck spinner.
          () => {
            setStatus({
              state: "error",
              message:
                "No training run registered within 2 minutes. The training worker may not be " +
                "running, or the trigger event never reached it -- check Recent Training Runs " +
                "or the training-trigger dead-letter queue.",
            });
          },
        );
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "training trigger failed";
        setStatus({ state: "error", message });
      });
  }

  const submitting = status.state === "queued" || status.state === "running";

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-emerald-200" />
          Fine-tune {architectureLabel}
        </span>
      }
      subtitle={
        architecture === "timesfm_demand_correction"
          ? "Publishes a real training-trigger event -- refits TimesFM's Ridge correction layer fresh on the selected window (no previous version to warm-start from)."
          : "Publishes a real training-trigger event -- app.service.training_worker's consumer picks it up and runs a warm-started incremental fine-tune from the current Production/Staging version."
      }
    >
      <form onSubmit={submit} className="space-y-4" data-testid="finetune-form">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Regions (optional)
            </label>
            <input
              type="text"
              value={regionsInput}
              onChange={(e) => setRegionsInput(e.target.value)}
              placeholder="e.g. NSW1, QLD1 -- blank uses the server default"
              data-testid="finetune-regions"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
            />
          </div>
          <div>
            <NumberField label="Window" unit="hours" value={windowHours} onChange={setWindowHours} min={1} max={720} />
            {architecture !== "timesfm_demand_correction" && windowHours < 240 && (
              <p className="mt-1 text-[10px] text-amber-300/80">
                LSTM/TFT need roughly ~230+ real hours of recent history to build even one
                train/val/calibration window at this platform&apos;s current lookback/horizon --
                a window this short will likely fail with "not enough history".
              </p>
            )}
          </div>
        </div>
        {status.state === "queued" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200">
            <PlayCircle className="mr-1 inline h-3.5 w-3.5 animate-pulse" />
            Queued — {status.trigger.regions.join(", ")}, window {new Date(status.trigger.window_since).toLocaleString("en-AU")} → {new Date(status.trigger.window_until).toLocaleString("en-AU")}. Waiting for the training worker to pick it up…
          </div>
        )}
        {status.state === "running" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200" data-testid="finetune-progress">
            <div className="flex items-center gap-1.5">
              <PlayCircle className="h-3.5 w-3.5 animate-pulse" />
              Training run in progress — <ElapsedSince iso={status.run.started_at} /> elapsed.
            </div>
            <div className="mt-1 text-white/50">
              Regions: {status.run.regions.join(", ")} · window {formatRelativeTime(status.run.window_start)} → {formatRelativeTime(status.run.window_end)}
            </div>
          </div>
        )}
        {status.state === "success" && (
          <div className="rounded-md border border-emerald-200/30 bg-emerald-200/5 p-3 text-xs text-emerald-100" data-testid="finetune-success">
            Done — v{status.run.model_version ?? "?"} registered
            {status.run.finished_at
              ? ` in ${formatDurationBetween(status.run.started_at, status.run.finished_at)}`
              : ""}
            . Switching to the Registry tab…
          </div>
        )}
        {status.state === "error" && (
          <p className="text-xs text-rose-300" data-testid="finetune-error">{status.message}</p>
        )}
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting}
            data-testid="start-finetune"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-semibold",
              submitting
                ? "cursor-not-allowed bg-white/10 text-white/40"
                : "bg-lime-100 text-black hover:bg-lime-100",
            )}
          >
            <PlayCircle className="h-3.5 w-3.5" /> Start fine-tune
          </button>
          <p className="text-[11px] text-white/45">
            Runs in <code className="rounded bg-black/30 px-1 font-mono">forecast-api</code>'s
            train-worker process. The new version is registered in MLflow on completion.
          </p>
        </div>
      </form>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────────
// Import tab -- registers an already-trained model bundle (trained
// anywhere: a notebook, a different machine, a one-off experiment) as a
// new registry version, without going through this service's own
// training loop. Two real bundle formats, two real endpoints:
//   - `.pt` (PyTorch state_dict) -> `POST /v1/model/versions/import` --
//     the bundle's own `manifest.json` declares LSTM vs TFT.
//   - `.onnx` -> `POST /v1/model/versions/import-onnx` (2026-08-21) --
//     open-ended/user-named, architecture is always reported back as
//     `"onnx_custom"`. Framework-agnostic: any model that exports to the
//     ONNX graph format works, not just LSTM/TFT re-exported.
// The format toggle below picks which endpoint `ImportForm` posts to;
// the response always reports which `model_name`/architecture it
// actually registered against (`ImportForm`'s `onImported` callback
// switches the shared `architecture` state to match, see the Import tab
// render block above).
// ────────────────────────────────────────────────────────────────────

type ImportFormat = "pt" | "onnx";

type ImportState =
  | { state: "idle" }
  | { state: "uploading" }
  | { state: "success"; result: ModelImportResult }
  | { state: "error"; message: string };

function ImportForm({
  onImported,
}: {
  onImported: (modelName: string, versions: ModelVersion[]) => void;
}) {
  const [format, setFormat] = useState<ImportFormat>("pt");
  const [file, setFile] = useState<File | null>(null);
  const [uploadedBy, setUploadedBy] = useState("");
  const [status, setStatus] = useState<ImportState>({ state: "idle" });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setStatus({ state: "uploading" });
    const upload = format === "onnx" ? importOnnxBundle : importModelBundle;
    upload(file, uploadedBy.trim() || undefined)
      .then((result) => {
        setStatus({ state: "success", result });
        // The import response reports the new version but not the full
        // registry list -- same "re-fetch the list after a real mutation"
        // pattern `TrainForm`/`FineTuneForm` already use after their own
        // trigger succeeds, just against `result.model_name` (decided by
        // the bundle itself) rather than the page's already-selected
        // architecture.
        fetchModelVersions(result.model_name)
          .then((fresh) => onImported(result.model_name, fresh.data))
          .catch(() => {}); // registry refresh is best-effort -- the success message above is already real
      })
      .catch((err) => {
        setStatus({
          state: "error",
          message: err instanceof Error ? err.message : "import failed",
        });
      });
  }

  const submitting = status.state === "uploading";

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Upload className="h-4 w-4 text-emerald-200" />
          Import a trained model bundle
        </span>
      }
      subtitle={
        <>
          <span>
            Upload a zip bundle trained anywhere (a notebook, another machine) and register it
            as a new registry version -- no training loop runs here. A live evaluation gate runs
            automatically against fresh warehouse data right after registration, same as a
            freshly-trained version.{" "}
            {format === "pt" ? (
              <>
                The bundle&apos;s own <code className="font-mono">manifest.json</code> decides
                the architecture (LSTM or TFT).
              </>
            ) : (
              <>
                Framework-agnostic -- any model exported to ONNX works, not just LSTM/TFT.
                Registers under the bundle&apos;s own chosen model name, tagged{" "}
                <code className="font-mono">onnx_custom</code>.
              </>
            )}
          </span>
          <br />
          <span className="font-mono text-white/35">
            POST /v1/model/versions/{format === "onnx" ? "import-onnx" : "import"}
          </span>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" data-testid="import-form">
        <div
          className="flex flex-wrap gap-1"
          role="tablist"
          aria-label="Bundle format"
          data-testid="import-format-selector"
        >
          <TabButton
            active={format === "pt"}
            onClick={() => {
              setFormat("pt");
              setFile(null);
            }}
            data-testid="import-format-pt"
          >
            PyTorch (.pt)
          </TabButton>
          <TabButton
            active={format === "onnx"}
            onClick={() => {
              setFormat("onnx");
              setFile(null);
            }}
            data-testid="import-format-onnx"
          >
            ONNX (.onnx)
          </TabButton>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Bundle (.zip)
            </label>
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              data-testid="import-file"
              className="block w-full text-xs text-white/60 file:mr-3 file:rounded-md file:border-0 file:bg-lime-100 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-black file:hover:bg-lime-200"
            />
            {format === "pt" ? (
              <p className="mt-1.5 text-[10px] text-white/35">
                Must contain <code className="font-mono">manifest.json</code>,{" "}
                <code className="font-mono">model_state_dict.pt</code>,{" "}
                <code className="font-mono">feature_scalers.json</code>, and{" "}
                <code className="font-mono">target_scaler.json</code> -- see
                service/ml/model_import.py for the exact format.
              </p>
            ) : (
              <p className="mt-1.5 text-[10px] text-white/35">
                Must contain <code className="font-mono">manifest.json</code>,{" "}
                <code className="font-mono">model.onnx</code>,{" "}
                <code className="font-mono">feature_scalers.json</code>, and{" "}
                <code className="font-mono">target_scaler.json</code> -- see
                service/ml/onnx_import.py for the exact format.
              </p>
            )}
          </div>
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Uploaded by (optional)
            </label>
            <input
              type="text"
              value={uploadedBy}
              onChange={(e) => setUploadedBy(e.target.value)}
              placeholder="e.g. your name -- tagged on the MLflow run"
              data-testid="import-uploaded-by"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
            />
          </div>
        </div>

        {status.state === "error" && (
          <p className="text-xs text-rose-300" data-testid="import-error">
            {status.message}
          </p>
        )}
        {status.state === "success" && (
          <div
            className="rounded-md border border-emerald-200/30 bg-emerald-200/5 p-3 text-xs text-emerald-100"
            data-testid="import-success"
          >
            <p>
              Registered{" "}
              {status.result.architecture === "onnx_custom"
                ? "ONNX"
                : status.result.architecture.toUpperCase()}{" "}
              v{status.result.model_version} ({status.result.model_name}). Switching to the
              Registry tab…
            </p>
            <p className="mt-1 text-white/60">
              Live evaluation gate:{" "}
              {status.result.eval_gate_passed === null
                ? "did not run (see server logs) -- registered in the None stage regardless."
                : status.result.eval_gate_passed
                  ? `passed (fresh walk-forward MAPE ${status.result.eval_gate_mape?.toFixed(2) ?? "—"}%).`
                  : `failed (fresh walk-forward MAPE ${status.result.eval_gate_mape?.toFixed(2) ?? "—"}%) -- registered in the None stage, review before promoting.`}
            </p>
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting || !file}
            data-testid="start-import"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-semibold",
              submitting || !file
                ? "cursor-not-allowed bg-white/10 text-white/40"
                : "bg-lime-100 text-black hover:bg-lime-100",
            )}
          >
            <Upload className="h-3.5 w-3.5" /> {submitting ? "Uploading…" : "Import bundle"}
          </button>
          <p className="text-[11px] text-white/45">
            Validated end-to-end before anything is registered — feature-set fingerprint, model
            weights, and a dummy-input sanity check. A bad bundle is rejected with a specific
            reason; nothing is half-registered. Never auto-promoted — lands in the{" "}
            <code className="font-mono">None</code> stage, same as any other new version.
          </p>
        </div>
      </form>
    </Card>
  );
}

function NumberField({
  label, unit, value, onChange, min, max, step,
}: {
  label: string;
  unit?: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
        {label}
      </label>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          min={min}
          max={max}
          step={step ?? 1}
          className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
        />
        {unit && (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[10px] text-white/40">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}
