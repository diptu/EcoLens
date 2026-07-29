/**
 * /dashboard/admin/system — system health.
 *
 * Component health, disk/memory, scheduler status, and a rolling
 * log of recent errors. Links out to the data-pipeline and
 * forecast-api admin endpoints.
 */
"use client";

import {
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  FileText,
  HardDrive,
  MemoryStick,
  Network,
  Server,
  ShieldCheck,
  Timer,
  Workflow,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  generateSystemHealth,
  type SystemHealth,
} from "@/lib/admin";

const COMPONENT_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  postgres: Database,
  mongodb: Database,
  redis: Network,
  mlflow: Workflow,
  dbt: FileText,
  model_loader: Cpu,
  scheduler: Timer,
};

export default function AdminSystemPage() {
  const health = generateSystemHealth();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">System</h1>
        <p className="mt-1 text-sm text-white/55">
          Component health, resource usage, scheduler, and recent error log.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-emerald-200/20 bg-emerald-300/5 px-4 py-3 text-sm text-emerald-100">
        <ShieldCheck className="h-4 w-4" />
        <strong>All systems operational</strong>
        <span className="text-white/50">·</span>
        <span className="font-mono text-white/70">
          uptime {Math.floor(health.uptime_seconds / 3600)}h
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <ComponentCard health={health} />
        <ResourcesCard health={health} />
      </div>

      <RecentErrorsCard errors={health.recent_errors} />
    </div>
  );
}

