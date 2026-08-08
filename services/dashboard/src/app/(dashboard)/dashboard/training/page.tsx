/**
 * /dashboard/training — Model Training & Experiments (ML Engineers)
 *
 * Focused view on training jobs, hyperparameter tuning, and experiment
 * tracking. Distinct from /operational-tasks (which handles ingestion,
 * warehouse refresh, and system maintenance).
 *
 * This page used to be this app's own documented "known precedent
 * violation" of its no-silently-fabricated-dashboards rule
 * (`IllustrativeBadge`'s own docstring named it directly) — every tab
 * read from hardcoded mock generators with no real backend at all, even
 * though `GET /v1/model/versions` and `GET /v1/model/training-runs`
 * (real, already used by `models`/`performance`/`operational-tasks`)
 * cover most of what "Training Jobs" and "Model Registry" need. Fixed:
 * those two tabs are now real. MLflow experiments, feature-store
 * listings, deployment status, and hyperparameter-search history have
 * no backing endpoint anywhere in this platform — those stay
 * illustrative, now honestly marked as such (`IllustrativeBadge`)
 * instead of presented as real.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { Beaker, Play, Clock } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { IllustrativeBadge } from "@/components/dashboard/illustrative-badge";
import { cn } from "@/lib/utils";
import { fetchModelVersions, MODEL_ARCHITECTURES, type ModelVersion } from "@/lib/emissions";
import { fetchTrainingRuns, formatRelativeTime, type TrainingRunLog } from "@/lib/ingestion";
import { getFeatureGroups, getMlflowExperiments, getMlflowRuns, getDeployments } from "@/lib/dashboards";

function useModelVersions() {
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchModelVersions(MODEL_ARCHITECTURES[0].modelName)
      .then((res) => {
        if (!cancelled) setVersions(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { versions, error };
}

function useTrainingRuns() {
  const [runs, setRuns] = useState<TrainingRunLog[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTrainingRuns(20)
      .then((res) => {
        if (!cancelled) setRuns(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { runs, error };
}

export default function TrainingPage() {
  const { versions, error: versionsError } = useModelVersions();
  const { runs, error: runsError } = useTrainingRuns();

  // No real endpoint for any of these -- see this page's own module
  // docstring. Kept as static sample content (not deleted) so the tabs
  // still show what the real thing would look like, but every card now
  // carries `IllustrativeBadge` per this app's own convention.
  const experiments = useMemo(() => getMlflowExperiments(), []);
  const mlflowRuns = useMemo(() => getMlflowRuns(8), []);
  const featureGroups = useMemo(() => getFeatureGroups(), []);
  const deployments = useMemo(() => getDeployments(), []);

  const [tab, setTab] = useState<"jobs" | "hptune" | "experiments" | "datasets" | "deployments">("jobs");

  const kpis = useMemo(() => {
    const runningCount = runs?.filter((r) => r.status === "running").length ?? null;
    const lastRun = runs?.[0];
    return [
      { label: "Model Versions", value: versions ? String(versions.length) : "…", sub: versions ? `${versions.filter((v) => v.stage === "Production").length} production` : undefined },
      { label: "Active Training Jobs", value: runningCount != null ? String(runningCount) : "…", sub: undefined },
      { label: "Last Train", value: lastRun ? formatRelativeTime(lastRun.started_at) : (runs ? "—" : "…"), sub: lastRun?.model_name },
    ];
  }, [versions, runs]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Beaker className="h-6 w-6 text-emerald-100" />
          Model Training &amp; Experiments
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Train, tune, and track ML models. Hyperparameter search, experiment comparison, and feature store integration.
        </p>
      </div>

      {/* KPIs — only the ones with a real source (GET /v1/model/versions, GET /v1/model/training-runs) */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
            <div className="mt-1.5 text-2xl font-bold text-white">{k.value}</div>
            {k.sub && <p className="mt-1 text-[11px] text-white/50">{k.sub}</p>}
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
        {([
          { id: "jobs",        label: "Training Jobs"   },
          { id: "hptune",      label: "Hyperparameter Tuning" },
          { id: "experiments", label: "Experiments"     },
          { id: "datasets",    label: "Feature Store"   },
          { id: "deployments", label: "Deployments"     },
        ] as const).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
              tab === t.id ? "border-emerald-200 text-emerald-100" : "border-transparent text-white/60 hover:text-white",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "jobs" && (
        <div className="space-y-4">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Recent Training Runs</h2>
              <span className="text-[11px] text-white/40">GET /v1/model/training-runs (forecast-api)</span>
            </div>
            {runsError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load training runs ({runsError}).</p>
            ) : runs === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : runs.length === 0 ? (
              <p className="text-sm text-white/55">No training runs yet.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Run ID</th>
                    <th className="py-2">Model</th>
                    <th className="py-2">Triggered By</th>
                    <th className="py-2">Started</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Version</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {runs.map((r) => (
                    <tr key={r.id} className="text-white/85">
                      <td className="py-2 font-mono text-[11px] text-white/60">{r.id.slice(0, 8)}</td>
                      <td className="py-2">{r.model_name}</td>
                      <td className="py-2 text-white/60">{r.triggered_by}</td>
                      <td className="py-2 text-white/60">{formatRelativeTime(r.started_at)}</td>
                      <td className="py-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                          r.status === "success" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                          r.status === "running"  ? "border-cyan-300/40 bg-cyan-300/10 text-cyan-200" :
                                                    "border-rose-300/40 bg-rose-300/10 text-rose-200"
                        )}>{r.status}</span>
                      </td>
                      <td className="py-2 font-mono text-[11px] text-purple-200">{r.model_version ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}

      {tab === "hptune" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-white">Hyperparameter Tuning</h2>
                <p className="text-xs text-white/50">
                  Not wired to a real endpoint yet — <code className="rounded bg-black/30 px-1 font-mono text-lime-100">POST /v1/model/train</code> triggers
                  a bare training run today, no hyperparameter payload support.
                </p>
              </div>
              <IllustrativeBadge label="Not wired to a real endpoint yet" />
            </div>
            <button
              type="button"
              disabled
              title="Not wired to a real endpoint yet"
              className="inline-flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-md bg-emerald-200/40 px-4 py-2 text-sm font-semibold text-black/60"
            >
              <Play className="h-4 w-4" /> Start Tuning
            </button>
          </Card>

          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Hparam Search History</h2>
              <IllustrativeBadge />
            </div>
            <table className="w-full text-left text-sm opacity-60">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Trial</th>
                  <th className="py-2">LR</th>
                  <th className="py-2">Batch</th>
                  <th className="py-2">Hidden</th>
                  <th className="py-2">MAPE</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-white/85">
                {[
                  { t: "01", lr: "0.001", b: "32", h: "128", mape: 2.41 },
                  { t: "02", lr: "0.001", b: "64", h: "128", mape: 2.38 },
                  { t: "03", lr: "0.0005", b: "64", h: "256", mape: 2.31 },
                  { t: "04", lr: "0.0005", b: "32", h: "256", mape: 2.18 },
                ].map((r) => (
                  <tr key={r.t}>
                    <td className="py-1.5 font-mono text-[11px] text-white/60">{r.t}</td>
                    <td className="py-1.5 text-white/60">{r.lr}</td>
                    <td className="py-1.5 text-white/60">{r.b}</td>
                    <td className="py-1.5 text-white/60">{r.h}</td>
                    <td className="py-1.5 text-emerald-100 tabular-nums">{r.mape.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === "experiments" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">MLflow Experiments</h2>
              <IllustrativeBadge label="No experiments-listing endpoint exists yet" />
            </div>
            <ul className="space-y-1.5 text-sm opacity-60">
              {experiments.map((e) => (
                <li key={e.id} className="rounded-md border border-white/5 bg-white/[0.02] p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-white/85 font-medium">{e.name}</div>
                      <div className="text-[11px] text-white/50">Owner: {e.owner} · {e.runs} runs</div>
                    </div>
                    <div className="text-right">
                      <div className="text-emerald-100 tabular-nums">{e.best_value} {e.best_metric}</div>
                      <div className="text-[11px] text-white/50">best</div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Recent MLflow Runs</h2>
              <IllustrativeBadge />
            </div>
            <table className="w-full text-left text-sm opacity-60">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Run</th>
                  <th className="py-2">Experiment</th>
                  <th className="py-2">Started</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {mlflowRuns.map((r) => (
                  <tr key={r.id} className="text-white/85">
                    <td className="py-2 font-mono text-[11px] text-white/60">{r.id}</td>
                    <td className="py-2 text-white/80">{r.experiment}</td>
                    <td className="py-2 text-white/60">{r.started}</td>
                    <td className="py-2"><span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                      r.status === "finished" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                      r.status === "running"  ? "border-cyan-300/40 bg-cyan-300/10 text-cyan-200" :
                      r.status === "failed"   ? "border-rose-300/40 bg-rose-300/10 text-rose-200" :
                                                "border-white/10 bg-white/5 text-white/60"
                    )}>{r.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === "datasets" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Feature Groups</h2>
              <IllustrativeBadge label="No feature-store listing endpoint exists yet" />
            </div>
            <ul className="space-y-1.5 text-sm opacity-60">
              {featureGroups.map((f) => (
                <li key={f.id} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-white/85 font-mono">{f.name}</div>
                      <div className="text-[11px] text-white/50">Entity: {f.entity} · {f.features} features</div>
                    </div>
                    <div className="text-[11px] text-white/60">{f.last_materialized}</div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Model Registry</h2>
              <span className="text-[11px] text-white/40">GET /v1/model/versions (forecast-api)</span>
            </div>
            {versionsError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load model versions ({versionsError}).</p>
            ) : versions === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : versions.length === 0 ? (
              <p className="text-sm text-white/55">No registered versions yet.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr><th className="py-2">Version</th><th className="py-2">Stage</th><th className="py-2">Created</th><th className="py-2">Metrics</th></tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {versions.map((v) => (
                    <tr key={v.version} className="text-white/85">
                      <td className="py-2"><span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[11px] text-purple-200">v{v.version}</span></td>
                      <td className="py-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                          v.stage === "Production" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                          v.stage === "Staging"    ? "border-amber-300/40 bg-amber-300/10 text-amber-200" :
                                                      "border-white/10 bg-white/5 text-white/60"
                        )}>{v.stage}</span>
                      </td>
                      <td className="py-2 text-white/60">{formatRelativeTime(v.created_at)}</td>
                      <td className="py-2 text-emerald-100 tabular-nums text-[11px]">
                        {v.metrics.test_mape != null ? `MAPE ${v.metrics.test_mape.toFixed(2)}%` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}

      {tab === "deployments" && (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold text-white">Active Deployments</h2>
            <IllustrativeBadge label="No deployment-status endpoint exists yet" />
          </div>
          <table className="w-full text-left text-sm opacity-60">
            <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
              <tr>
                <th className="py-2">Model</th>
                <th className="py-2">Version</th>
                <th className="py-2">Environment</th>
                <th className="py-2">Replicas</th>
                <th className="py-2">CPU%</th>
                <th className="py-2">P95 (ms)</th>
                <th className="py-2">Traffic</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {deployments.map((d) => (
                <tr key={d.id} className="text-white/85">
                  <td className="py-2">{d.model}</td>
                  <td className="py-2 font-mono text-[11px] text-purple-200">{d.version}</td>
                  <td className="py-2">
                    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                      d.environment === "production" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                      d.environment === "canary"     ? "border-cyan-300/40 bg-cyan-300/10 text-cyan-200" :
                                                        "border-amber-300/40 bg-amber-300/10 text-amber-200"
                    )}>{d.environment}</span>
                  </td>
                  <td className="py-2 text-white/60">{d.replicas}</td>
                  <td className="py-2 text-white/60 tabular-nums">{d.cpu_pct}%</td>
                  <td className="py-2 text-white/60 tabular-nums">{d.latency_p95_ms}</td>
                  <td className="py-2 text-emerald-100 tabular-nums">{d.traffic_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
