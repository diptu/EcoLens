/**
 * /dashboard/operations — Operations Dashboard (Ops Manager view)
 *
 * Real data where it exists, honest placeholders where it doesn't:
 *   forecast-api /v1/readyz, data-pipeline /v1/readyz, ingestion
 *     /v1/readyz (added 2026-08-07), warehouse /v1/readyz (added
 *     alongside the training-code migration follow-up pass), IAM /
 *     + /db_health (lib/health.ts)
 *   GET /v1/model (lib/emissions.ts, forecast-api)
 *   GET /v1/data-sources (lib/data-sources.ts, ingestion) — real
 *     per-source health/schedule, replaces the old static
 *     `PIPELINE_CATALOG` (real source names, but no live status) now
 *     that a deliberately open (no auth) `GET /v1/data-sources` exists
 *     on `services/ingestion` — see that endpoint's own docstring in
 *     `api/v1/datasources/routes.py`.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { Server } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { SectionPage } from "@/components/dashboard/section-page";
import { cn } from "@/lib/utils";
import { fetchPublicDataSources, healthDotStatus, type DataSource } from "@/lib/data-sources";
import { fetchModelInfo, type ModelInfo } from "@/lib/emissions";
import { fetchAllServicesHealth, type ServiceHealth } from "@/lib/health";

export default function OperationsDashboardPage() {
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
  const [servicesHealth, setServicesHealth] = useState<ServiceHealth[] | null>(null);
  const [sources, setSources] = useState<DataSource[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchModelInfo()
      .then((r) => {
        if (!cancelled) setModelInfo(r);
      })
      .catch(() => {});
    // IAM (services/iam) is no longer building, so it's filtered out of
    // this page's Service Health grid -- `lib/health.ts`'s
    // `fetchAllServicesHealth` is left as-is (still used elsewhere).
    fetchAllServicesHealth().then((r) => {
      if (!cancelled) setServicesHealth(r.filter((s) => s.service !== "iam"));
    });
    fetchPublicDataSources()
      .then((r) => {
        if (!cancelled) setSources(r.data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const kpis = useMemo(() => {
    const healthyCount = servicesHealth?.filter((s) => s.ready).length ?? null;
    const healthySourceCount = sources?.filter((s) => s.health.status === "healthy").length ?? null;
    return [
      {
        label: "Ingestion Pipelines",
        value: sources ? `${sources.length}` : "…",
        sub: healthySourceCount != null ? `${healthySourceCount} healthy` : "trigger from Ingestion Pipeline page",
      },
      {
        label: "Model Status",
        value: modelInfo ? (modelInfo.status === "loaded" ? "OK" : "not loaded") : "—",
        sub: modelInfo?.stage ? `${modelInfo.name}@${modelInfo.stage}` : modelInfo?.name,
      },
      {
        label: "Services Healthy",
        value: healthyCount != null ? `${healthyCount}/${servicesHealth!.length}` : "…",
        sub: servicesHealth
          ?.filter((s) => !s.ready)
          .map((s) => s.service)
          .join(", ") || (healthyCount != null ? "all ready" : undefined),
      },
    ];
  }, [modelInfo, servicesHealth, sources]);

  return (
    <SectionPage
      icon={<Server className="h-6 w-6" />}
      title="Operations Dashboard"
      description="Ops Manager view: service readiness and the ingestion pipeline inventory."
      tabs={[
        { id: "overview",   label: "Overview"   },
        { id: "services",   label: "Services"   },
      ]}
      defaultTab="overview"
      kpis={kpis}
      panels={{
        overview: (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-base font-semibold text-white">Ingestion Pipelines</h2>
              {sources === null ? (
                <p className="text-sm text-white/40">Loading…</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {sources.map((s) => (
                    <li key={s.id} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                      <span className="flex items-center gap-2 text-white/85">
                        <SourceDot status={healthDotStatus(s.health.status)} />
                        {s.name}
                      </span>
                      <span className="text-[11px] text-white/40">{s.schedule.cadence}</span>
                    </li>
                  ))}
                </ul>
              )}
              <a
                href="/dashboard/data-sources/"
                className="mt-3 inline-flex w-full items-center justify-center gap-1 text-xs text-emerald-100 hover:underline"
              >
                Trigger or monitor runs on the Data Sources page
              </a>
            </Card>
            <Card>
              <h2 className="mb-3 text-base font-semibold text-white">Service Health</h2>
              {servicesHealth === null ? (
                <p className="text-sm text-white/40">Checking…</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {servicesHealth.map((s) => (
                    <li key={s.service} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                      <span className="text-white/85">{s.service}</span>
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="text-white/50">
                          {s.latencyMs != null ? `${s.latencyMs}ms` : "—"}
                        </span>
                        <HealthChip health={s.reachable ? (s.ready ? "healthy" : "down") : "unreachable"} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        ),
        services: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Service Components</h2>
            {servicesHealth === null ? (
              <p className="py-6 text-center text-sm text-white/40">Checking service health…</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                  <tr>
                    <th className="py-2">Service</th>
                    <th className="py-2">Components</th>
                    <th className="py-2">Latency (this check)</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {servicesHealth.map((s) => (
                    <tr key={s.service} className="text-white/85">
                      <td className="py-2">{s.service}</td>
                      <td className="py-2">
                        {s.components.length === 0 ? (
                          <span className="text-white/40">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {s.components.map((c) => (
                              <span
                                key={c.name}
                                title={c.detail ?? undefined}
                                className={cn(
                                  "rounded-md border px-1.5 py-0.5 text-[10px] font-medium",
                                  c.healthy
                                    ? "border-emerald-200/30 bg-emerald-200/10 text-emerald-100"
                                    : "border-rose-300/30 bg-rose-500/10 text-rose-200",
                                )}
                              >
                                {c.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="py-2 text-white/60">{s.latencyMs != null ? `${s.latencyMs}ms` : "—"}</td>
                      <td className="py-2">
                        <HealthChip health={s.reachable ? (s.ready ? "healthy" : "down") : "unreachable"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ),
      }}
    />
  );
}

function SourceDot({ status }: { status: "healthy" | "degraded" | "down" | "unknown" }) {
  const map = {
    healthy:  "bg-emerald-200",
    degraded: "bg-amber-400",
    down:     "bg-rose-400",
    unknown:  "bg-white/40",
  } as const;
  return <span className={cn("h-2 w-2 rounded-full", map[status])} title={status} />;
}

function HealthChip({ health }: { health: string }) {
  const map: Record<string, string> = {
    healthy:     "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
    degraded:    "border-amber-300/40 bg-amber-300/10 text-amber-200",
    down:        "border-rose-300/40 bg-rose-300/10 text-rose-200",
    unreachable: "border-rose-300/40 bg-rose-300/10 text-rose-200",
    failed:      "border-rose-300/40 bg-rose-300/10 text-rose-200",
    success:     "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
    running:     "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
    queued:      "border-amber-300/40 bg-amber-300/10 text-amber-200",
    paused:      "border-white/10 bg-white/5 text-white/60",
    idle:        "border-white/10 bg-white/5 text-white/60",
  };
  return (
    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", map[health] ?? "border-white/10 bg-white/5 text-white/60")}>
      {health}
    </span>
  );
}
