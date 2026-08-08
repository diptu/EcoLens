/**
 * /dashboard/admin/anomaly-detection — anomaly log.
 *
 * Lists real records flagged by the ingestion-layer hybrid detector
 * (rule-based + IsolationForest ML) — `meta.anomalies`, 150K+ real rows
 * confirmed live 2026-08-08 (real `pipeline.anomaly.detect_anomalies`,
 * real `pipeline.ml_anomaly` IsolationForest per source). The admin can:
 *   - filter by severity / method / status / source / reason kind
 *   - search reason text / the flagged row's own snapshot
 *   - acknowledge / resolve / mark false-positive — real PATCH mutations
 *
 * Was fully mock (`generateAnomalies()`/`summarizeAnomalies()` from
 * `lib/admin.ts`, deterministic fake data; mutation handlers were
 * local-state-only). Rewired 2026-08-08 (root TODO.md's "make every
 * page fully functional with real data") to `lib/anomalies.ts`'s real
 * `fetchAnomalies`/`fetchAnomalySummary`/`updateAnomalyStatus`
 * (`GET/PATCH /v1/anomalies*`, `services/ingestion`, built the same
 * session — real `meta.anomalies` didn't have a listing endpoint or a
 * status column before this).
 *
 * Real vs. the old mock's invented taxonomy: `severity`/`method` are
 * server-derived from real columns (see `lib/anomalies.ts`'s own
 * docstring), not separately tracked. "Type" used to be a fictional
 * 12-value enum (demand_spike/negative_price/etc.) this detector never
 * actually produces — replaced with the *real* reason-kind prefixes
 * that exist in the data: `missing_value` (121K), `ml_outlier` (25K),
 * `statistical_outlier` (4K), `out_of_range` (803).
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Gauge,
  Layers,
  Lightbulb,
  Loader2,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  fetchAnomalies,
  fetchAnomalySummary,
  updateAnomalyStatus,
  type Anomaly,
  type AnomalyMethod,
  type AnomalySeverity,
  type AnomalyStatus,
  type AnomalySummary,
} from "@/lib/anomalies";

const SEVERITY_FILTERS: Array<{ value: AnomalySeverity | "all"; label: string }> = [
  { value: "all",    label: "All severities" },
  { value: "high",   label: "High"           },
  { value: "medium", label: "Medium"         },
  { value: "low",    label: "Low"            },
];

const METHOD_FILTERS: Array<{ value: AnomalyMethod | "all"; label: string }> = [
  { value: "all",    label: "All methods" },
  { value: "hybrid", label: "Hybrid"      },
  { value: "rule",   label: "Rule"        },
  { value: "ml",     label: "ML"          },
];

const STATUS_FILTERS: Array<{ value: AnomalyStatus | "all"; label: string }> = [
  { value: "all",          label: "All statuses"    },
  { value: "new",          label: "New"             },
  { value: "acknowledged", label: "Acknowledged"    },
  { value: "resolved",     label: "Resolved"        },
  { value: "false_positive", label: "False positive" },
];

// Real reason-kind prefixes -- the only 4 that exist in `meta.anomalies`
// (confirmed live), replacing the old mock's fictional 12-type taxonomy.
const REASON_KIND_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All reasons" },
  { value: "missing_value", label: "Missing value" },
  { value: "out_of_range", label: "Out of range" },
  { value: "statistical_outlier", label: "Statistical outlier" },
  { value: "ml_outlier", label: "ML outlier" },
];

const SEVERITY_STYLES: Record<AnomalySeverity, { dot: string; text: string; chip: string }> = {
  high:   { dot: "bg-rose-300",    text: "text-rose-200",    chip: "border-rose-300/40 bg-rose-300/10"    },
  medium: { dot: "bg-amber-300",   text: "text-amber-200",   chip: "border-amber-300/40 bg-amber-300/10"  },
  low:    { dot: "bg-emerald-200", text: "text-emerald-100", chip: "border-emerald-200/40 bg-emerald-200/10" },
};

const STATUS_STYLES: Record<AnomalyStatus, { label: string; className: string; icon: React.ComponentType<{ className?: string }> }> = {
  new:           { label: "New",           className: "border-rose-300/40 bg-rose-300/10 text-rose-200",     icon: AlertCircle  },
  acknowledged:  { label: "Acknowledged",  className: "border-amber-300/40 bg-amber-300/10 text-amber-200",   icon: ShieldAlert  },
  resolved:      { label: "Resolved",      className: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100", icon: CheckCircle2 },
  false_positive:{ label: "False +",       className: "border-white/10 bg-white/5 text-white/60",            icon: XCircle      },
};

const METHOD_ICONS = {
  rule: ShieldCheck,
  ml: Bot,
  hybrid: Sparkles,
};

function formatTs(iso: string): string {
  return new Date(iso).toLocaleString("en-AU", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const PAGE_SIZE = 25;

export default function AdminAnomalyDetectionPage() {
  const [anomalies, setAnomalies] = useState<Anomaly[] | null>(null);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<AnomalySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);

  const [severityFilter, setSeverityFilter] = useState<AnomalySeverity | "all">("all");
  const [methodFilter, setMethodFilter] = useState<AnomalyMethod | "all">("all");
  const [statusFilter, setStatusFilter] = useState<AnomalyStatus | "all">("all");
  const [reasonKindFilter, setReasonKindFilter] = useState<string>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [mutating, setMutating] = useState<string | null>(null);

  // Real server-side filtering/pagination -- 150K+ real rows, not
  // something to fetch-all-then-filter-client-side the way the old
  // mock's fixed 30-row batch could get away with.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchAnomalies({
      severity: severityFilter === "all" ? undefined : severityFilter,
      method: methodFilter === "all" ? undefined : methodFilter,
      status: statusFilter === "all" ? undefined : statusFilter,
      search: search || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }).then((r) => {
      if (cancelled) return;
      setAnomalies(r.data);
      setTotal(r.meta.total);
    }).catch(() => {
      if (cancelled) return;
      setAnomalies([]);
      setTotal(0);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [severityFilter, methodFilter, statusFilter, reasonKindFilter, search, page]);

  useEffect(() => {
    fetchAnomalySummary().then(setSummary).catch(() => {});
  }, []);

  // Client-side reason-kind filter (real prefix of `reason`, same
  // taxonomy the backend's own `reason_kind` filter uses server-side --
  // kept client-side here too since it composes with the free-text
  // search box without a 6th round-trip param).
  const filtered = useMemo(() => {
    if (!anomalies) return [];
    if (reasonKindFilter === "all") return anomalies;
    return anomalies.filter((a) => a.reason.startsWith(reasonKindFilter));
  }, [anomalies, reasonKindFilter]);

  function clearFilters() {
    setSeverityFilter("all");
    setMethodFilter("all");
    setStatusFilter("all");
    setReasonKindFilter("all");
    setSearchInput("");
    setSearch("");
    setPage(0);
  }

  function mutate(id: string, status: AnomalyStatus) {
    setMutating(id);
    updateAnomalyStatus(id, status)
      .then((updated) => {
        setAnomalies((prev) => prev?.map((a) => (a.id === id ? updated : a)) ?? null);
      })
      .catch(() => {})
      .finally(() => setMutating(null));
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <ShieldAlert className="h-6 w-6 text-rose-200" />
            Anomaly Detection
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-white/60">
            Real records flagged by the ingestion-layer hybrid detector (rule-based
            + IsolationForest ML, per source). Suspicious records are tagged here, not
            dropped, so downstream systems can distinguish a real
            operational event from a data-quality issue.
          </p>
        </div>
        {summary && (
          <div className="flex items-center gap-2 text-xs text-white/50">
            <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-1">
              <TrendingUp className="h-3 w-3" />
              {summary.total.toLocaleString()} total · {(summary.by_status.new ?? 0).toLocaleString()} new
            </span>
          </div>
        )}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <AnomalyKpi
          label="New anomalies"
          value={summary ? (summary.by_status.new ?? 0).toLocaleString() : "—"}
          sub="Need acknowledgement"
          tone={summary && (summary.by_status.new ?? 0) > 0 ? "warn" : "neutral"}
          icon={AlertCircle}
        />
        <AnomalyKpi
          label="High severity"
          value={summary ? (summary.by_severity.high ?? 0).toLocaleString() : "—"}
          sub={`Of ${summary ? summary.total.toLocaleString() : "—"} total`}
          tone={summary && (summary.by_severity.high ?? 0) > 0 ? "warn" : "neutral"}
          icon={AlertTriangle}
        />
        <AnomalyKpi
          label="Detected today"
          value={summary ? (summary.daily_counts.at(-1)?.count ?? 0).toLocaleString() : "—"}
          sub="Real detections, last 24h"
          tone="neutral"
          icon={Gauge}
        />
        <AnomalyKpi
          label="Avg anomaly score"
          value={summary ? summary.avg_score.toFixed(3) : "—"}
          sub="Across all real flagged rows"
          tone="neutral"
          icon={TrendingUp}
        />
      </div>

      {/* Detection methods breakdown */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MethodCard
          label="Rule"
          count={summary?.by_method.rule ?? 0}
          icon={ShieldCheck}
          color="emerald"
          blurb="Missing values, out-of-range physical bounds, statistical (z-score) outliers."
        />
        <MethodCard
          label="ML (IsolationForest)"
          count={summary?.by_method.ml ?? 0}
          icon={Bot}
          color="amber"
          blurb="Per-source IsolationForest over numeric columns. Catches multivariate outliers rule checks miss."
        />
        <MethodCard
          label="Hybrid"
          count={summary?.by_method.hybrid ?? 0}
          icon={Sparkles}
          color="rose"
          blurb="Both rule/statistical AND ML flagged the same row. Highest confidence."
        />
      </div>

      {/* Daily counts (last 7 days, real) */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Layers className="h-4 w-4 text-white/60" />
            Anomalies detected per day (last 7, real)
          </h2>
        </div>
        {summary ? (
          <div className="flex h-32 items-end gap-2">
            {summary.daily_counts.map((d) => {
              const max = Math.max(1, ...summary.daily_counts.map((x) => x.count));
              const h = (d.count / max) * 100;
              return (
                <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                  <div className="w-full text-center text-xs text-white/50">
                    {d.count || ""}
                  </div>
                  <div
                    className="w-full rounded-t bg-rose-300/40"
                    style={{ height: `${h}%`, minHeight: 2 }}
                  />
                  <div className="text-[10px] text-white/40">{d.date.slice(5)}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="py-8 text-center text-xs text-white/40">Loading…</p>
        )}
      </Card>

      {/* Filter bar */}
      <Card>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect
              label="Severity"
              value={severityFilter}
              options={SEVERITY_FILTERS}
              onChange={(v) => { setSeverityFilter(v as AnomalySeverity | "all"); setPage(0); }}
            />
            <FilterSelect
              label="Method"
              value={methodFilter}
              options={METHOD_FILTERS}
              onChange={(v) => { setMethodFilter(v as AnomalyMethod | "all"); setPage(0); }}
            />
            <FilterSelect
              label="Status"
              value={statusFilter}
              options={STATUS_FILTERS}
              onChange={(v) => { setStatusFilter(v as AnomalyStatus | "all"); setPage(0); }}
            />
            <FilterSelect
              label="Reason"
              value={reasonKindFilter}
              options={REASON_KIND_FILTERS}
              onChange={setReasonKindFilter}
            />
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white/70 hover:bg-white/10"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          </div>
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => { e.preventDefault(); setSearch(searchInput); setPage(0); }}
          >
            <Search className="h-4 w-4 text-white/40" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search reason / row snapshot…"
              className="w-56 rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
            />
          </form>
        </div>
        <div className="mt-3 text-xs text-white/50">
          {loading ? "Loading…" : `Showing ${filtered.length} of ${total.toLocaleString()} real anomalies`}
        </div>
      </Card>

      {/* Anomaly table */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <AlertTriangle className="h-4 w-4 text-amber-200" />
            Recent anomalies
          </h2>
          <div className="flex items-center gap-2 text-xs text-white/50">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
              className="rounded-md border border-white/10 bg-white/5 px-2 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <span>Page {page + 1} of {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1 || loading}
              className="rounded-md border border-white/10 bg-white/5 px-2 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/5 text-xs uppercase text-white/50">
              <tr>
                <th className="px-3 py-2">Detected</th>
                <th className="px-3 py-2">Region</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Method</th>
                <th className="px-3 py-2 text-right">Score</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-white/50">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                  </td>
                </tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-sm text-white/50">
                    No anomalies match the current filters.
                  </td>
                </tr>
              )}
              {!loading && filtered.map((a) => {
                const sev = SEVERITY_STYLES[a.severity];
                const stat = STATUS_STYLES[a.status];
                const statIcon = stat.icon;
                const methodIcon = METHOD_ICONS[a.method];
                const expanded = expandedId === a.id;
                return (
                  <AnomalyRow
                    key={a.id}
                    a={a}
                    sev={sev}
                    stat={stat}
                    StatIcon={statIcon}
                    MethodIcon={methodIcon}
                    expanded={expanded}
                    mutating={mutating === a.id}
                    onToggle={() => setExpandedId(expanded ? null : a.id)}
                    onAcknowledge={() => mutate(a.id, "acknowledged")}
                    onResolve={() => mutate(a.id, "resolved")}
                    onFalsePositive={() => mutate(a.id, "false_positive")}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* How it works */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <Lightbulb className="h-4 w-4 text-amber-200" />
          How the hybrid detector works
        </h2>
        <div className="grid grid-cols-1 gap-3 text-sm text-white/70 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-100">
              1. Rule / statistical layer
            </h3>
            <p className="leading-relaxed">
              Each ingested record is checked for missing values on key
              columns, physical out-of-range values, and statistical
              (z-score) outliers against a rolling window. Failures land
              on this page tagged <span className="font-mono text-xs">rule</span>.
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-200">
              2. ML layer
            </h3>
            <p className="leading-relaxed">
              A per-source <span className="font-mono text-xs">IsolationForest</span>{" "}
              (scikit-learn) scores each record across its own numeric
              columns. Records above the anomaly threshold are flagged,
              tagged <span className="font-mono text-xs">ml</span>.
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-rose-200">
              3. Hybrid agreement
            </h3>
            <p className="leading-relaxed">
              When both a rule/statistical check and the ML model flag
              the same row, it&apos;s marked{" "}
              <span className="font-mono text-xs">hybrid</span> — the
              highest-confidence class.
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-white/60">
              4. Disposition
            </h3>
            <p className="leading-relaxed">
              Flagged records are <strong>never dropped</strong> — they
              are tagged with anomaly metadata and continue through the
              pipeline. Admins acknowledge, mark resolved, or mark as
              false-positive (e.g. a real, planned operational event).
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Sub-components
// ────────────────────────────────────────────────────────────────────

function AnomalyKpi({
  label,
  value,
  sub,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "warn" | "neutral";
  icon: React.ComponentType<{ className?: string }>;
}) {
  const color = tone === "warn" ? "text-rose-200" : "text-emerald-100";
  const ring = tone === "warn" ? "border-rose-300/30" : "border-white/10";
  return (
    <div className={cn("rounded-xl border bg-white/[0.02] p-4", ring)}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-white/60">
          {label}
        </h3>
        <Icon className={cn("h-4 w-4", color)} />
      </div>
      <div className="text-3xl font-bold text-white">{value}</div>
      <p className="mt-1 text-xs text-white/50">{sub}</p>
    </div>
  );
}

function MethodCard({
  label,
  count,
  icon: Icon,
  color,
  blurb,
}: {
  label: string;
  count: number;
  icon: React.ComponentType<{ className?: string }>;
  color: "emerald" | "amber" | "rose";
  blurb: string;
}) {
  const ring = {
    emerald: "border-emerald-200/30 from-emerald-200/10",
    amber:   "border-amber-300/30 from-amber-300/10",
    rose:    "border-rose-300/30 from-rose-300/10",
  }[color];
  const iconColor = {
    emerald: "text-emerald-100",
    amber: "text-amber-200",
    rose: "text-rose-200",
  }[color];
  return (
    <div
      className={cn(
        "rounded-xl border bg-gradient-to-br to-transparent p-4",
        ring,
      )}
    >
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-white/70">{label}</h3>
        <Icon className={cn("h-4 w-4", iconColor)} />
      </div>
      <div className="text-3xl font-bold text-white">{count.toLocaleString()}</div>
      <p className="mt-1 text-xs text-white/50">{blurb}</p>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-white/70">
      <span className="text-white/50">{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-white focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-[#0a1410] text-white">
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function AnomalyRow({
  a,
  sev,
  stat,
  StatIcon,
  MethodIcon,
  expanded,
  mutating,
  onToggle,
  onAcknowledge,
  onResolve,
  onFalsePositive,
}: {
  a: Anomaly;
  sev: { dot: string; text: string; chip: string };
  stat: { label: string; className: string; icon: React.ComponentType<{ className?: string }> };
  StatIcon: React.ComponentType<{ className?: string }>;
  MethodIcon: React.ComponentType<{ className?: string }>;
  expanded: boolean;
  mutating: boolean;
  onToggle: () => void;
  onAcknowledge: () => void;
  onResolve: () => void;
  onFalsePositive: () => void;
}) {
  return (
    <>
      <tr
        className="cursor-pointer transition-colors hover:bg-white/[0.03]"
        onClick={onToggle}
        data-testid={`anomaly-row-${a.id}`}
      >
        <td className="whitespace-nowrap px-3 py-2 text-white/80">
          <div className="flex items-center gap-1.5">
            {expanded ? (
              <ChevronDown className="h-3 w-3 text-white/40" />
            ) : (
              <ChevronRight className="h-3 w-3 text-white/40" />
            )}
            {formatTs(a.detected_at)}
          </div>
        </td>
        <td className="px-3 py-2 font-mono text-xs text-white/80">{a.region ?? "—"}</td>
        <td className="px-3 py-2 text-xs text-white/60">{a.source}</td>
        <td className="px-3 py-2">
          <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium", sev.chip, sev.text)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", sev.dot)} />
            {a.severity}
          </span>
        </td>
        <td className="px-3 py-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] text-white/70">
            <MethodIcon className="h-3.5 w-3.5" />
            {a.method}
          </span>
        </td>
        <td className="px-3 py-2 text-right font-mono text-xs text-white/80">
          {a.score.toFixed(3)}
        </td>
        <td className="px-3 py-2">
          <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium", stat.className)}>
            <StatIcon className="h-3 w-3" />
            {stat.label}
          </span>
        </td>
        <td className="px-3 py-2 text-right">
          {mutating ? (
            <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-white/50" />
          ) : a.status === "new" ? (
            <div className="flex justify-end gap-1">
              <button
                onClick={(e) => { e.stopPropagation(); onAcknowledge(); }}
                className="rounded-md border border-amber-300/30 bg-amber-300/10 px-2 py-1 text-[11px] font-medium text-amber-200 hover:bg-amber-300/20"
                data-testid={`ack-${a.id}`}
              >
                Ack
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onFalsePositive(); }}
                className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/70 hover:bg-white/10"
                data-testid={`fp-${a.id}`}
              >
                FP
              </button>
            </div>
          ) : a.status === "acknowledged" ? (
            <button
              onClick={(e) => { e.stopPropagation(); onResolve(); }}
              className="rounded-md border border-emerald-200/30 bg-emerald-200/10 px-2 py-1 text-[11px] font-medium text-emerald-100 hover:bg-emerald-200/20"
              data-testid={`resolve-${a.id}`}
            >
              Resolve
            </button>
          ) : (
            <span className="text-[11px] text-white/40">—</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-white/[0.02]">
          <td colSpan={8} className="px-6 py-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Interval
                </h4>
                <p className="font-mono text-xs text-white/80">
                  {a.ts ?? "—"}
                </p>
              </div>
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Observed vs expected
                </h4>
                <p className="font-mono text-xs text-white/80">
                  {a.metric ?? "value"} ={" "}
                  <span className="text-amber-200">
                    {a.observed_value != null ? a.observed_value : "—"}
                  </span>
                  <br />
                  {(a.expected_low != null || a.expected_high != null) && (
                    <>
                      expected ={" "}
                      <span className="text-emerald-100">
                        [{a.expected_low ?? "—"}, {a.expected_high ?? "—"}]
                      </span>
                      {a.z_score != null && (
                        <span className="text-white/40"> (z={a.z_score.toFixed(2)})</span>
                      )}
                    </>
                  )}
                </p>
              </div>
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Status updated
                </h4>
                <p className="text-xs text-white/80">
                  {a.status_updated_at ? formatTs(a.status_updated_at) : <span className="text-white/40">never</span>}
                </p>
              </div>
              <div className="md:col-span-3">
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Reason
                </h4>
                <p className="text-sm text-white/80">{a.reason}</p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
