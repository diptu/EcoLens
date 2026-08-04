/**
 * /dashboard/admin/operational-tasks — Operational control surface.
 *
 * Mirrors the "Operational Tasks" reference layout: 6 KPIs, Pipeline
 * Operations + Model Operations tables side by side, Active Tasks
 * with tabbed filters, Model Training & Tuning form, Recent
 * Training Runs, Scheduled Operations, and System Commands.
 *
 * Pipeline Operations is wired to real data-pipeline data (see
 * `todo-operational-tasks.md` for the full per-section plan): the same
 * `GET /v1/ingestion/public/pipelines` this session's Operations page
 * and Ingestion Pipeline page already use — real 6-pipeline inventory
 * (OpenElectricity, AEMO NEM, AEMO WEM, BoM, AEMO Public Holidays, dbt
 * warehouse build), not the old mock's 5 fictional vendors (ENTSO-E,
 * Open-Meteo, EIA, "Carbon Intensity API", ICE).
 *
 * Per-row "Run now" is real too: `triggerIngestionRun()`
 * (`POST /v1/data-sources/{id}/run`) — deliberately open, no auth
 * required (this platform has no sign-in at all; see `lib/ingestion.ts`'s
 * module docstring). The dbt warehouse-build "pipeline" (`source_id:
 * null`) still can't be triggered this way — that's a
 * `POST /v1/dbt/{subcommand}` call, a different, not-yet-bridged route.
 *
 * AEMO NEM/WEM additionally get a "Backfill" action
 * (`triggerBackfill()`, `POST /v1/data-sources/{id}/backfill`) with a
 * month/year picker — real historical data for the whole selected
 * month, not the 30-min-lookback "Run now" gets. Only these two:
 * `PIPELINE_CATALOG[].backfillable` is `false` for the other 3 sources
 * because their backfill path isn't actually date-anchored yet (see
 * that flag's own docstring in `lib/ingestion.ts`).
 *
 * The other 7 sections (KPI row, Model Operations, Active Tasks, Model
 * Training & Tuning, Recent Training Runs, Scheduled Operations, System
 * Commands) are still the old mock; see `todo-operational-tasks.md` for
 * what's real/fake in each.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  Cpu,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getActiveTasks,
  getOperationalKpis,
  getScheduledOps,
  getSystemCommands,
  type ActiveTask,
  type OperationalKpi,
  type ScheduledOp,
  type SystemCommand,
  type TaskStatus,
  type TaskType,
} from "@/lib/admin-dashboard";
import {
  fetchModelInfo,
  fetchModelVersions,
  pollForNewModelVersion,
  type ModelInfo,
  type ModelVersion,
} from "@/lib/emissions";
import {
  PIPELINE_CATALOG,
  triggerTraining,
  fetchTrainingRuns,
  triggerIngestionRun,
  pollLatestRun,
  triggerBackfill,
  pollBackfillSummary,
  monthToRange,
  formatRelativeTime,
  TriggerIngestionError,
  type RunStatus,
  type TrainingRunLog,
  type BackfillTrigger,
  type BackfillProgress,
} from "@/lib/ingestion";

// ────────────────────────────────────────────────────────────────────
// Icons
// ────────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Play, Database, Cpu, Calendar, RefreshCw, Trash2, Search, Activity,
};

function IconFor({ name, className = "h-4 w-4" }: { name: string; className?: string }) {
  const I = ICON_MAP[name] ?? Activity;
  return <I className={className} />;
}

// ────────────────────────────────────────────────────────────────────
// Building blocks
// ────────────────────────────────────────────────────────────────────

function OperationalKpiCard({ k }: { k: OperationalKpi }) {
  const Icon = ICON_MAP[k.icon] ?? Activity;
  const toneColor = {
    ok: "text-emerald-100",
    warn: "text-amber-200",
    neutral: "text-white/60",
  }[k.tone];
  const subTone = k.tone === "warn" ? "text-amber-200" : "text-white/50";
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className="mb-2 flex items-center gap-2">
        <Icon className={cn("h-4 w-4", toneColor)} />
        <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
      </div>
      <div className="text-2xl font-bold text-white">{k.value}</div>
      <p className={cn("mt-1 text-[11px]", subTone)}>{k.sub}</p>
    </div>
  );
}

type RowStatus = "idle" | RunStatus;

/** Reflects the actual trigger state of a real `POST /v1/data-sources/
 * {id}/run` (see `lib/ingestion.ts`'s module docstring — deliberately
 * open, no auth required) -- there's no "list pipelines with health"
 * endpoint used here, so this chip only ever shows what a real
 * trigger+poll actually observed for this pipeline in this session
 * (idle until triggered). */
