/**
 * /data-ingestion — Operational control surface.
 * Previously "Operational Tasks" / `/dashboard/operational-tasks`,
 * then `/dashboard/data-ingestion` — both now redirect here (see
 * those routes' own page.tsx) — same page, moved to a top-level path
 * same as `/analytics-forecast`'s own move.
 *
 * Mirrors the "Operational Tasks" reference layout: 6 KPIs, Pipeline
 * Operations + Model Operations tables side by side, Active Tasks
 * with tabbed filters. (System Commands removed 2026-08-11. Of its 3
 * real wired actions: system-health checks and dbt builds are still
 * reachable elsewhere on this page -- System Diagnostics' own Refresh
 * button, and Pipeline Operations' own "Run now" on the dbt-warehouse
 * row, respectively -- but "Rebuild Features" (`POST /v1/features/
 * rebuild`) had no other UI entry point and is no longer triggerable
 * from this page at all.
 *
 * **Model Training & Tuning form, Recent Training Runs, and Scheduled
 * Operations removed** (their own dedicated sections, not the real
 * data/control behind them): Model Operations' own "Fine-tune" button
 * still triggers the same real `triggerTraining()` this form used to
 * (just without the regions/window-hours override fields, which had
 * no other real entry point and are gone with the form); Active
 * Tasks' real in-flight training rows are still derived from the same
 * `fetchTrainingRuns()` call; Pipeline Operations above still shows/
 * triggers each pipeline's real schedule. `ScheduledTable`/
 * `RecentTrainingRunsList` (this page's own components, only ever
 * rendered by these sections) were removed as dead code along with
 * them.)
 *
 * Pipeline Operations lists the real 6-pipeline inventory (OpenElectricity,
 * AEMO NEM, AEMO WEM, BoM, AEMO Public Holidays, dbt warehouse build) from
 * the static `PIPELINE_CATALOG` (`lib/ingestion.ts`), not the old mock's
 * 5 fictional vendors (ENTSO-E, Open-Meteo, EIA, "Carbon Intensity API",
 * ICE) -- see `todo-operational-tasks.md` for the full per-section plan.
 *
 * **Cutover**: per-row actions now talk to `services/ingestion` and
 * `services/waerehouse` instead of `data-pipeline` (`lib/ingestion.ts`'s
 * own module docstring has the full detail on what moved, including
 * the dbt endpoint's real, Postgres-backed concurrent-build lock).
 *
 * Per-row "Run now" is real: `triggerIngestionRun()`
 * (`POST /v1/data-sources/{id}/run`, `services/ingestion`) — deliberately
 * open, no auth required (this platform has no sign-in at all; see
 * `lib/ingestion.ts`'s module docstring). The dbt warehouse-build
 * "pipeline" (`source_id: null`) can't be triggered this way — it uses
 * its own `triggerDbtBuild()` (`POST /v1/dbt/build`, `services/waerehouse`).
 *
 * AEMO NEM/WEM, BoM, and OpenElectricity additionally get a "Backfill"
 * action (`triggerBackfill()`, `POST /v1/data-sources/{id}/backfill`)
 * with a month/day picker — real historical data for the selected
 * range, not the 30-min-lookback "Run now" gets. `PIPELINE_CATALOG[].
 * backfillable` is `false` only for Holidays/dbt-warehouse: Holidays is
 * a once-a-year (region, date) snapshot with no HTTP call and no
 * date-range concept at all (`ingest_holidays.py`'s own docstring), and
 * dbt-warehouse isn't a data source to begin with (see that flag's own
 * docstring in `lib/ingestion.ts`). BoM joined the real-backfill set
 * 2026-08-05, sourced from Open-Meteo's ERA5 archive rather than BoM's
 * own API (which has no date-range query at all) — see `ingest_bom.py`'s
 * module docstring for why. OpenElectricity joined the same day, real
 * `network_region`/`date_start`/`date_end` params on its own API.
 *
 * **2026-08-08 follow-up pass**: KPI row and Active Tasks
 * (`ingestion`-typed rows) are now real too -- derived from
 * `fetchPublicPipelines()`/this page's own live pipeline-poll state/
 * `modelInfo`, not `getOperationalKpis()`/`getActiveTasks()`'s mocks
 * (full reasoning in `services/ingestion/TODO.md`'s Operational Tasks
 * section). Active Tasks' other 5 task types
 * (data_quality/feature_build/forecast/report/anomaly) still have no
 * "task in flight" concept anywhere in any service -- `getActiveTasks()`'s
 * hardcoded mock rows for them were removed entirely (2026-08-08, root
 * `TODO.md`'s "Active Tasks" item) rather than kept: they were shown with
 * zero visual distinction from the real rows above, a real violation of
 * this app's own no-silent-fabrication convention. An honest empty state
 * for those types is more truthful than a labeled-fake row.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Calendar,
  Check,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  type ActiveTask,
  type OperationalKpi,
  type TaskStatus,
} from "@/lib/admin-dashboard";
import {
  fetchModelInfo,
  fetchModelVersions,
  pollForNewModelVersion,
  type ModelInfo,
  type ModelVersion,
} from "@/lib/emissions";
import { fetchAllServicesHealth, fetchSystemLoad, type ServiceHealth, type SystemLoad } from "@/lib/health";
import {
  PIPELINE_CATALOG,
  triggerTraining,
  fetchTrainingRuns,
  triggerIngestionRun,
  pollLatestRun,
  triggerBackfill,
  pollBackfillSummary,
  fetchBackfillStatus,
  triggerDbtBuild,
  pollLatestDbtBuild,
  fetchPublicPipelines,
  fetchPublicRuns,
  monthToRange,
  dayToRange,
  formatRelativeTime,
  formatTimeUntil,
  formatSource,
  TriggerIngestionError,
  type RunStatus,
  type TrainingRunLog,
  type BackfillTrigger,
  type BackfillProgress,
  type LivePipeline,
  type PublicRun,
} from "@/lib/ingestion";

// Mirrors `services/waerehouse`'s `Settings.scheduled_build_min_interval_minutes`
// default (15) -- kept in sync by hand, same convention `lib/env.ts`'s own
// port-number fallbacks already document; not exposed via any API response
// this dashboard currently fetches. Used by the "Next Retrain" KPI below.
const DBT_MIN_INTERVAL_MINUTES = 15;

// ────────────────────────────────────────────────────────────────────
// Icons
// ────────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Play, Database, Cpu, Calendar, RefreshCw, Trash2, Search, Activity,
};

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


// ────────────────────────────────────────────────────────────────────
// Page
// ────────────────────────────────────────────────────────────────────

/** `runId`/`startedAt`/`triggeredBy` come straight off the real
 * `PublicRun` `pollLatestRun`'s callback hands back -- carried here (not
 * just `status`/`records`) so the Active Tasks KPI tile can synthesize
 * real `ingestion`-typed rows for whichever pipelines are actually
 * in flight right now, instead of only ever showing the mock's fake
 * ones (see `pipelineActiveTasks` below). */
