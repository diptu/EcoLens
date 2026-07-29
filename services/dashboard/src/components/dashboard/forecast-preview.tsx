/**
 * ForecastPreview — small inline widget for the home page.
 *
 * Shows the next 4 hours of NSW1 demand as a sparkline with a
 * single KPI (current P50) and a "View full forecast →" link to
 * /dashboard/forecast.
 *
 * Server-rendered (no "use client") — uses the deterministic
 * mock generator so the SSR'd HTML matches the client render
 * and the widget is visible in the initial paint.
 */
import { ArrowUpRight, Gauge, TrendingUp, Zap } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/dashboard/card";
import { Sparkline } from "@/components/dashboard/fan-chart";
import { generateMockForecast, summarize } from "@/lib/forecast";

export function ForecastPreview() {
  // 4 hours = 8 30-min steps; deterministic for the same render
  const forecast = generateMockForecast("NSW1", 8);
  const summary = summarize(forecast);
  const values = forecast.points.map((p) => p.p50);
  const first = values[0];
  const last = values[values.length - 1];
  const delta = last - first;
  const deltaPct = (delta / first) * 100;

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-emerald-200" />
          Next 4 hours · NSW1 demand
        </span>
      }
      actions={
        <Link
          href="/dashboard/forecast/"
          className="inline-flex items-center gap-1 text-xs text-emerald-100 hover:text-emerald-100"
        >
          View full forecast
          <ArrowUpRight className="h-3 w-3" />
        </Link>
      }
      data-testid="forecast-preview"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        {/* KPI: current P50 */}
        <div className="md:col-span-1">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Current (P50)
          </div>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-3xl font-bold text-white">{first.toFixed(0)}</span>
            <span className="text-sm text-white/50">MW</span>
          </div>
          <div
            className={`mt-0.5 flex items-center gap-1 text-[11px] ${
              deltaPct >= 0 ? "text-emerald-100" : "text-rose-300"
            }`}
          >
            <Zap className="h-3 w-3" />
            {deltaPct >= 0 ? "↑" : "↓"} {Math.abs(deltaPct).toFixed(1)}% over 4h
          </div>
          <div className="mt-2 text-[10px] text-white/40">
            <span className="inline-block h-0.5 w-2 align-middle bg-rose-300/80" /> P10{" "}
            {forecast.points[0].p10.toFixed(0)} ·{" "}
            <span className="inline-block h-0.5 w-2 align-middle bg-emerald-100/80" /> P90{" "}
            {forecast.points[0].p90.toFixed(0)}
          </div>
        </div>

        {/* Sparkline */}
        <div className="flex items-center justify-center md:col-span-2">
          <Sparkline values={values} width={320} height={56} />
        </div>

        {/* KPI: peak in horizon */}
        <div className="md:col-span-1 md:text-right">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Peak in next 4h
          </div>
          <div className="mt-1 flex items-baseline justify-end gap-1 md:justify-end">
            <span className="text-3xl font-bold text-white">{summary.peak.value.toFixed(0)}</span>
            <span className="text-sm text-white/50">MW</span>
          </div>
          <div className="mt-0.5 flex items-center justify-end gap-1 text-[11px] text-white/55">
            <Gauge className="h-3 w-3" />
            ±{summary.uncertaintyAtPeak.toFixed(0)} MW band
          </div>
        </div>
      </div>
    </Card>
  );
}
