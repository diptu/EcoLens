/**
 * /dashboard/admin/system — system health.
 *
 * Was 100% fabricated (`lib/admin.ts`'s `generateSystemHealth()` --
 * fixed fake uptime, a fake "mongodb" component this platform doesn't
 * even use anywhere, fake disk/memory numbers, fake error log). Rewired
 * 2026-08-08 (root TODO.md's "make every page fully functional with
 * real data") to `fetchAllServicesHealth()` (`lib/health.ts`) -- the
 * same real `/v1/readyz` checks `operational-tasks/page.tsx`'s System
 * Diagnostics card already uses, real for all 5 services (forecast-api/
 * data-pipeline/ingestion/warehouse/iam) with real per-component
 * (database/redis/rabbitmq/model) detail and a real single-sample
 * round-trip latency per check.
 *
 * Disk/memory usage and a rolling error log have no real backend
 * anywhere in this platform (no host-metrics endpoint, no centralized
 * log aggregation -- confirmed, same gap `operational-tasks/page.tsx`'s
 * own KPI row already discloses for "System Load") -- marked
 * `IllustrativeBadge` rather than silently kept as fabricated numbers.
 */
"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Clock,
  RefreshCw,
  Server,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { IllustrativeBadge } from "@/components/dashboard/illustrative-badge";
import { cn } from "@/lib/utils";
import { fetchAllServicesHealth, type ServiceHealth } from "@/lib/health";

export default function AdminSystemPage() {
  const [health, setHealth] = useState<ServiceHealth[] | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  function refresh() {
    setRefreshing(true);
    fetchAllServicesHealth()
      .then((results) => {
        setHealth(results);
        setCheckedAt(new Date().toISOString());
      })
      .catch(() => {})
      .finally(() => setRefreshing(false));
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  }, []);

  const allHealthy = health != null && health.every((h) => h.reachable && h.ready !== false);
  const anyUnreachable = health != null && health.some((h) => !h.reachable);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">System</h1>
          <p className="mt-1 text-sm text-white/55">
            Real per-service readiness from each service&apos;s own <code className="rounded bg-black/30 px-1 font-mono text-[11px]">/v1/readyz</code>.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium",
            refreshing
              ? "cursor-not-allowed border-white/10 bg-white/5 text-white/40"
              : "border-emerald-200/30 bg-emerald-200/10 text-emerald-100 hover:bg-emerald-200/15",
          )}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          Recheck
        </button>
      </div>

      {health === null ? (
        <p className="py-6 text-center text-xs text-white/40">Checking services…</p>
      ) : (
        <div
          className={cn(
            "flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm",
            anyUnreachable
              ? "border-rose-400/20 bg-rose-500/5 text-rose-200"
              : allHealthy
                ? "border-emerald-200/20 bg-emerald-300/5 text-emerald-100"
                : "border-amber-400/20 bg-amber-500/5 text-amber-200",
          )}
        >
          {anyUnreachable ? <XCircle className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
          <strong>
            {anyUnreachable
              ? `${health.filter((h) => !h.reachable).length}/${health.length} service(s) unreachable`
              : allHealthy
                ? "All services healthy"
                : "Some services not ready"}
          </strong>
          {checkedAt && (
            <>
              <span className="text-white/30">·</span>
              <span className="font-mono text-white/60">
                checked {new Date(checkedAt).toLocaleTimeString("en-AU")}
              </span>
            </>
          )}
        </div>
      )}

      <ComponentsCard health={health} />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <IllustrativeResourcesCard />
        <IllustrativeErrorsCard />
      </div>
    </div>
  );
}

function ComponentsCard({ health }: { health: ServiceHealth[] | null }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Server className="h-4 w-4 text-emerald-200" />
          Services
        </span>
      }
      subtitle="Real reachability/readiness/per-component detail from each service's own GET /v1/readyz."
    >
      {health === null ? (
        <p className="py-6 text-center text-xs text-white/40">Checking…</p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5" data-testid="components">
          {health.map((h) => {
            const tone = !h.reachable
              ? { dot: "bg-rose-400", border: "border-rose-300/30", label: "Unreachable", text: "text-rose-200" }
              : h.ready
                ? { dot: "bg-emerald-300", border: "border-emerald-200/30", label: "Healthy", text: "text-emerald-100" }
                : { dot: "bg-amber-300", border: "border-amber-300/30", label: "Not ready", text: "text-amber-200" };
            return (
              <div
                key={h.service}
                className={cn("rounded-md border bg-white/[0.02] p-3", tone.border)}
                data-testid={`component-row-${h.service}`}
              >
                <div className="mb-1.5 flex items-center gap-1.5">
                  <span className={cn("h-2 w-2 rounded-full", tone.dot)} />
                  <span className="font-mono text-sm font-semibold text-white">{h.service}</span>
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
                        <span
                          className={c.healthy ? "text-emerald-200/80" : "text-rose-300"}
                          title={c.detail ?? undefined}
                        >
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
      )}
    </Card>
  );
}

/** No host-metrics endpoint exists on any service (same gap
 * `operational-tasks/page.tsx`'s "System Load" KPI already discloses)
 * -- an honest illustrative shape preview, not fabricated live numbers. */
function IllustrativeResourcesCard() {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-amber-200" />
          Resources
        </span>
      }
      subtitle="Disk/memory usage — no host-metrics endpoint exists on any service yet."
      badge={<IllustrativeBadge />}
    >
      <p className="py-6 text-center text-xs text-white/40">
        Would show real disk/memory usage per service once a metrics endpoint exists.
        No fabricated numbers shown in the meantime.
      </p>
    </Card>
  );
}

/** No centralized log aggregation exists anywhere in this platform --
 * same honest-illustrative treatment. */
function IllustrativeErrorsCard() {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-amber-200" />
          Recent errors
        </span>
      }
      subtitle="Rolling error log — no centralized log aggregation exists across services yet."
      badge={<IllustrativeBadge />}
    >
      <p className="py-6 text-center text-xs text-white/40">
        Would show a real rolling error log across services once one exists.
        Each service&apos;s own structured logs are real today, just not aggregated here.
      </p>
    </Card>
  );
}
