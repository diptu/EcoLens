/**
 * /dashboard/admin/anomaly-detection — anomaly log.
 *
 * Lists real records flagged by the ingestion-layer detector —
 * `meta.anomalies`, 150K+ real rows confirmed live 2026-08-08 (real
 * `pipeline.anomaly.detect_anomalies`, real `pipeline.ml_anomaly`
 * IsolationForest per source). The admin can:
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
 * that exist in the data.
 *
 * **2026-08-12**: the rule-based signal (out-of-range bounds,
 * missing-value flagging — real, live-observed cost: it accounted for
 * 121K/150K+ of these rows, the overwhelming majority structurally
 * expected rather than anomalous) was retired backend-side —
 * `pipeline/anomaly.py`'s own docstring has the full reasoning. The
 * detector is statistical (z-score) + ML now; `method: "rule"` and the
 * `missing_value`/`out_of_range` reason kinds are real but legacy-only
 * going forward, not removed from this page since the historical rows
 * are still real data worth being able to see/filter.
 *
 * **2026-08-12, redesigned**: added the "Anomaly Overview" chart and
 * the KPI row + master-detail (table + details panel) layout, backed by
 * the new `GET /v1/anomalies/timeseries` (`services/ingestion`, real
 * per-timestamp `raw_marts.fct_energy_demand` rows with the same
 * `is_anomalous`/`anomaly_score` dbt already joins onto that mart, plus
 * a real rolling-window expected-range band computed with the exact
 * same z-score arithmetic `pipeline.anomaly.detect_anomalies` itself
 * uses). The KPI row and chart are scoped to whichever region/metric is
 * selected in the chart filters (real, not the same global scope as the
 * table below, which keeps its own independent severity/method/status/
 * reason filters) -- two real, honestly-different scopes, not the same
 * number shown twice.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  Layers,
  Lightbulb,
  Loader2,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  fetchAnomalies,
  fetchAnomalyContext,
  fetchAnomalySummary,
  fetchAnomalyTimeseries,
  updateAnomalyStatus,
  type Anomaly,
  type AnomalyContext,
  type AnomalyContextPoint,
  type AnomalyMethod,
  type AnomalySeverity,
  type AnomalyStatus,
  type AnomalySummary,
  type AnomalyTimeseriesPoint,
  type AnomalyTimeseriesResponse,
} from "@/lib/anomalies";

const CHART_REGIONS: Array<{ value: string; label: string }> = [
  { value: "NSW1", label: "NSW1" },
  { value: "QLD1", label: "QLD1" },
  { value: "VIC1", label: "VIC1" },
  { value: "SA1", label: "SA1" },
  { value: "TAS1", label: "TAS1" },
  { value: "WEM", label: "WEM" },
];

const CHART_METRICS: Array<{ value: "demand_mw" | "price_mwh"; label: string }> = [
  { value: "demand_mw", label: "Demand (MW)" },
  { value: "price_mwh", label: "Price ($/MWh)" },
];

const SEVERITY_FILTERS: Array<{ value: AnomalySeverity | "all"; label: string }> = [
  { value: "all",    label: "All severities" },
  { value: "high",   label: "High"           },
  { value: "medium", label: "Medium"         },
  { value: "low",    label: "Low"            },
];

const METHOD_FILTERS: Array<{ value: AnomalyMethod | "all"; label: string }> = [
  { value: "all",         label: "All methods"       },
  { value: "hybrid",      label: "Hybrid"            },
  { value: "statistical", label: "Statistical"       },
  { value: "ml",          label: "ML"                },
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
// `missing_value`/`out_of_range` are legacy -- the rule-based signal
// that produced them was retired 2026-08-12 (see this file's own header
// docstring); real historical rows still carry these, nothing new does.
const REASON_KIND_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All reasons" },
  { value: "statistical_outlier", label: "Statistical outlier" },
  { value: "ml_outlier", label: "ML outlier" },
  { value: "missing_value", label: "Missing value (legacy)" },
  { value: "out_of_range", label: "Out of range (legacy)" },
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mutating, setMutating] = useState<string | null>(null);

  const [chartRegion, setChartRegion] = useState("NSW1");
  const [chartMetric, setChartMetric] = useState<"demand_mw" | "price_mwh">("demand_mw");
  const [timeseries, setTimeseries] = useState<AnomalyTimeseriesResponse | null>(null);
  const [timeseriesError, setTimeseriesError] = useState<string | null>(null);

  // Real per-timestamp series + anomaly overlay for the selected region/
  // metric -- a genuinely different scope than the table below (which
  // spans every region/source via its own independent filters), not the
  // same number re-shown.
  useEffect(() => {
    let cancelled = false;
    setTimeseries(null);
    setTimeseriesError(null);
    fetchAnomalyTimeseries({ region: chartRegion, metric: chartMetric })
      .then((r) => {
        if (!cancelled) setTimeseries(r);
      })
      .catch((err) => {
        if (!cancelled) setTimeseriesError(err instanceof Error ? err.message : "failed to load");
      });
    return () => { cancelled = true; };
  }, [chartRegion, chartMetric]);

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

  // The selected row for the details panel -- defaults to the first
  // real row on the current page once one loads, so the panel isn't
  // empty on first paint (matches the reference layout's default
  // "details for the top row" state), but still respects an explicit
  // pick, including one that's since scrolled off `filtered` (falls
  // back to the first row rather than showing a stale/missing anomaly).
  const selected = useMemo(() => {
    if (filtered.length === 0) return null;
    return filtered.find((a) => a.id === selectedId) ?? filtered[0];
  }, [filtered, selectedId]);

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
            Real records flagged by the ingestion-layer detector (statistical z-score
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

      {/* KPI cards -- scoped to the chart's region/metric selection below
          (real `timeseries.total_points`/`anomalous_points`), a
          genuinely different scope than the global breakdown/daily-count
          cards further down (this file's own header comment). */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-5">
        <AnomalyKpi
          label="Total Data Points"
          value={timeseries ? timeseries.total_points.toLocaleString() : "—"}
          sub={`${chartRegion}, last 7 days`}
          tone="neutral"
          icon={Database}
        />
        <AnomalyKpi
          label="Anomalies Detected"
          value={timeseries ? timeseries.anomalous_points.toLocaleString() : "—"}
          sub={
            timeseries && timeseries.total_points > 0
              ? `${((timeseries.anomalous_points / timeseries.total_points) * 100).toFixed(2)}% of total`
              : "in selected period"
          }
          tone={timeseries && timeseries.anomalous_points > 0 ? "warn" : "neutral"}
          icon={AlertTriangle}
        />
        <AnomalyKpi
          label="High Severity"
          value={
            timeseries
              ? timeseries.points.filter((p) => p.severity === "high").length.toLocaleString()
              : "—"
          }
          sub={
            timeseries && timeseries.total_points > 0
              ? `${((timeseries.points.filter((p) => p.severity === "high").length / timeseries.total_points) * 100).toFixed(2)}% of total`
              : "in selected period"
          }
          tone="warn"
          icon={AlertCircle}
        />
        <AnomalyKpi
          label="Normal Points"
          value={
            timeseries
              ? (timeseries.total_points - timeseries.anomalous_points).toLocaleString()
              : "—"
          }
          sub={
            timeseries && timeseries.total_points > 0
              ? `${(((timeseries.total_points - timeseries.anomalous_points) / timeseries.total_points) * 100).toFixed(2)}% of total`
              : "in selected period"
          }
          tone="neutral"
          icon={CheckCircle2}
        />
        <AnomalyKpi
          label="Detection Model"
          value="Statistical + ML"
          sub={
            summary?.latest_detected_at
              ? `Last flagged ${formatTs(summary.latest_detected_at)}`
              : "No detections yet"
          }
          tone="neutral"
          icon={Cpu}
        />
      </div>

      {/* Anomaly Overview chart */}
      <Card>
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Activity className="h-4 w-4 text-sky-200" />
            Anomaly Overview
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <FilterSelect
              label="Region"
              value={chartRegion}
              options={CHART_REGIONS.map((r) => ({ value: r.value, label: r.label }))}
              onChange={setChartRegion}
            />
            <FilterSelect
              label="Metric"
              value={chartMetric}
              options={CHART_METRICS}
              onChange={(v) => setChartMetric(v as "demand_mw" | "price_mwh")}
            />
          </div>
        </div>
        {timeseriesError ? (
          <p className="py-16 text-center text-xs text-white/40">
            Unavailable — {timeseriesError}
          </p>
        ) : timeseries === null ? (
          <p className="py-16 text-center text-xs text-white/40">Loading real demand data…</p>
        ) : (
          <>
            <AnomalyOverviewChart points={timeseries.points} metric={timeseries.metric} />
            <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-white/65">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-300" />
                Normal
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-amber-300" />
                Moderate Anomaly
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-rose-400" />
                High Anomaly
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-3.5 rounded-sm border border-white/20 bg-white/10" />
                Expected Range (real, rolling {`±`}3{`σ`})
              </span>
            </div>
          </>
        )}
      </Card>

      {/* Detection methods breakdown */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MethodCard
          label="Statistical"
          count={summary?.by_method.statistical ?? 0}
          icon={Activity}
          color="sky"
          blurb="Per-batch z-score against each column's own mean/std within the current fetch."
        />
        <MethodCard
          label="ML (IsolationForest)"
          count={summary?.by_method.ml ?? 0}
          icon={Bot}
          color="amber"
          blurb="Per-source IsolationForest over numeric columns. Catches multivariate outliers the statistical check misses."
        />
        <MethodCard
          label="Hybrid"
          count={summary?.by_method.hybrid ?? 0}
          icon={Sparkles}
          color="rose"
          blurb="Both statistical AND ML flagged the same row. Highest confidence."
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

      {/* Detected Anomalies (left) + Anomaly Details (right) --
          master-detail, replacing the old single wide table + inline
          accordion: clicking a row selects it into the details panel
          instead of expanding inline, matching the reference layout. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <AlertTriangle className="h-4 w-4 text-amber-200" />
              Detected Anomalies
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
                  <th className="px-3 py-2">Severity</th>
                  <th className="px-3 py-2">Method</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {loading && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-sm text-white/50">
                      <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                    </td>
                  </tr>
                )}
                {!loading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-sm text-white/50">
                      No anomalies match the current filters.
                    </td>
                  </tr>
                )}
                {!loading && filtered.map((a) => {
                  const sev = SEVERITY_STYLES[a.severity];
                  const stat = STATUS_STYLES[a.status];
                  const isSelected = selected?.id === a.id;
                  return (
                    <tr
                      key={a.id}
                      onClick={() => setSelectedId(a.id)}
                      data-testid={`anomaly-row-${a.id}`}
                      className={cn(
                        "cursor-pointer transition-colors hover:bg-white/[0.03]",
                        isSelected && "bg-sky-300/[0.06]",
                      )}
                    >
                      <td className="whitespace-nowrap px-3 py-2 text-white/80">
                        {formatTs(a.detected_at)}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-white/80">{a.region ?? "—"}</td>
                      <td className="px-3 py-2">
                        <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium", sev.chip, sev.text)}>
                          <span className={cn("h-1.5 w-1.5 rounded-full", sev.dot)} />
                          {a.severity}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-1.5 text-[11px] text-white/70">
                          {a.method}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs text-white/80">
                        {a.score.toFixed(2)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium", stat.className)}>
                          {stat.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-3 text-xs text-white/50">
            {loading ? "Loading…" : `Showing ${filtered.length} of ${total.toLocaleString()} real anomalies`}
          </div>
        </Card>

        <div className="xl:col-span-2">
          <AnomalyDetailsPanel
            anomaly={selected}
            mutating={selected ? mutating === selected.id : false}
            onAcknowledge={() => selected && mutate(selected.id, "acknowledged")}
            onResolve={() => selected && mutate(selected.id, "resolved")}
            onFalsePositive={() => selected && mutate(selected.id, "false_positive")}
          />
        </div>
      </div>

      {/* How it works */}
      <Card>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <Lightbulb className="h-4 w-4 text-amber-200" />
          How the detector works
        </h2>
        <div className="grid grid-cols-1 gap-3 text-sm text-white/70 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-sky-200">
              1. Statistical layer
            </h3>
            <p className="leading-relaxed">
              Each ingested record is checked for statistical (z-score)
              outliers against its own column's mean/std within the
              current batch. Failures land on this page tagged{" "}
              <span className="font-mono text-xs">statistical</span>.
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
              When both the statistical check and the ML model flag the
              same row, it&apos;s marked{" "}
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
        <p className="mt-3 border-t border-white/10 pt-3 text-xs text-white/50">
          A third, rule-based layer (out-of-range bounds, missing-value
          flagging) ran until 2026-08-12, when it was retired — it
          accounted for the large majority of flagged rows, most of them
          structurally expected rather than anomalous. Rows it already
          flagged are still real and still shown here, tagged{" "}
          <span className="font-mono">rule</span> — nothing new lands in
          that bucket going forward.
        </p>
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
  color: "emerald" | "amber" | "rose" | "sky";
  blurb: string;
}) {
  const ring = {
    emerald: "border-emerald-200/30 from-emerald-200/10",
    amber:   "border-amber-300/30 from-amber-300/10",
    rose:    "border-rose-300/30 from-rose-300/10",
    sky:     "border-sky-300/30 from-sky-300/10",
  }[color];
  const iconColor = {
    emerald: "text-emerald-100",
    amber: "text-amber-200",
    rose: "text-rose-200",
    sky: "text-sky-200",
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

// ────────────────────────────────────────────────────────────────────
// Anomaly Details panel
// ────────────────────────────────────────────────────────────────────

// Real thresholds `ml_anomaly.ANOMALY_SCORE_THRESHOLD` / `pipeline.
// anomaly._Z_SCORE_THRESHOLD` use (`services/ingestion/app/service/
// pipeline/{ml_anomaly,anomaly}.py`) -- only mirrored here to honestly
// label a contributing factor, not re-derived. Raised 0.5->0.7 /
// 3.0->4.0, 2026-08-13, matching the same operator-requested backend
// tightening -- keep in sync if those change again.
const ML_ANOMALY_SCORE_THRESHOLD = 0.7;
const Z_SCORE_THRESHOLD = 4.0;

// Real per-column "how far off is this row's own real value from its
// own real ±3-day baseline" (`context.baseline`, `services/ingestion`'s
// `get_anomaly_context` docstring has the full derivation) -- normalized
// to 0..1 (5 real std devs -> fully saturated) so every column is
// comparable on one radar/bar scale regardless of its own unit. Not a
// trained feature-importance value (the real `IsolationForest` never
// persists one, `ml_anomaly.py`'s own docstring/module has no
// per-feature contribution anywhere) -- this is the honest, real
// substitute: an actual deviation strength per real scanned column,
// computed against real wider-window history so a narrow local
// excursion (e.g. a multi-hour heatwave filling the ±2h window itself)
// can't silently understate it.
function computeContributingFactors(
  context: AnomalyContext | null,
  anomalyTs: string | null,
): Array<{ column: string; score: number; z: number }> {
  if (!context || !anomalyTs) return [];
  const ownPoint = context.points.find(
    (p) => new Date(p.ts).getTime() === new Date(anomalyTs).getTime(),
  );
  if (!ownPoint) return [];
  const out: Array<{ column: string; score: number; z: number }> = [];
  for (const col of context.columns) {
    const value = ownPoint.values[col];
    const baseline = context.baseline[col];
    if (value == null || !baseline || baseline.std <= 1e-9) continue;
    const z = (value - baseline.mean) / baseline.std;
    out.push({ column: col, score: Math.min(1, Math.abs(z) / 5), z });
  }
  return out;
}

function AnomalyDetailsPanel({
  anomaly,
  mutating,
  onAcknowledge,
  onResolve,
  onFalsePositive,
}: {
  anomaly: Anomaly | null;
  mutating: boolean;
  onAcknowledge: () => void;
  onResolve: () => void;
  onFalsePositive: () => void;
}) {
  const [context, setContext] = useState<AnomalyContext | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);

  // Real, narrowly-scoped fetch (±2h around the selected anomaly's own
  // `ts`, `services/ingestion`'s own `_CONTEXT_WINDOW_HOURS`) -- reads
  // straight from this anomaly's own source's `raw.*` table (region-
  // scoped), so it works for every source the detector covers (`bom`'s
  // `temp_c`/`humidity_pct`/`wind_speed_kmh` just as well as
  // `aemo_nem`/`aemo_wem`'s `demand_mw`/`price_mwh`), not just the 2
  // metrics `fetchAnomalyTimeseries` (the overview chart's own data
  // source) covers.
  useEffect(() => {
    if (!anomaly) {
      setContext(null);
      setContextError(null);
      return;
    }
    let cancelled = false;
    setContext(null);
    setContextError(null);
    fetchAnomalyContext(anomaly.id)
      .then((r) => { if (!cancelled) setContext(r); })
      .catch((err) => {
        if (!cancelled) setContextError(err instanceof Error ? err.message : "failed to load");
      });
    return () => { cancelled = true; };
  }, [anomaly?.id]);

  if (!anomaly) {
    return (
      <Card className="flex h-full items-center justify-center">
        <p className="py-16 text-center text-xs text-white/40">
          Select a row to see its detail.
        </p>
      </Card>
    );
  }

  const sev = SEVERITY_STYLES[anomaly.severity];
  const stat = STATUS_STYLES[anomaly.status];
  const StatIcon = stat.icon;

  // Real, derived-from-the-row contributing factors -- only ever states
  // something that's actually true of this specific row's own real
  // fields, never a fixed/templated list (the reference layout's own
  // "Z-score > 3.5"/"Outside expected range"/"Change rate > 50%" read as
  // fixed always-on bullets; here each only appears when the real data
  // backs it).
  const factors: string[] = [];
  if (anomaly.z_score != null && Math.abs(anomaly.z_score) > Z_SCORE_THRESHOLD) {
    factors.push(`Z-score ${anomaly.z_score >= 0 ? ">" : "<"} ${anomaly.z_score >= 0 ? Z_SCORE_THRESHOLD.toFixed(1) : `-${Z_SCORE_THRESHOLD.toFixed(1)}`} (actual: ${anomaly.z_score.toFixed(2)})`);
  }
  if (
    anomaly.observed_value != null &&
    (anomaly.expected_low != null || anomaly.expected_high != null) &&
    ((anomaly.expected_low != null && anomaly.observed_value < anomaly.expected_low) ||
      (anomaly.expected_high != null && anomaly.observed_value > anomaly.expected_high))
  ) {
    factors.push(
      `Outside expected range [${anomaly.expected_low?.toFixed(1) ?? "—"}, ${anomaly.expected_high?.toFixed(1) ?? "—"}]`,
    );
  }
  if ((anomaly.method === "ml" || anomaly.method === "hybrid") && anomaly.score >= ML_ANOMALY_SCORE_THRESHOLD) {
    factors.push(`ML (IsolationForest) anomaly score ≥ ${ML_ANOMALY_SCORE_THRESHOLD.toFixed(1)} (actual: ${anomaly.score.toFixed(2)})`);
  }

  // Real fallback for "Observed Value" when this row has no single
  // `metric`/`observed_value` of its own -- true for every pure-ML
  // detection (multivariate by construction, `services/ingestion`'s
  // `ml_anomaly.py` own docstring: isolation forest scores several
  // columns jointly, there's no one "the value"). Once `context` loads,
  // its own row at this exact anomaly matches on `ts` -- real per-column
  // readings from the same `raw.*` row the detector actually scored,
  // not a fabricated single number.
  const contextOwnPoint =
    context?.points.find(
      (p) => anomaly.ts && new Date(p.ts).getTime() === new Date(anomaly.ts).getTime(),
    ) ?? null;
  const observedFromContext =
    contextOwnPoint &&
    Object.entries(contextOwnPoint.values)
      .filter(([, v]) => v != null)
      .map(([k, v]) => `${k} ${v!.toLocaleString()}`)
      .join(" · ");

  // Real fallback for "Expected Range" -- same idea as `observedFromContext`
  // above: a pure ML detection has no single batch-level bound of its
  // own (`ml_anomaly.py`'s own docstring -- multivariate by
  // construction), so derive one per real scanned column from
  // `context.baseline` -- a real ±3-day window, deliberately *not* the
  // narrow ±2h `points` window (which can itself be almost entirely
  // anomalous during a sustained real excursion, e.g. a multi-hour
  // heatwave -- confirmed live: that made an earlier, narrower version
  // of this fallback trivially contain the very reading it was meant to
  // judge, `services/ingestion`'s own `get_anomaly_context` docstring
  // has the full story).
  const expectedRangeFromContext = context
    ? context.columns
        .map((col) => {
          const baseline = context.baseline[col];
          if (!baseline) return null;
          return `${col} ${baseline.low.toFixed(1)}–${baseline.high.toFixed(1)}`;
        })
        .filter((s): s is string => s != null)
        .join(" · ")
    : "";

  // Not memoized -- `anomaly`/`context` already only change on a real
  // selection/fetch, and this is a small, cheap pass over an already-
  // small (±2h) points array, not worth a hook here (this sits after
  // the early `if (!anomaly) return` above, so a `useMemo` here would
  // be called conditionally across renders and break the rules of
  // hooks).
  const contributingFactors = computeContributingFactors(context, anomaly.ts);

  return (
    <Card className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Lightbulb className="h-4 w-4 text-amber-200" />
          Anomaly Details
        </h2>
        <span className="font-mono text-[10px] text-white/40">{anomaly.id.slice(0, 8)}</span>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold", sev.chip, sev.text)}>
          <span className={cn("h-2 w-2 rounded-full", sev.dot)} />
          {anomaly.severity === "high" ? "High" : anomaly.severity === "medium" ? "Moderate" : "Low"} Anomaly
        </span>
        <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium", stat.className)}>
          <StatIcon className="h-3 w-3" />
          {stat.label}
        </span>
      </div>

      <dl className="space-y-2 text-xs">
        <DetailRow label="Time Detected" value={formatTs(anomaly.detected_at)} />
        <DetailRow label="Interval" value={anomaly.ts ?? "—"} mono />
        <DetailRow label="Metric" value={anomaly.metric ?? "—"} />
        <DetailRow label="Source" value={anomaly.source} />
        <DetailRow label="Region" value={anomaly.region ?? "—"} />
        <DetailRow
          label="Observed Value"
          value={
            anomaly.observed_value != null
              ? anomaly.observed_value.toLocaleString()
              : observedFromContext || (context === null && !contextError ? "Loading…" : "—")
          }
          valueClassName="text-amber-200"
        />
        {/* Real "Expected Range" -- the statistical (z-score) signal's own
            single-`metric` bound when this row has one; otherwise (every
            pure-ML detection, multivariate by construction -- see
            `observedFromContext` above's own comment) the real per-column
            fallback from `context.baseline` (`expectedRangeFromContext`,
            a real ±3-day window -- deliberately wider than the ±2h
            `points` window below, which can itself be almost entirely
            anomalous during a sustained real excursion and would
            otherwise make this trivially contain the very reading it's
            meant to judge), never a fabricated or blank value. */}
        <DetailRow
          label="Expected Range"
          value={
            anomaly.expected_low != null || anomaly.expected_high != null
              ? `${anomaly.expected_low?.toFixed(1) ?? "—"} – ${anomaly.expected_high?.toFixed(1) ?? "—"}`
              : expectedRangeFromContext || (context === null && !contextError ? "Loading…" : "—")
          }
        />
        <DetailRow label="Anomaly Score" value={anomaly.score.toFixed(3)} valueClassName="text-rose-200" />
        <DetailRow label="Detection Method" value={anomaly.method} />
        <DetailRow
          label="Status Updated"
          value={anomaly.status_updated_at ? formatTs(anomaly.status_updated_at) : "never"}
        />
      </dl>

      <div className="mt-3">
        <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Reason</h4>
        <p className="text-xs leading-relaxed text-white/80">{anomaly.reason}</p>
      </div>

      {/* Metric Behavior -- real narrow window around this row's own ts,
          every real numeric column the detector actually scanned for
          this source plotted together on one shared time axis (own
          y-scale per column), the real vertical guide at this row's own
          `ts` and its own point on each line ring-highlighted -- other
          real anomalous neighbors in the same window still shown, just
          not ring-highlighted (only the one this panel is about is). */}
      <div className="mt-3">
        <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">
          Metric Behavior (±2h around event, real)
        </h4>
        {contextError ? (
          <p className="py-4 text-center text-[11px] text-white/35">Unavailable — {contextError}</p>
        ) : context === null ? (
          <p className="py-4 text-center text-[11px] text-white/35">Loading…</p>
        ) : context.points.length === 0 ? (
          <p className="py-4 text-center text-[11px] text-white/35">
            Not enough real data nearby.
          </p>
        ) : (
          <AnomalyMetricBehaviorChart
            columns={context.columns}
            points={context.points}
            highlightTs={anomaly.ts ?? context.center_ts}
          />
        )}
      </div>

      {/* Contributing Factors -- real per-column local-deviation strength
          (`computeContributingFactors`'s own comment has the exact
          method) plotted as a radar when there are enough real scanned
          columns to make a polygon meaningful (3+), a bar list
          otherwise. Falls back to the plain-text signal-threshold facts
          below when the ±2h context hasn't loaded / has no columns for
          this row (e.g. `aemo_holidays`, which scans none) rather than
          showing nothing. */}
      {contributingFactors.length > 0 ? (
        <div className="mt-3">
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            Contributing Factors
          </h4>
          <ContributingFactorsRadar factors={contributingFactors} />
          {/* The ML model's own `anomaly.score` above is trained against
              this source's full accumulated history (`ml_anomaly.py`);
              this radar is a real but *different* measure -- each real
              column's own deviation from a real ±3-day baseline. The two
              can legitimately disagree in either direction -- said
              explicitly so that isn't read as a bug. */}
          <p className="mt-1.5 text-center text-[9px] leading-relaxed text-white/35">
            Real per-column deviation from this row&apos;s own ±3-day baseline — a different, complementary measure to the ML model&apos;s own full-history score above.
          </p>
        </div>
      ) : factors.length > 0 ? (
        <div className="mt-3">
          <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/50">
            Contributing Factors
          </h4>
          <ul className="space-y-1">
            {factors.map((f) => (
              <li key={f} className="flex items-start gap-1.5 text-[11px] text-white/75">
                <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-300" />
                {f}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-auto pt-3">
        {mutating ? (
          <div className="flex justify-center py-1">
            <Loader2 className="h-4 w-4 animate-spin text-white/50" />
          </div>
        ) : anomaly.status === "new" ? (
          <div className="flex gap-2">
            <button
              onClick={onAcknowledge}
              className="flex-1 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-300/20"
              data-testid={`ack-${anomaly.id}`}
            >
              Acknowledge
            </button>
            <button
              onClick={onFalsePositive}
              className="flex-1 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:bg-white/10"
              data-testid={`fp-${anomaly.id}`}
            >
              False Positive
            </button>
          </div>
        ) : anomaly.status === "acknowledged" ? (
          <button
            onClick={onResolve}
            className="w-full rounded-md border border-emerald-200/30 bg-emerald-200/10 px-3 py-1.5 text-xs font-medium text-emerald-100 hover:bg-emerald-200/20"
            data-testid={`resolve-${anomaly.id}`}
          >
            Mark Resolved
          </button>
        ) : null}
      </div>
    </Card>
  );
}

function DetailRow({
  label,
  value,
  mono,
  valueClassName,
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-1.5">
      <dt className="text-white/50">{label}</dt>
      <dd className={cn("truncate text-right text-white/85", mono && "font-mono", valueClassName)}>
        {value}
      </dd>
    </div>
  );
}

/** Real per-column local-deviation strength (`computeContributingFactors`
 * in `AnomalyDetailsPanel` above has the exact real derivation), plotted
 * as a spider/radar polygon -- one axis per real scanned column, radius
 * = that column's own real 0..1 deviation score. Needs 3+ real axes for
 * a polygon to mean anything; falls back to a plain bar list for
 * 1-2-column sources (`aemo_nem`/`aemo_wem`/`openelectricity`) instead
 * of drawing a degenerate 2-point "polygon". */
function ContributingFactorsRadar({
  factors,
}: {
  factors: Array<{ column: string; score: number; z: number }>;
}) {
  if (factors.length < 3) {
    return (
      <div className="space-y-1.5">
        {factors.map((f, i) => (
          <div key={f.column} className="flex items-center gap-2">
            <span className="w-28 shrink-0 truncate text-[10px] text-white/60">{f.column}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full"
                style={{ width: `${f.score * 100}%`, backgroundColor: METRIC_COLORS[i % METRIC_COLORS.length] }}
              />
            </div>
            <span className="w-9 shrink-0 text-right font-mono text-[10px] text-white/70">
              {f.score.toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    );
  }

  const n = factors.length;
  const size = 200;
  const center = size / 2;
  const maxR = size / 2 - 30;
  const angleFor = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pointFor = (i: number, r: number): [number, number] => {
    const a = angleFor(i);
    return [center + r * Math.cos(a), center + r * Math.sin(a)];
  };
  const ringLevels = [0.25, 0.5, 0.75, 1];
  const polygonPts = factors.map((f, i) => pointFor(i, f.score * maxR));
  const polygonPath =
    polygonPts.map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`).join(" ") + " Z";

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto h-[200px] w-[200px]">
      {ringLevels.map((lvl) => {
        const ringPts = factors.map((_, i) => pointFor(i, lvl * maxR));
        const ringPath =
          ringPts.map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`).join(" ") + " Z";
        return <path key={lvl} d={ringPath} fill="none" stroke="rgba(255,255,255,0.08)" />;
      })}
      {factors.map((_, i) => {
        const [px, py] = pointFor(i, maxR);
        return <line key={i} x1={center} y1={center} x2={px} y2={py} stroke="rgba(255,255,255,0.08)" />;
      })}
      <path d={polygonPath} fill="rgba(244,63,94,0.18)" stroke="#fb7185" strokeWidth={1.5} strokeLinejoin="round" />
      {polygonPts.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py} r={2.5} fill="#fb7185" />
      ))}
      {factors.map((f, i) => {
        const [lx, ly] = pointFor(i, maxR + 20);
        return (
          <text key={f.column} x={lx} y={ly} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.7)">
            <tspan x={lx} dy="0">{f.column}</tspan>
            <tspan x={lx} dy="12" fontSize="9" fill="rgba(255,255,255,0.4)">{f.score.toFixed(2)}</tspan>
          </text>
        );
      })}
    </svg>
  );
}

// Fixed palette, applied by column position -- matches the reference
// layout's temp_c=red/humidity_pct=blue/wind_speed_kmh=green convention
// for `bom` while still giving every other real source (nem/wem's 2
// columns, openelectricity's 1) a stable, distinct color per line.
const METRIC_COLORS = ["#fb7185", "#38bdf8", "#4ade80", "#c084fc", "#fbbf24"];

// Real units for the columns `pipeline.anomaly._NUMERIC_COLUMNS` actually
// scans -- label-only, doesn't affect any value.
const COLUMN_UNITS: Record<string, string> = {
  temp_c: "°C",
  humidity_pct: "%",
  wind_speed_kmh: "km/h",
  demand_mw: "MW",
  price_mwh: "$/MWh",
  total_generation_mw: "MW",
};

function columnLabel(column: string): string {
  const unit = COLUMN_UNITS[column];
  return unit ? `${column} (${unit})` : column;
}

/** Every real numeric column this anomaly's own source was scanned on,
 * plotted together on one shared real time axis (own y-scale per
 * column, own color) -- a real vertical guide at this row's own `ts`,
 * and that row's own point on each line ring-highlighted so it reads
 * apart from any *other* real anomalous neighbor in the same window
 * (those still show, just larger/rose, not ringed). */
function AnomalyMetricBehaviorChart({
  columns,
  points,
  highlightTs,
}: {
  columns: string[];
  points: AnomalyContextPoint[];
  highlightTs: string | null;
}) {
  const w = 720, h = 220;
  const padT = 16, padB = 34;
  const rightAxesCount = Math.max(0, columns.length - 1);
  const padL = 48;
  const padR = 16 + rightAxesCount * 50;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const sorted = [...points].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());

  const series = columns.map((col, i) => {
    const pts = sorted
      .map((p) => ({ ts: p.ts, value: p.values[col], is_anomalous: p.is_anomalous }))
      .filter((p): p is { ts: string; value: number; is_anomalous: boolean } => p.value != null);
    let vMin = 0, vMax = 1;
    if (pts.length >= 2) {
      const vMinRaw = Math.min(...pts.map((p) => p.value));
      const vMaxRaw = Math.max(...pts.map((p) => p.value));
      const vSpan = Math.max(1e-6, vMaxRaw - vMinRaw);
      vMin = vMinRaw - vSpan * 0.15;
      vMax = vMaxRaw + vSpan * 0.15;
    }
    return { column: col, color: METRIC_COLORS[i % METRIC_COLORS.length], pts, vMin, vMax };
  });
  const usable = series.filter((s) => s.pts.length >= 2);

  if (usable.length === 0) {
    return <p className="py-4 text-center text-[11px] text-white/35">Not enough real data nearby.</p>;
  }

  const tMin = new Date(sorted[0].ts).getTime();
  const tMax = new Date(sorted[sorted.length - 1].ts).getTime();
  const tSpan = Math.max(1, tMax - tMin);
  const x = (ts: string) => padL + ((new Date(ts).getTime() - tMin) / tSpan) * innerW;
  const yFor = (s: (typeof usable)[number]) => (v: number) =>
    padT + (1 - (v - s.vMin) / Math.max(1e-6, s.vMax - s.vMin)) * innerH;

  const highlightMs = highlightTs ? new Date(highlightTs).getTime() : null;
  const highlightInRange = highlightMs !== null && highlightMs >= tMin && highlightMs <= tMax;

  // A handful of real x-axis time labels, evenly spaced across the real window.
  const tickCount = Math.min(5, sorted.length);
  const xTicks = Array.from({ length: tickCount }, (_, i) => {
    const idx = Math.round((i / Math.max(1, tickCount - 1)) * (sorted.length - 1));
    return sorted[idx];
  });
  const dateLabel = new Date(sorted[0].ts).toLocaleDateString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "UTC",
  });

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[10px] text-white/60">
        {usable.map((s) => (
          <span key={s.column} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
            {columnLabel(s.column)}
          </span>
        ))}
        {highlightInRange && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-amber-200" />
            Anomaly Point
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-[190px] w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => (
          <line
            key={`grid-${i}`}
            x1={padL} x2={w - padR}
            y1={padT + p * innerH} y2={padT + p * innerH}
            stroke="rgba(255,255,255,0.05)"
            strokeDasharray={i === 0 || i === 4 ? "" : "4 4"}
          />
        ))}

        {highlightInRange && (
          <line
            x1={x(highlightTs!)} x2={x(highlightTs!)}
            y1={padT} y2={padT + innerH}
            stroke="#fbbf24" strokeWidth={1.25} strokeDasharray="4 3" opacity={0.75}
          />
        )}

        {/* left axis -- first usable series */}
        {[0, 0.5, 1].map((p, i) => {
          const s = usable[0];
          const v = s.vMax - p * (s.vMax - s.vMin);
          return (
            <text key={`ly-${i}`} x={padL - 8} y={padT + p * innerH + 4} textAnchor="end" fontSize="12" fill={usable[0].color} opacity={0.85}>
              {v.toFixed(Math.abs(v) < 10 ? 1 : 0)}
            </text>
          );
        })}

        {/* right axes -- remaining series, stacked outward */}
        {usable.slice(1).map((s, i) => {
          const axisX = w - padR + i * 50 + 6;
          return (
            <g key={`raxis-${s.column}`}>
              {[0, 0.5, 1].map((p, j) => {
                const v = s.vMax - p * (s.vMax - s.vMin);
                return (
                  <text key={j} x={axisX} y={padT + p * innerH + 4} textAnchor="start" fontSize="12" fill={s.color} opacity={0.85}>
                    {v.toFixed(Math.abs(v) < 10 ? 1 : 0)}
                  </text>
                );
              })}
            </g>
          );
        })}

        {usable.map((s) => {
          const yy = yFor(s);
          const linePath = smoothPath(s.pts.map((p) => [x(p.ts), yy(p.value)]));
          return (
            <g key={s.column}>
              <path d={linePath} fill="none" stroke={s.color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" opacity={0.9} />
              {s.pts.map((p) => {
                const isThisAnomaly = highlightMs !== null && new Date(p.ts).getTime() === highlightMs;
                return (
                  <circle
                    key={p.ts}
                    cx={x(p.ts)}
                    cy={yy(p.value)}
                    r={isThisAnomaly ? 5 : p.is_anomalous ? 3 : 1.75}
                    fill={p.is_anomalous ? "#fb7185" : s.color}
                    stroke={isThisAnomaly ? "#fde68a" : "#0a1410"}
                    strokeWidth={isThisAnomaly ? 2 : 1}
                  />
                );
              })}
            </g>
          );
        })}

        {xTicks.map((p, i) => (
          <text key={`xt-${i}`} x={x(p.ts)} y={h - padB + 18} textAnchor="middle" fontSize="12" fill="rgba(255,255,255,0.5)">
            {new Date(p.ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}
          </text>
        ))}
      </svg>
      <p className="mt-0.5 text-center text-[9px] text-white/35">{dateLabel} (UTC)</p>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Anomaly Overview chart
// ────────────────────────────────────────────────────────────────────

const OVERVIEW_SEVERITY_COLOR: Record<string, string> = {
  high: "#fb7185",
  medium: "#fbbf24",
  low: "#34d399",
};

function AnomalyOverviewChart({
  points,
  metric,
}: {
  points: AnomalyTimeseriesPoint[];
  metric: string;
}) {
  const w = 1200, h = 320;
  const padL = 60, padR = 24, padT = 20, padB = 32;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;

  const withValues = points.filter((p) => p.value !== null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; idx: number } | null>(null);

  const yMaxRaw = Math.max(1, ...withValues.map((p) => Math.max(p.value ?? 0, p.expected_high ?? 0)));
  const yMinRaw = Math.min(0, ...withValues.map((p) => Math.min(p.value ?? 0, p.expected_low ?? 0)));
  const yMax = niceY(yMaxRaw);
  const yMin = yMinRaw < 0 ? -niceY(-yMinRaw) : 0;

  const tMin = withValues.length ? new Date(withValues[0].ts).getTime() : Date.now();
  const tMax = withValues.length ? new Date(withValues[withValues.length - 1].ts).getTime() : Date.now();
  const tSpan = Math.max(1, tMax - tMin);
  const x = (tMs: number) => padL + ((tMs - tMin) / tSpan) * innerW;
  const y = (v: number) => padT + innerH * (1 - (v - yMin) / (yMax - yMin));

  const linePath = smoothPath(withValues.map((p) => [x(new Date(p.ts).getTime()), y(p.value!)]));

  // Real expected-range band -- only where both edges are non-null
  // (rolling window edges / too-few-real-points stretches have none,
  // see `get_demand_timeseries`'s own docstring), split into segments
  // so a gap in the band doesn't draw a straight line across it.
  const bandSegments: Array<Array<[number, number, number]>> = [];
  let current: Array<[number, number, number]> = [];
  for (const p of withValues) {
    if (p.expected_low !== null && p.expected_high !== null) {
      current.push([new Date(p.ts).getTime(), p.expected_low, p.expected_high]);
    } else if (current.length > 1) {
      bandSegments.push(current);
      current = [];
    } else {
      current = [];
    }
  }
  if (current.length > 1) bandSegments.push(current);

  const anomalousPoints = withValues.filter((p) => p.is_anomalous);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || withValues.length === 0) return;
    function onMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const svgX = (mx / rect.width) * w;
      let nearest = 0;
      let best = Infinity;
      for (let i = 0; i < withValues.length; i++) {
        const d = Math.abs(x(new Date(withValues[i].ts).getTime()) - svgX);
        if (d < best) { best = d; nearest = i; }
      }
      setHover({ x: mx, y: (e.clientY - rect.top), idx: nearest });
    }
    function onLeave() { setHover(null); }
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [withValues, tMin, tSpan]);

  if (withValues.length === 0) {
    return <p className="py-16 text-center text-xs text-white/40">No real data for this region/metric yet.</p>;
  }

  const hoverPoint = hover ? withValues[hover.idx] : null;

  return (
    <div ref={wrapRef} className="relative">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-72 w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
          const yy = padT + p * innerH;
          const labelVal = yMax - p * (yMax - yMin);
          return (
            <g key={`y-${i}`}>
              <line x1={padL} x2={w - padR} y1={yy} y2={yy} stroke="rgba(255,255,255,0.05)" strokeDasharray={i === 0 ? "" : "4 4"} />
              <text x={padL - 8} y={yy + 3} textAnchor="end" fontSize="11" fill="rgba(255,255,255,0.4)">
                {Math.round(labelVal).toLocaleString()}
              </text>
            </g>
          );
        })}
        <text x={padL - 44} y={padT - 6} fontSize="11" fill="rgba(255,255,255,0.55)">
          {metric === "price_mwh" ? "$/MWh" : "MW"}
        </text>

        {bandSegments.map((seg, i) => (
          <path
            key={`band-${i}`}
            d={smoothBandPath(
              seg.map(([t, , eh]) => [x(t), y(eh)]),
              seg.map(([t, el]) => [x(t), y(el)]),
            )}
            fill="rgba(255,255,255,0.08)"
            stroke="none"
          />
        ))}

        <path d={linePath} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />

        {anomalousPoints.map((p) => (
          <circle
            key={p.ts}
            cx={x(new Date(p.ts).getTime())}
            cy={y(p.value!)}
            r={3.5}
            fill={OVERVIEW_SEVERITY_COLOR[p.severity ?? "low"]}
            stroke="#0a1410"
            strokeWidth={1}
          />
        ))}

        {hover && hoverPoint && hoverPoint.value !== null && (
          <g>
            <line
              x1={x(new Date(hoverPoint.ts).getTime())}
              x2={x(new Date(hoverPoint.ts).getTime())}
              y1={padT}
              y2={padT + innerH}
              stroke="rgba(125,211,252,0.35)"
              strokeWidth={0.5}
              strokeDasharray="2 2"
            />
            <circle
              cx={x(new Date(hoverPoint.ts).getTime())}
              cy={y(hoverPoint.value)}
              r={4}
              fill="#0a1410"
              stroke="#7dd3fc"
              strokeWidth={2}
            />
          </g>
        )}
      </svg>

      {hover && hoverPoint && (
        <div
          className="pointer-events-none absolute z-20 min-w-[180px] -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-md border border-white/10 bg-[#0a1410]/95 px-3 py-2 text-xs shadow-2xl backdrop-blur"
          style={{ left: Math.min(Math.max(hover.x, 90), w - 90), top: hover.y }}
        >
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-white/50">
            {new Date(hoverPoint.ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-white/65">Value</span>
            <span className="font-mono font-semibold text-white">{hoverPoint.value?.toLocaleString()}</span>
          </div>
          {hoverPoint.expected_low !== null && hoverPoint.expected_high !== null && (
            <div className="flex items-center justify-between gap-3">
              <span className="text-white/65">Expected</span>
              <span className="font-mono text-white/80">
                {hoverPoint.expected_low.toFixed(0)} – {hoverPoint.expected_high.toFixed(0)}
              </span>
            </div>
          )}
          {hoverPoint.is_anomalous && (
            <div className="mt-1 flex items-center gap-1.5 text-rose-200">
              <AlertTriangle className="h-3 w-3" />
              {hoverPoint.severity} anomaly (score {hoverPoint.anomaly_score?.toFixed(2)})
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function smoothPath(pts: Array<[number, number]>, tension: number = 0.3): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  if (pts.length === 2) {
    return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)} L ${pts[1][0].toFixed(2)} ${pts[1][1].toFixed(2)}`;
  }
  const k = tension;
  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? pts[i + 1];
    const cp1x = p1[0] + ((p2[0] - p0[0]) * k) / 3;
    const cp1y = p1[1] + ((p2[1] - p0[1]) * k) / 3;
    const cp2x = p2[0] - ((p3[0] - p1[0]) * k) / 3;
    const cp2y = p2[1] - ((p3[1] - p1[1]) * k) / 3;
    d += ` C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)}, ${cp2x.toFixed(2)} ${cp2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

function smoothBandPath(topPts: Array<[number, number]>, botPts: Array<[number, number]>): string {
  if (topPts.length === 0 || botPts.length === 0) return "";
  const top = smoothPath(topPts);
  const bottomReversed = smoothPath([...botPts].reverse()).replace(/^M/, "L");
  return `${top} ${bottomReversed} Z`;
}

function niceY(v: number): number {
  if (v <= 0) return 100;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = (v / mag) * 1.1;
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (norm <= step) return step * mag;
  }
  return 10 * mag;
}
