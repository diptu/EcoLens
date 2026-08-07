/**
 * /dashboard/data-sources — Data Sources management
 *
 * Real data from data-pipeline's `GET /v1/data-sources/public`
 * (`lib/data-sources.ts`) — replaces the old fictional 9-source catalog
 * (`lib/dashboards.ts`'s `getDataSources()`, sources like "ENTSO-E API"/
 * "EIA API" that don't exist in this platform). No mock fallback on
 * fetch failure — an honest empty state beats silently reintroducing
 * fabricated numbers (same policy as the Carbon/Ingestion/Executive
 * pages once they were wired to real data).
 *
 * "Refresh latest" (`POST /v1/data-sources/{id}/run`) and "Backfill"
 * (`POST /v1/data-sources/{id}/backfill`, trailing 7 days) are real —
 * both routes are deliberately open, no auth required
 * (`lib/ingestion.ts`'s `triggerIngestionRun`/`triggerBackfill`, already
 * used by the Ingestion Pipeline page, reused directly here).
 *
 * Schedule editing and enable/disable ARE NOT real — both need
 * `PATCH /v1/data-sources/{id}` with an `admin`-role bearer token, and
 * this dashboard has no auth flow that can hold one (see
 * `lib/data-sources.ts`'s module docstring). Shown as disabled controls
 * with an explanatory tooltip rather than faking a local-state mutation
 * that never reaches the backend — same "no silently fabricated
 * success" convention `models/page.tsx`'s Train tab already follows.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Edit3,
  History,
  Info,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  DATA_SOURCE_CATEGORIES,
  fetchPublicDataSources,
  healthDotStatus,
  type DataSource,
} from "@/lib/data-sources";
import {
  PIPELINE_CATALOG,
  TriggerIngestionError,
  formatRelativeTime,
  triggerBackfill,
  triggerIngestionRun,
} from "@/lib/ingestion";

const CRON_PRESETS: Array<{ label: string; value: string; desc: string }> = [
  { label: "Every 5 min",  value: "*/5 * * * *",   desc: "High-frequency telemetry" },
  { label: "Every 15 min", value: "*/15 * * * *",  desc: "Moderate telemetry" },
  { label: "Every 30 min", value: "*/30 * * * *",  desc: "Market data" },
  { label: "Hourly",       value: "0 * * * *",     desc: "Slow-changing feeds" },
  { label: "Daily 02:00",  value: "0 2 * * *",     desc: "Daily refresh" },
  { label: "Weekly Sun",   value: "0 0 * * 0",     desc: "Weekly refresh" },
  { label: "Monthly 1st",  value: "0 0 1 * *",     desc: "Monthly refresh" },
];

/** `sourceId` ("ds-aemo-nem") -> whether `POST .../backfill` is
 * meaningful for it (`aemo_holidays` is an annual snapshot, not a
 * continuous feed — see `PIPELINE_CATALOG`'s own docstring). */
const BACKFILLABLE_SOURCE_IDS = new Set(
  PIPELINE_CATALOG.filter((p) => p.backfillable && p.sourceId).map((p) => p.sourceId),
);

/** Trailing 7 days from now, both ends inclusive-day per
 * `triggerBackfill`'s own contract (`lib/ingestion.ts`). A fixed window
 * rather than a date-range picker — this page has no modal UI for one
 * yet; the Operational Tasks page's backfill modal is the place for an
 * arbitrary custom range. */
function lastSevenDaysRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 24 * 60 * 60 * 1000);
  const toDay = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  return { start: toDay(start).toISOString(), end: toDay(end).toISOString() };
}

