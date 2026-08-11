/**
 * /dashboard/analytics — Energy Analytics (Australia).
 *
 * Full rebuild (2026-08-11) of what was previously an entirely mock page
 * (`ANALYTICS_KPIS`/`ANALYTICS_INDUSTRY`/`ANALYTICS_OPPORTUNITIES` from
 * `lib/data.ts`, a fabricated North America/Europe/Asia world map --
 * none of which correspond to anything this platform actually monitors,
 * a real Australian NEM+WEM grid-emissions dataset). Every number here
 * is real, from the same `forecast-api` endpoints the rest of this
 * dashboard already uses (`GET /v1/generation-mix`, `/v1/emissions/
 * timeseries`, `/v1/demand/summary`, `/v1/emissions/forecast`).
 *
 * Ported from a reference design (`analytics.png`) built for a generic
 * "Energy Analytics" SaaS template -- two things in that design don't
 * exist for real in this platform and are honestly re-scoped rather
 * than faked to match pixel-for-pixel:
 *   - "Emission Intensity ... tCO2e/$K" (revenue-based intensity) --
 *     this platform monitors a national grid, not a company's spend, so
 *     there's no real "revenue" to divide by. Shown instead as real
 *     grid carbon intensity (kgCO2e/MWh), the same unit "Carbon
 *     Intensity" already uses on the Executive Dashboard.
 *   - "Emissions Forecast" reaching monthly bars out to December --
 *     the only real forecast model in this platform is near-term
 *     (<=48h, confirmed repeatedly elsewhere in this codebase). The
 *     forecast section here is `RealEmissionsTrend` (already built,
 *     already real, already handles the Actual/Forecast continuity and
 *     gap-disclosure work) with this page's own title, not a fabricated
 *     multi-month projection.
 *   - "Reduction vs Baseline" (vs a fixed prior-year reference) --
 *     no declared baseline year exists anywhere in this platform
 *     (same reasoning `executive/page.tsx`'s own "Total CO₂e (MTD)"
 *     comment gives for why it has no YoY comparison either). Replaced
 *     with "Clean Energy Share", a real, independently useful MTD
 *     number, rather than inventing a baseline to compare against.
 *
 * All periods are real month-to-date (MTD) vs the preceding full
 * calendar month, computed client-side from real per-request date
 * ranges -- no interactive date-range picker (the reference design's
 * "May 1 - May 31" button): building one that actually re-queries every
 * section below is real, separate scope this pass doesn't cover, and a
 * decorative button that doesn't do anything would be worse than not
 * having it.
 */
"use client";

import { useEffect, useState } from "react";
import {
  Cloud,
  Gauge as GaugeIcon,
  DollarSign,
  Leaf,
  CalendarClock,
  Info,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DonutChart } from "@/components/dashboard/charts";
import { Sparkline } from "@/components/dashboard/fan-chart";
import { RealEmissionsTrend } from "@/components/dashboard/real-emissions-trend";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/ingestion";
import {
  fetchGenerationMix,
  fetchDemandSummary,
  fetchEmissionsTimeseries,
  fetchEmissionsForecast,
  formatFuelType,
  fuelColor,
  formatEnergy,
  ALL_EMISSION_REGIONS,
  type GenerationMix,
  type EmissionRegion,
} from "@/lib/emissions";

// ────────────────────────────────────────────────────────────────────
// Real region -> state label (`README.md`'s NEM/WEM region list) --
// WEM's own real coverage is the WA grid specifically (AEMO's separate
// West Australian market), the honest reason it maps to "WA" here
// rather than a literal "WEM".
// ────────────────────────────────────────────────────────────────────
const STATE_LABELS: Record<EmissionRegion, string> = {
  NSW1: "NSW",
  VIC1: "VIC",
  QLD1: "QLD",
  SA1: "SA",
  WEM: "WA",
  TAS1: "TAS",
};
const STATE_ORDER: EmissionRegion[] = ["NSW1", "VIC1", "QLD1", "SA1", "WEM", "TAS1"];