type RowState = {
  status: RowStatus;
  records?: number | null;
  error?: string;
  runId?: string;
  startedAt?: string;
  triggeredBy?: string;
};

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
  const [pipelines, setPipelines] = useState<LivePipeline[] | null>(null);
  const [pipelineRows, setPipelineRows] = useState<Record<string, RowState>>({});
  const cancelFns = useRef<Record<string, () => void>>({});
  const [backfillModal, setBackfillModal] = useState<{ sourceId: string; label: string } | null>(null);
  const [backfillStatus, setBackfillStatus] = useState<Record<string, BackfillState>>({});
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [modelInfoLoaded, setModelInfoLoaded] = useState(false);
  const [modelVersions, setModelVersions] = useState<ModelVersion[] | null>(null);
  const [trainStatus, setTrainStatus] = useState<TrainStatus>({ state: "idle" });
  const [trainingRuns, setTrainingRuns] = useState<TrainingRunLog[] | null>(null);
  const [serviceHealth, setServiceHealth] = useState<ServiceHealth[] | null>(null);
  const [serviceHealthCheckedAt, setServiceHealthCheckedAt] = useState<string | null>(null);
  const [serviceHealthRefreshing, setServiceHealthRefreshing] = useState(false);
  // Real host/VM load (`GET /v1/system/load`, 2026-08-20) -- `null`
  // while loading/unreachable, same "System Load" KPI this used to show
  // as a permanent placeholder for, now backed by a real endpoint.
  const [systemLoad, setSystemLoad] = useState<SystemLoad | null>(null);
  const [runLog, setRunLog] = useState<PublicRun[] | null>(null);
  const [runLogRefreshKey, setRunLogRefreshKey] = useState(0);
  const [runLogRefreshing, setRunLogRefreshing] = useState(false);
  const [runLogHasMore, setRunLogHasMore] = useState(false);
  // Real cursor-based pagination (`GET /v1/ingestion/public/runs`'s own
  // `cursor`/`has_more`/`next_cursor` -- not a client-side offset, this
  // is a real DB keyset cursor). `runLogCursorStack[i]` is the cursor
  // used to fetch page `i` (`null` for page 0, the newest rows) --
  // recorded as each page's own response comes back so "Previous" can
  // jump straight back to a page already visited instead of re-deriving
  // it, matching how forward-only cursor pagination is normally driven
  // from a UI that still wants to go both directions.
  const [runLogCursorStack, setRunLogCursorStack] = useState<(string | null)[]>([null]);
  const [runLogPageIndex, setRunLogPageIndex] = useState(0);
  const RUN_LOG_PAGE_SIZE = 10;

  // System Diagnostics card -- root TODO.md's "should show which system
  // are healthy and which are not": a persistent status grid, not just
  // the one-shot "Check System Health" button `executeCommand`'s `c6`
  // already had (that button's real call, `fetchAllServicesHealth()`,
  // is reused here so both surfaces agree). Fetches on mount and every
  // 60s after that -- frequent enough to catch a service dying between
  // visits without hammering the 4 real `/readyz`-shaped endpoints on
  // every render.
  //
  // IAM (services/iam) is no longer building, so it's filtered out of
  // this page's grid + "Check System Health" result rather than
  // permanently reading as unhealthy. `lib/health.ts`'s
  // `fetchAllServicesHealth` is left as-is -- system-health/ now applies
  // this same filter too; operations/ still surfaces IAM. That leaves 3
  // services actually shown here: forecast-api, ingestion, warehouse
  // (`data-pipeline` removed 2026-09-12 -- no such service exists in
  // this monorepo any more).
  const fetchOperationalServicesHealth = () =>
    fetchAllServicesHealth().then((results) => results.filter((r) => r.service !== "iam"));

  const refreshServiceHealth = useMemo(
    () => () => {
      setServiceHealthRefreshing(true);
      fetchOperationalServicesHealth()
        .then((results) => {
          setServiceHealth(results);
          setServiceHealthCheckedAt(new Date().toISOString());
        })
        .catch(() => {})
        .finally(() => setServiceHealthRefreshing(false));
    },
    [],
  );

  useEffect(() => {
    refreshServiceHealth();
    const interval = setInterval(refreshServiceHealth, 60_000);
    return () => clearInterval(interval);
  }, [refreshServiceHealth]);

  // Real host/VM load average + memory pressure -- refreshed on the
  // same 60s cadence as service health above (load averages are
  // already smoothed over 1/5/15 real minutes, so anything faster would
  // just be extra load with no extra signal).
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetchSystemLoad()
        .then((load) => {
          if (!cancelled) setSystemLoad(load);
        })
        .catch(() => {
          if (!cancelled) setSystemLoad(null);
        });
    };
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

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

  // Backs the Scheduled Operations card (real cron/next-run/last-run per
  // pipeline) and the KPI row's "Ingestion Pipelines"/"Last Ingestion"
  // numbers below -- `fetchPublicPipelines()` already composes
  // ingestion's 5 real sources + a synthesized dbt-warehouse row from
  // `services/waerehouse`, it just had no caller on this page before.
  useEffect(() => {
    let cancelled = false;
    fetchPublicPipelines()
      .then((r) => {
        if (!cancelled) setPipelines(r.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Pipeline Run Log -- real rows straight from `meta._ingest_log` via
  // `GET /v1/ingestion/public/runs` (`fetchPublicRuns`, already used
  // elsewhere on this page for per-row poll state, just not rendered as
  // its own persistent history table before). Unlike `pipelineRows`
  // (`RowState`, reset on every page load, only ever populated by a
  // "Run now"/backfill click *this session*), this is the actual
  // cross-session history -- when a pipeline last ran whether or not
  // anyone had this tab open, how many rows it landed, and whether a
  // human or Celery Beat kicked it off (`trigger`: "manual"/"schedule"/
  // "backfill"). Re-fetches whenever `runLogRefreshKey` (manual refresh
  // button, always resets to page 0) or `runLogPageIndex` (Prev/Next)
  // changes -- no auto-poll interval, since this is a history list, not
  // a live status the user is watching resolve.
  useEffect(() => {
    let cancelled = false;
    setRunLogRefreshing(true);
    const cursor = runLogCursorStack[runLogPageIndex] ?? undefined;
    fetchPublicRuns(RUN_LOG_PAGE_SIZE, undefined, cursor)
      .then((r) => {
        if (cancelled) return;
        setRunLog(r.data);
        setRunLogHasMore(r.has_more);
        // Only append once -- if the user has already paged forward past
        // this point and come back, the next page's real cursor is
        // already recorded; re-appending here would fork the stack from
        // a possibly-stale `next_cursor` (real rows can land between
        // visits) instead of reusing the one already visited.
        setRunLogCursorStack((prev) =>
          r.has_more && r.next_cursor && prev.length === runLogPageIndex + 1
            ? [...prev, r.next_cursor]
            : prev,
        );
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setRunLogRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runLogRefreshKey, runLogPageIndex]);

  const refreshRunLog = () => {
    setRunLogCursorStack([null]);
    setRunLogPageIndex(0);
    setRunLogRefreshKey((k) => k + 1);
  };

  // `type: "ingestion"`/`"transform"` rows synthesized from this same
  // page's own live `pollLatestRun`/`pollLatestDbtBuild`/
  // `pollBackfillSummary` subscriptions (`pipelineRows`) -- real "is
  // this pipeline in flight right now" state this page was already
  // tracking for the Pipeline Operations card, just not previously
  // surfaced into Active Tasks (`services/ingestion/TODO.md`'s
  // Operational Tasks section). The dbt-warehouse row gets its own
  // `"transform"` type, not folded into `"ingestion"` (`services/
  // waerehouse/TODO.md`'s own note on that earlier mislabeling -- it's
  // a dbt build, not a fetch). Only non-idle, non-terminal rows count
  // as "active" -- a `success`/`failed` row isn't a task in flight
  // anymore, same terminal-status set `pollLatestRun`'s own
  // `TERMINAL_RUN_STATUSES` uses.
  const pipelineActiveTasks = useMemo((): ActiveTask[] => {
    return PIPELINE_CATALOG.filter((p) => p.triggerable)
      .map((p): ActiveTask | null => {
        const rowKey = p.sourceId ?? p.id;
        const row = pipelineRows[rowKey];
        if (!row) return null;
        if (row.status !== "queued" && row.status !== "running" && row.status !== "staged") {
          return null;
        }
        const status: TaskStatus = row.status === "queued" ? "queued" : "running";
        return {
          id: row.runId ?? rowKey,
          type: p.sourceId ? "ingestion" : "transform",
          target: p.label,
          triggered_by: row.triggeredBy ?? "dashboard",
          started_at: row.startedAt ? formatRelativeTime(row.startedAt) : "just now",
          status,
          progress: status === "queued" ? 10 : 60,
        };
      })
      .filter((t): t is ActiveTask => t !== null);
  }, [pipelineRows]);

  // `model_training`/`ingestion`/`transform`-typed rows are real
  // (`meta._training_log` + this page's own live pipeline/dbt-build
  // polling). The remaining 4 task types (data_quality, feature_build,
  // forecast, report, anomaly) used to fall back to `getActiveTasks()`'s
  // hardcoded mock rows (fake IDs, fake "May 19" dates that don't even
  // match this app's real calendar) shown with zero visual distinction
  // from the real rows above -- a real violation of this app's own
  // "no silently fabricated dashboards" convention every other section
  // follows (`IllustrativeBadge`, honest empty states). Removed
  // 2026-08-08 rather than badged: nothing logs "a task of this type is
  // in flight" anywhere in any service yet, so there's no real shape to
  // preview either -- an honest empty state for those types (via
  // `ActiveTasksTable`'s own "No tasks" case) is more truthful than a
  // labeled-fake row.
  const allTasks = useMemo((): ActiveTask[] => {
    const realTrainingTasks: ActiveTask[] = (trainingRuns ?? []).map((r) => ({
      id: r.id,
      type: "model_training",
      target: r.model_name,
      triggered_by: r.triggered_by,
      started_at: formatRelativeTime(r.started_at),
      status: r.status === "running" ? "running" : r.status === "success" ? "completed" : "failed",
      progress: r.status === "running" ? 50 : 100,
    }));
    return [...realTrainingTasks, ...pipelineActiveTasks];
  }, [trainingRuns, pipelineActiveTasks]);

  useEffect(() => {
    return () => {
      Object.values(cancelFns.current).forEach((cancel) => cancel());
    };
  }, []);

  // Rehydrates pipeline/backfill status from the backend on mount --
  // without this, `pipelineRows`/`backfillStatus` only ever get set as a
  // side effect of clicking "Run now"/"Start Backfill" in *this* browser
  // session, so a page refresh always resets every row to "Idle" even
  // when a run or backfill is genuinely still in progress server-side
  // (the `backfill:lock:{id}` Redis key / `meta._ingest_log` rows don't
  // go anywhere on refresh -- only this component's React state does).
  useEffect(() => {
    let cancelled = false;

    PIPELINE_CATALOG.forEach((p) => {
      if (!p.sourceId) {
        // dbt-warehouse row -- polls `GET /v1/dbt/build/runs` for its
        // live status instead of a per-source run, so a build triggered
        // from a *different* browser tab/session is visible here too,
        // not just self-triggered ones (`services/waerehouse/TODO.md`'s
        // own note on this gap).
        cancelFns.current[p.id] = pollLatestDbtBuild((latest) => {
          if (!latest) return;
          setPipelineRows((prev) => ({
            ...prev,
            [p.id]: {
              status: latest.status,
              runId: latest.id,
              startedAt: latest.started_at,
              triggeredBy: latest.trigger,
            },
          }));
        });
        return;
      }
      const sourceId = p.sourceId;

      cancelFns.current[sourceId] = pollLatestRun(sourceId, (latest) => {
        if (!latest) return;
        setPipelineRows((prev) => ({
          ...prev,
          [sourceId]: {
            status: latest.status,
            records: latest.records_inserted ?? latest.records_fetched,
            runId: latest.id,
            startedAt: latest.started_at,
            triggeredBy: latest.trigger,
          },
        }));
      });

      if (!p.backfillable) return;
      fetchBackfillStatus(sourceId)
        .then((status) => {
          if (cancelled || !status.running || !status.trigger) return;
          const trigger = status.trigger;

          // Don't re-grant the full estimated-duration timeout budget --
          // only what's left of it, so a stale lock (e.g. a crashed
          // background task that never cleared it) doesn't poll forever.
          const totalTimeoutMs = Math.max(30_000, trigger.estimated_duration_seconds * 1000 + 30_000);
          const elapsedMs = Date.now() - new Date(trigger.queued_at).getTime();
          const remainingMs = Math.max(30_000, totalTimeoutMs - elapsedMs);

          cancelFns.current[sourceId]?.(); // supersede the plain run-poll above
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
            remainingMs,
          );
        })
        .catch(() => {});
    });

    return () => {
      cancelled = true;
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
      .catch(() => {});
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
        cancelFns.current["__model_training__"] = pollForNewModelVersion(
          sinceVersion,
          (versions) => {
            setTrainStatus({ state: "polling" });
            fetchTrainingRuns(5).then((r) => setTrainingRuns(r.data)).catch(() => {});
            const newest = versions.data[0]?.version ?? null;
            if (newest !== sinceVersion) {
              setModelVersions(versions.data);
              fetchModelInfo().then(setModelInfo).catch(() => {});
              setTrainStatus({ state: "idle" });
            }
          },
          5000,
          120_000,
          undefined,
          // Real bug fix (2026-08-11) -- see `pollForNewModelVersion`'s
          // own comment: previously left this stuck on "polling" forever
          // if the real training-trigger consumer crashed or the run
          // genuinely failed, no error, no way to tell.
          () => {
            setTrainStatus({
              state: "error",
              message:
                "No new version registered within 2 minutes -- check the training worker, or the Active Tasks tab above.",
            });
          },
        );
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
              runId: latest.id,
              startedAt: latest.started_at,
              triggeredBy: latest.trigger,
            },
          }));
        });
      })
      .catch((err) => {
        const message = err instanceof TriggerIngestionError ? err.message : "trigger failed";
        setPipelineRows((prev) => ({ ...prev, [sourceId]: { status: "failed", error: message } }));
      });
  }

  // `pipe-dbt-warehouse` has no `sourceId` (it's a dbt build, not an
  // ingestion fetch) -- keyed by the pipeline id instead, same
  // `pipelineRows` map `triggerPipeline` above uses. Unlike that one,
  // `triggerDbtBuild()` resolves only once the real build finishes
  // (TODO.md's backfill section) -- no poll loop needed, just set the
  // final status directly.
  function triggerDbtWarehouseBuildRow() {
    const key = "pipe-dbt-warehouse";
    cancelFns.current[key]?.();
    setPipelineRows((prev) => ({ ...prev, [key]: { status: "queued" } }));

    triggerDbtBuild()
      .then((result) => {
        setPipelineRows((prev) => ({
          ...prev,
          [key]: { status: result.exit_code === 0 ? "success" : "failed" },
        }));
      })
      .catch((err) => {
        const message = err instanceof TriggerIngestionError ? err.message : "dbt build trigger failed";
        setPipelineRows((prev) => ({ ...prev, [key]: { status: "failed", error: message } }));
      });
  }

  function submitBackfill(sourceId: string, start: string, end: string) {
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

  // Replaces `getOperationalKpis()`'s 6 hardcoded numbers -- all 6 are
  // now derived from data this page fetches for real (`pipelines`/
  // `allTasks`/`modelInfo`; "System Load" joined 2026-08-20 via
  // ingestion's real `GET /v1/system/load`, `os.getloadavg()`/
  // `/proc/meminfo` read fresh on every call -- see `lib/health.ts`'s
  // `SystemLoad` type for why that reflects the whole shared VM, not
  // just one container).
  //
  // "Next Retrain" is genuinely event-driven -- there's no fixed cron,
  // training only fires off a successful dbt build (`services/
  // waerehouse/app/dbt/scheduler.py`'s `run_build`). But that scheduler
  // *does* debounce: `trigger_build_if_due` only lets a new build start
  // once `Settings.scheduled_build_min_interval_minutes` has passed
  // since the last build attempt (`meta._dbt_build_log.started_at`),
  // regardless of status. That's a real, computable "earliest a retrain
  // can possibly fire next" -- last build's `started_at` (already
  // live-polled into `pipelineRows["pipe-dbt-warehouse"]` for the dbt
  // row above) plus that interval -- just not a *guaranteed* time, since
  // it still needs a new landed event to actually trigger it. Shown as
  // an honest lower bound, not a promise.
  //
  const kpis = useMemo((): OperationalKpi[] => {
    const total = pipelines?.length ?? null;
    const activeCount = pipelines?.filter((p) => p.schedule.enabled).length ?? null;
    const pausedCount = total != null && activeCount != null ? total - activeCount : null;
    const lastRunAt = (pipelines ?? [])
      .map((p) => p.last_run_at)
      .filter((v): v is string => v != null)
      .sort()
      .at(-1);
    const modelStatusLabel =
      modelInfo == null
        ? "—"
        : modelInfo.status === "loaded"
          ? "Healthy"
          : "Not loaded";
    const modelStatusSub =
      modelInfo?.status === "loaded"
        ? `v${modelInfo.version ?? "?"} in ${modelInfo.stage ?? "an unknown stage"}`
        : "No model trained + promoted yet";
    const lastDbtBuildStartedAt = pipelineRows["pipe-dbt-warehouse"]?.startedAt ?? null;
    const earliestNextRetrainAt = lastDbtBuildStartedAt
      ? new Date(
          new Date(lastDbtBuildStartedAt).getTime() + DBT_MIN_INTERVAL_MINUTES * 60_000,
        ).toISOString()
      : null;
    const nextRetrainValue = earliestNextRetrainAt
      ? formatTimeUntil(earliestNextRetrainAt)
      : "—";
    const nextRetrainSub = earliestNextRetrainAt
      ? nextRetrainValue === "due now"
        ? "Eligible now -- fires on the next landed event"
        : `Eligible from ${new Date(earliestNextRetrainAt).toLocaleString()} -- still needs new data to land`
      : "Event-driven only, no fixed cron";
    return [
      {
        label: "Ingestion Pipelines",
        value: total ?? "—",
        sub: total == null ? "Loading…" : `${activeCount} Active · ${pausedCount} Paused`,
        icon: "Play",
        tone: "ok",
      },
      {
        label: "Active Tasks",
        value: taskCounts.all,
        sub: `${taskCounts.running} Running · ${taskCounts.queued} Queued`,
        icon: "ListTodo",
        tone: "ok",
      },
      {
        label: "Last Ingestion",
        value: lastRunAt ? formatRelativeTime(lastRunAt) : "—",
        sub: lastRunAt ?? "No pipeline has run yet",
        icon: "Database",
        tone: "neutral",
      },
      {
        label: "Model Status",
        value: modelStatusLabel,
        sub: modelStatusSub,
        icon: "Cpu",
        tone: modelInfo?.status === "loaded" ? "ok" : "neutral",
      },
      {
        label: "Next Retrain",
        value: nextRetrainValue,
        sub: nextRetrainSub,
        icon: "Calendar",
        tone: "neutral",
      },
      {
        label: "System Load",
        value: systemLoad ? `${systemLoad.mem_used_pct.toFixed(0)}%` : "—",
        sub: systemLoad
          ? `Load avg ${systemLoad.load_avg_1m.toFixed(2)} · ${systemLoad.cpu_count} cores · ${Math.round(systemLoad.mem_available_mb).toLocaleString()}MB free`
          : "Unreachable — GET /v1/system/load failed",
        icon: "Activity",
        tone:
          systemLoad == null
            ? "neutral"
            : systemLoad.mem_used_pct >= 85 || systemLoad.load_avg_1m / systemLoad.cpu_count >= 1
              ? "warn"
              : "ok",
      },
    ];
  }, [pipelines, taskCounts, modelInfo, pipelineRows, systemLoad]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Activity className="h-6 w-6 text-emerald-100" />
          Data Ingestion
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Trigger pipelines, retrain models, tune parameters and manage system operations.
        </p>
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
            onTriggerDbtBuild={triggerDbtWarehouseBuildRow}
            backfillStatus={backfillStatus}
            onOpenBackfill={(sourceId, label) => setBackfillModal({ sourceId, label })}
          />
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
        </Card>
      </div>

      {/* Pipeline Run Log */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-white">Pipeline Run Log</h2>
            <p className="text-xs text-white/50">
              Real history from <code className="rounded bg-black/30 px-1 font-mono">meta._ingest_log</code> —
              last run per pipeline, records fetched, status, and whether a person or the
              scheduler triggered it. Persists across page loads, unlike Pipeline Operations above.
            </p>
          </div>
          <button
            onClick={refreshRunLog}
            disabled={runLogRefreshing}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
              runLogRefreshing
                ? "cursor-not-allowed border-white/10 bg-white/5 text-white/40"
                : "border-emerald-200/30 bg-emerald-200/10 text-emerald-100 hover:bg-emerald-200/15",
            )}
          >
            <RefreshCw className={cn("h-3 w-3", runLogRefreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
        <RunLogTable runs={runLog} />
        <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-3 text-xs text-white/50">
          <span>Page {runLogPageIndex + 1}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setRunLogPageIndex((i) => Math.max(0, i - 1))}
              disabled={runLogPageIndex === 0 || runLogRefreshing}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 font-medium",
                runLogPageIndex === 0 || runLogRefreshing
                  ? "cursor-not-allowed border-white/10 bg-white/5 text-white/30"
                  : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white",
              )}
            >
              <ChevronLeft className="h-3 w-3" />
              Previous
            </button>
            <button
              type="button"
              onClick={() => setRunLogPageIndex((i) => i + 1)}
              disabled={!runLogHasMore || runLogRefreshing}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 font-medium",
                !runLogHasMore || runLogRefreshing
                  ? "cursor-not-allowed border-white/10 bg-white/5 text-white/30"
                  : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white",
              )}
            >
              Next
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      </Card>

      {/* Active Tasks (its own card + All/Running/Queued/Completed/
          Failed filter tabs, `ActiveTasksTable`), Model Training &
          Tuning, Recent Training Runs, and Scheduled Operations were
          all removed here (real functionality, not stubs) -- Model
          Operations' own "Fine-tune" button still triggers the same
          real `triggerTraining()`, the "Active Tasks" KPI tile above
          still shows the same real running/queued counts (derived
          from the same `allTasks`/`taskCounts`), and Pipeline
          Operations above still shows/triggers each pipeline's real
          schedule -- so no real data or control surface was lost,
          just these sections' own separate dedicated UI for it. */}

      {/* System Diagnostics */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-white">System Diagnostics</h2>
            <p className="text-xs text-white/50">
              Real <code className="rounded bg-black/30 px-1 font-mono">/v1/readyz</code> checks
              across forecast-api, ingestion, and warehouse — reachability, readiness, and
              per-component detail (database/redis/rabbitmq/model), not a fabricated status list.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {serviceHealthCheckedAt && (
              <span className="text-[11px] text-white/40">
                Checked {formatRelativeTime(serviceHealthCheckedAt)}
              </span>
            )}
            <button
              onClick={refreshServiceHealth}
              disabled={serviceHealthRefreshing}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
                serviceHealthRefreshing
                  ? "cursor-not-allowed border-white/10 bg-white/5 text-white/40"
                  : "border-emerald-200/30 bg-emerald-200/10 text-emerald-100 hover:bg-emerald-200/15",
              )}
            >
              <RefreshCw className={cn("h-3 w-3", serviceHealthRefreshing && "animate-spin")} />
              Recheck
            </button>
          </div>
        </div>
        <SystemDiagnosticsGrid health={serviceHealth} />
      </Card>

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
  onTriggerDbtBuild,
  backfillStatus,
  onOpenBackfill,
}: {
  rows: Record<string, RowState>;
  onTrigger: (sourceId: string) => void;
  onTriggerDbtBuild: () => void;
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
        {PIPELINE_CATALOG.filter((p) => p.triggerable).map((p) => {
          // `pipe-dbt-warehouse` has `sourceId: null` (a dbt build, not an
          // ingestion fetch) -- keyed by its pipeline id instead so it
          // still gets its own row state, just via `onTriggerDbtBuild`
          // rather than `onTrigger(sourceId)`.
          const rowKey = p.sourceId ?? p.id;
          const row = rows[rowKey] ?? { status: "idle" as RowStatus };
          const busy = row.status === "queued" || row.status === "running" || row.status === "staged";
          const runDisabled = busy;
          const runTitle = "Run now";
          const backfill = backfillStatus[rowKey];
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
                    onClick={() => (p.sourceId ? onTrigger(p.sourceId) : onTriggerDbtBuild())}
                    title={p.sourceId ? runTitle : "Rebuild the warehouse marts now"}
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
                        onClick={() => onOpenBackfill(rowKey, p.label)}
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

/** `<input type="date">`'s default -- yesterday (UTC), the same
 * "don't default to a range that's still in progress and look like a
 * bug" reasoning as `defaultBackfillMonth`, just at day granularity. */
function defaultBackfillDay(): string {
  const now = new Date();
  const yesterday = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - 1));
  return yesterday.toISOString().slice(0, 10);
}

type BackfillRangeMode = "month" | "day";

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
  onSubmit: (sourceId: string, start: string, end: string) => void;
}) {
  const [mode, setMode] = useState<BackfillRangeMode>("month");
  const [yearMonth, setYearMonth] = useState(defaultBackfillMonth);
  const [day, setDay] = useState(defaultBackfillDay);
  const submitting = status?.state === "submitting";
  const canSubmit = mode === "month" ? !!yearMonth : !!day;

  function submit() {
    const { start, end } = mode === "month" ? monthToRange(yearMonth) : dayToRange(day);
    onSubmit(sourceId, start, end);
  }

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
          Fetches real historical data for the selected range from the source's
          own archive — not a repeated "last 30 min" run.
        </p>
        <div className="mb-3 flex gap-1" role="tablist" aria-label="Backfill range mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "month"}
            onClick={() => setMode("month")}
            data-testid="backfill-mode-month"
            className={cn(
              "flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
              mode === "month"
                ? "bg-emerald-200 text-black"
                : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
            )}
          >
            Month
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "day"}
            onClick={() => setMode("day")}
            data-testid="backfill-mode-day"
            className={cn(
              "flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
              mode === "day"
                ? "bg-emerald-200 text-black"
                : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
            )}
          >
            Single day
          </button>
        </div>
        {mode === "month" ? (
          <Field label="Month">
            <input
              type="month"
              value={yearMonth}
              onChange={(e) => setYearMonth(e.target.value)}
              data-testid="backfill-month-input"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
            />
          </Field>
        ) : (
          <Field label="Day">
            <input
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              data-testid="backfill-day-input"
              className="w-full rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
            />
          </Field>
        )}
        {status?.state === "error" && (
          <p className="mt-2 text-xs text-rose-300">{status.message}</p>
        )}
        <button
          disabled={submitting || !canSubmit}
          onClick={submit}
          data-testid="backfill-submit"
          className={cn(
            "mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold",
            submitting || !canSubmit
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
 * `forecast-api/app/service/ml/train.py`), not the old mock's
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

/** `trigger` is `meta._ingest_log.triggered_by` verbatim -- "schedule"
 * (Celery Beat), "public" (this dashboard's own "Run now"/backfill
 * buttons, `POST /v1/data-sources/{id}/run|backfill` -- see
 * `app/api/v1/datasources/routes.py`), "manual" (the CLI, `app/cli.py`'s
 * own default), or "backfill" (the pipeline-internal backfill runner,
 * `pipeline/backfill.py`). "public" and "manual" both read as "Manual"
 * here -- a human caused the run either way, just from a different
 * front door; the underlying value is preserved for anything else so an
 * unrecognized trigger still renders instead of silently disappearing. */
function RunTriggerBadge({ trigger }: { trigger: string }) {
  const color: Record<string, string> = {
    manual: "border-sky-300/40 bg-sky-300/10 text-sky-200",
    public: "border-sky-300/40 bg-sky-300/10 text-sky-200",
    schedule: "border-purple-300/40 bg-purple-300/10 text-purple-200",
    backfill: "border-amber-300/40 bg-amber-300/10 text-amber-200",
  };
  const label: Record<string, string> = {
    manual: "Manual",
    public: "Manual",
    schedule: "Cron",
    backfill: "Backfill",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        color[trigger] ?? "border-white/10 bg-white/5 text-white/60",
      )}
    >
      {label[trigger] ?? trigger}
    </span>
  );
}

