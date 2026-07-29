/**
 * /dashboard/data-sources — Data Sources management
 *
 * Lets admins:
 *   - View all registered data sources (status, cadence, last run, rows)
 *   - Edit the cron schedule for each source (with validation)
 *   - Edit the cadence description (human-readable)
 *   - Toggle enabled/disabled
 *   - Trigger refresh / backfill
 *   - View a cron-expression cheat sheet
 */
"use client";

import { useMemo, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Edit3,
  History,
  Info,
  Loader2,
  RefreshCw,
  Save,
  ToggleLeft,
  ToggleRight,
  X,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import { getDataSources, getSourceCategories, type DataSource } from "@/lib/dashboards";

const CRON_PRESETS: Array<{ label: string; value: string; desc: string }> = [
  { label: "Every 5 min",  value: "*/5 * * * *",   desc: "High-frequency telemetry" },
  { label: "Every 15 min", value: "*/15 * * * *",  desc: "Moderate telemetry" },
  { label: "Every 30 min", value: "*/30 * * * *",  desc: "Market data" },
  { label: "Hourly",       value: "0 * * * *",     desc: "Slow-changing feeds" },
  { label: "Daily 02:00",  value: "0 2 * * *",     desc: "Daily refresh" },
  { label: "Weekly Sun",   value: "0 0 * * 0",     desc: "Weekly refresh" },
  { label: "Monthly 1st",  value: "0 0 1 * *",     desc: "Monthly refresh" },
];

const CRON_RE = /^(\*|\d+|\*\/\d+|\d+-\d+)( (\*|\d+|\*\/\d+|\d+-\d+)){4}$/;

function isValidCron(expr: string): boolean {
  return CRON_RE.test(expr.trim());
}

function describeCron(expr: string): string {
  if (expr === "*/5 * * * *")   return "Every 5 minutes";
  if (expr === "*/15 * * * *")  return "Every 15 minutes";
  if (expr === "*/30 * * * *")  return "Every 30 minutes";
  if (expr === "0 * * * *")     return "Every hour";
  if (expr === "0 2 * * *")     return "Daily at 02:00";
  if (expr === "0 0 * * 0")     return "Weekly on Sunday at 00:00";
  if (expr === "0 0 1 * *")     return "Monthly on the 1st at 00:00";
  return expr; // raw fallback
}

export default function DataSourcesPage() {
  const [sources, setSources] = useState<DataSource[]>(() => getDataSources());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "refresh" | "backfill" | "save" | "toggle" | "error"; msg: string } | null>(null);

  const categories = useMemo(() => getSourceCategories(), []);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const filteredSources = activeCategory === "all"
    ? sources
    : sources.filter((s) => s.category === activeCategory);

  function trigger(id: string, kind: "refresh" | "backfill") {
    setActionInFlight(`${id}-${kind}`);
    setTimeout(() => {
      setActionInFlight(null);
      setToast({
        kind,
        msg: `${kind === "refresh" ? "Refresh" : "Backfill"} job queued for ${id}. See Jobs page for progress.`,
      });
      setTimeout(() => setToast(null), 4000);
    }, 800);
  }

  function toggle(id: string) {
    setSources((curr) =>
      curr.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s)),
    );
    const s = sources.find((x) => x.id === id);
    setToast({
      kind: "toggle",
      msg: `${s?.name} ${s?.enabled ? "disabled" : "enabled"}.`,
    });
    setTimeout(() => setToast(null), 3000);
  }

  function saveCron(id: string, newCron: string, newCadence: string) {
    if (!isValidCron(newCron)) {
      setToast({ kind: "error", msg: `Invalid cron expression: "${newCron}". Use 5 fields (min hr dom mon dow).` });
      setTimeout(() => setToast(null), 5000);
      return;
    }
    setSources((curr) =>
      curr.map((s) =>
        s.id === id ? { ...s, cron: newCron, cadence: newCadence } : s,
      ),
    );
    setEditingId(null);
    setToast({ kind: "save", msg: `Schedule updated for ${id}. Next run: ${describeCron(newCron)}.` });
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Data Sources</h1>
        <p className="mt-1 text-sm text-white/60">
          Manage external data providers — grid, weather, carbon, fuel markets.
          Edit cron schedules, trigger refreshes, and monitor health.
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
          {filteredSources.map((s) => {
            const expanded = expandedId === s.id;
            const isEditing = editingId === s.id;
            return (
              <SourceRow
                key={s.id}
                source={s}
                expanded={expanded}
                isEditing={isEditing}
                actionInFlight={actionInFlight}
                onToggleExpand={() => {
                  setExpandedId(expanded ? null : s.id);
                  setEditingId(null);
                }}
                onStartEdit={() => setEditingId(s.id)}
                onCancelEdit={() => setEditingId(null)}
                onSaveEdit={(cron, cadence) => saveCron(s.id, cron, cadence)}
                onTrigger={(kind) => trigger(s.id, kind)}
                onToggle={() => toggle(s.id)}
              />
            );
          })}
        </div>
      </Card>

      <CronCheatSheet />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Source row (view + edit modes)
// ────────────────────────────────────────────────────────────────────

function SourceRow({
  source: s,
  expanded,
  isEditing,
  actionInFlight,
  onToggleExpand,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onTrigger,
  onToggle,
}: {
  source: DataSource;
  expanded: boolean;
  isEditing: boolean;
  actionInFlight: string | null;
  onToggleExpand: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (cron: string, cadence: string) => void;
  onTrigger: (kind: "refresh" | "backfill") => void;
  onToggle: () => void;
}) {
  const [draftCron, setDraftCron] = useState(s.cron);
  const [draftCadence, setDraftCadence] = useState(s.cadence);

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
          <SourceStatus status={s.health} />
          <span className="font-mono text-sm text-white">{s.id}</span>
          <span className="truncate text-xs text-white/55">{s.name}</span>
        </div>
        <div className="flex items-center gap-3 text-right text-[11px]">
          <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-white/65">
            {s.cadence}
          </span>
          <span className="text-white/40">last:</span>
          <span className="font-mono text-white/70 tabular-nums">{s.last_sync}</span>
          <span className="text-white/40">rows:</span>
          <span className="font-mono text-white/70 tabular-nums">{s.records_today.toLocaleString()}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/5 px-4 py-3 text-xs">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <p className="text-white/65">Region: {s.region} · Category: {s.category}</p>
              <p className="mt-1 text-white/40">Endpoint: <code className="font-mono text-emerald-100">{s.api_endpoint}</code></p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Health" value={s.health} tone={s.health === "healthy" ? "up" : "down"} />
              <Field label="Last Status" value={s.last_status} tone={s.last_status === "success" ? "up" : "down"} />
              <Field label="Vendor" value={s.vendor} />
              <Field label="Records Today" value={s.records_today.toLocaleString()} />
            </div>
          </div>

          {/* Cron editor */}
          <div className="mt-4 rounded-md border border-white/5 bg-white/[0.02] p-3">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-white/60">Schedule</h3>
              {!isEditing ? (
                <button
                  onClick={onStartEdit}
                  data-testid={`edit-cron-${s.id}`}
                  className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/70 hover:border-emerald-200/30 hover:text-white"
                >
                  <Edit3 className="h-3 w-3" /> Edit
                </button>
              ) : (
                <div className="flex items-center gap-1">
                  <button
                    onClick={onCancelEdit}
                    className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/70 hover:bg-white/10"
                  >
                    <X className="h-3 w-3" /> Cancel
                  </button>
                  <button
                    onClick={() => onSaveEdit(draftCron, draftCadence)}
                    data-testid={`save-cron-${s.id}`}
                    className="inline-flex items-center gap-1 rounded-md border border-emerald-200/30 bg-emerald-200/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-200/20"
                  >
                    <Save className="h-3 w-3" /> Save
                  </button>
                </div>
              )}
            </div>

            {!isEditing ? (
              <div className="flex items-center gap-2">
                <code className="rounded bg-black/30 px-2 py-1 font-mono text-emerald-100">{s.cron}</code>
                <span className="text-white/50">— {describeCron(s.cron)}</span>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-[10px] uppercase tracking-wide text-white/50">
                      Cron expression <span className="text-white/30">(min hr dom mon dow)</span>
                    </label>
                    <input
                      type="text"
                      value={draftCron}
                      onChange={(e) => setDraftCron(e.target.value)}
                      data-testid={`cron-input-${s.id}`}
                      className={cn(
                        "w-full rounded-md border bg-white/[0.04] px-2.5 py-1.5 font-mono text-sm text-white focus:outline-none",
                        isValidCron(draftCron)
                          ? "border-emerald-200/30 focus:border-emerald-200/60"
                          : "border-rose-300/40 focus:border-rose-300/60",
                      )}
                    />
                    {!isValidCron(draftCron) && (
                      <p className="mt-1 text-[10px] text-rose-200">Invalid format. Example: <code className="font-mono">*/5 * * * *</code></p>
                    )}
                  </div>
                  <div>
                    <label className="mb-1 block text-[10px] uppercase tracking-wide text-white/50">Cadence label</label>
                    <input
                      type="text"
                      value={draftCadence}
                      onChange={(e) => setDraftCadence(e.target.value)}
                      data-testid={`cadence-input-${s.id}`}
                      className="w-full rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] uppercase tracking-wide text-white/50">Presets</label>
                  <div className="flex flex-wrap gap-1">
                    {CRON_PRESETS.map((p) => (
                      <button
                        key={p.value}
                        type="button"
                        onClick={() => {
                          setDraftCron(p.value);
                          setDraftCadence(p.label);
                        }}
                        className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/70 hover:border-emerald-200/30 hover:text-white"
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
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
              Backfill range
            </button>
            <button
              type="button"
              onClick={onToggle}
              data-testid={`toggle-${s.id}`}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px]",
                s.enabled
                  ? "border-amber-400/20 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
                  : "border-emerald-200/20 bg-emerald-300/10 text-emerald-100 hover:bg-emerald-300/20",
              )}
            >
              {s.enabled ? (
                <>
                  <ToggleRight className="h-3 w-3" /> Enabled — disable
                </>
              ) : (
                <>
                  <ToggleLeft className="h-3 w-3" /> Disabled — enable
                </>
              )}
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

function SourceStatus({ status }: { status: DataSource["health"] }) {
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
