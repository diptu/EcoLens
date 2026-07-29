/**
 * /dashboard/training — Model Training & Experiments (ML Engineers)
 *
 * Focused view on training jobs, hyperparameter tuning, and experiment
 * tracking. Distinct from /operational-tasks (which handles ingestion,
 * warehouse refresh, and system maintenance).
 */
"use client";

import { useMemo, useState } from "react";
import { Beaker, Cpu, Play, Sparkles, Clock, CheckCircle2, AlertTriangle, Activity } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  getActiveTasks, getRecentTrainingRuns,
  getTrainingConfigOptions,
} from "@/lib/admin-dashboard";
import { getFeatureGroups, getMlflowExperiments, getMlflowRuns } from "@/lib/dashboards";
import { getTrainingJobs, getMLModels, getDeployments } from "@/lib/dashboards";

export default function TrainingPage() {
  const models = useMemo(() => getMLModels(), []);
  const trainingJobs = useMemo(() => getTrainingJobs(), []);
  const experiments = useMemo(() => getMlflowExperiments(), []);
  const mlflowRuns = useMemo(() => getMlflowRuns(8), []);
  const recentRuns = useMemo(() => getRecentTrainingRuns(), []);
  const featureGroups = useMemo(() => getFeatureGroups(), []);
  const deployments = useMemo(() => getDeployments(), []);
  const configOpts = useMemo(() => getTrainingConfigOptions(), []);

  const [tab, setTab] = useState<"jobs" | "hptune" | "experiments" | "datasets" | "deployments">("jobs");
  const [selectedModel, setSelectedModel] = useState(configOpts.models[0]);
  const [dataRange, setDataRange] = useState("2023-01-01 → 2025-05-18");
  const [env, setEnv] = useState(configOpts.environments[0]);
  const [compute, setCompute] = useState(configOpts.compute[1]);
  const [expName, setExpName] = useState("");

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

      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {[
          { label: "Models",         value: "5",       sub: "3 production" },
          { label: "Active Training Jobs", value: "1", sub: "v9 candidate" },
          { label: "Experiments",    value: "4",       sub: "90 runs" },
          { label: "Best MAPE",      value: "2.18%",   sub: "v8c candidate" },
          { label: "Feature Groups", value: "5",       sub: "102 features" },
          { label: "Last Train",     value: "May 18",  sub: "12 min" },
        ].map((k) => (
          <div key={k.label} className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
            <h3 className="text-xs font-medium uppercase tracking-wide text-white/60">{k.label}</h3>
            <div className="mt-1.5 text-2xl font-bold text-white">{k.value}</div>
            <p className="mt-1 text-[11px] text-white/50">{k.sub}</p>
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
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-base font-semibold text-white">Training Jobs</h2>
                <button className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
                  <Play className="h-3.5 w-3.5" /> New Training Job
                </button>
              </div>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Job ID</th>
                    <th className="py-2">Model</th>
                    <th className="py-2">Type</th>
                    <th className="py-2">Started</th>
                    <th className="py-2">Duration</th>
                    <th className="py-2">State</th>
                    <th className="py-2">Progress</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {trainingJobs.map((t) => (
                    <tr key={t.id} className="text-white/85">
                      <td className="py-2 font-mono text-[11px] text-white/60">{t.id}</td>
                      <td className="py-2">{t.model}</td>
                      <td className="py-2 text-white/60">{t.type}</td>
                      <td className="py-2 text-white/60">{t.started_at}</td>
                      <td className="py-2 text-white/60">{t.duration}</td>
                      <td className="py-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                          t.state === "finished" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                          t.state === "running"  ? "border-cyan-300/40 bg-cyan-300/10 text-cyan-200" :
                          t.state === "failed"   ? "border-rose-300/40 bg-rose-300/10 text-rose-200" :
                                                    "border-amber-300/40 bg-amber-300/10 text-amber-200"
                        )}>{t.state}</span>
                      </td>
                      <td className="py-2">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/5">
                            <div className={cn("h-full rounded-full",
                              t.state === "finished" ? "bg-emerald-300" :
                              t.state === "running"  ? "bg-cyan-300" :
                              t.state === "failed"   ? "bg-rose-300" : "bg-amber-300"
                            )} style={{ width: `${t.progress_pct}%` }} />
                          </div>
                          <span className="w-9 text-right text-[11px] tabular-nums text-white/70">{t.progress_pct}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>

            <Card>
              <h2 className="mb-3 text-base font-semibold text-white">Recent Runs</h2>
              <ul className="space-y-1.5 text-sm">
                {recentRuns.map((r) => (
                  <li key={r.version} className="rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-sm font-medium text-white">{r.model}</div>
                        <div className="text-[11px] text-white/50 font-mono">{r.version} · {r.trained_at}</div>
                      </div>
                      <span className="rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 text-[11px] font-medium text-emerald-100">
                        {r.status}
                      </span>
                    </div>
                    <div className="mt-1.5 text-[11px] text-white/60">
                      MAPE {r.performance.mape.toFixed(2)}% · RMSE {r.performance.rmse.toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}

      {tab === "hptune" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-white">Model Training &amp; Tuning</h2>
                <p className="text-xs text-white/50">Configure and launch training / hyperparameter tuning.</p>
              </div>
            </div>
            <div className="mb-3 flex items-center gap-2 border-b border-white/5">
              <TabBtn active>Train Model</TabBtn>
              <TabBtn>Hyperparameter Tuning</TabBtn>
            </div>
            <div className="space-y-3">
              <Field label="Select Model">
                <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none">
                  {configOpts.models.map((m) => <option key={m} className="bg-[#0a1410]">{m}</option>)}
                </select>
              </Field>
              <Field label="Training Data Range">
                <div className="flex items-center gap-2">
                  <input type="text" value={dataRange} onChange={(e) => setDataRange(e.target.value)} className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none" />
                  <button className="rounded-md border border-white/10 bg-white/[0.04] p-2 text-white/60 hover:text-white">📅</button>
                </div>
              </Field>
              <Field label="Training Environment">
                <select value={env} onChange={(e) => setEnv(e.target.value)} className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none">
                  {configOpts.environments.map((e) => <option key={e} className="bg-[#0a1410]">{e}</option>)}
                </select>
              </Field>
              <Field label="Compute Resource">
                <select value={compute} onChange={(e) => setCompute(e.target.value)} className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none">
                  {configOpts.compute.map((c) => <option key={c} className="bg-[#0a1410]">{c}</option>)}
                </select>
              </Field>
              <Field label="Experiment Name (Optional)">
                <input type="text" value={expName} onChange={(e) => setExpName(e.target.value)} placeholder="e.g., lstm_retrain_may19" className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none" />
              </Field>
              <details className="rounded-md border border-white/5 bg-white/[0.02]">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-white/70">Advanced Settings</summary>
                <div className="border-t border-white/5 p-3 text-xs text-white/50">
                  Learning rate, batch size, epochs, early stopping, MLflow experiment, etc.
                </div>
              </details>
              <button className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-emerald-200 px-4 py-2 text-sm font-semibold text-black hover:bg-emerald-100">
                <Play className="h-4 w-4" /> Start Tuning
              </button>
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Hparam Search History</h2>
            <table className="w-full text-left text-sm">
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
                  { t: "05", lr: "0.0003", b: "64", h: "256", mape: 2.24 },
                  { t: "06", lr: "0.0003", b: "32", h: "128", mape: 2.29 },
                  { t: "07", lr: "0.0005", b: "64", h: "256", mape: 2.20 },
                  { t: "08", lr: "0.0005", b: "32", h: "128", mape: 2.26 },
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
            <h2 className="mb-3 text-base font-semibold text-white">MLflow Experiments</h2>
            <ul className="space-y-1.5 text-sm">
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
            <h2 className="mb-3 text-base font-semibold text-white">Recent MLflow Runs</h2>
            <table className="w-full text-left text-sm">
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
            <h2 className="mb-3 text-base font-semibold text-white">Feature Groups</h2>
            <ul className="space-y-1.5 text-sm">
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
            <h2 className="mb-3 text-base font-semibold text-white">Model Registry</h2>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr><th className="py-2">Model</th><th className="py-2">Version</th><th className="py-2">Stage</th><th className="py-2">MAPE</th></tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {models.map((m) => (
                  <tr key={m.id} className="text-white/85">
                    <td className="py-2">{m.name}</td>
                    <td className="py-2"><span className="rounded bg-purple-300/15 px-1.5 py-0.5 font-mono text-[11px] text-purple-200">{m.version}</span></td>
                    <td className="py-2">
                      <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium",
                        m.stage === "production" ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100" :
                        m.stage === "staging"    ? "border-amber-300/40 bg-amber-300/10 text-amber-200" :
                                                    "border-white/10 bg-white/5 text-white/60"
                      )}>{m.stage}</span>
                    </td>
                    <td className="py-2 text-emerald-100 tabular-nums">{m.performance.mape?.toFixed(2) ?? "—"}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {tab === "deployments" && (
        <Card>
          <h2 className="mb-3 text-base font-semibold text-white">Active Deployments</h2>
          <table className="w-full text-left text-sm">
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-white/50">{label}</label>
      {children}
    </div>
  );
}

function TabBtn({ children, active }: { children: React.ReactNode; active?: boolean }) {
  return (
    <button className={cn(
      "border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
      active ? "border-emerald-200 text-emerald-100" : "border-transparent text-white/60 hover:text-white",
    )}>
      {children}
    </button>
  );
}
