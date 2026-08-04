/**
 * /dashboard/admin/models — model registry, training, fine-tuning.
 *
 * Lists all model versions with their stage + metrics. Lets the
 * admin (diptu) start a full retrain, a fine-tune job, or promote
 * a Staging model to Production.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import {
  Box,
  ChevronDown,
  ChevronRight,
  GitBranch,
  PlayCircle,
  Rocket,
  Sliders,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  fetchModelVersions,
  pollForNewModelVersion,
  promoteModelVersion,
  type ModelVersion,
} from "@/lib/emissions";
import { formatRelativeTime, triggerTraining, type TrainTrigger } from "@/lib/ingestion";

type Tab = "registry" | "train" | "fine-tune";

export default function AdminModelsPage() {
  const [tab, setTab] = useState<Tab>("registry");
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [modelName, setModelName] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [expandedVersion, setExpandedVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchModelVersions()
      .then((r) => {
        if (!cancelled) {
          setVersions(r.data);
          setModelName(r.name);
          setExpandedVersion(r.data[0]?.version ?? null);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function refreshVersions(fresh: ModelVersion[]) {
    setVersions(fresh);
    setExpandedVersion(fresh[0]?.version ?? null);
  }

  const [promoting, setPromoting] = useState<string | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  function handlePromote(version: string, stage: "Production" | "Staging" | "Archived") {
    setPromoting(version);
    setPromoteError(null);
    promoteModelVersion(version, stage)
      .then(() => fetchModelVersions())
      .then((r) => refreshVersions(r.data))
      .catch((err) => {
        setPromoteError(err instanceof Error ? err.message : "promotion failed");
      })
      .finally(() => setPromoting(null));
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
              {modelName ?? "ecolens_lstm_demand"}
              {versions ? ` · ${versions.length} version${versions.length === 1 ? "" : "s"}` : ""}
            </span>
          }
          actions={
            <span className="text-[10px] text-white/40">
              real data from GET /v1/model/versions — click a row to expand
            </span>
          }
        >
          {promoteError && (
            <p className="mb-2 text-xs text-rose-300">{promoteError}</p>
          )}
          <div className="space-y-2" data-testid="model-registry">
            <RealModelVersions
              versions={versions}
              loaded={loaded}
              expandedVersion={expandedVersion}
              onToggle={(v) => setExpandedVersion(expandedVersion === v ? null : v)}
              onPromote={handlePromote}
              promoting={promoting}
            />
          </div>
        </Card>
      )}

      {/* ── Train tab ────────────────────────────────────────── */}
      {tab === "train" && <TrainForm />}

      {/* ── Fine-tune tab ───────────────────────────────────── */}
      {tab === "fine-tune" && (
        <FineTuneForm
          currentVersion={versions?.[0]?.version ?? null}
          onNewVersion={(fresh) => {
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
  versions, loaded, expandedVersion, onToggle, onPromote, promoting,
}: {
  versions: ModelVersion[] | null;
  loaded: boolean;
  expandedVersion: string | null;
  onToggle: (version: string) => void;
  onPromote: (version: string, stage: "Production" | "Staging" | "Archived") => void;
  promoting: string | null;
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
        />
      ))}
    </>
  );
}

function RealModelVersionRow({
  version, expanded, onToggle, onPromote, promoting,
}: {
  version: ModelVersion;
  expanded: boolean;
  onToggle: () => void;
  onPromote: (version: string, stage: "Production" | "Staging" | "Archived") => void;
  promoting: boolean;
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
function TrainForm() {
  const [windowDays, setWindowDays] = useState(1095);
  const [epochs, setEpochs]         = useState(50);
  const [batchSize, setBatchSize]   = useState(128);
  const [hidden, setHidden]         = useState(128);
  const [layers, setLayers]         = useState(2);
  const [dropout, setDropout]       = useState(0.2);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Rocket className="h-4 w-4 text-emerald-200" />
          Train a new version
        </span>
      }
      subtitle="Full retrain on the historical window. Not wired to a real endpoint yet -- see TODO.md's Model Operations Phase 2."
    >
      <form className="space-y-4" data-testid="train-form" onSubmit={(e) => e.preventDefault()}>
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
        </div>
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled
            title="Not wired to a real endpoint yet"
            data-testid="start-train"
            className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-4 py-2 text-sm font-semibold text-black opacity-50 cursor-not-allowed"
          >
            <PlayCircle className="h-3.5 w-3.5" /> Start training
          </button>
          <p className="text-[11px] text-white/45">
            No trigger endpoint exists yet — this button is a preview of the
            request shape, not a real action.
          </p>
        </div>
      </form>
    </Card>
  );
}

