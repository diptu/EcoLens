/**
 * /dashboard/admin/models — model registry, training, fine-tuning.
 *
 * Lists all model versions with their stage + metrics. Lets the
 * admin (diptu) start a full retrain, a fine-tune job, or promote
 * a Staging model to Production.
 */
"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Box,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Database,
  GitBranch,
  Loader2,
  PlayCircle,
  Rocket,
  Settings as SettingsIcon,
  Sliders,
  Sparkles,
  Target,
  TrendingUp,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  generateModelRegistry,
  type ModelVersion,
} from "@/lib/admin";

type Tab = "registry" | "train" | "fine-tune";

export default function AdminModelsPage() {
  const [tab, setTab] = useState<Tab>("registry");
  const [models, setModels] = useState<ModelVersion[]>(() => generateModelRegistry());
  const [expandedVersion, setExpandedVersion] = useState<number | null>(7);

  function promote(model: ModelVersion, stage: ModelVersion["stage"]) {
    setModels((curr) => {
      const next = curr.map((m) => {
        if (m.name === model.name && m.stage === "Production" && stage === "Production" && m.version !== model.version) {
          return { ...m, stage: "Archived" as const };
        }
        if (m.name === model.name && m.version === model.version) {
          return { ...m, stage };
        }
        return m;
      });
      return next;
    });
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
        <TabButton active={tab === "train"}     onClick={() => setTab("train")}     data-testid="tab-train">
          <Rocket className="h-3.5 w-3.5" /> Train
        </TabButton>
        <TabButton active={tab === "fine-tune"} onClick={() => setTab("fine-tune")} data-testid="tab-fine-tune">
          <Sliders className="h-3.5 w-3.5" /> Fine-tune
        </TabButton>
      </div>

      {/* ── Registry tab ────────────────────────────────────── */}
      {tab === "registry" && (
        <Card
          title={
            <span className="flex items-center gap-2">
              <Box className="h-4 w-4 text-emerald-200" />
              ecolens_lstm_demand · {models.length} versions
            </span>
          }
          actions={
            <span className="text-[10px] text-white/40">
              click a row to expand
            </span>
          }
        >
          <div className="space-y-2" data-testid="model-registry">
            {models.map((m) => (
              <ModelRow
                key={m.version}
                model={m}
                expanded={expandedVersion === m.version}
                onToggle={() => setExpandedVersion(expandedVersion === m.version ? null : m.version)}
                onPromote={promote}
              />
            ))}
          </div>
        </Card>
      )}

      {/* ── Train tab ────────────────────────────────────────── */}
      {tab === "train" && <TrainForm onStarted={() => setTab("registry")} />}

      {/* ── Fine-tune tab ───────────────────────────────────── */}
      {tab === "fine-tune" && <FineTuneForm onStarted={() => setTab("registry")} />}
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

const STAGE_COLORS: Record<ModelVersion["stage"], string> = {
  Production: "bg-lime-100/15 text-lime-100 border-lime-200/30",
  Staging:    "bg-sky-500/15 text-sky-200 border-sky-400/30",
  Archived:   "bg-white/5 text-white/55 border-white/10",
};

function ModelRow({
  model, expanded, onToggle, onPromote,
}: {
  model: ModelVersion;
  expanded: boolean;
  onToggle: () => void;
  onPromote: (m: ModelVersion, stage: ModelVersion["stage"]) => void;
}) {
  return (
    <div
      className="rounded-lg border border-white/5 bg-white/[0.02] transition-colors hover:border-white/10"
      data-testid={`model-row-${model.version}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-white/45" /> : <ChevronRight className="h-3.5 w-3.5 text-white/45" />}
          <span className="font-mono text-base font-semibold text-white">v{model.version}</span>
          <span className={cn("rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider", STAGE_COLORS[model.stage])}>
            {model.stage}
          </span>
          <span className="text-xs text-white/55">trained by {model.trained_by}</span>
        </div>
        <div className="flex items-center gap-3 text-right text-[11px]">
          <Metric label="MAPE" value={`${model.metrics.mape}%`} highlight={model.metrics.mape < 5 ? "text-emerald-100" : "text-amber-300"} />
          <Metric label="RMSE" value={`${model.metrics.rmse_mw} MW`} />
          <Metric label="MAE"  value={`${model.metrics.mae_mw} MW`} />
          <span className="text-[10px] text-white/40">
            {new Date(model.created_at).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" })}
          </span>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-white/5 px-4 py-3 text-xs">
          <p className="text-white/65">{model.notes}</p>
          <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            <Field label="Training window" value={`${model.training_window_days} days (${(model.training_window_days / 365).toFixed(1)} years)`} />
            <Field label="Pinball P10"      value={model.metrics.pinball_p10.toString()} />
            <Field label="Pinball P90"      value={model.metrics.pinball_p90.toString()} />
            <Field label="Created"          value={new Date(model.created_at).toLocaleString("en-AU")} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {model.stage !== "Production" && (
              <button
                type="button"
                onClick={() => onPromote(model, "Production")}
                data-testid={`promote-${model.version}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-lime-200/30 bg-lime-100/10 px-2.5 py-1 text-[11px] font-semibold text-lime-100 hover:bg-lime-100/20"
              >
                <Rocket className="h-3 w-3" /> Promote to Production
              </button>
            )}
            {model.stage !== "Staging" && (
              <button
                type="button"
                onClick={() => onPromote(model, "Staging")}
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200 hover:bg-sky-500/20"
              >
                <GitBranch className="h-3 w-3" /> Move to Staging
              </button>
            )}
            {model.stage !== "Archived" && (
              <button
                type="button"
                onClick={() => onPromote(model, "Archived")}
                className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:bg-white/10"
              >
                <XCircle className="h-3 w-3" /> Archive
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: string }) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-[9px] uppercase tracking-wider text-white/40">{label}</span>
      <span className={cn("font-mono font-medium", highlight ?? "text-white")}>{value}</span>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-white/5 bg-white/[0.02] px-2 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 font-mono text-white/85">{value}</div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Train form
// ────────────────────────────────────────────────────────────────────
function TrainForm({ onStarted }: { onStarted: () => void }) {
  const [windowDays, setWindowDays] = useState(1095);
  const [epochs, setEpochs]         = useState(50);
  const [batchSize, setBatchSize]   = useState(128);
  const [hidden, setHidden]         = useState(128);
  const [layers, setLayers]         = useState(2);
  const [dropout, setDropout]       = useState(0.2);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setTimeout(() => {
      setJobId(`job-train-${Date.now().toString(36)}`);
      setSubmitting(false);
      setTimeout(onStarted, 8000);
    }, 600);
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-emerald-200" />
          Train a new version
        </span>
      }
      subtitle="Full retrain on the historical window. New version is added to the registry at the Staging stage."
    >
      <form onSubmit={submit} className="space-y-4" data-testid="train-form">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <NumberField label="Training window" unit="days" value={windowDays} onChange={setWindowDays} min={90} max={3650} />
          <NumberField label="Epochs" value={epochs} onChange={setEpochs} min={5} max={200} />
          <NumberField label="Batch size" value={batchSize} onChange={setBatchSize} min={16} max={512} />
          <NumberField label="Hidden size" value={hidden} onChange={setHidden} min={32} max={512} />
          <NumberField label="Num layers" value={layers} onChange={setLayers} min={1} max={4} />
          <NumberField label="Dropout" value={dropout} onChange={setDropout} min={0} max={0.5} step={0.05} />
        </div>
        <div className="rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs text-white/55">
          <strong className="text-white">Plan:</strong> {windowDays} days of data
          ({Math.round(windowDays * 17520).toLocaleString()} 30-min samples) · {epochs} epochs ·
          batch {batchSize} · {hidden} hidden × {layers} layers · dropout {dropout}
          <br />
          <strong className="text-white">Est. time:</strong> ~{Math.ceil((windowDays / 365) * 4 * (epochs / 25))} min on a single A100
          (or ~{Math.ceil((windowDays / 365) * 25 * (epochs / 25))} min on CPU).
        </div>
        {jobId && (
          <div className="rounded-md border border-emerald-200/20 bg-emerald-300/5 p-3 text-xs text-emerald-100" data-testid="train-success">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> Training job{" "}
            <code className="rounded bg-black/30 px-1 font-mono">{jobId}</code> queued. It will appear in the
            Jobs page. The new model version will be added to Staging.
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting}
            data-testid="start-train"
            className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-100 disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Queuing…
              </>
            ) : (
              <>
                <PlayCircle className="h-3.5 w-3.5" /> Start training
              </>
            )}
          </button>
          <p className="text-[11px] text-white/45">
            Training runs in <code className="rounded bg-black/30 px-1 font-mono">data-pipeline</code>.
            The new version is registered in MLflow on completion.
          </p>
        </div>
      </form>
    </Card>
  );
}