function PipelineStatusChip({ status }: { status: RowStatus }) {
  const map = {
    idle:        { color: "border-white/10 bg-white/5 text-white/60", icon: Calendar, label: "Idle" },
    queued:      { color: "border-amber-300/40 bg-amber-300/10 text-amber-200", icon: Loader2, label: "Queued" },
    running:     { color: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200", icon: Loader2, label: "Running" },
    staged:      { color: "border-sky-300/40 bg-sky-300/10 text-sky-200", icon: Loader2, label: "Staged" },
    success:     { color: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100", icon: Check, label: "Success" },
    failed:      { color: "border-rose-300/40 bg-rose-300/10 text-rose-200", icon: AlertTriangle, label: "Failed" },
    sync_failed: { color: "border-rose-300/40 bg-rose-300/10 text-rose-200", icon: AlertTriangle, label: "Sync Failed" },
    partial:     { color: "border-amber-300/40 bg-amber-300/10 text-amber-200", icon: AlertTriangle, label: "Partial" },
  };
  const m = map[status];
  const Icon = m.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium", m.color)}>
      <Icon className={cn("h-3 w-3", (status === "queued" || status === "running" || status === "staged") && "animate-spin")} />
      {m.label}
    </span>
  );
}

/** `ModelInfo.stage` is whatever MLflow's registry actually reports —
 * today that's always "Production" (`GET /v1/model` only ever loads
 * the Production version, see `service/ml/registry.py`'s `load_bundle`
 * default) or absent entirely (`status: "not_loaded"`, a real state
 * before the first model is ever trained+promoted). Not a closed union
 * like the old mock's deployed/staging/deprecated -- Phase 1's
 * `GET /v1/model/versions` will surface Staging/Archived for real. */
function ModelStageChip({ stage }: { stage: string | null }) {
  if (!stage) {
    return (
      <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] font-medium text-white/50">
        Not loaded
      </span>
    );
  }
  const color =
    stage === "Production"
      ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
      : "border-amber-300/40 bg-amber-300/10 text-amber-200";
  return <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", color)}>{stage}</span>;
}