function monthRange(monthsAgo: number): { since: string; until: string; label: string } {
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - monthsAgo, 1));
  const end =
    monthsAgo === 0
      ? now
      : new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - monthsAgo + 1, 1));
  return {
    since: start.toISOString(),
    until: end.toISOString(),
    label: start.toLocaleDateString([], { month: "short", year: "numeric" }),
  };
}

function pctDelta(current: number, previous: number): number | null {
  if (!previous) return null;
  return ((current - previous) / previous) * 100;
}

function cleanShare(mix: GenerationMix): number {
  if (!mix.total_generation_mwh) return 0;
  const clean = mix.items
    .filter((i) => i.is_renewable)
    .reduce((s, i) => s + i.total_generation_mwh, 0);
  return (clean / mix.total_generation_mwh) * 100;
}

type LoadedAnalytics = {
  mtd: GenerationMix;
  prevMonth: GenerationMix;
  mtdLabel: string;
  prevMonthLabel: string;
  totalCost: number;
  prevTotalCost: number;
  forecastTotalTco2e: number | null;
  forecastHorizonLabel: string | null;
  forecastSparkline: number[];
  dailyEmissionsTco2e: number[];
  dailyIntensity: { label: string; value: number }[];
  dailyEmissionsLabels: string[];
  states: { region: EmissionRegion; label: string; kgPerMwh: number }[];
  heatmapMonths: string[];
  heatmapRows: { region: EmissionRegion; label: string; byMonth: number[] }[];
  generatedAt: string;
};

