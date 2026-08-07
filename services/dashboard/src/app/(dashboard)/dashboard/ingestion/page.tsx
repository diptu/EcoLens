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
  fetchPublicFailedRuns,
  fetchPublicRetryQueue,
  fetchPublicScheduler,
  formatPipeline,
  formatRelativeTime,
  formatTimeUntil,
  TriggerIngestionError,
  type RunStatus,
  type PublicRun,
  type FailedRun,
  type RetryQueueItem,
  type SchedulerInfo,
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

/** `GET /v1/ingestion/public/failed` — real, replaces the old "not
 * wired up yet" stub. */
function useFailedRuns() {
  const [failed, setFailed] = useState<{ data: FailedRun[]; total_failed_24h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicFailedRuns(50)
      .then((res) => {
        if (!cancelled) setFailed({ data: res.data, total_failed_24h: res.meta.total_failed_24h });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { failed, error };
}

/** `GET /v1/ingestion/public/retry-queue` — real, replaces the old
 * static prose-only tab. */
function useRetryQueue() {
  const [queue, setQueue] = useState<RetryQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicRetryQueue(50)
      .then((res) => {
        if (!cancelled) setQueue(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { queue, error };
}

/** `GET /v1/ingestion/public/scheduler` — real, replaces the old
 * static cron-file mockup. */
function useScheduler() {
  const [scheduler, setScheduler] = useState<SchedulerInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicScheduler()
      .then((res) => {
        if (!cancelled) setScheduler(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { scheduler, error };
}

export default function DataIngestionPage() {
  const { rows, run, runAll } = usePipelineRuns();
  const { runs, error: runsError } = useRecentRuns();
  const { failed, error: failedError } = useFailedRuns();
  const { queue, error: queueError } = useRetryQueue();
  const { scheduler, error: schedulerError } = useScheduler();

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
        { label: "Failed (24h)", value: failed ? String(failed.total_failed_24h) : "…" },
        { label: "Retry Queue",  value: queue ? String(queue.length) : "…" },
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
            {failedError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load failed jobs ({failedError}).</p>
            ) : failed === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : failed.data.length === 0 ? (
              <p className="text-sm text-white/55">No failed runs in the queried window.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Run ID</th>
                    <th className="py-2">Pipeline</th>
                    <th className="py-2">Started</th>
                    <th className="py-2">Error</th>
                    <th className="py-2">Retries</th>
                    <th className="py-2">In DLQ</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {failed.data.map((r) => (
                    <tr key={r.run_id} className="text-white/85">
                      <td className="py-2 font-mono text-[11px] text-white/60">{r.run_id.slice(0, 8)}</td>
                      <td className="py-2">{formatPipeline(r.pipeline_id)}</td>
                      <td className="py-2 text-white/60">{formatRelativeTime(r.started_at)}</td>
                      <td className="py-2 text-white/60 text-[11px]" title={r.error.message}>
                        {r.error.code ?? r.error.message.slice(0, 40)}
                      </td>
                      <td className="py-2 text-white/60 tabular-nums">{r.retry_count}</td>
                      <td className="py-2">
                        {r.in_dlq ? (
                          <span className="rounded-md border border-rose-300/40 bg-rose-300/10 px-2 py-0.5 text-[11px] font-medium text-rose-200">yes</span>
                        ) : (
                          <span className="text-white/40">no</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ),
        retry: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Retry Queue</h2>
            <p className="mb-3 text-xs text-white/50">
              Backed by <code className="rounded bg-black/30 px-1 py-0.5 font-mono text-emerald-100">status=&apos;sync_failed&apos;</code> runs
              — fetched fine, but the warehouse-sync consumer failed to load them into Postgres. There is no
              automated backoff/retry scheduler; a run sits here until an operator intervenes.
            </p>
            {queueError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load the retry queue ({queueError}).</p>
            ) : queue === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : queue.length === 0 ? (
              <p className="text-sm text-white/55">Retry queue is empty.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Run ID</th>
                    <th className="py-2">Pipeline</th>
                    <th className="py-2">Queued</th>
                    <th className="py-2">Last Error</th>
                    <th className="py-2">Retries</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {queue.map((q) => (
                    <tr key={q.queue_id} className="text-white/85">
                      <td className="py-2 font-mono text-[11px] text-white/60">{q.run_id.slice(0, 8)}</td>
                      <td className="py-2">{formatPipeline(q.pipeline_id)}</td>
                      <td className="py-2 text-white/60">{formatRelativeTime(q.queued_at)}</td>
                      <td className="py-2 text-white/60 text-[11px]" title={q.last_error.message}>
                        {q.last_error.code ?? q.last_error.message.slice(0, 40)}
                      </td>
                      <td className="py-2 text-white/60 tabular-nums">{q.retry_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ),
        scheduler: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Scheduler Status</h2>
            {schedulerError ? (
              <p className="py-6 text-center text-sm text-white/40">Couldn&apos;t load scheduler status ({schedulerError}).</p>
            ) : scheduler === null ? (
              <p className="py-6 text-center text-sm text-white/40">Loading…</p>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field label="Status" value={scheduler.scheduler.status} />
                  <Field label="Workers" value={`${scheduler.scheduler.active_workers}/${scheduler.scheduler.total_workers}`} />
                  <Field label="Queue Depth" value={String(scheduler.scheduler.queue_depth)} />
                </div>
                <p className="text-[11px] text-white/40">
                  Runs execute in-process (FastAPI background tasks for API-triggered runs, the calling
                  GitHub Actions runner for cron-triggered ones) — no separate worker pool or Airflow/Prefect
                  dependency behind this.
                </p>
                <div>
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/60">Upcoming Runs</h3>
                  {scheduler.upcoming_runs.length === 0 ? (
                    <p className="text-sm text-white/55">Nothing scheduled.</p>
                  ) : (
                    <ul className="space-y-1.5 text-sm">
                      {scheduler.upcoming_runs.map((u, i) => (
                        <li key={`${u.pipeline_id}-${i}`} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                          <span className="text-white/85">{formatPipeline(u.pipeline_id)}</span>
                          <span className="text-[11px] text-white/50">{formatTimeUntil(u.scheduled_at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/60">Recent Runs</h3>
                  {scheduler.recent_runs.length === 0 ? (
                    <p className="text-sm text-white/55">No recent runs.</p>
                  ) : (
                    <ul className="space-y-1.5 text-sm">
                      {scheduler.recent_runs.map((r) => (
                        <li key={r.run_id} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                          <span className="text-white/85">{formatPipeline(r.pipeline_id)}</span>
                          <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", STATE_TONE[r.status])}>{r.status}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </Card>
        ),
      }}
    />
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-white/5 bg-white/[0.02] px-2.5 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 font-mono text-white/85">{value}</div>
    </div>
  );
}
