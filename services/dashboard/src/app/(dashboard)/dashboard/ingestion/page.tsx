/**
 * /dashboard/data-ingestion — Data Ingestion (Pipelines)
 */
"use client";

import { useMemo } from "react";
import { Webhook, Play, RefreshCw, Calendar, AlertTriangle, X, Plus } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { SectionPage } from "@/components/dashboard/section-page";
import { getPipelines, getPipelineRuns, getFailedJobs, type PipelineState } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const STATE_TONE: Record<PipelineState, string> = {
  running: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
  success: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  failed:  "border-rose-300/40 bg-rose-300/10 text-rose-200",
  queued:  "border-amber-300/40 bg-amber-300/10 text-amber-200",
  paused:  "border-white/10 bg-white/5 text-white/60",
};

export default function DataIngestionPage() {
  const pipelines = useMemo(() => getPipelines(), []);
  const runs = useMemo(() => getPipelineRuns(12), []);
  const failed = useMemo(() => getFailedJobs(), []);

  return (
    <SectionPage
      icon={<Webhook className="h-6 w-6" />}
      title="Data Ingestion"
      description="Pipelines, scheduling, and retry queue."
      tabs={[
        { id: "pipelines",    label: "Pipelines",    description: "All running pipelines" },
        { id: "builder",      label: "Builder",      description: "Pipeline builder" },
        { id: "runs",         label: "Runs",         description: "Recent runs" },
        { id: "failed",       label: "Failed Jobs",  description: "Failed + retry queue" },
        { id: "retry",        label: "Retry Queue",  description: "Retry queue" },
        { id: "scheduler",    label: "Scheduler",    description: "Cron scheduler" },
      ]}
      defaultTab="pipelines"
      kpis={[
        { label: "Pipelines",    value: "8"  },
        { label: "Running",      value: "1"  },
        { label: "Failed (24h)", value: "3"  },
        { label: "Records (24h)", value: "12.3M" },
        { label: "Avg duration", value: "5.2s" },
        { label: "Success rate", value: "97.8%" },
      ]}
      panels={{
        pipelines: (
          <div className="space-y-3">
            <div className="flex justify-end gap-2">
              <button className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-white/80 hover:border-emerald-200/30">
                <Plus className="h-3.5 w-3.5" /> New Pipeline
              </button>
              <button className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20">
                <Play className="h-3.5 w-3.5" /> Trigger All
              </button>
            </div>
            <Card>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Pipeline</th>
                    <th className="py-2">Source</th>
                    <th className="py-2">Schedule</th>
                    <th className="py-2">Last Run</th>
                    <th className="py-2">Duration</th>
                    <th className="py-2">Records</th>
                    <th className="py-2">State</th>
                    <th className="py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {pipelines.map((p) => (
                    <tr key={p.id} className="text-white/85">
                      <td className="py-2 pr-2">{p.name}</td>
                      <td className="py-2 pr-2 text-white/60">{p.source}</td>
                      <td className="py-2 pr-2">
                        <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-[11px] text-emerald-100">{p.cron}</code>
                      </td>
                      <td className="py-2 pr-2 text-white/60">{p.last_run}</td>
                      <td className="py-2 pr-2 text-white/60">{p.duration}</td>
                      <td className="py-2 pr-2 text-white/60 tabular-nums">{p.records.toLocaleString()}</td>
                      <td className="py-2 pr-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", STATE_TONE[p.state])}>{p.state}</span>
                      </td>
                      <td className="py-2 text-right">
                        <div className="inline-flex items-center gap-1">
                          <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Run now"><Play className="h-3.5 w-3.5" /></button>
                          <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Reschedule"><Calendar className="h-3.5 w-3.5" /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        ),
        builder: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Pipeline Builder</h2>
            <p className="text-sm text-white/70">Drag-and-drop builder. Connect a source → add a transform → choose destination. We're not exposing a real builder in this prototype; the JSON-equivalent pipeline config is editable below.</p>
            <pre className="mt-3 rounded-md border border-white/5 bg-black/30 p-3 text-[11px] text-emerald-100 font-mono overflow-x-auto">
{`{
  "name": "AEMO NEM 5-min",
  "source": "ds-aemo-nem",
  "schedule": "*/5 * * * *",
  "transforms": [
    { "type": "validate", "rules": ["ts.region != null", "demand_mw >= 0"] },
    { "type": "enrich",   "with": ["weather_join", "calendar_join"] },
    { "type": "dedupe",   "by": ["ts", "region"] }
  ],
  "destination": "postgresql://ecolens/market_data.fact_demand_5min"
}`}
            </pre>
          </Card>
        ),
        runs: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Pipeline Runs (last 12)</h2>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Run ID</th>
                  <th className="py-2">Pipeline</th>
                  <th className="py-2">Started</th>
                  <th className="py-2">Duration</th>
                  <th className="py-2">Records</th>
                  <th className="py-2">State</th>
                  <th className="py-2">Triggered By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {runs.map((r) => (
                  <tr key={r.id} className="text-white/85">
                    <td className="py-2 font-mono text-[11px] text-white/60">{r.id}</td>
                    <td className="py-2">{r.pipeline_id}</td>
                    <td className="py-2 text-white/60">{r.started_at}</td>
                    <td className="py-2 text-white/60">{r.duration}</td>
                    <td className="py-2 text-white/60 tabular-nums">{r.records.toLocaleString()}</td>
                    <td className="py-2"><span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", STATE_TONE[r.state])}>{r.state}</span></td>
                    <td className="py-2 text-white/60">{r.triggered_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ),
        failed: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Failed Jobs (Retry Queue)</h2>
            <ul className="space-y-2 text-sm">
              {failed.map((j) => (
                <li key={j.id} className="rounded-md border border-rose-300/20 bg-rose-300/[0.04] p-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-white/85 font-medium">{j.pipeline}</div>
                      <div className="text-[11px] text-white/50">
                        <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-rose-200">{j.error_code}</code> {j.error_message}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-white/50">{j.occurred_at}</span>
                      {j.retryable ? (
                        <button className="rounded-md border border-emerald-200/40 bg-emerald-200/10 px-2 py-0.5 font-medium text-emerald-100 hover:bg-emerald-200/15">Retry</button>
                      ) : (
                        <span className="text-white/40">manual fix</span>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        ),
        retry: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Retry Queue</h2>
            <p className="text-sm text-white/70">Exponential backoff (1m, 5m, 15m, 1h, 6h). After 5 attempts the job moves to Manual Triage.</p>
          </Card>
        ),
        scheduler: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Cron Scheduler</h2>
            <p className="text-sm text-white/70">Schedules use the system crontab (no Airflow / Prefect dependency). All times are in <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-emerald-100">Australia/Sydney</code> timezone.</p>
            <pre className="mt-3 rounded-md border border-white/5 bg-black/30 p-3 text-[11px] text-emerald-100 font-mono overflow-x-auto">
{`# /etc/cron.d/ecolens
*/5 * * * *  ecolens  /opt/ecolens/run-pipeline.sh aemo_nem
*/15 * * * * ecolens  /opt/ecolens/run-pipeline.sh bom
0 */1 * * *  ecolens  /opt/ecolens/run-pipeline.sh carbon_intensity
0 2 * * *    ecolens  /opt/ecolens/dbt-run.sh --select tag:nightly`}
            </pre>
          </Card>
        ),
      }}
    />
  );
}
