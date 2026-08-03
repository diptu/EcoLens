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
 * (`POST /v1/data-sources/{id}/run`) now works from here using the
 * dashboard's own IAM session — data-pipeline accepts IAM-issued bearer
 * tokens directly (its `role` claim, `admin` for superusers) as a second
 * trust anchor alongside its own self-issued ones, so no separate
 * data-pipeline login is needed. Requires the signed-in user to be an
 * IAM superuser; anyone else gets data-pipeline's own real 403.
 * The dbt warehouse-build "pipeline" (`source_id: null`) still can't be
 * triggered this way — that's a `POST /v1/dbt/{subcommand}` call, a
 * different, not-yet-bridged route. The other 7 sections (KPI row,
 * Model Operations, Active Tasks, Model Training & Tuning, Recent
 * Training Runs, Scheduled Operations, System Commands) are still the
 * old mock; see `todo-operational-tasks.md` for what's real/fake in
 * each.
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
  getModelOps,
  getOperationalKpis,
  getRecentTrainingRuns,
  getScheduledOps,
  getSystemCommands,
  getTrainingConfigOptions,
  type ActiveTask,
  type ModelOp,
  type OperationalKpi,
  type ScheduledOp,
  type SystemCommand,
  type TaskStatus,
  type TaskType,
  type TrainingRun,
} from "@/lib/admin-dashboard";
import {
  PIPELINE_CATALOG,
  triggerHistoricalIngest,
  getHistoricalIngestJob,
  pollIngestJob,
  IngestionApiError,
  type Source,
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

type RowStatus = "idle" | "queued" | "running" | "success" | "failed";

/** Reflects the actual trigger state of a `POST /ingestion/historical`
 * job (see `lib/ingestion.ts`) -- there's no "list pipelines with
 * health" endpoint on data-pipeline to derive a passive health signal
 * from, so this chip only ever shows what a real trigger+poll actually
 * observed for this pipeline in this session (idle until triggered). */
function PipelineStatusChip({ status }: { status: RowStatus }) {
  const map = {
    idle:    { color: "border-white/10 bg-white/5 text-white/60", icon: Calendar, label: "Idle" },
    queued:  { color: "border-amber-300/40 bg-amber-300/10 text-amber-200", icon: Loader2, label: "Queued" },
    running: { color: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200", icon: Loader2, label: "Running" },
    success: { color: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100", icon: Check, label: "Success" },
    failed:  { color: "border-rose-300/40 bg-rose-300/10 text-rose-200", icon: AlertTriangle, label: "Failed" },
  };
  const m = map[status];
  const Icon = m.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium", m.color)}>
      <Icon className={cn("h-3 w-3", (status === "queued" || status === "running") && "animate-spin")} />
      {m.label}
    </span>
  );
}

function ModelStatusChip({ status }: { status: ModelOp["status"] }) {
  const map = {
    deployed:   { color: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100", label: "Deployed"  },
    staging:    { color: "border-amber-300/40 bg-amber-300/10 text-amber-200",     label: "Staging"   },
    deprecated: { color: "border-white/10 bg-white/5 text-white/60",                label: "Deprecated"},
  };
  const m = map[status];
  return (
    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", m.color)}>
      {m.label}
    </span>
  );
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

type RowState = { status: RowStatus; written?: number; error?: string };

export default function OperationalTasksPage() {
  const kpis = useMemo(() => getOperationalKpis(), []);
  const [pipelineRows, setPipelineRows] = useState<Record<string, RowState>>({});
  const cancelFns = useRef<Record<string, () => void>>({});
  const models = useMemo(() => getModelOps(), []);
  const allTasks = useMemo(() => getActiveTasks(), []);
  const recentRuns = useMemo(() => getRecentTrainingRuns(), []);
  const scheduled = useMemo(() => getScheduledOps(), []);
  const commands = useMemo(() => getSystemCommands(), []);
  const configOpts = useMemo(() => getTrainingConfigOptions(), []);

  const [tab, setTab] = useState<TaskStatus | "all">("all");
  const [selectedModel, setSelectedModel] = useState(configOpts.models[0]);
  const [dataRange, setDataRange] = useState("2023-01-01 → 2025-05-18");
  const [env, setEnv] = useState(configOpts.environments[0]);
  const [compute, setCompute] = useState(configOpts.compute[1]); // GPU (NVIDIA T4)
  const [expName, setExpName] = useState("");

  useEffect(() => {
    return () => {
      Object.values(cancelFns.current).forEach((cancel) => cancel());
    };
  }, []);

  function triggerPipeline(source: Source) {
    cancelFns.current[source]?.();
    setPipelineRows((prev) => ({ ...prev, [source]: { status: "queued" } }));

    triggerHistoricalIngest(source, { date: new Date().toISOString().slice(0, 10) })
      .then(({ job_id }) => {
        setPipelineRows((prev) => ({ ...prev, [source]: { status: "running" } }));
        cancelFns.current[source] = pollIngestJob(getHistoricalIngestJob, job_id, (job) => {
          if (job.status === "running") {
            setPipelineRows((prev) => ({ ...prev, [source]: { status: "running" } }));
          } else if (job.status === "completed") {
            setPipelineRows((prev) => ({ ...prev, [source]: { status: "success", written: job.written ?? 0 } }));
          } else {
            setPipelineRows((prev) => ({ ...prev, [source]: { status: "failed", error: job.error ?? "unknown error" } }));
          }
        });
      })
      .catch((err) => {
        const message = err instanceof IngestionApiError ? err.message : "trigger failed";
        setPipelineRows((prev) => ({ ...prev, [source]: { status: "failed", error: message } }));
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
          <PipelineTable rows={pipelineRows} onTrigger={triggerPipeline} />
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
              <p className="text-xs text-white/50">Manage model training, tuning and deployments.</p>
            </div>
            <button className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
              <RefreshCw className="h-3.5 w-3.5" />
              Retrain Model
            </button>
          </div>
          <ModelTable rows={models} />
          <button className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline">
            View all models <ChevronDown className="h-3 w-3" />
          </button>
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
            <p className="text-xs text-white/50">Configure and launch model training or hyperparameter tuning jobs.</p>
          </div>
          <div className="mb-3 flex items-center gap-2 border-b border-white/5">
            <TabBtn active>Train Model</TabBtn>
            <TabBtn>Hyperparameter Tuning</TabBtn>
          </div>
          <div className="space-y-3">
            <Field label="Select Model">
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              >
                {configOpts.models.map((m) => <option key={m} className="bg-[#0a1410]">{m}</option>)}
              </select>
            </Field>
            <Field label="Training Data Range">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={dataRange}
                  onChange={(e) => setDataRange(e.target.value)}
                  className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
                />
                <button className="rounded-md border border-white/10 bg-white/[0.04] p-2 text-white/60 hover:text-white">
                  <Calendar className="h-4 w-4" />
                </button>
              </div>
            </Field>
            <Field label="Training Environment">
              <select
                value={env}
                onChange={(e) => setEnv(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              >
                {configOpts.environments.map((e) => <option key={e} className="bg-[#0a1410]">{e}</option>)}
              </select>
            </Field>
            <Field label="Compute Resource">
              <select
                value={compute}
                onChange={(e) => setCompute(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              >
                {configOpts.compute.map((c) => <option key={c} className="bg-[#0a1410]">{c}</option>)}
              </select>
            </Field>
            <Field label="Experiment Name (Optional)">
              <input
                type="text"
                value={expName}
                onChange={(e) => setExpName(e.target.value)}
                placeholder="e.g., lstm_retrain_may19"
                className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
              />
            </Field>
            <details className="rounded-md border border-white/5 bg-white/[0.02]">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-white/70">Advanced Settings</summary>
              <div className="border-t border-white/5 p-3 text-xs text-white/50">
                <p>Learning rate, batch size, epochs, early stopping, MLflow experiment, etc.</p>
              </div>
            </details>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-emerald-200 px-4 py-2 text-sm font-semibold text-black hover:bg-emerald-100">
              <Play className="h-4 w-4" />
              Start Training
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
          <TrainingRunsList runs={recentRuns} />
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
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Tables
// ────────────────────────────────────────────────────────────────────

function PipelineTable({
  rows,
  onTrigger,
}: {
  rows: Record<string, RowState>;
  onTrigger: (source: Source) => void;
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
        {PIPELINE_CATALOG.filter((p) => p.triggerable).map((p) => {
          const row = rows[p.id] ?? { status: "idle" as RowStatus };
          const busy = row.status === "queued" || row.status === "running";
          const runDisabled = busy;
          const runTitle = "Run now";
          return (
            <tr key={p.id} className="text-white/85">
              <td className="py-2 pr-2">{p.label}</td>
              <td className="py-2 pr-2">
                <PipelineStatusChip status={row.status} />
                {row.status === "success" && (
                  <span className="ml-1 text-[11px] text-white/50">{row.written ?? 0} rows</span>
                )}
                {row.status === "failed" && row.error && (
                  <span className="ml-1 text-[11px] text-rose-300" title={row.error}>{row.error}</span>
                )}
              </td>
              <td className="py-2 text-right">
                <div className="inline-flex items-center gap-2">
                  <button
                    disabled={runDisabled}
                    onClick={() => p.triggerable && onTrigger(p.id as Source)}
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

function ModelTable({ rows }: { rows: ModelOp[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Model Name</th>
          <th className="py-2">Version</th>
          <th className="py-2">Type</th>
          <th className="py-2">Last Trained</th>
          <th className="py-2">Performance</th>
          <th className="py-2">Status</th>
          <th className="py-2 text-right">Actions</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        {rows.map((m) => (
          <tr key={m.id} className="text-white/85">
            <td className="py-2 pr-2">{m.name}</td>
            <td className="py-2 pr-2">
              <span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[11px] text-purple-200">{m.version}</span>
            </td>
            <td className="py-2 pr-2 text-white/60">{m.type}</td>
            <td className="py-2 pr-2 text-white/60">{m.last_trained}</td>
            <td className="py-2 pr-2 text-[11px] text-white/70">
              <div>MAPE {m.performance.mape.toFixed(2)}%</div>
              <div>RMSE {m.performance.rmse.toLocaleString()}</div>
            </td>
            <td className="py-2 pr-2"><ModelStatusChip status={m.status} /></td>
            <td className="py-2 text-right">
              <div className="inline-flex items-center gap-1">
                <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Retrain">
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
                <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Tune">
                  <Sparkles className="h-3.5 w-3.5" />
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

function TrainingRunsList({ runs }: { runs: TrainingRun[] }) {
  return (
    <ul className="space-y-1.5">
      {runs.map((r) => (
        <li key={r.version} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white">{r.model}</span>
                <span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">{r.version}</span>
              </div>
              <div className="text-[11px] text-white/50">{r.trained_at}</div>
            </div>
            <span className="rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 text-[11px] font-medium text-emerald-100">
              {r.status.charAt(0).toUpperCase() + r.status.slice(1)}
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-3 text-[11px] text-white/60">
            <span>MAPE {r.performance.mape.toFixed(2)}%</span>
            <span>RMSE {r.performance.rmse.toLocaleString()}</span>
          </div>
        </li>
      ))}
      <li className="pt-1 text-center">
        <button className="text-xs text-emerald-100 hover:underline">View all runs</button>
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

function TabBtn({ children, active }: { children: React.ReactNode; active?: boolean }) {
  return (
    <button className={cn(
      "border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
      active
        ? "border-emerald-200 text-emerald-100"
        : "border-transparent text-white/60 hover:text-white",
    )}>
      {children}
    </button>
  );
}
