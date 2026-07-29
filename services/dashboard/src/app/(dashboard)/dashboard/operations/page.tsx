/**
 * /dashboard/operations — Operations Dashboard (Ops Manager view)
 */
"use client";

import { useMemo } from "react";
import { Activity, Server, Cpu, AlertTriangle, Check } from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { SectionPage } from "@/components/dashboard/section-page";
import { getOpsKpis, getOpsPipelines, getOpsServices } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

export default function OperationsDashboardPage() {
  const kpis = useMemo(() => getOpsKpis(), []);
  const pipelines = useMemo(() => getOpsPipelines(), []);
  const services = useMemo(() => getOpsServices(), []);

  return (
    <SectionPage
      icon={<Server className="h-6 w-6" />}
      title="Operations Dashboard"
      description="Ops Manager view: pipeline health, service uptime, ingestion status."
      tabs={[
        { id: "overview",   label: "Overview"   },
        { id: "pipelines",  label: "Pipelines"  },
        { id: "services",   label: "Services"   },
        { id: "incidents",  label: "Incidents"  },
      ]}
      defaultTab="overview"
      kpis={kpis}
      panels={{
        overview: (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <h2 className="mb-3 text-base font-semibold text-white">Active Pipelines</h2>
              <ul className="space-y-1.5 text-sm">
                {pipelines.slice(0, 4).map((p) => (
                  <li key={p.id} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                    <span className="text-white/85">{p.name}</span>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-white/50">{p.last_run}</span>
                      <HealthChip health={p.health} />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h2 className="mb-3 text-base font-semibold text-white">Service Health</h2>
              <ul className="space-y-1.5 text-sm">
                {services.slice(0, 4).map((s) => (
                  <li key={s.name} className="flex items-center justify-between rounded-md border border-white/5 bg-white/[0.02] p-2.5">
                    <span className="text-white/85">{s.name}</span>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-white/50">{s.latency_p95}</span>
                      <HealthChip health={s.status} />
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        ),
        pipelines: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">All Pipelines</h2>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Pipeline</th>
                  <th className="py-2">Last Run</th>
                  <th className="py-2">Records</th>
                  <th className="py-2">Health</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {pipelines.map((p) => (
                  <tr key={p.id} className="text-white/85">
                    <td className="py-2">{p.name}</td>
                    <td className="py-2 text-white/60">{p.last_run}</td>
                    <td className="py-2 text-white/60 tabular-nums">{p.records_today.toLocaleString()}</td>
                    <td className="py-2"><HealthChip health={p.health} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ),
        services: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Service Components</h2>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/5 text-[11px] uppercase tracking-wide text-white/40">
                <tr>
                  <th className="py-2">Service</th>
                  <th className="py-2">Uptime</th>
                  <th className="py-2">P95 Latency</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {services.map((s) => (
                  <tr key={s.name} className="text-white/85">
                    <td className="py-2">{s.name}</td>
                    <td className="py-2 text-white/60">{s.uptime}</td>
                    <td className="py-2 text-white/60">{s.latency_p95}</td>
                    <td className="py-2"><HealthChip health={s.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ),
        incidents: (
          <Card>
            <h2 className="mb-3 text-base font-semibold text-white">Recent Incidents</h2>
            <p className="text-sm text-white/70">No active incidents. See the Alert Rules section for threshold configuration.</p>
          </Card>
        ),
      }}
    />
  );
}

function HealthChip({ health }: { health: string }) {
  const map: Record<string, string> = {
    healthy:  "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
    degraded: "border-amber-300/40 bg-amber-300/10 text-amber-200",
    down:     "border-rose-300/40 bg-rose-300/10 text-rose-200",
    failed:   "border-rose-300/40 bg-rose-300/10 text-rose-200",
    success:  "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
    running:  "border-cyan-300/40 bg-cyan-300/10 text-cyan-200",
    queued:   "border-amber-300/40 bg-amber-300/10 text-amber-200",
  };
  return (
    <span className={cn("rounded-md border px-2 py-0.5 text-[11px] font-medium", map[health] ?? "border-white/10 bg-white/5 text-white/60")}>
      {health}
    </span>
  );
}