function FineTuneForm({ onStarted }: { onStarted: () => void }) {
  const [baseVersion, setBaseVersion] = useState(7);
  const [windowDays, setWindowDays]     = useState(30);
  const [lr, setLr]                     = useState(1e-4);
  const [epochs, setEpochs]             = useState(5);
  const [submitting, setSubmitting]     = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setTimeout(() => {
      setJobId(`job-ft-${Date.now().toString(36)}`);
      setSubmitting(false);
      setTimeout(onStarted, 8000);
    }, 600);
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-emerald-200" />
          Fine-tune the production model
        </span>
      }
      subtitle="Incremental training on the latest data window. New version is added to the registry at the Staging stage."
    >
      <form onSubmit={submit} className="space-y-4" data-testid="finetune-form">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Base version
            </label>
            <select
              value={baseVersion}
              onChange={(e) => setBaseVersion(parseInt(e.target.value, 10))}
              data-testid="finetune-base"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
            >
              <option value={7}>v7 (Production)</option>
              <option value={6}>v6 (Staging)</option>
              <option value={5}>v5 (Archived)</option>
            </select>
          </div>
          <NumberField label="Fine-tune window" unit="days" value={windowDays} onChange={setWindowDays} min={1} max={365} />
          <NumberField label="Learning rate" value={lr} onChange={setLr} min={0} max={1} step={0.0001} />
          <NumberField label="Epochs" value={epochs} onChange={setEpochs} min={1} max={50} />
        </div>
        <div className="rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs text-white/55">
          <strong className="text-white">Plan:</strong> Initialize from v{baseVersion} · train
          on the last {windowDays} days · {epochs} epochs at lr={lr} · new version
          will be v{baseVersion + 1}
        </div>
        {jobId && (
          <div className="rounded-md border border-emerald-200/20 bg-emerald-300/5 p-3 text-xs text-emerald-100" data-testid="finetune-success">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> Fine-tune job{" "}
            <code className="rounded bg-black/30 px-1 font-mono">{jobId}</code> queued.
            It will appear in the Jobs page.
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting}
            data-testid="start-finetune"
            className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-100 disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Queuing…
              </>
            ) : (
              <>
                <PlayCircle className="h-3.5 w-3.5" /> Start fine-tune
              </>
            )}
          </button>
          <p className="text-[11px] text-white/45">
            Fine-tune runs in <code className="rounded bg-black/30 px-1 font-mono">data-pipeline</code>.
            The new version is registered in MLflow on completion.
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
