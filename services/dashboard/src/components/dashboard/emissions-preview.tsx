/**
 * EmissionsPreview — small inline widget for the home page.
 *
 * Shows the last hour's NEM-wide emissions total, a 24h sparkline, and
 * the current grid intensity (kgCO₂e/MWh) — real data from
 * forecast-api's `GET /v1/emissions/current` and
 * `GET /v1/emissions/timeseries` (`lib/emissions.ts`), same endpoints
 * the Executive Dashboard already uses. No "vs prior period" delta or
 * renewable-share figure here — neither endpoint exposes them, and
 * this widget doesn't fabricate numbers to fill the gap.
 *
 * Async Server Component (no "use client") — fetched at request time,
 * not client-side, so there's no loading flash on the home page.
 */
import { ArrowUpRight, Factory, Gauge } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/dashboard/card";
import { Sparkline } from "@/components/dashboard/fan-chart";
import { fetchCurrentEmissions, fetchEmissionsTimeseries, formatIntensity, formatTco2e } from "@/lib/emissions";

export async function EmissionsPreview() {
  const [current, ts] = await Promise.all([
    fetchCurrentEmissions().catch(() => null),
    fetchEmissionsTimeseries("hour", 1).catch(() => null),
  ]);

  const sparkValues = ts?.points.map((p) => p.total_emissions_kgco2e ?? 0) ?? [];

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Factory className="h-4 w-4 text-emerald-200" />
          Emissions · NEM-wide
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
            Total (this hour)
          </div>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-3xl font-bold text-white">
              {formatTco2e(current?.total_emissions_kgco2e)}
            </span>
            <span className="text-sm text-white/50">CO₂e</span>
          </div>
        </div>

        <div className="flex items-center justify-center md:col-span-2">
          <Sparkline values={sparkValues} width={320} height={56} />
        </div>

        <div className="md:col-span-1 md:text-right">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Grid intensity
          </div>
          <div className="mt-1 flex items-center justify-end gap-1 text-3xl font-bold text-white">
            <Gauge className="h-4 w-4 text-white/50" />
            {formatIntensity(current?.intensity_kgco2e_per_mwh)}
          </div>
        </div>
      </div>
    </Card>
  );
}