function ComponentCard({ health }: { health: SystemHealth }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Server className="h-4 w-4 text-emerald-200" />
          Components
        </span>
      }
      subtitle="Internal services the platform depends on."
    >
      <div className="space-y-2" data-testid="components">
        {Object.entries(health.components).map(([name, comp]) => {
          const Icon = COMPONENT_ICON[name] ?? Server;
          const healthy = comp.status === "healthy";
          return (
            <div
              key={name}
              className={cn(
                "rounded-md border p-3",
                healthy ? "border-white/5 bg-white/[0.02]" : "border-amber-400/20 bg-amber-500/5",
              )}
              data-testid={`component-row-${name}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-white/65" />
                  <span className="font-mono text-sm font-semibold text-white">{name}</span>
                  <span
                    className={cn(
                      "rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                      healthy
                        ? "border-emerald-200/30 bg-emerald-300/10 text-emerald-100"
                        : "border-amber-400/30 bg-amber-500/10 text-amber-200",
                    )}
                  >
                    {comp.status}
                  </span>
                </div>
                {comp.latency_ms != null && (
                  <span className="font-mono text-[11px] text-white/55">
                    {comp.latency_ms}ms
                  </span>
                )}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-white/55 md:grid-cols-3">
                {comp.pool_active != null && comp.pool_idle != null && (
                  <FieldInline label="pool" value={`${comp.pool_active} active / ${comp.pool_idle} idle`} />
                )}
                {comp.collections != null && (
                  <FieldInline label="collections" value={comp.collections.toString()} />
                )}
                {comp.keys != null && (
                  <FieldInline label="keys" value={comp.keys.toString()} />
                )}
                {comp.experiments != null && (
                  <FieldInline label="experiments" value={comp.experiments.toString()} />
                )}
                {comp.current_model != null && (
                  <FieldInline label="model" value={comp.current_model} />
                )}
                {comp.last_reload != null && (
                  <FieldInline
                    label="last reload"
                    value={new Date(comp.last_reload).toLocaleString("en-AU", {
                      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                    })}
                  />
                )}
                {comp.last_run != null && (
                  <FieldInline
                    label="last dbt run"
                    value={new Date(comp.last_run).toLocaleString("en-AU", {
                      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                    })}
                  />
                )}
                {comp.last_duration_s != null && (
                  <FieldInline label="dbt duration" value={`${comp.last_duration_s}s`} />
                )}
                {comp.queued_jobs != null && (
                  <FieldInline label="queued" value={comp.queued_jobs.toString()} />
                )}
                {comp.next_run != null && (
                  <FieldInline
                    label="next run"
                    value={new Date(comp.next_run).toLocaleString("en-AU", {
                      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                    })}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function FieldInline({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-white/40">{label}: </span>
      <span className="font-mono text-white/85">{value}</span>
    </div>
  );
}

function ResourcesCard({ health }: { health: SystemHealth }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <HardDrive className="h-4 w-4 text-emerald-200" />
          Resources
        </span>
      }
      subtitle="Disk, memory, scheduler state."
    >
      <div className="space-y-4">
        <ResourceBar
          icon={HardDrive}
          label="Disk"
          used={health.disk.used_gb}
          total={health.disk.total_gb}
          unit="GB"
          pct={health.disk.pct_used}
        />
        <ResourceBar
          icon={MemoryStick}
          label="Memory"
          used={health.memory.used_mb}
          total={health.memory.total_mb}
          unit="MB"
          pct={health.memory.pct_used}
        />
        <div className="rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs">
          <div className="flex items-center gap-2 text-white/55">
            <Activity className="h-3.5 w-3.5" /> Scheduler
          </div>
          <div className="mt-1 space-y-0.5 font-mono text-white/70">
            <div>
              next run:{" "}
              {new Date(health.components.scheduler.next_run!).toLocaleString("en-AU", {
                day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                timeZone: "Australia/Sydney",
              })}
            </div>
            <div>queued jobs: {health.components.scheduler.queued_jobs}</div>
          </div>
        </div>
        <div className="rounded-md border border-white/5 bg-white/[0.02] p-3 text-xs">
          <div className="flex items-center gap-2 text-white/55">
            <Timer className="h-3.5 w-3.5" /> Uptime
          </div>
          <div className="mt-1 font-mono text-white/70">
            {Math.floor(health.uptime_seconds / 3600)}h{" "}
            ({Math.floor(health.uptime_seconds / 86400)}d)
          </div>
        </div>
      </div>
    </Card>
  );
}

function ResourceBar({
  icon: Icon, label, used, total, unit, pct,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  used: number;
  total: number;
  unit: string;
  pct: number;
}) {
  const tone = pct >= 80 ? "rose" : pct >= 60 ? "amber" : "emerald";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5 text-white/55">
          <Icon className="h-3.5 w-3.5" /> {label}
        </div>
        <div className="font-mono text-white/85">
          {used} / {total} {unit}
          <span className={cn(
            "ml-2",
            tone === "rose"    && "text-rose-200",
            tone === "amber"   && "text-amber-200",
            tone === "emerald" && "text-emerald-100",
          )}>
            {pct}%
          </span>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/5">
        <div
          className={cn(
            "h-full transition-all",
            tone === "rose"    && "bg-rose-400",
            tone === "amber"   && "bg-amber-400",
            tone === "emerald" && "bg-emerald-200",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function RecentErrorsCard({
  errors,
}: {
  errors: SystemHealth["recent_errors"];
}) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-amber-300" />
          Recent errors
        </span>
      }
      subtitle="Last 24h, rolled up across all services."
    >
      <div className="space-y-2" data-testid="errors">
        {errors.map((e, i) => (
          <div
            key={i}
            className={cn(
              "rounded-md border p-3 text-xs",
              e.level === "ERROR" ? "border-rose-400/20 bg-rose-500/5" :
              e.level === "WARN"  ? "border-amber-400/20 bg-amber-500/5" :
              "border-white/5 bg-white/[0.02]",
            )}
            data-testid={`error-${i}`}
          >
            <div className="flex items-center gap-2">
              {e.level === "ERROR" ? (
                <AlertCircle className="h-3.5 w-3.5 text-rose-300" />
              ) : e.level === "WARN" ? (
                <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 text-white/45" />
              )}
              <span className={cn(
                "rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                e.level === "ERROR" ? "border-rose-400/30 text-rose-200" :
                e.level === "WARN"  ? "border-amber-400/30 text-amber-200" :
                "border-white/10 text-white/55",
              )}>
                {e.level}
              </span>
              <span className="font-mono text-white/65">{e.service}</span>
              <span className="ml-auto font-mono text-[10px] text-white/40">
                {new Date(e.ts).toLocaleString("en-AU", {
                  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                })}
              </span>
            </div>
            <p className="mt-1.5 text-white/75">{e.message}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}
