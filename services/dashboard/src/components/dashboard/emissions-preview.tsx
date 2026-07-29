/**
 * EmissionsPreview — small inline widget for the home page.
 *
 * Shows the last 24h of NEM-wide emissions as a sparkline, plus
 * a current "kgCO₂e per MWh" intensity KPI and a "View details"
 * link to /dashboard/carbon.
 *
 * Server-rendered (no "use client") so the SSR HTML matches the
 * initial client paint.
 */
import { ArrowUpRight, Factory, Gauge, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/dashboard/card";
import { Sparkline } from "@/components/dashboard/fan-chart";
import {
  formatIntensity,
  formatTco2e,
  generateMockEmissionsTimeseries,
  generateMockNationalEmissions,
  summarizeEmissions,
} from "@/lib/emissions";

export function EmissionsPreview() {
  const now = new Date();
  const since = new Date(now);
  since.setDate(since.getDate() - 1);
  const sinceIso = since.toISOString();
  const untilIso = now.toISOString();

  const national = generateMockNationalEmissions(sinceIso, untilIso, "scope2");
  const ts = generateMockEmissionsTimeseries("NSW1" as never, sinceIso, untilIso, "hour");
  const summary = summarizeEmissions(national, ts);

  const sparkValues = ts.points.map((p) => p.kgco2e);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Factory className="h-4 w-4 text-emerald-200" />
          Last 24h emissions · NEM-wide
        </span>
      }
      actions={
        <Link
          href="/dashboard/carbon/"
          className="inline-flex items-center gap-1 text-xs text-emerald-100 hover:text-emerald-100"
        >
          View details
          <ArrowUpRight className="h-3 w-3" />
        </Link>
      }
      data-testid="emissions-preview"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="md:col-span-1">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Total (Scope 2)
          </div>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-3xl font-bold text-white">
              {formatTco2e(national.total_kgco2e)}
            </span>
            <span className="text-sm text-white/50">CO₂e</span>
          </div>
          <div
            className={`mt-0.5 flex items-center gap-1 text-[11px] ${
              summary.vsPriorPct >= 0 ? "text-rose-300" : "text-emerald-100"
            }`}
          >
            {summary.vsPriorPct >= 0 ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {summary.vsPriorPct >= 0 ? "↑" : "↓"} {Math.abs(summary.vsPriorPct).toFixed(1)}% vs prior 24h
          </div>
          <div className="mt-2 text-[10px] text-white/40">
            across {national.regions.length} NEM regions + WEM
          </div>
        </div>

        <div className="flex items-center justify-center md:col-span-2">
          <Sparkline values={sparkValues} width={320} height={56} />
        </div>

        <div className="md:col-span-1 md:text-right">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Grid intensity
          </div>
          <div className="mt-1 flex items-baseline justify-end gap-1 md:justify-end">
            <span className="text-3xl font-bold text-white">
              {Math.round(national.intensity_kgco2e_per_mwh ?? 0)}
            </span>
            <span className="text-sm text-white/50">kg/MWh</span>
          </div>
          <div className="mt-0.5 flex items-center justify-end gap-1 text-[11px] text-white/55">
            <Gauge className="h-3 w-3" />
            {summary.renewablePct}% renewable share
          </div>
        </div>
      </div>
    </Card>
  );
}
