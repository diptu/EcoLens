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
  triggerIngestionRun,
  pollLatestRun,
  fetchPublicRuns,
  formatPipeline,
  formatRelativeTime,
  TriggerIngestionError,
  type RunStatus,
  type PublicRun,
} from "@/lib/ingestion";
import { cn } from "@/lib/utils";

type RowStatus = "idle" | RunStatus;
type RowState = { status: RowStatus; records?: number | null; error?: string };

const STATE_TONE: Record<RowStatus, string> = {
  idle:        "border-white/10 bg-white/5 text-white/60",
  queued:      "border-amber-300/40 bg-amber-300/10 text-amber-200",
  running:     "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
  staged:      "border-sky-300/40 bg-sky-300/10 text-sky-200",
  success:     "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  failed:      "border-rose-300/40 bg-rose-300/10 text-rose-200",
  sync_failed: "border-rose-300/40 bg-rose-300/10 text-rose-200",
  partial:     "border-amber-300/40 bg-amber-300/10 text-amber-200",
};

/** Live trigger-and-poll against data-pipeline's real, currently open
 * `POST /v1/data-sources/{id}/run` (see `lib/ingestion.ts`'s module
 * docstring — verified against a running instance, no auth required)
 * — replaces the fictional pipeline list `lib/dashboards.ts`'s old
 * `getPipelines()` mock used to render here (8 pipelines from sources
 * like "ENTSO-E API"/"EIA API" that don't exist in this platform).
 * `PIPELINE_CATALOG` is the honest 6: the 5 real ingestion sources +
 * the dbt-warehouse build (not triggerable from here — that's a dbt
 * run, not an ingestion fetch). */
function usePipelineRuns() {
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const cancelFns = useRef<Record<string, () => void>>({});

  useEffect(() => {
    return () => {
      Object.values(cancelFns.current).forEach((cancel) => cancel());
    };
  }, []);

  function run(sourceId: string) {
    cancelFns.current[sourceId]?.();
    setRows((prev) => ({ ...prev, [sourceId]: { status: "queued" } }));

    triggerIngestionRun(sourceId)
      .then(() => {
        cancelFns.current[sourceId] = pollLatestRun(sourceId, (latest) => {
          if (!latest) return;
          setRows((prev) => ({
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
        setRows((prev) => ({ ...prev, [sourceId]: { status: "failed", error: message } }));
      });
  }

  function runAll() {
    for (const entry of PIPELINE_CATALOG) {
      if (entry.triggerable && entry.sourceId) run(entry.sourceId);
    }
  }

  return { rows, run, runAll };
}

function useRecentRuns() {
  const [runs, setRuns] = useState<PublicRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicRuns(12)
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

export default function DataIngestionPage() {
  const { rows, run, runAll } = usePipelineRuns();
  const { runs, error: runsError } = useRecentRuns();

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
                    const row = (p.sourceId ? rows[p.sourceId] : undefined) ?? { status: "idle" as RowStatus };
                    const busy = row.status === "queued" || row.status === "running" || row.status === "staged";
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
                          {(row.status === "success" || row.status === "partial") && row.records != null && `${row.records} records`}
                          {(row.status === "failed" || row.status === "sync_failed") && (row.error ?? "failed")}
                          {!p.triggerable && "dbt build — not triggerable here"}
                        </td>
                        <td className="py-2 text-right">
                          <div className="inline-flex items-center gap-1">
                            <button
                              onClick={() => p.triggerable && p.sourceId && run(p.sourceId)}
                              disabled={!p.triggerable || busy}
                              title={p.triggerable ? "Run now" : "Not triggerable via this API"}
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
            <h2 className="mb-3 text-base font-semibold text-white">Pipeline Runs (last 12)</h2>
            {runsError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load runs ({runsError}).</p>
            ) : runs === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : runs.length === 0 ? (
              <p className="text-sm text-white/55">No runs yet — trigger a pipeline from the Pipelines tab.</p>
            ) : (
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
                      <td className="py-2 font-mono text-[11px] text-white/60">{r.id.slice(0, 8)}</td>
                      <td className="py-2">{formatPipeline(r.pipeline_id)}</td>
                      <td className="py-2 text-white/60">{formatRelativeTime(r.started_at)}</td>
                      <td className="py-2 text-white/60">
                        {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
                      </td>
                      <td className="py-2 text-white/60 tabular-nums">
                        {(r.records_inserted ?? r.records_fetched ?? 0).toLocaleString()}
                      </td>
                      <td className="py-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", STATE_TONE[r.status])}>{r.status}</span>
                      </td>
                      <td className="py-2 text-white/60">{r.trigger}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ),
        failed: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Failed Jobs</h2>
            <p className="text-sm text-white/50">
              Use the Pipelines tab to trigger a run and see its outcome, or the Runs tab for
              recent history — a dedicated failed-jobs view isn&apos;t wired up on this page yet.
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
