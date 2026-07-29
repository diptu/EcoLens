/**
 * /dashboard/admin/anomaly-detection — anomaly log.
 *
 * Lists every record that the ingestion-layer anomaly detector
 * flagged (rule-based + ML-residual hybrid). The admin can:
 *   - filter by severity / method / status / source / type
 *   - search by region or reason text
 *   - acknowledge a new anomaly
 *   - mark it resolved (after remediation)
 *   - mark it false-positive (when the ML flags a genuine event)
 *
 * In the demo, the underlying list comes from `generateAnomalies()`
 * (deterministic). The mutation handlers update local state only —
 * no real backend.
 */
"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Filter,
  Gauge,
  Layers,
  Lightbulb,
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
  generateAnomalies,
  summarizeAnomalies,
  type Anomaly,
  type AnomalyMethod,
  type AnomalySeverity,
  type AnomalyStatus,
  type AnomalyType,
} from "@/lib/admin";

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

const TYPE_FILTERS: Array<{ value: AnomalyType | "all"; label: string }> = [
  { value: "all", label: "All types" },
  { value: "demand_spike", label: "Demand spike" },
  { value: "demand_drop", label: "Demand drop" },
  { value: "negative_price", label: "Negative price" },
  { value: "stale_observation", label: "Stale obs" },
  { value: "missing_interval", label: "Missing interval" },
  { value: "out_of_range", label: "Out of range" },
  { value: "interconnector_imbalance", label: "Interconnector" },
  { value: "schema_mismatch", label: "Schema mismatch" },
  { value: "source_disagreement", label: "Source disagreement" },
  { value: "duplicate", label: "Duplicate" },
  { value: "future_ts", label: "Future TS" },
  { value: "backdated_revision", label: "Backdated rev" },
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

function formatDate(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

export default function AdminAnomalyDetectionPage() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>(() => generateAnomalies(30));
  const [severityFilter, setSeverityFilter] = useState<AnomalySeverity | "all">("all");
  const [methodFilter, setMethodFilter] = useState<AnomalyMethod | "all">("all");
  const [statusFilter, setStatusFilter] = useState<AnomalyStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState<AnomalyType | "all">("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const summary = useMemo(() => summarizeAnomalies(anomalies), [anomalies]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return anomalies.filter((a) => {
      if (severityFilter !== "all" && a.severity !== severityFilter) return false;
      if (methodFilter !== "all" && a.method !== methodFilter) return false;
      if (statusFilter !== "all" && a.status !== statusFilter) return false;
      if (typeFilter !== "all" && a.type !== typeFilter) return false;
      if (q) {
        const hay = `${a.region} ${a.source} ${a.type} ${a.reason}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [anomalies, severityFilter, methodFilter, statusFilter, typeFilter, search]);

  function acknowledge(id: string) {
    setAnomalies((curr) =>
      curr.map((a) =>
        a.id === id && a.status === "new"
          ? { ...a, status: "acknowledged", assigned_to: "diptu.app" }
          : a,
      ),
    );
  }
  function resolve(id: string) {
    setAnomalies((curr) =>
      curr.map((a) => (a.id === id ? { ...a, status: "resolved" } : a)),
    );
  }
  function markFalsePositive(id: string) {
    setAnomalies((curr) =>
      curr.map((a) =>
        a.id === id
          ? { ...a, status: "false_positive", notes: "Confirmed as a planned operational event." }
          : a,
      ),
    );
  }
  function clearFilters() {
    setSeverityFilter("all");
    setMethodFilter("all");
    setStatusFilter("all");
    setTypeFilter("all");
    setSearch("");
  }

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
            Records flagged by the ingestion-layer hybrid detector (rule-based
            + LSTM-residual ML). Suspicious records are tagged here, not
            dropped, so downstream systems can distinguish a real
            operational event from a data-quality issue.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-white/50">
          <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2 py-1">
            <Activity className="h-3 w-3" />
            {summary.total} total · {summary.new_count} new
          </span>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <AnomalyKpi
          label="New anomalies"
          value={String(summary.new_count)}
          sub="Need acknowledgement"
          tone={summary.new_count > 0 ? "warn" : "neutral"}
          icon={AlertCircle}
        />
        <AnomalyKpi
          label="High severity"
          value={String(summary.high_severity)}
          sub="Of 30 recent"
          tone={summary.high_severity > 0 ? "warn" : "neutral"}
          icon={AlertTriangle}
        />
        <AnomalyKpi
          label="Anomaly rate"
          value={`${summary.anomaly_rate_pct}%`}
          sub="≈1 per 8,300 rows"
          tone="neutral"
          icon={Gauge}
        />
        <AnomalyKpi
          label="Avg ML score"
          value={summary.avg_score.toFixed(3)}
          sub="Hybrid + rule"
          tone="neutral"
          icon={TrendingUp}
        />
      </div>

      {/* Detection methods breakdown */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MethodCard
          label="Rule"
          count={summary.rule_count}
          icon={ShieldCheck}
          color="emerald"
          blurb="Schema, range, freshness, duplicates, interconnector balance."
        />
        <MethodCard
          label="ML (residual)"
          count={summary.ml_count}
          icon={Bot}
          color="amber"
          blurb="LSTM residual > 3σ. Catches demand spikes, drops, price anomalies."
        />
        <MethodCard
          label="Hybrid"
          count={summary.hybrid_count}
          icon={Sparkles}
          color="rose"
          blurb="Both rule + ML agreed. Highest severity, route to on-call."
        />
      </div>

      {/* Daily counts (last 7 days) */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Layers className="h-4 w-4 text-white/60" />
            Anomalies by day (last 7)
          </h2>
        </div>
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
      </Card>

      {/* Filter bar */}
      <Card>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect
              label="Severity"
              value={severityFilter}
              options={SEVERITY_FILTERS}
              onChange={(v) => setSeverityFilter(v as AnomalySeverity | "all")}
            />
            <FilterSelect
              label="Method"
              value={methodFilter}
              options={METHOD_FILTERS}
              onChange={(v) => setMethodFilter(v as AnomalyMethod | "all")}
            />
            <FilterSelect
              label="Status"
              value={statusFilter}
              options={STATUS_FILTERS}
              onChange={(v) => setStatusFilter(v as AnomalyStatus | "all")}
            />
            <FilterSelect
              label="Type"
              value={typeFilter}
              options={TYPE_FILTERS}
              onChange={(v) => setTypeFilter(v as AnomalyType | "all")}
            />
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-white/70 hover:bg-white/10"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-white/40" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search region, reason…"
              className="w-56 rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white placeholder:text-white/35 focus:border-emerald-200/60 focus:outline-none"
            />
          </div>
        </div>
        <div className="mt-3 text-xs text-white/50">
          Showing {filtered.length} of {anomalies.length} anomalies
        </div>
      </Card>

      {/* Anomaly table */}
      <Card>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <AlertTriangle className="h-4 w-4 text-amber-200" />
            Recent anomalies
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/5 text-xs uppercase text-white/50">
              <tr>
                <th className="px-3 py-2">Detected</th>
                <th className="px-3 py-2">Region</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Method</th>
                <th className="px-3 py-2 text-right">Score</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-sm text-white/50">
                    No anomalies match the current filters.
                  </td>
                </tr>
              )}
              {filtered.map((a) => {
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
                    onToggle={() => setExpandedId(expanded ? null : a.id)}
                    onAcknowledge={() => acknowledge(a.id)}
                    onResolve={() => resolve(a.id)}
                    onFalsePositive={() => markFalsePositive(a.id)}
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
              1. Rule layer
            </h3>
            <p className="leading-relaxed">
              Each record passes a battery of deterministic checks before
              it lands in DuckDB: schema match, null thresholds, physical
              range (e.g. demand 0–100,000 MW), timestamp not in the
              future, no (ts, region) duplicates within 60 s, and
              interconnector flow balance. Failures land on this page
              tagged <span className="font-mono text-xs">rule</span>.
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-200">
              2. ML layer
            </h3>
            <p className="leading-relaxed">
              The current production LSTM produces a 1-step-ahead forecast
              for the same (ts, region). Records where the actual demand
              differs from the forecast by more than 3 σ are flagged with
              the LSTM residual. Tagged{" "}
              <span className="font-mono text-xs">ml</span>.
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-rose-200">
              3. Hybrid agreement
            </h3>
            <p className="leading-relaxed">
              When both layers agree, the record is marked{" "}
              <span className="font-mono text-xs">hybrid</span> and
              assigned a higher severity. Hybrid is the highest-priority
              class — these are the records an on-call engineer should
              look at first.
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
              false-positive (e.g. a planned industrial load loss).
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
      <div className="text-3xl font-bold text-white">{count}</div>
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
        <td className="px-3 py-2 font-mono text-xs text-white/80">{a.region}</td>
        <td className="px-3 py-2 text-xs text-white/60">{a.source}</td>
        <td className="px-3 py-2 text-xs text-white/80">{a.type}</td>
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
          {a.status === "new" ? (
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
          <td colSpan={9} className="px-6 py-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Interval
                </h4>
                <p className="font-mono text-xs text-white/80">
                  {a.ts}
                </p>
              </div>
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Observed vs expected
                </h4>
                <p className="font-mono text-xs text-white/80">
                  observed ={" "}
                  <span className="text-amber-200">{String(a.observed_value)}</span>
                  {a.unit && <span className="text-white/40"> {a.unit}</span>}
                  <br />
                  expected ={" "}
                  <span className="text-emerald-100">{String(a.expected_value)}</span>
                  {a.unit && <span className="text-white/40"> {a.unit}</span>}
                </p>
              </div>
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Assigned to
                </h4>
                <p className="text-xs text-white/80">
                  {a.assigned_to ?? <span className="text-white/40">unassigned</span>}
                </p>
              </div>
              <div className="md:col-span-3">
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
                  Reason
                </h4>
                <p className="text-sm text-white/80">{a.reason}</p>
                {a.notes && (
                  <p className="mt-1 text-xs text-white/50">
                    <span className="text-white/40">notes:</span> {a.notes}
                  </p>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