function TaskStatusChip({ status }: { status: TaskStatus }) {
  const map: Record<TaskStatus, { color: string; icon: React.ComponentType<{ className?: string }> }> = {
    running:   { color: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",         icon: Loader2 },
    queued:    { color: "border-amber-300/40 bg-amber-300/10 text-amber-200",       icon: Calendar },
    completed: { color: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100", icon: CheckCircle2 },
    failed:    { color: "border-rose-300/40 bg-rose-300/10 text-rose-200",           icon: AlertTriangle },
  };
  const m = map[status];
  const Icon = m.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", m.color.replace("border-", "text-"))}>
      <Icon className={cn("h-3 w-3", status === "running" && "animate-spin")} />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function ProgressBar({ value, status }: { value: number; status: TaskStatus }) {
  const color = {
    running:   "bg-cyan-300",
    queued:    "bg-amber-300",
    completed: "bg-emerald-300",
    failed:    "bg-rose-300",
  }[status];
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-20 overflow-hidden rounded-full bg-white/5">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${value}%` }} />
      </div>
      <span className="w-8 text-right text-[10px] tabular-nums text-white/65">{value}%</span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Page
// ────────────────────────────────────────────────────────────────────

const TASK_TAB_LABELS: Array<{ value: TaskStatus | "all"; label: string }> = [
  { value: "all",       label: "All"       },
  { value: "running",   label: "Running"   },
  { value: "queued",    label: "Queued"    },
  { value: "completed", label: "Completed" },
  { value: "failed",    label: "Failed"    },
];

type RowState = { status: RowStatus; records?: number | null; error?: string };

type TrainStatus =
  | { state: "idle" }
  | { state: "queued" }
  | { state: "polling" }
  | { state: "error"; message: string };

type BackfillState =
  | { state: "submitting" }
  | { state: "running"; trigger: BackfillTrigger; progress: BackfillProgress }
  | { state: "done"; trigger: BackfillTrigger; progress: BackfillProgress }
  | { state: "error"; message: string };

export default function OperationalTasksPage() {
  const kpis = useMemo(() => getOperationalKpis(), []);
  const [pipelineRows, setPipelineRows] = useState<Record<string, RowState>>({});
  const cancelFns = useRef<Record<string, () => void>>({});
  const [backfillModal, setBackfillModal] = useState<{ sourceId: string; label: string } | null>(null);
  const [backfillStatus, setBackfillStatus] = useState<Record<string, BackfillState>>({});
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [modelInfoLoaded, setModelInfoLoaded] = useState(false);
  const [modelVersions, setModelVersions] = useState<ModelVersion[] | null>(null);
  const [modelVersionsLoaded, setModelVersionsLoaded] = useState(false);
  const [trainStatus, setTrainStatus] = useState<TrainStatus>({ state: "idle" });
  const [trainingRuns, setTrainingRuns] = useState<TrainingRunLog[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTrainingRuns(5)
      .then((r) => {
        if (!cancelled) setTrainingRuns(r.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // The `model_training`-typed rows are real (`meta._training_log`,
  // Model Operations TODO.md Phase 4); the other 6 task types
  // (ingestion, data_quality, feature_build, forecast, report, anomaly)
  // stay mock -- nothing else logs "a task is in flight" anywhere yet.
  const allTasks = useMemo(() => {
    const mockTasks = getActiveTasks().filter((t) => t.type !== "model_training");
    const realTrainingTasks: ActiveTask[] = (trainingRuns ?? []).map((r) => ({
      id: r.id,
      type: "model_training",
      target: r.model_name,
      triggered_by: r.triggered_by,
      started_at: formatRelativeTime(r.started_at),
      status: r.status === "running" ? "running" : r.status === "success" ? "completed" : "failed",
      progress: r.status === "running" ? 50 : 100,
    }));
    return [...realTrainingTasks, ...mockTasks];
  }, [trainingRuns]);
  const scheduled = useMemo(() => getScheduledOps(), []);
  const commands = useMemo(() => getSystemCommands(), []);

  const [tab, setTab] = useState<TaskStatus | "all">("all");
  const [trainRegionsInput, setTrainRegionsInput] = useState("");
  const [trainWindowHours, setTrainWindowHours] = useState(24);

  useEffect(() => {
    return () => {
      Object.values(cancelFns.current).forEach((cancel) => cancel());
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchModelInfo()
      .then((info) => {
        if (!cancelled) setModelInfo(info);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setModelInfoLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchModelVersions()
      .then((r) => {
        if (!cancelled) setModelVersions(r.data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setModelVersionsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function triggerFineTune(opts?: { regions?: string[]; windowHours?: number }) {
    cancelFns.current["__model_training__"]?.();
    setTrainStatus({ state: "queued" });
    const sinceVersion = modelVersions?.[0]?.version ?? null;

    triggerTraining(opts)
      .then(() => {
        fetchTrainingRuns(5).then((r) => setTrainingRuns(r.data)).catch(() => {});
        cancelFns.current["__model_training__"] = pollForNewModelVersion(sinceVersion, (versions) => {
          setTrainStatus({ state: "polling" });
          fetchTrainingRuns(5).then((r) => setTrainingRuns(r.data)).catch(() => {});
          const newest = versions.data[0]?.version ?? null;
          if (newest !== sinceVersion) {
            setModelVersions(versions.data);
            fetchModelInfo().then(setModelInfo).catch(() => {});
            setTrainStatus({ state: "idle" });
          }
        });
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "training trigger failed";
        setTrainStatus({ state: "error", message });
      });
  }

  function triggerPipeline(sourceId: string) {
    cancelFns.current[sourceId]?.();
    setPipelineRows((prev) => ({ ...prev, [sourceId]: { status: "queued" } }));

    triggerIngestionRun(sourceId)
      .then(() => {
        cancelFns.current[sourceId] = pollLatestRun(sourceId, (latest) => {
          if (!latest) return;
          setPipelineRows((prev) => ({
            ...prev,
            [sourceId]: {
              status: latest.status,
              records: latest.records_inserted ?? latest.records_fetched,
            },
          }));
        });
      })
      .catch((err) => {
        const message = err instanceof TriggerIngestionError ? err.message : "trigger failed";
        setPipelineRows((prev) => ({ ...prev, [sourceId]: { status: "failed", error: message } }));
      });
  }

  function submitBackfill(sourceId: string, yearMonth: string) {
    const { start, end } = monthToRange(yearMonth);
    cancelFns.current[sourceId]?.();
    setBackfillStatus((prev) => ({ ...prev, [sourceId]: { state: "submitting" } }));
    setPipelineRows((prev) => ({ ...prev, [sourceId]: { status: "queued" } }));

    triggerBackfill(sourceId, start, end)
      .then((trigger) => {
        setBackfillModal(null);

        // A backfill is dozens of independent per-day runs, not one run
        // -- poll the whole estimated duration (+ buffer), not the 30s
        // `pollLatestRun` default sized for a single "Run now" click,
        // and tally real per-day outcomes instead of one flickering
        // "latest run" status (see `pollBackfillSummary`'s docstring).
        const timeoutMs = Math.max(30_000, trigger.estimated_duration_seconds * 1000 + 30_000);
        cancelFns.current[sourceId] = pollBackfillSummary(
          sourceId,
          trigger.queued_at,
          trigger.total_chunks,
          (progress) => {
            const isDone = progress.total > 0 && progress.done >= progress.total;
            setBackfillStatus((prev) => ({
              ...prev,
              [sourceId]: { state: isDone ? "done" : "running", trigger, progress },
            }));
            setPipelineRows((prev) => ({
              ...prev,
              [sourceId]: {
                status: isDone ? (progress.failed > 0 ? "partial" : "success") : "running",
              },
            }));
          },
          3000,
          timeoutMs,
        );
      })
      .catch((err) => {
        const message = err instanceof TriggerIngestionError ? err.message : "backfill trigger failed";
        setBackfillStatus((prev) => ({ ...prev, [sourceId]: { state: "error", message } }));
        setPipelineRows((prev) => ({ ...prev, [sourceId]: { status: "idle" } }));
      });
  }

  const taskCounts = useMemo(() => ({
    all:       allTasks.length,
    running:   allTasks.filter((t) => t.status === "running").length,
    queued:    allTasks.filter((t) => t.status === "queued").length,
    completed: allTasks.filter((t) => t.status === "completed").length,
    failed:    allTasks.filter((t) => t.status === "failed").length,
  }), [allTasks]);

  const tasks = useMemo(() => {
    if (tab === "all") return allTasks;
    return allTasks.filter((t) => t.status === tab);
  }, [allTasks, tab]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <Activity className="h-6 w-6 text-emerald-100" />
            Operational Tasks
          </h1>
          <p className="mt-1 text-sm text-white/60">
            Trigger pipelines, retrain models, tune parameters and manage system operations.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white/80 hover:border-emerald-200/30">
            <Sparkles className="h-3.5 w-3.5" />
            Quick Actions
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {kpis.map((k) => (
          <OperationalKpiCard key={k.label} k={k} />
        ))}
      </div>

      {/* Pipeline + Model ops */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Pipeline Operations</h2>
              <p className="text-xs text-white/50">Trigger data ingestion pipelines.</p>
            </div>
          </div>
          <PipelineTable
            rows={pipelineRows}
            onTrigger={triggerPipeline}
            backfillStatus={backfillStatus}
            onOpenBackfill={(sourceId, label) => setBackfillModal({ sourceId, label })}
          />
          <a
            href="/dashboard/ingestion/"
            className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline"
          >
            View all pipelines <ChevronDown className="h-3 w-3" />
          </a>
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Model Operations</h2>
              <p className="text-xs text-white/50">The one real model in this system.</p>
            </div>
            <button
              onClick={() => triggerFineTune()}
              disabled={trainStatus.state === "queued" || trainStatus.state === "polling"}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-semibold",
                trainStatus.state === "queued" || trainStatus.state === "polling"
                  ? "cursor-not-allowed bg-white/10 text-white/40"
                  : "bg-emerald-200/15 text-emerald-100 hover:bg-emerald-200/20",
              )}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", trainStatus.state === "polling" && "animate-spin")} />
              Fine-tune
            </button>
          </div>
          <ModelInfoTable info={modelInfo} loaded={modelInfoLoaded} />
          {trainStatus.state === "queued" && (
            <p className="mt-2 text-[11px] text-sky-300">Training trigger queued — waiting for the worker to pick it up.</p>
          )}
          {trainStatus.state === "polling" && (
            <p className="mt-2 text-[11px] text-sky-300">Waiting for a new registered version — this can take a few minutes.</p>
          )}
          {trainStatus.state === "error" && (
            <p className="mt-2 text-[11px] text-rose-300">{trainStatus.message}</p>
          )}
          <a
            href="/dashboard/models/"
            className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline"
          >
            View model registry <ChevronDown className="h-3 w-3" />
          </a>
        </Card>
      </div>

      {/* Active Tasks + Training form */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-white">Active Tasks</h2>
            <p className="text-xs text-white/50">Real-time view of running and queued tasks.</p>
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-1">
            {TASK_TAB_LABELS.map((t) => (
              <button
                key={t.value}
                onClick={() => setTab(t.value)}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs",
                  tab === t.value
                    ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                    : "border-white/10 bg-white/[0.02] text-white/60 hover:border-white/20",
                )}
              >
                {t.label} ({taskCounts[t.value]})
              </button>
            ))}
          </div>
          <ActiveTasksTable rows={tasks} />
          <button className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline">
            View all tasks <ChevronDown className="h-3 w-3" />
          </button>
        </Card>

        <Card>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-white">Model Training &amp; Tuning</h2>
            <p className="text-xs text-white/50">
              Publishes a real training-trigger event to data-pipeline's train-worker --
              only the incremental fine-tune path exists (see the Model Registry page's
              Train tab for the still-unbuilt full-retrain path).
            </p>
          </div>
          <div className="space-y-3">
            <Field label="Regions (optional)">
              <input
                type="text"
                value={trainRegionsInput}
                onChange={(e) => setTrainRegionsInput(e.target.value)}
                placeholder="e.g. NSW1, QLD1 -- blank uses the server default"
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
              />
            </Field>
            <Field label="Window (hours)">
              <input
                type="number"
                min={1}
                max={720}
                value={trainWindowHours}
                onChange={(e) => setTrainWindowHours(parseInt(e.target.value, 10) || 1)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              />
            </Field>
            {trainStatus.state === "queued" && (
              <p className="text-xs text-sky-300">Queued — waiting for the worker to pick it up.</p>
            )}
            {trainStatus.state === "polling" && (
              <p className="text-xs text-sky-300">Waiting for a new registered version — this can take a few minutes.</p>
            )}
            {trainStatus.state === "error" && (
              <p className="text-xs text-rose-300">{trainStatus.message}</p>
            )}
            <button
              onClick={() => {
                const regions = trainRegionsInput.split(",").map((r) => r.trim()).filter(Boolean);
                triggerFineTune({ regions: regions.length ? regions : undefined, windowHours: trainWindowHours });
              }}
              disabled={trainStatus.state === "queued" || trainStatus.state === "polling"}
              className={cn(
                "inline-flex w-full items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold",
                trainStatus.state === "queued" || trainStatus.state === "polling"
                  ? "cursor-not-allowed bg-white/10 text-white/40"
                  : "bg-emerald-200 text-black hover:bg-emerald-100",
              )}
            >
              <Play className="h-4 w-4" />
              Start Fine-tune
            </button>
          </div>
        </Card>
      </div>

      {/* Recent training runs (right rail) — wait, schema wants it next to training form */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="lg:col-start-2">
          <div className="mb-3">
            <h2 className="text-base font-semibold text-white">Recent Training Runs</h2>
          </div>
          <TrainingRunsList versions={modelVersions} loaded={modelVersionsLoaded} />
        </Card>
      </div>

      {/* Scheduled operations + system commands */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-white">Scheduled Operations</h2>
            <p className="text-xs text-white/50">Manage cron schedules for automated operations.</p>
          </div>
          <ScheduledTable rows={scheduled} />
          <button className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline">
            View all schedules <ChevronDown className="h-3 w-3" />
          </button>
        </Card>

        <Card>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-white">System Commands</h2>
            <p className="text-xs text-white/50">Execute system level commands.</p>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {commands.map((c) => <CommandCard key={c.id} c={c} />)}
          </div>
        </Card>
      </div>

      {backfillModal && (
        <BackfillModal
          sourceId={backfillModal.sourceId}
          label={backfillModal.label}
          status={backfillStatus[backfillModal.sourceId]}
          onClose={() => setBackfillModal(null)}
          onSubmit={submitBackfill}
        />
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tables
// ────────────────────────────────────────────────────────────────────

function PipelineTable({
  rows,
  onTrigger,
  backfillStatus,
  onOpenBackfill,
}: {
  rows: Record<string, RowState>;
  onTrigger: (sourceId: string) => void;
  backfillStatus: Record<string, BackfillState>;
  onOpenBackfill: (sourceId: string, label: string) => void;
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Pipeline Name</th>
          <th className="py-2">Status</th>
          <th className="py-2 text-right">Actions</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        {PIPELINE_CATALOG.filter((p) => p.triggerable && p.sourceId).map((p) => {
          const sourceId = p.sourceId as string;
          const row = rows[sourceId] ?? { status: "idle" as RowStatus };
          const busy = row.status === "queued" || row.status === "running" || row.status === "staged";
          const runDisabled = busy;
          const runTitle = "Run now";
          const backfill = backfillStatus[sourceId];
          return (
            <tr key={p.id} className="text-white/85">
              <td className="py-2 pr-2">{p.label}</td>
              <td className="py-2 pr-2">
                <PipelineStatusChip status={row.status} />
                {(row.status === "success" || row.status === "partial") && row.records != null && (
                  <span className="ml-1 text-[11px] text-white/50">{row.records} records</span>
                )}
                {(row.status === "failed" || row.status === "sync_failed") && row.error && (
                  <span className="ml-1 text-[11px] text-rose-300" title={row.error}>{row.error}</span>
                )}
                {backfill?.state === "running" && (
                  <div className="mt-0.5 text-[11px] text-sky-300">
                    Backfilling — {backfill.progress.done}/{backfill.progress.total} day(s) done
                    {backfill.progress.failed > 0 && ` (${backfill.progress.failed} failed)`}
                  </div>
                )}
                {backfill?.state === "done" && (
                  <div className="mt-0.5 text-[11px] text-white/50">
                    Backfill complete — {backfill.progress.succeeded}/{backfill.progress.total} succeeded
                    {backfill.progress.failed > 0 && `, ${backfill.progress.failed} failed`}
                  </div>
                )}
                {backfill?.state === "error" && (
                  <div className="mt-0.5 text-[11px] text-rose-300" title={backfill.message}>
                    Backfill: {backfill.message}
                  </div>
                )}
              </td>
              <td className="py-2 text-right">
                <div className="inline-flex items-center gap-2">
                  <button
                    disabled={runDisabled}
                    onClick={() => onTrigger(sourceId)}
                    title={runTitle}
                    className={cn(
                      "rounded p-1",
                      runDisabled
                        ? "cursor-not-allowed text-white/25"
                        : "text-white/50 hover:bg-white/5 hover:text-white",
                    )}
                  >
                    {busy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                  </button>
                  {p.backfillable && (() => {
                    const backfillBusy = backfill?.state === "submitting" || backfill?.state === "running";
                    return (
                      <button
                        disabled={backfillBusy}
                        onClick={() => onOpenBackfill(sourceId, p.label)}
                        title={backfillBusy ? "A backfill is already running for this source" : "Backfill a specific month"}
                        className={cn(
                          "rounded p-1",
                          backfillBusy
                            ? "cursor-not-allowed text-white/25"
                            : "text-white/50 hover:bg-white/5 hover:text-white",
                        )}
                      >
                        <Database className="h-3.5 w-3.5" />
                      </button>
                    );
                  })()}
                  <a
                    href="/dashboard/ingestion/"
                    className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white"
                    title="View details on the Ingestion Pipeline page"
                  >
                    <Activity className="h-3.5 w-3.5" />
                  </a>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Defaults to last month, not the current (partial) one — backfilling a
 * month that's still in progress would silently under-fetch it and look
 * like a bug. Users can still pick the current month explicitly. */
function defaultBackfillMonth(): string {
  const now = new Date();
  const prev = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1));
  return `${prev.getUTCFullYear()}-${String(prev.getUTCMonth() + 1).padStart(2, "0")}`;
}

function BackfillModal({
  sourceId,
  label,
  status,
  onClose,
  onSubmit,
}: {
  sourceId: string;
  label: string;
  status?: BackfillState;
  onClose: () => void;
  onSubmit: (sourceId: string, yearMonth: string) => void;
}) {
  const [yearMonth, setYearMonth] = useState(defaultBackfillMonth);
  const submitting = status?.state === "submitting";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-white/10 bg-[#0a1410] p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Backfill — {label}</h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-3 text-xs text-white/60">
          Fetches real historical data for every day in the selected month from the
          source's own archive — not a repeated "last 30 min" run.
        </p>
        <Field label="Month">
          <input
            type="month"
            value={yearMonth}
            onChange={(e) => setYearMonth(e.target.value)}
            className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
          />
        </Field>
        {status?.state === "error" && (
          <p className="mt-2 text-xs text-rose-300">{status.message}</p>
        )}
        <button
          disabled={submitting || !yearMonth}
          onClick={() => onSubmit(sourceId, yearMonth)}
          className={cn(
            "mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold",
            submitting || !yearMonth
              ? "cursor-not-allowed bg-white/10 text-white/40"
              : "bg-emerald-200 text-black hover:bg-emerald-100",
          )}
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Database className="h-4 w-4" />
          )}
          Start Backfill
        </button>
      </div>
    </div>
  );
}

/** Renders `GET /v1/model`'s single row honestly -- there is exactly one
 * real model in this system (see this file's module docstring), so
 * unlike the old mock's 5-row fake table, this either shows that one
 * model's real fields or an explicit "not loaded yet" state (a real,
 * expected condition before the first model is ever trained+promoted,
 * not an error). Metrics are rendered generically from whatever keys
 * `info.metrics` actually has -- real training only ever logs
 * `test_mape`/`test_coverage_raw`/`test_coverage_calibrated` (see
 * `data-pipeline/app/service/ml/train.py`), not the old mock's
 * fabricated MAPE+RMSE pair. */
function ModelInfoTable({ info, loaded }: { info: ModelInfo | null; loaded: boolean }) {
  if (!loaded) {
    return <p className="py-4 text-center text-xs text-white/40">Loading model info…</p>;
  }
  if (!info || info.status === "not_loaded") {
    return (
      <div className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/50">
        No model has been trained and promoted to Production yet
        {info?.name ? ` (${info.name})` : ""}.
      </div>
    );
  }
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Model Name</th>
          <th className="py-2">Version</th>
          <th className="py-2">Stage</th>
          <th className="py-2">Loaded</th>
          <th className="py-2">Metrics</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        <tr className="text-white/85">
          <td className="py-2 pr-2">{info.name}</td>
          <td className="py-2 pr-2">
            {info.version ? (
              <span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[11px] text-purple-200">v{info.version}</span>
            ) : (
              "—"
            )}
          </td>
          <td className="py-2 pr-2"><ModelStageChip stage={info.stage} /></td>
          <td className="py-2 pr-2 text-white/60">{formatRelativeTime(info.loaded_at)}</td>
          <td className="py-2 pr-2 text-[11px] text-white/70">
            {Object.keys(info.metrics).length === 0
              ? "—"
              : Object.entries(info.metrics).map(([key, value]) => (
                  <div key={key}>
                    {key.replace(/_/g, " ")}: {value.toFixed(2)}
                  </div>
                ))}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

function ActiveTasksTable({ rows }: { rows: ActiveTask[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Task ID</th>
          <th className="py-2">Type</th>
          <th className="py-2">Target</th>
          <th className="py-2">Triggered By</th>
          <th className="py-2">Started</th>
          <th className="py-2">Status</th>
          <th className="py-2">Progress</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        {rows.map((t) => (
          <tr key={t.id} className="text-white/85">
            <td className="py-2 pr-2 font-mono text-[11px] text-white/70">{t.id}</td>
            <td className="py-2 pr-2 text-white/70">{t.type.replace("_", " ")}</td>
            <td className="py-2 pr-2">{t.target}</td>
            <td className="py-2 pr-2 text-white/60">{t.triggered_by}</td>
            <td className="py-2 pr-2 text-[11px] text-white/50">{t.started_at}</td>
            <td className="py-2 pr-2"><TaskStatusChip status={t.status} /></td>
            <td className="py-2"><ProgressBar value={t.progress} status={t.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ScheduledTable({ rows }: { rows: ScheduledOp[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Schedule Name</th>
          <th className="py-2">Task Type</th>
          <th className="py-2">Cron Expression</th>
          <th className="py-2">Next Run</th>
          <th className="py-2">Last Run</th>
          <th className="py-2">Status</th>
          <th className="py-2 text-right">Actions</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        {rows.map((s) => (
          <tr key={s.id} className="text-white/85">
            <td className="py-2 pr-2">{s.name}</td>
            <td className="py-2 pr-2 text-white/60">{s.type.replace("_", " ")}</td>
            <td className="py-2 pr-2">
              <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-[11px] text-emerald-100">{s.cron}</code>
            </td>
            <td className="py-2 pr-2 text-white/60">{s.next_run}</td>
            <td className="py-2 pr-2 text-white/60">{s.last_run}</td>
            <td className="py-2 pr-2">
              <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                s.status === "active"
                  ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                  : "border-white/10 bg-white/5 text-white/60"
              )}>
                {s.status.charAt(0).toUpperCase() + s.status.slice(1)}
              </span>
            </td>
            <td className="py-2 text-right">
              <div className="inline-flex items-center gap-1">
                <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Info">
                  <Activity className="h-3.5 w-3.5" />
                </button>
                <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Edit">
                  <Search className="h-3.5 w-3.5" />
                </button>
                <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="More">
                  ⋯
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Real registered versions from `GET /v1/model/versions`, newest first
 * (Model Operations TODO.md Phase 1) -- metrics are rendered generically
 * from whatever keys are actually present (`test_mape`/
 * `test_coverage_raw`/`test_coverage_calibrated`, see
 * `data-pipeline/app/service/ml/train.py`), not the old mock's
 * fabricated MAPE+RMSE pair. */
function TrainingRunsList({ versions, loaded }: { versions: ModelVersion[] | null; loaded: boolean }) {
  if (!loaded) {
    return <p className="py-4 text-center text-xs text-white/40">Loading training history…</p>;
  }
  if (!versions || versions.length === 0) {
    return (
      <div className="rounded-md border border-white/5 bg-white/[0.02] p-3 text-center text-xs text-white/50">
        No model has been trained and registered yet.
      </div>
    );
  }
  return (
    <ul className="space-y-1.5">
      {versions.map((v) => (
        <li key={v.version} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">v{v.version}</span>
              </div>
              <div className="text-[11px] text-white/50">{formatRelativeTime(v.created_at)}</div>
            </div>
            <span className="rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 text-[11px] font-medium text-emerald-100">
              {v.stage}
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-white/60">
            {Object.keys(v.metrics).length === 0 ? (
              <span>No test metrics logged for this run.</span>
            ) : (
              Object.entries(v.metrics).map(([key, value]) => (
                <span key={key}>{key.replace(/_/g, " ")}: {value.toFixed(2)}</span>
              ))
            )}
          </div>
        </li>
      ))}
      <li className="pt-1 text-center">
        <a href="/dashboard/models/" className="text-xs text-emerald-100 hover:underline">View all versions</a>
      </li>
    </ul>
  );
}

function CommandCard({ c }: { c: SystemCommand }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.02] p-3">
      <div className="mb-1 flex items-center gap-2">
        <IconFor name={c.icon} className="h-4 w-4 text-emerald-100" />
        <h3 className="text-sm font-medium text-white">{c.label}</h3>
      </div>
      <p className="mb-2 text-[11px] text-white/50">{c.description}</p>
      <button
        className={cn(
          "inline-flex w-full items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium",
          c.destructive
            ? "border-rose-300/40 bg-rose-300/10 text-rose-200 hover:bg-rose-300/15"
            : "border-emerald-200/40 bg-emerald-200/10 text-emerald-100 hover:bg-emerald-200/15",
        )}
      >
        <Play className="h-3 w-3" /> Execute
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Small building blocks
// ────────────────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/50">
        {label}
      </label>
      {children}
    </div>
  );
}