/** Same "not wired yet" treatment as `TrainForm` -- see that component's
 * docstring. `baseVersion`'s options are hardcoded placeholders since
 * Phase 1's real version list doesn't exist yet either. */
type FineTuneState =
  | { state: "idle" }
  | { state: "queued"; trigger: TrainTrigger }
  | { state: "polling"; trigger: TrainTrigger }
  | { state: "error"; message: string };

/** Real, wired to `POST /v1/model/train` (Model Operations TODO.md
 * Phase 2). Only exposes the fields that endpoint actually accepts --
 * `regions`/`window_hours` -- not a base-version picker, learning rate,
 * or epoch count: `train_and_register_incremental` fine-tunes from
 * whatever the current Production/Staging version is and always uses
 * `Settings.incremental_train_epochs`/`incremental_train_lr`, neither
 * of which is configurable per-trigger. Fabricating those controls
 * (like the old mock did) would suggest a precision this endpoint
 * doesn't have. */
function FineTuneForm({
  currentVersion,
  onNewVersion,
}: {
  currentVersion: string | null;
  onNewVersion: (versions: ModelVersion[]) => void;
}) {
  const [regionsInput, setRegionsInput] = useState("");
  const [windowHours, setWindowHours] = useState(24);
  const [status, setStatus] = useState<FineTuneState>({ state: "idle" });
  const cancelPoll = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      cancelPoll.current?.();
    };
  }, []);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const regions = regionsInput
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

    cancelPoll.current?.();
    setStatus({ state: "idle" });
    triggerTraining({ regions: regions.length ? regions : undefined, windowHours })
      .then((trigger) => {
        setStatus({ state: "queued", trigger });
        cancelPoll.current = pollForNewModelVersion(currentVersion, (versions) => {
          setStatus({ state: "polling", trigger });
          const newest = versions.data[0]?.version ?? null;
          if (newest !== currentVersion) {
            onNewVersion(versions.data);
          }
        });
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "training trigger failed";
        setStatus({ state: "error", message });
      });
  }

  const submitting = status.state === "queued" || status.state === "polling";

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-emerald-200" />
          Fine-tune the production model
        </span>
      }
      subtitle="Publishes a real training-trigger event -- app.service.training_worker's consumer picks it up and runs a warm-started incremental fine-tune."
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
          <NumberField label="Window" unit="hours" value={windowHours} onChange={setWindowHours} min={1} max={720} />
        </div>
        {status.state === "queued" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200">
            Queued — {status.trigger.regions.join(", ")}, window {new Date(status.trigger.window_since).toLocaleString("en-AU")} → {new Date(status.trigger.window_until).toLocaleString("en-AU")}.
          </div>
        )}
        {status.state === "polling" && (
          <div className="rounded-md border border-sky-400/20 bg-sky-500/5 p-3 text-xs text-sky-200">
            <PlayCircle className="mr-1 inline h-3.5 w-3.5 animate-pulse" />
            Waiting for the worker to register a new version — this can take a few minutes.
          </div>
        )}
        {status.state === "error" && (
          <p className="text-xs text-rose-300">{status.message}</p>
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
            Runs in <code className="rounded bg-black/30 px-1 font-mono">data-pipeline</code>'s
            train-worker process. The new version is registered in MLflow on completion.
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