async function loadAnalytics(): Promise<LoadedAnalytics> {
  const mtdRange = monthRange(0);
  const prevRange = monthRange(1);

  const [mtd, prevMonth, demandSummary, prevDemandSummary, forecast, dailySeries] =
    await Promise.all([
      fetchGenerationMix(undefined, mtdRange.since, mtdRange.until),
      fetchGenerationMix(undefined, prevRange.since, prevRange.until),
      fetchDemandSummary(mtdRange.since, mtdRange.until),
      fetchDemandSummary(prevRange.since, prevRange.until),
      fetchEmissionsForecast().catch(() => null),
      // Real daily NEM-wide series -- 95 days comfortably covers this
      // month + the prior 2 full months for the heatmap below, however
      // far back this platform's real data actually reaches (a young
      // dataset just yields fewer real heatmap columns, not an error).
      fetchEmissionsTimeseries("day", 95),
    ]);

  const totalCost = (demandSummary.avg_price_mwh ?? 0) * mtd.total_generation_mwh;
  const prevTotalCost = (prevDemandSummary.avg_price_mwh ?? 0) * prevMonth.total_generation_mwh;

  const mtdStartMs = new Date(mtdRange.since).getTime();
  const dailyThisMonth = dailySeries.points.filter(
    (p) => new Date(p.bucket).getTime() >= mtdStartMs,
  );
  const dailyEmissionsTco2e = dailyThisMonth.map((p) =>
    Math.round((p.total_emissions_kgco2e ?? 0) / 1000),
  );
  const dailyEmissionsLabels = dailyThisMonth.map((p) =>
    new Date(p.bucket).toLocaleDateString([], { month: "short", day: "numeric" }),
  );
  const dailyIntensity = dailySeries.points.map((p) => ({
    label: new Date(p.bucket).toLocaleDateString([], { month: "short", day: "numeric" }),
    value: Math.round(p.intensity_kgco2e_per_mwh ?? 0),
  }));

  const forecastPoints = forecast?.points ?? [];
  const forecastTotalTco2e = forecast
    ? forecastPoints.reduce((s, p) => s + p.p50_kgco2e, 0) / 1000
    : null;
  const forecastSparkline = forecastPoints.map((p) => Math.round(p.p50_kgco2e / 1000));

  // Per-region real day series, one call per real NEM/WEM region --
  // backs both "State Comparison" (this month's own intensity) and the
  // heatmap below (grouped by real calendar month) from the same fetch,
  // not two separate round-trips per region.
  const perRegion = await Promise.all(
    ALL_EMISSION_REGIONS.map((region) =>
      fetchEmissionsTimeseries("day", 95, region)
        .then((series) => ({ region, series }))
        .catch(() => ({ region, series: null })),
    ),
  );

  const states = STATE_ORDER.map((region) => {
    const found = perRegion.find((r) => r.region === region);
    const pts = (found?.series?.points ?? []).filter(
      (p) => new Date(p.bucket).getTime() >= mtdStartMs,
    );
    const emissions = pts.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0);
    const generation = pts.reduce((s, p) => s + (p.total_generation_mwh ?? 0), 0);
    return {
      region,
      label: STATE_LABELS[region],
      kgPerMwh: generation ? emissions / generation : 0,
    };
  });

  // Real calendar months present across every region's own series,
  // newest 3 (or fewer, for a younger real dataset) -- a month with no
  // real data for a given region just reads as 0 in that cell, not a
  // fabricated fill-in.
  const monthKeySet = new Set<string>();
  for (const { series } of perRegion) {
    for (const p of series?.points ?? []) {
      const d = new Date(p.bucket);
      monthKeySet.add(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`);
    }
  }
  const heatmapMonths = [...monthKeySet].sort().slice(-3);
  const heatmapRows = STATE_ORDER.map((region) => {
    const found = perRegion.find((r) => r.region === region);
    const byMonth = heatmapMonths.map((key) => {
      const [y, m] = key.split("-").map(Number);
      const total = (found?.series?.points ?? [])
        .filter((p) => {
          const d = new Date(p.bucket);
          return d.getUTCFullYear() === y && d.getUTCMonth() + 1 === m;
        })
        .reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0);
      return Math.round(total / 1000);
    });
    return { region, label: STATE_LABELS[region], byMonth };
  });

  return {
    mtd,
    prevMonth,
    mtdLabel: mtdRange.label,
    prevMonthLabel: prevRange.label,
    totalCost,
    prevTotalCost,
    forecastTotalTco2e,
    forecastHorizonLabel: forecast?.horizon ?? null,
    forecastSparkline,
    dailyEmissionsTco2e,
    dailyIntensity,
    dailyEmissionsLabels,
    states,
    heatmapMonths,
    heatmapRows,
    generatedAt: new Date().toISOString(),
  };
}

export default function AnalyticsPage() {
  const [data, setData] = useState<LoadedAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadAnalytics()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalEmissionsTco2e = data ? data.mtd.total_emissions_kgco2e / 1000 : null;
  const prevTotalEmissionsTco2e = data ? data.prevMonth.total_emissions_kgco2e / 1000 : null;
  const intensity = data
    ? data.mtd.total_generation_mwh
      ? data.mtd.total_emissions_kgco2e / data.mtd.total_generation_mwh
      : 0
    : null;
  const prevIntensity = data
    ? data.prevMonth.total_generation_mwh
      ? data.prevMonth.total_emissions_kgco2e / data.prevMonth.total_generation_mwh
      : 0
    : null;
  const clean = data ? cleanShare(data.mtd) : null;
  const prevClean = data ? cleanShare(data.prevMonth) : null;

  const emissionsDeltaPct =
    totalEmissionsTco2e !== null && prevTotalEmissionsTco2e !== null
      ? pctDelta(totalEmissionsTco2e, prevTotalEmissionsTco2e)
      : null;
  const intensityDeltaPct =
    intensity !== null && prevIntensity !== null ? pctDelta(intensity, prevIntensity) : null;
  const costDeltaPct = data ? pctDelta(data.totalCost, data.prevTotalCost) : null;
  const cleanDeltaPct = clean !== null && prevClean !== null ? clean - prevClean : null;

  const topSource = data
    ? [...data.mtd.items].sort((a, b) => b.total_emissions_kgco2e - a.total_emissions_kgco2e)[0]
    : null;
  const maxStateIntensity = data ? Math.max(...data.states.map((s) => s.kgPerMwh), 1) : 1;
  const maxHeatmapValue = data
    ? Math.max(...data.heatmapRows.flatMap((r) => r.byMonth), 1)
    : 1;

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white md:text-3xl">Energy Analytics</h1>
          <p className="mt-1 text-sm text-white/60 max-w-2xl">
            Australia&apos;s real energy outlook and carbon insights — NEM + WEM, market time AEST
            (UTC+10)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70">
            <CalendarClock className="h-3.5 w-3.5" /> {data ? data.mtdLabel : "This month"} (MTD)
          </span>
        </div>
      </div>

      {error && (
        <p className="rounded-lg border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-xs text-rose-200">
          Unavailable — {error}
        </p>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <AnalyticsKpi
          icon={Cloud}
          label="Total Emissions"
          value={totalEmissionsTco2e !== null ? Math.round(totalEmissionsTco2e).toLocaleString() : "—"}
          unit="tCO₂e"
          deltaPct={emissionsDeltaPct}
          goodWhen="down"
          compareLabel={data?.prevMonthLabel}
          sparkline={data?.dailyEmissionsTco2e}
          sparkColor="rgba(52,211,153,0.9)"
        />
        <AnalyticsKpi
          icon={GaugeIcon}
          label="Emission Intensity"
          value={intensity !== null ? intensity.toFixed(2) : "—"}
          unit="kg/MWh"
          deltaPct={intensityDeltaPct}
          goodWhen="down"
          compareLabel={data?.prevMonthLabel}
          sparkline={data?.dailyIntensity.map((d) => d.value)}
          sparkColor="rgba(56,189,248,0.9)"
        />
        <AnalyticsKpi
          icon={DollarSign}
          label="Total Wholesale Cost"
          value={data ? `$${Math.round(data.totalCost / 1000).toLocaleString()}K` : "—"}
          deltaPct={costDeltaPct}
          goodWhen="down"
          compareLabel={data?.prevMonthLabel}
          info="Real avg wholesale price ($/MWh, GET /v1/demand/summary) × real total generation (MWh) for the period — not a metered bill."
        />
        <AnalyticsKpi
          icon={Leaf}
          label="Clean Energy Share"
          value={clean !== null ? clean.toFixed(1) : "—"}
          unit="%"
          deltaPct={cleanDeltaPct}
          deltaIsPoints
          goodWhen="up"
          compareLabel={data?.prevMonthLabel}
        />
        <AnalyticsKpi
          icon={CalendarClock}
          label="Forecasted Emissions"
          value={
            data?.forecastTotalTco2e !== null && data?.forecastTotalTco2e !== undefined
              ? Math.round(data.forecastTotalTco2e).toLocaleString()
              : "—"
          }
          unit="tCO₂e"
          compareLabel={data?.forecastHorizonLabel ? `next ${data.forecastHorizonLabel}` : undefined}
          sparkline={data?.forecastSparkline}
          sparkColor="rgba(125,211,252,0.9)"
          info="Real near-term demand-forecast-derived total (GET /v1/emissions/forecast) — this platform's only real forecast horizon, not a monthly projection."
        />
      </div>

      {/* Row 1 — Forecast + Emissions by Source */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RealEmissionsTrend title="Emissions Forecast (Australia)" />
        </div>
        <Card title="Emissions by Source (Australia)" subtitle={data ? data.mtdLabel : undefined}>
          {data ? (
            <div className="flex flex-col items-center">
              <DonutChart
                data={data.mtd.items.map((i) => ({
                  label: formatFuelType(i.fuel_type),
                  value: i.total_emissions_kgco2e,
                  color: fuelColor(i.fuel_type),
                }))}
                size={180}
                thickness={22}
                centerLabel={Math.round(data.mtd.total_emissions_kgco2e / 1000).toLocaleString()}
                centerSub="tCO₂e"
                formatTooltip={(label, value) => (
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">{label}</span>
                    <span className="ml-auto font-mono font-medium text-white">
                      {Math.round(value / 1000).toLocaleString()} tCO₂e
                    </span>
                  </div>
                )}
              />
              <div className="mt-4 w-full space-y-1.5 text-xs">
                {[...data.mtd.items]
                  .sort((a, b) => b.total_emissions_kgco2e - a.total_emissions_kgco2e)
                  .map((i) => (
                    <div key={i.fuel_type} className="flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: fuelColor(i.fuel_type) }}
                        />
                        <span className="text-white/70">{formatFuelType(i.fuel_type)}</span>
                      </span>
                      <span className="text-white">
                        {data.mtd.total_emissions_kgco2e
                          ? Math.round((i.total_emissions_kgco2e / data.mtd.total_emissions_kgco2e) * 100)
                          : 0}
                        %{" "}
                        <span className="text-white/40">
                          ({Math.round(i.total_emissions_kgco2e / 1000).toLocaleString()})
                        </span>
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          ) : (
            <p className="py-12 text-center text-xs text-white/40">Loading…</p>
          )}
        </Card>
      </div>

      {/* Row 2 — At a Glance + State Comparison + Generation Mix + Key Insights */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
        <Card title="Australia at a Glance" subtitle={data ? data.mtdLabel : undefined}>
          <div className="grid grid-cols-2 gap-4">
            <GlanceStat
              icon={Cloud}
              label="National Emissions"
              value={totalEmissionsTco2e !== null ? Math.round(totalEmissionsTco2e).toLocaleString() : "—"}
              unit="tCO₂e"
            />
            <GlanceStat
              icon={Leaf}
              label="Clean Energy Share"
              value={clean !== null ? clean.toFixed(0) : "—"}
              unit="%"
            />
            <GlanceStat
              icon={GaugeIcon}
              label="Avg Emission Intensity"
              value={intensity !== null ? intensity.toFixed(2) : "—"}
              unit="kg/MWh"
            />
            <GlanceStat
              icon={DollarSign}
              label="Total Wholesale Cost"
              value={data ? `$${Math.round(data.totalCost / 1000).toLocaleString()}K` : "—"}
            />
          </div>
        </Card>

        <Card title="State Comparison" subtitle="By emission intensity (kgCO₂e/MWh)">
          {data ? (
            <div className="space-y-2.5">
              {data.states.map((s) => (
                <div key={s.region} className="flex items-center gap-2 text-xs">
                  <span className="w-8 shrink-0 text-white/60">{s.label}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-lime-300/80"
                      style={{ width: `${Math.max(4, (s.kgPerMwh / maxStateIntensity) * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right font-mono text-white/80">
                    {s.kgPerMwh.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">Loading…</p>
          )}
        </Card>

        <Card title="Generation Mix (Australia)" subtitle="Share of generation">
          {data ? (
            <div className="flex flex-col items-center">
              <DonutChart
                data={data.mtd.items.map((i) => ({
                  label: formatFuelType(i.fuel_type),
                  value: i.total_generation_mwh,
                  color: fuelColor(i.fuel_type),
                }))}
                size={150}
                thickness={18}
                centerLabel={formatEnergy(data.mtd.total_generation_mwh)}
                formatTooltip={(label, value) => (
                  <div className="flex items-center gap-2">
                    <span className="text-white/65">{label}</span>
                    <span className="ml-auto font-mono font-medium text-white">
                      {formatEnergy(value)}
                    </span>
                  </div>
                )}
              />
              <div className="mt-3 w-full space-y-1 text-[11px]">
                {[...data.mtd.items]
                  .sort((a, b) => b.total_generation_mwh - a.total_generation_mwh)
                  .map((i) => (
                    <div key={i.fuel_type} className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ backgroundColor: fuelColor(i.fuel_type) }}
                        />
                        <span className="text-white/70">{formatFuelType(i.fuel_type)}</span>
                      </span>
                      <span className="text-white">{i.pct_of_total_generation.toFixed(0)}%</span>
                    </div>
                  ))}
              </div>
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">Loading…</p>
          )}
        </Card>

        <Card title="Key Insights">
          {data ? (
            <div className="space-y-3 text-xs">
              {emissionsDeltaPct !== null && (
                <Insight
                  tone={emissionsDeltaPct <= 0 ? "positive" : "negative"}
                  title={`Emissions ${emissionsDeltaPct <= 0 ? "down" : "up"} ${Math.abs(emissionsDeltaPct).toFixed(0)}%`}
                  body={`Total emissions vs ${data.prevMonthLabel}.`}
                />
              )}
              {cleanDeltaPct !== null && (
                <Insight
                  tone={cleanDeltaPct >= 0 ? "positive" : "negative"}
                  title={`Clean energy ${cleanDeltaPct >= 0 ? "growing" : "shrinking"}`}
                  body={`Renewables contributed ${clean!.toFixed(0)}% of generation this month.`}
                />
              )}
              {topSource && (
                <Insight
                  tone="warning"
                  title={`${formatFuelType(topSource.fuel_type)} remains the largest source`}
                  body={`${formatFuelType(topSource.fuel_type)} contributed ${
                    data.mtd.total_emissions_kgco2e
                      ? Math.round((topSource.total_emissions_kgco2e / data.mtd.total_emissions_kgco2e) * 100)
                      : 0
                  }% of emissions.`}
                />
              )}
              {data.forecastHorizonLabel && (
                <Insight
                  tone="default"
                  title="Forecast available"
                  body={`Real near-term forecast covers the next ${data.forecastHorizonLabel}.`}
                />
              )}
            </div>
          ) : (
            <p className="py-8 text-center text-xs text-white/40">Loading…</p>
          )}
        </Card>
      </div>

      {/* Row 3 — Intensity over time + Heatmap */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Emission Intensity Over Time (Australia)" subtitle="kgCO₂e/MWh, real daily readings">
          {data && data.dailyIntensity.length > 1 ? (
            <IntensityLineChart points={data.dailyIntensity} />
          ) : (
            <p className="py-16 text-center text-xs text-white/40">
              {data ? "Not enough real history yet." : "Loading…"}
            </p>
          )}
        </Card>

        <Card title="Emissions Heatmap (Australia)" subtitle="By state and month (tCO₂e)">
          {data && data.heatmapMonths.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-white/50">
                    <th className="pb-2 text-left font-medium">State</th>
                    {data.heatmapMonths.map((m) => (
                      <th key={m} className="pb-2 text-right font-medium">
                        {new Date(`${m}-01T00:00:00Z`).toLocaleDateString([], {
                          month: "short",
                          year: "numeric",
                        })}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.heatmapRows.map((row) => (
                    <tr key={row.region}>
                      <td className="py-1.5 text-white/70">{row.label}</td>
                      {row.byMonth.map((v, i) => (
                        <td
                          key={i}
                          className="py-1.5 text-right font-mono text-white"
                          style={{
                            backgroundColor: `rgba(52,211,153,${0.1 + 0.55 * (v / maxHeatmapValue)})`,
                          }}
                        >
                          {v.toLocaleString()}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr className="border-t border-white/10 font-semibold">
                    <td className="py-1.5 text-white/70">Total</td>
                    {data.heatmapMonths.map((_, i) => (
                      <td key={i} className="py-1.5 text-right font-mono text-white">
                        {data.heatmapRows.reduce((s, r) => s + r.byMonth[i], 0).toLocaleString()}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
              <div className="mt-3 flex items-center justify-end gap-2 text-[10px] text-white/50">
                Low
                <span
                  className="h-2 w-16 rounded-full"
                  style={{
                    background: "linear-gradient(90deg, rgba(52,211,153,0.1), rgba(52,211,153,0.65))",
                  }}
                />
                High
              </div>
            </div>
          ) : (
            <p className="py-16 text-center text-xs text-white/40">
              {data ? "Not enough real history yet." : "Loading…"}
            </p>
          )}
        </Card>
      </div>

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-4 text-[11px] text-white/40">
        <span>All metrics include Australia (NEM + WEM) only.</span>
        <span>
          Data refreshed:{" "}
          {data ? formatRelativeTime(data.generatedAt) : "—"}
        </span>
        <span>Source: AEMO, Clean Energy Regulator, NGER</span>
      </p>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Small bits
// ────────────────────────────────────────────────────────────────────

function AnalyticsKpi({
  icon: Icon,
  label,
  value,
  unit,
  deltaPct,
  deltaIsPoints,
  goodWhen,
  compareLabel,
  sparkline,
  sparkColor,
  info,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  unit?: string;
  deltaPct?: number | null;
  /** When true, `deltaPct` is already a real percentage-point delta
   * (e.g. clean-share moved from 41% to 44%, a real +3 pts), not a
   * relative % change of `value` itself -- different real math,
   * different honest label ("pts" not "%"). */
  deltaIsPoints?: boolean;
  goodWhen?: "up" | "down";
  compareLabel?: string;
  sparkline?: number[];
  sparkColor?: string;
  info?: string;
}) {
  const isGood =
    deltaPct == null || !goodWhen
      ? null
      : goodWhen === "down"
        ? deltaPct <= 0
        : deltaPct >= 0;
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
      <div className="flex items-center justify-between">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-emerald-200/10 text-emerald-100">
          <Icon className="h-4 w-4" />
        </span>
        {info && (
          <span title={info}>
            <Info className="h-3.5 w-3.5 text-white/30" />
          </span>
        )}
      </div>
      <p className="mt-2 text-xs font-medium text-white/60">{label}</p>
      <div className="mt-1 flex items-baseline gap-1.5">
        <p className="text-xl font-bold text-white md:text-2xl">{value}</p>
        {unit && <p className="text-xs text-white/50">{unit}</p>}
      </div>
      <div className="mt-1 flex items-center gap-1 text-[11px]">
        {deltaPct != null && (
          <span className={cn("font-medium", isGood ? "text-emerald-200" : "text-rose-300")}>
            {deltaPct >= 0 ? "↑" : "↓"} {Math.abs(deltaPct).toFixed(deltaIsPoints ? 1 : 0)}
            {deltaIsPoints ? " pts" : "%"}
          </span>
        )}
        {compareLabel && <span className="text-white/40">vs {compareLabel}</span>}
      </div>
      {sparkline && sparkline.length > 1 && (
        <Sparkline values={sparkline} width={140} height={28} color={sparkColor} className="mt-2 w-full" />
      )}
    </div>
  );
}

function GlanceStat({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/10 bg-white/5 text-emerald-100">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide text-white/45">{label}</p>
        <p className="truncate text-sm font-semibold text-white">
          {value} {unit && <span className="text-[10px] font-normal text-white/50">{unit}</span>}
        </p>
      </div>
    </div>
  );
}

function Insight({
  tone,
  title,
  body,
}: {
  tone: "positive" | "negative" | "warning" | "default";
  title: string;
  body: string;
}) {
  const color =
    tone === "positive"
      ? "text-emerald-200"
      : tone === "negative"
        ? "text-rose-300"
        : tone === "warning"
          ? "text-amber-200"
          : "text-sky-200";
  return (
    <div>
      <p className={cn("font-semibold", color)}>{title}</p>
      <p className="mt-0.5 text-white/55">{body}</p>
    </div>
  );
}

function IntensityLineChart({ points }: { points: { label: string; value: number }[] }) {
  const w = 700;
  const h = 220;
  const padL = 40;
  const padR = 12;
  const padT = 10;
  const padB = 24;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const max = Math.max(...points.map((p) => p.value), 1);
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0;
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + innerH * (1 - v / max);
  const linePts = points.map((p, i): [number, number] => [x(i), y(p.value)]);
  const line = linePts.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L ${x(points.length - 1).toFixed(1)} ${padT + innerH} L ${x(0).toFixed(1)} ${padT + innerH} Z`;
  const labelEvery = points.length > 20 ? 5 : points.length > 10 ? 2 : 1;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-56 w-full">
      {[0, 0.5, 1].map((f, i) => (
        <line
          key={i}
          x1={padL}
          x2={w - padR}
          y1={padT + f * innerH}
          y2={padT + f * innerH}
          stroke="rgba(255,255,255,0.05)"
        />
      ))}
      <path d={area} fill="rgba(132,204,22,0.12)" stroke="none" />
      <path d={line} fill="none" stroke="rgba(132,204,22,0.95)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      {points.map(
        (p, i) =>
          i % labelEvery === 0 && (
            <text key={i} x={x(i)} y={h - 6} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.4)">
              {p.label}
            </text>
          ),
      )}
    </svg>
  );
}