/** Real per-pipeline run history from `GET /v1/ingestion/public/runs`
 * (`meta._ingest_log`) -- root `TODO.md`'s "last run log (when last ran,
 * how many data points fetched, status, trigger manual or cron)". Every
 * real ingest attempt across all 5 sources, most recent first (already
 * sorted that way server-side), not just this session's own trigger
 * clicks (that's `PipelineTable`/`RowState` above). `records_fetched`
 * is `rows_landed` (raw rows the source returned); `records_inserted`
 * (`rows_loaded`, shown muted) is what actually made it into the
 * warehouse after dedup -- both real, separate counts, not one number
 * doing double duty. */
function RunLogTable({ runs }: { runs: PublicRun[] | null }) {
  if (runs === null) {
    return <p className="py-6 text-center text-xs text-white/40">Loading run history…</p>;
  }
  if (runs.length === 0) {
    return (
      <div className="rounded-md border border-white/5 bg-white/[0.02] px-4 py-6 text-center text-xs text-white/50">
        No ingestion runs have been logged yet.
      </div>
    );
  }
  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
        <tr>
          <th className="py-2">Pipeline</th>
          <th className="py-2">Last Ran</th>
          <th className="py-2">Trigger</th>
          <th className="py-2">Status</th>
          <th className="py-2 text-right">Records Fetched</th>
          <th className="py-2 text-right">Duration</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/5">
        {runs.map((r) => (
          <tr key={r.id} className="text-white/85">
            <td className="py-2 pr-2">{formatSource(r.source_id)}</td>
            <td className="py-2 pr-2 text-white/60" title={new Date(r.started_at).toLocaleString()}>
              {formatRelativeTime(r.started_at)}
            </td>
            <td className="py-2 pr-2">
              <RunTriggerBadge trigger={r.trigger} />
            </td>
            <td className="py-2 pr-2">
              <PipelineStatusChip status={r.status} />
            </td>
            <td className="py-2 text-right tabular-nums">
              {r.records_fetched != null ? (
                <>
                  {r.records_fetched.toLocaleString()}
                  {r.records_inserted != null && r.records_inserted !== r.records_fetched && (
                    <span className="ml-1 text-white/40">({r.records_inserted.toLocaleString()} inserted)</span>
                  )}
                </>
              ) : (
                <span className="text-white/40">—</span>
              )}
            </td>
            <td className="py-2 text-right text-white/60 tabular-nums">
              {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One tile per service, real `reachable`/`ready`/`components`/
 * `latencyMs` from `fetchAllServicesHealth()` (`lib/health.ts`) -- no
 * "degraded"/"warning" middle state fabricated beyond what each
 * service's own `/v1/readyz` actually reports (unreachable vs.
 * reachable-but-not-ready vs. ready), and `latencyMs` is a real
 * single-sample round-trip for *this* check, labeled as such rather
 * than implying a tracked historical p95. */
function SystemDiagnosticsGrid({ health }: { health: ServiceHealth[] | null }) {
  if (health === null) {
    return <p className="py-6 text-center text-xs text-white/40">Checking services…</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {health.map((h) => {
        const tone = !h.reachable
          ? { dot: "bg-rose-400", border: "border-rose-300/30", label: "Unreachable", text: "text-rose-200" }
          : h.ready
            ? { dot: "bg-emerald-300", border: "border-emerald-200/30", label: "Healthy", text: "text-emerald-100" }
            : { dot: "bg-amber-300", border: "border-amber-300/30", label: "Not ready", text: "text-amber-200" };
        return (
          <div key={h.service} className={cn("rounded-md border bg-white/[0.02] p-3", tone.border)}>
            <div className="mb-1.5 flex items-center gap-1.5">
              <span className={cn("h-2 w-2 rounded-full", tone.dot)} />
              <span className="text-xs font-semibold text-white">{h.service}</span>
            </div>
            <div className={cn("text-[11px] font-medium", tone.text)}>{tone.label}</div>
            {h.latencyMs != null && (
              <div className="mt-0.5 text-[10px] text-white/40">{h.latencyMs}ms (this check)</div>
            )}
            {h.components.length > 0 && (
              <div className="mt-2 space-y-0.5 border-t border-white/5 pt-1.5">
                {h.components.map((c) => (
                  <div key={c.name} className="flex items-center justify-between text-[10px]">
                    <span className="text-white/50">{c.name}</span>
                    <span className={c.healthy ? "text-emerald-200/80" : "text-rose-300"} title={c.detail ?? undefined}>
                      {c.healthy ? "ok" : (c.detail ?? "down")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
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

