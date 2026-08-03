/**
 * /dashboard/data-ingestion — Data Ingestion (Pipelines)
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { Webhook, Play, RefreshCw, Calendar, AlertTriangle, X, Plus, Loader2 } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { SectionPage } from "@/components/dashboard/section-page";
import {
  PIPELINE_CATALOG,
  triggerHistoricalIngest,
  getHistoricalIngestJob,
  pollIngestJob,
  IngestionApiError,
  type Source,
} from "@/lib/ingestion";
import { cn } from "@/lib/utils";

type RowStatus = "idle" | "queued" | "running" | "success" | "failed";
type RowState = { status: RowStatus; written?: number; error?: string };

const STATE_TONE: Record<RowStatus, string> = {
  idle:    "border-white/10 bg-white/5 text-white/60",
  queued:  "border-amber-300/40 bg-amber-300/10 text-amber-200",
  running: "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
  success: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  failed:  "border-rose-300/40 bg-rose-300/10 text-rose-200",
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Live trigger-and-poll against data-pipeline's real `/ingestion/historical`
 * route (see `lib/ingestion.ts`) — replaces the fictional pipeline list
 * `lib/dashboards.ts`'s old `getPipelines()` mock used to render here
 * (8 pipelines from sources like "ENTSO-E API"/"EIA API" that don't
 * exist in this platform). `PIPELINE_CATALOG` is the honest 6: the 5
 * real ingestion sources + the dbt-warehouse build (not triggerable
 * from here — that's a dbt run, not an ingestion fetch). */
function usePipelineRuns() {
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const cancelFns = useRef<Record<string, () => void>>({});

  useEffect(() => {
    return () => {
      Object.values(cancelFns.current).forEach((cancel) => cancel());
    };
  }, []);

  function run(id: Source) {
    cancelFns.current[id]?.();
    setRows((prev) => ({ ...prev, [id]: { status: "queued" } }));

    triggerHistoricalIngest(id, { date: todayIso() })
      .then(({ job_id }) => {
        setRows((prev) => ({ ...prev, [id]: { status: "running" } }));
        cancelFns.current[id] = pollIngestJob(getHistoricalIngestJob, job_id, (job) => {
          if (job.status === "running") {
            setRows((prev) => ({ ...prev, [id]: { status: "running" } }));
          } else if (job.status === "completed") {
            setRows((prev) => ({ ...prev, [id]: { status: "success", written: job.written ?? 0 } }));
          } else {
            setRows((prev) => ({ ...prev, [id]: { status: "failed", error: job.error ?? "unknown error" } }));
          }
        });
      })
      .catch((err) => {
        const message = err instanceof IngestionApiError ? err.message : "trigger failed";
        setRows((prev) => ({ ...prev, [id]: { status: "failed", error: message } }));
      });
  }

  function runAll() {
    for (const entry of PIPELINE_CATALOG) {
      if (entry.triggerable) run(entry.id as Source);
    }
  }

  return { rows, run, runAll };
}

export default function DataIngestionPage() {
  const { rows, run, runAll } = usePipelineRuns();

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
        { label: "Pipelines",    value: String(PIPELINE_CATALOG.length) },
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
              <button
                onClick={runAll}
                className="inline-flex items-center gap-1 rounded-md bg-emerald-200/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-200/20"
              >
                <Play className="h-3.5 w-3.5" /> Trigger All
              </button>
            </div>
            <Card>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Pipeline</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Detail</th>
                    <th className="py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {PIPELINE_CATALOG.map((p) => {
                    const row = rows[p.id] ?? { status: "idle" as RowStatus };
                    const busy = row.status === "queued" || row.status === "running";
                    return (
                      <tr key={p.id} className="text-white/85">
                        <td className="py-2 pr-2">{p.label}</td>
                        <td className="py-2 pr-2">
                          <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium", STATE_TONE[row.status])}>
                            {busy && <Loader2 className="h-3 w-3 animate-spin" />}
                            {row.status}
                          </span>
                        </td>
                        <td className="py-2 pr-2 text-white/60 text-[11px]">
                          {row.status === "success" && `${row.written ?? 0} rows written`}
                          {row.status === "failed" && (row.error ?? "failed")}
                          {!p.triggerable && "dbt build — not triggerable here"}
                        </td>
                        <td className="py-2 text-right">
                          <div className="inline-flex items-center gap-1">
                            <button
                              onClick={() => p.triggerable && run(p.id as Source)}
                              disabled={!p.triggerable || busy}
                              title={p.triggerable ? "Run now (today)" : "Not triggerable via this API"}
                              className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
                            >
                              <Play className="h-3.5 w-3.5" />
                            </button>
                            <button className="rounded p-1 text-white/50 hover:bg-white/5 hover:text-white" title="Reschedule"><Calendar className="h-3.5 w-3.5" /></button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
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
            <h2 className="mb-3 text-base font-semibold text-white">Pipeline Runs</h2>
            <p className="text-sm text-white/50">
              data-pipeline has no run-history endpoint yet — only trigger + poll
              (see <code className="rounded bg-black/30 px-1 font-mono text-emerald-100">lib/ingestion.ts</code>).
              Trigger a pipeline from the Pipelines tab to see its live status here in this session.
            </p>
          </Card>
        ),
        failed: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Failed Jobs</h2>
            <p className="text-sm text-white/50">
              No failed-jobs list endpoint exists yet. Use the Pipelines tab to trigger a run
              and see its outcome, or <code className="rounded bg-black/30 px-1 font-mono text-emerald-100">/ingestion/retry-missing</code> to
              find and re-ingest days with missing rows for a given source.
            </p>
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