export default function DataSourcesPage() {
  const [sources, setSources] = useState<DataSource[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "success" | "error"; msg: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicDataSources()
      .then((res) => {
        if (!cancelled) setSources(res.data);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const categories = useMemo(() => {
    const present = new Set((sources ?? []).map((s) => s.category));
    return DATA_SOURCE_CATEGORIES.filter((c) => present.has(c.id));
  }, [sources]);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const filteredSources = (sources ?? []).filter(
    (s) => activeCategory === "all" || s.category === activeCategory,
  );

  function showToast(kind: "success" | "error", msg: string) {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 5000);
  }

  async function trigger(id: string, kind: "refresh" | "backfill") {
    setActionInFlight(`${id}-${kind}`);
    try {
      if (kind === "refresh") {
        await triggerIngestionRun(id);
        showToast("success", `Refresh triggered for ${id}.`);
      } else {
        const { start, end } = lastSevenDaysRange();
        await triggerBackfill(id, start, end);
        showToast("success", `Backfill queued for ${id} (last 7 days).`);
      }
    } catch (err) {
      const msg =
        err instanceof TriggerIngestionError
          ? err.message
          : `${kind === "refresh" ? "Refresh" : "Backfill"} failed for ${id}.`;
      showToast("error", msg);
    } finally {
      setActionInFlight(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Data Sources</h1>
        <p className="mt-1 text-sm text-white/60">
          Real external data providers — grid, weather, carbon, fuel markets.
          Trigger refreshes and backfills; schedule editing requires admin auth this dashboard doesn&apos;t hold.
        </p>
      </div>

      {toast && (
        <div
          data-testid="action-toast"
          className={cn(
            "rounded-md border p-3 text-xs",
            toast.kind === "error"
              ? "border-rose-300/30 bg-rose-300/5 text-rose-200"
              : "border-emerald-200/20 bg-emerald-300/5 text-emerald-100",
          )}
        >
          {toast.kind === "error" ? (
            <AlertCircle className="mr-1 inline h-3.5 w-3.5" />
          ) : (
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
          )}
          {toast.msg}
        </div>
      )}

      {sources === null && !loadError && (
        <Card>
          <p className="py-8 text-center text-sm text-white/40">Loading data sources…</p>
        </Card>
      )}

      {loadError && (
        <Card>
          <p className="py-8 text-center text-sm text-rose-200">
            Couldn&apos;t reach data-pipeline&apos;s data-sources catalog. Is it running?
          </p>
        </Card>
      )}

      {sources !== null && (
        <>
          {/* Category filter */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setActiveCategory("all")}
              className={cn(
                "rounded-md border px-3 py-1 text-xs",
                activeCategory === "all"
                  ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                  : "border-white/10 bg-white/[0.04] text-white/70 hover:border-white/20",
              )}
            >
              All ({sources.length})
            </button>
            {categories.map((c) => {
              const count = sources.filter((s) => s.category === c.id).length;
              return (
                <button
                  key={c.id}
                  onClick={() => setActiveCategory(c.id)}
                  className={cn(
                    "rounded-md border px-3 py-1 text-xs",
                    activeCategory === c.id
                      ? "border-emerald-200/40 bg-emerald-200/10 text-emerald-100"
                      : "border-white/10 bg-white/[0.04] text-white/70 hover:border-white/20",
                  )}
                >
                  {c.label} ({count})
                </button>
              );
            })}
          </div>

          <Card>
            <div className="space-y-2" data-testid="data-sources">
              {filteredSources.map((s) => (
                <SourceRow
                  key={s.id}
                  source={s}
                  expanded={expandedId === s.id}
                  actionInFlight={actionInFlight}
                  backfillable={BACKFILLABLE_SOURCE_IDS.has(s.id)}
                  onToggleExpand={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  onTrigger={(kind) => trigger(s.id, kind)}
                />
              ))}
              {filteredSources.length === 0 && (
                <p className="py-6 text-center text-sm text-white/40">No sources in this category.</p>
              )}
            </div>
          </Card>
        </>
      )}

      <CronCheatSheet />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Source row
// ────────────────────────────────────────────────────────────────────

function SourceRow({
  source: s,
  expanded,
  actionInFlight,
  backfillable,
  onToggleExpand,
  onTrigger,
}: {
  source: DataSource;
  expanded: boolean;
  actionInFlight: string | null;
  backfillable: boolean;
  onToggleExpand: () => void;
  onTrigger: (kind: "refresh" | "backfill") => void;
}) {
  return (
    <div
      className="rounded-lg border border-white/5 bg-white/[0.02]"
      data-testid={`source-row-${s.id}`}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-white/45" /> : <ChevronRight className="h-3.5 w-3.5 text-white/45" />}
          <SourceStatus status={healthDotStatus(s.health.status)} />
          <span className="font-mono text-sm text-white">{s.id}</span>
          <span className="truncate text-xs text-white/55">{s.name}</span>
        </div>
        <div className="flex items-center gap-3 text-right text-[11px]">
          <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-white/65">
            {s.schedule.cadence}
          </span>
          <span className="text-white/40">last:</span>
          <span className="font-mono text-white/70 tabular-nums">
            {formatRelativeTime(s.last_run?.started_at ?? s.schedule.last_run_at)}
          </span>
          <span className="text-white/40">rows:</span>
          <span className="font-mono text-white/70 tabular-nums">
            {(s.last_run?.records_inserted ?? 0).toLocaleString()}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/5 px-4 py-3 text-xs">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <p className="text-white/65">
                Regions: {s.regions.length ? s.regions.join(", ") : "—"} · Category: {s.category}
                {!s.schedule.enabled && <span className="ml-2 text-amber-200">(disabled)</span>}
              </p>
              <p className="mt-1 text-white/40">Source: <code className="font-mono text-emerald-100">{s.url}</code></p>
              <p className="mt-1 text-white/40">{s.description}</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Health" value={s.health.status} tone={s.health.status === "healthy" ? "up" : "down"} />
              <Field
                label="Last Status"
                value={s.last_run?.status ?? "no runs yet"}
                tone={s.last_run?.status === "success" ? "up" : s.last_run ? "down" : undefined}
              />
              <Field label="Success Rate (24h)" value={s.health.success_rate_pct_24h != null ? `${s.health.success_rate_pct_24h.toFixed(1)}%` : "—"} />
              <Field label="Circuit Breaker" value={s.health.circuit_breaker} tone={s.health.circuit_breaker === "closed" ? "up" : "down"} />
            </div>
          </div>

          {/* Schedule (read-only) */}
          <div className="mt-4 rounded-md border border-white/5 bg-white/[0.02] p-3">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-white/60">Schedule</h3>
              <button
                disabled
                title="Editing the schedule requires admin authentication -- not available in this demo"
                data-testid={`edit-cron-${s.id}`}
                className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/40 opacity-50"
              >
                <Edit3 className="h-3 w-3" /> Edit
              </button>
            </div>
            <div className="flex items-center gap-2">
              <code className="rounded bg-black/30 px-2 py-1 font-mono text-emerald-100">{s.schedule.cron}</code>
              <span className="text-white/50">— {s.schedule.cadence}</span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onTrigger("refresh")}
              disabled={actionInFlight === `${s.id}-refresh`}
              data-testid={`refresh-${s.id}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200/30 bg-emerald-300/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-300/20 disabled:opacity-50"
            >
              {actionInFlight === `${s.id}-refresh` ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              Refresh latest
            </button>
            {backfillable && (
              <button
                type="button"
                onClick={() => onTrigger("backfill")}
                disabled={actionInFlight === `${s.id}-backfill`}
                data-testid={`backfill-${s.id}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-400/20 bg-sky-500/10 px-2.5 py-1 text-[11px] text-sky-200 hover:bg-sky-500/20 disabled:opacity-50"
              >
                {actionInFlight === `${s.id}-backfill` ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <History className="h-3 w-3" />
                )}
                Backfill last 7 days
              </button>
            )}
            <button
              type="button"
              disabled
              title="Enabling/disabling a source requires admin authentication -- not available in this demo"
              data-testid={`toggle-${s.id}`}
              className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/40 opacity-50"
            >
              {s.schedule.enabled ? "Enabled" : "Disabled"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Helper components
// ────────────────────────────────────────────────────────────────────

function SourceStatus({ status }: { status: "healthy" | "degraded" | "down" | "unknown" }) {
  const map = {
    healthy:  { dot: "bg-emerald-200", title: "healthy"  },
    degraded: { dot: "bg-amber-400",   title: "degraded" },
    down:     { dot: "bg-rose-400",    title: "down"     },
    unknown:  { dot: "bg-white/40",    title: "unknown"  },
  } as const;
  const m = map[status];
  return <span className={cn("h-2 w-2 rounded-full", m.dot)} title={m.title} />;
}

function Field({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="rounded border border-white/5 bg-white/[0.02] px-2 py-1.5">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div
        className={cn(
          "mt-0.5 font-mono text-white/85",
          tone === "up" && "text-emerald-100",
          tone === "down" && "text-rose-200",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function CronCheatSheet() {
  return (
    <Card title={
      <span className="flex items-center gap-2">
        <Info className="h-4 w-4 text-cyan-300" /> Cron expression reference
      </span>
    }>
      <p className="text-xs text-white/65">
        Cron schedules use 5 fields: <code className="font-mono text-emerald-100">min hr dom mon dow</code>.
        All times are in <code className="font-mono text-emerald-100">Australia/Sydney</code> timezone.
      </p>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {CRON_PRESETS.map((p) => (
          <div key={p.value} className="rounded border border-white/5 bg-white/[0.02] p-2">
            <div className="flex items-center justify-between">
              <code className="font-mono text-emerald-100">{p.value}</code>
              <Calendar className="h-3 w-3 text-white/30" />
            </div>
            <div className="mt-1 text-[11px] font-medium text-white/85">{p.label}</div>
            <div className="text-[10px] text-white/45">{p.desc}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 text-[10px] text-white/50 sm:grid-cols-2">
        <p><code className="font-mono text-white/70">*</code> — any value</p>
        <p><code className="font-mono text-white/70">*/N</code> — every N (e.g. <code>*/5</code> = every 5)</p>
        <p><code className="font-mono text-white/70">N,M</code> — list (e.g. <code>0,30</code>)</p>
        <p><code className="font-mono text-white/70">N-M</code> — range (e.g. <code>9-17</code> = 9am-5pm)</p>
      </div>
    </Card>
  );
}
