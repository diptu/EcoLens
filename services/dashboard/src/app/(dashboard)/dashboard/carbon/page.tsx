/**
 * /dashboard/carbon — GHG emissions analytics.
 *
 * Real data from forecast-api:
 *   GET /v1/emissions/timeseries?bucket=&days=&region=
 *   GET /v1/generation-mix?region=&since=&until=
 *   GET /v1/emissions/forecast?region=
 *
 * No mock fallback on fetch failure (same policy as the Ingestion and
 * Executive Dashboard pages once they were wired to real data) — an
 * honest "—"/empty state beats silently reintroducing fabricated
 * numbers under the guise of "offline fallback".
 *
 * Layout:
 *   ┌─ Header (title) ────────────────────────────────────────┐
 *   ├─ Period selector (24h / 7d / 30d / 90d / 365d) ─────────┤
 *   ├─ Region selector (NEM (all) / 6 NEM+WEM regions) ───────┤
 *   ├─ KPI row: Total tCO₂e · Intensity · Renewables · Δ ─────┤
 *   ├─ Two-col: Timeseries line chart (left) + Fuel donut (right) ─┤
 *   ├─ Region table (6 NEM regions, vs-NEM-average column) ───┤
 *   ├─ Forecast projection (near-term emissions) ─────────────┤
 *   └─ Methodology footnote (real per-fuel effective factors) ─┘
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  BookOpen,
  ChevronDown,
  Factory,
  Gauge,
  Leaf,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DonutChart, LineChart } from "@/components/dashboard/charts";
import { cn } from "@/lib/utils";
import {
  ALL_EMISSION_REGIONS,
  fetchEmissionsForecast,
  fetchEmissionsTimeseries,
  fetchGenerationMix,
  formatFuelType,
  formatIntensity,
  formatTco2e,
  fuelColor,
  type EmissionRegion,
  type EmissionsForecast,
  type GenerationMix,
  type LiveEmissionsTimeseries,
} from "@/lib/emissions";

type Period = "24h" | "7d" | "30d" | "90d" | "365d";

// Real backend bucketing only supports "hour"/"day" (no "month") --
// 90d/365d just get daily granularity instead of monthly, which is more
// data points but still honest, unlike the old mock's fabricated
// monthly aggregation.
const PERIODS: { value: Period; label: string; bucket: "hour" | "day"; days: number }[] = [
  { value: "24h",  label: "Last 24h", bucket: "hour", days: 1   },
  { value: "7d",   label: "Last 7d",  bucket: "day",  days: 7   },
  { value: "30d",  label: "Last 30d", bucket: "day",  days: 30  },
  { value: "90d",  label: "Last 90d", bucket: "day",  days: 90  },
  { value: "365d", label: "Last 12m", bucket: "day",  days: 365 },
];

type RegionRow = {
  region: EmissionRegion;
  energy_mwh: number;
  emissions_kgco2e: number;
  intensity_kgco2e_per_mwh: number | null;
  share_of_nem_pct: number;
  renewable_pct: number | null;
  vs_nem_avg: "cleaner" | "dirtier" | "even";
};

export default function EmissionsPage() {
  const [period, setPeriod] = useState<Period>("7d");
  const [region, setRegion] = useState<EmissionRegion | "NEM">("NEM");
  const [showMethodology, setShowMethodology] = useState(false);

  const periodDef = PERIODS.find((p) => p.value === period)!;

  const { since, until } = useMemo(() => {
    const u = new Date();
    const s = new Date(u.getTime() - periodDef.days * 86_400_000);
    return { since: s.toISOString(), until: u.toISOString() };
  }, [periodDef.days]);

  const [timeseries, setTimeseries] = useState<LiveEmissionsTimeseries | null>(null);
  const [nemMix, setNemMix] = useState<GenerationMix | null>(null);
  const [regionMixes, setRegionMixes] = useState<Record<EmissionRegion, GenerationMix> | null>(null);
  const [forecast, setForecast] = useState<EmissionsForecast | null>(null);

  // Fuel-mix data (donut + region table + methodology factors) depends
  // only on the period, not the region selector -- the table always
  // shows all 6 regions, and the donut just picks one of these results.
  useEffect(() => {
    let cancelled = false;
    fetchGenerationMix(undefined, since, until)
      .then((mix) => {
        if (!cancelled) setNemMix(mix);
      })
      .catch(() => {});
    Promise.all(
      ALL_EMISSION_REGIONS.map(
        async (r) => [r, await fetchGenerationMix(r, since, until)] as const,
      ),
    )
      .then((entries) => {
        if (cancelled) return;
        setRegionMixes(
          Object.fromEntries(entries) as Record<EmissionRegion, GenerationMix>,
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [since, until]);

  // Timeseries drives the chart + "vs prior period" KPI. Fetches
  // *double* the selected period's days in one call and splits the
  // result in half client-side (older half = prior period, newer half
  // = current) rather than a second request -- the real endpoint only
  // takes a relative `days` window (days-ago-to-now), not an arbitrary
  // absolute since/until, so there's no way to ask for "the period
  // immediately before this one" directly.
  useEffect(() => {
    let cancelled = false;
    fetchEmissionsTimeseries(
      periodDef.bucket,
      periodDef.days * 2,
      region === "NEM" ? undefined : region,
    )
      .then((ts) => {
        if (!cancelled) setTimeseries(ts);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [periodDef.bucket, periodDef.days, region]);

  // Forecast is region-aware but not period-aware (it's always the
  // model's own native near-term horizon, a few hours -- see the
  // heading below, which reports the real horizon rather than a
  // hardcoded "24h").
  useEffect(() => {
    let cancelled = false;
    fetchEmissionsForecast(region)
      .then((f) => {
        if (!cancelled) setForecast(f);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [region]);

  const { currentPoints, priorPoints } = useMemo(() => {
    if (!timeseries) return { currentPoints: null, priorPoints: null };
    const half = Math.floor(timeseries.points.length / 2);
    return {
      currentPoints: timeseries.points.slice(half),
      priorPoints: timeseries.points.slice(0, half),
    };
  }, [timeseries]);

  const currentTotals = useMemo(() => {
    if (!currentPoints || currentPoints.length === 0) return null;
    return {
      emissions: currentPoints.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0),
      generation: currentPoints.reduce((s, p) => s + (p.total_generation_mwh ?? 0), 0),
    };
  }, [currentPoints]);

  const vsPriorPct = useMemo(() => {
    if (!currentTotals || !priorPoints || priorPoints.length === 0) return null;
    const priorEmissions = priorPoints.reduce((s, p) => s + (p.total_emissions_kgco2e ?? 0), 0);
    if (priorEmissions <= 0) return null;
    return ((currentTotals.emissions - priorEmissions) / priorEmissions) * 100;
  }, [currentTotals, priorPoints]);

  const peakTrough = useMemo(() => {
    if (!currentPoints || currentPoints.length === 0) return null;
    let peak = currentPoints[0], trough = currentPoints[0];
    for (const p of currentPoints) {
      if ((p.total_emissions_kgco2e ?? -Infinity) > (peak.total_emissions_kgco2e ?? -Infinity)) peak = p;
      if ((p.total_emissions_kgco2e ?? Infinity) < (trough.total_emissions_kgco2e ?? Infinity)) trough = p;
    }
    return { peak, trough };
  }, [currentPoints]);

  const donutMix = region === "NEM" ? nemMix : (regionMixes?.[region] ?? null);

  const renewablePct = useMemo(() => {
    if (!donutMix || donutMix.total_generation_mwh <= 0) return null;
    const renewableGen = donutMix.items
      .filter((i) => i.is_renewable)
      .reduce((s, i) => s + i.total_generation_mwh, 0);
    return (renewableGen / donutMix.total_generation_mwh) * 100;
  }, [donutMix]);

  const regionRows = useMemo((): RegionRow[] | null => {
    if (!regionMixes || !nemMix) return null;
    const nemAvgIntensity =
      nemMix.total_generation_mwh > 0
        ? nemMix.total_emissions_kgco2e / nemMix.total_generation_mwh
        : null;
    return ALL_EMISSION_REGIONS.map((r) => {
      const mix = regionMixes[r];
      const intensity =
        mix.total_generation_mwh > 0
          ? mix.total_emissions_kgco2e / mix.total_generation_mwh
          : null;
      const renewableGen = mix.items
        .filter((i) => i.is_renewable)
        .reduce((s, i) => s + i.total_generation_mwh, 0);
      let vsNemAvg: RegionRow["vs_nem_avg"] = "even";
      if (intensity != null && nemAvgIntensity != null) {
        if (intensity < nemAvgIntensity * 0.97) vsNemAvg = "cleaner";
        else if (intensity > nemAvgIntensity * 1.03) vsNemAvg = "dirtier";
      }
      return {
        region: r,
        energy_mwh: mix.total_generation_mwh,
        emissions_kgco2e: mix.total_emissions_kgco2e,
        intensity_kgco2e_per_mwh: intensity,
        share_of_nem_pct:
          nemMix.total_emissions_kgco2e > 0
            ? (mix.total_emissions_kgco2e / nemMix.total_emissions_kgco2e) * 100
            : 0,
        renewable_pct: mix.total_generation_mwh > 0 ? (renewableGen / mix.total_generation_mwh) * 100 : null,
        vs_nem_avg: vsNemAvg,
      };
    });
  }, [regionMixes, nemMix]);

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white">Emissions</h1>
            <a
              href="/dashboard/carbon/methodology/"
              data-testid="carbon-methodology-link"
              className="inline-flex items-center gap-1 rounded-full border border-emerald-200/20 bg-emerald-300/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-100 transition-colors hover:bg-emerald-300/20 hover:text-emerald-100"
            >
              <BookOpen className="h-3 w-3" /> How is this calculated?
            </a>
          </div>
          <p className="mt-1 text-sm text-white/55">
            Scope 2 (location-based) grid emissions from the ecoLens
            warehouse, per NEM/WEM region.{" "}
            <Link href="/dashboard/carbon/methodology/" className="text-emerald-100 hover:text-emerald-100 underline-offset-2 hover:underline">
              See the full calculation chain →
            </Link>
          </p>
        </div>
        <div className="text-right text-xs text-white/40">
          <div>
            <span className="text-white/30">period:</span>{" "}
            <span className="font-mono text-white/70">{periodDef.label}</span>
          </div>
          <div>
            <span className="text-white/30">region:</span>{" "}
            <span className="font-mono text-white/70">{region}</span>
          </div>
        </div>
      </div>

      {/* ── Period + Region selectors ───────────────────────── */}
      <Card>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Period
            </div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Period">
              {PERIODS.map((p) => {
                const active = p.value === period;
                return (
                  <button
                    key={p.value}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setPeriod(p.value)}
                    data-testid={`period-${p.value}`}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-lime-100 text-black"
                        : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                    )}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Region
            </div>
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Region">
              <button
                type="button"
                role="tab"
                aria-selected={region === "NEM"}
                onClick={() => setRegion("NEM")}
                data-testid="region-NEM"
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  region === ("NEM" as EmissionRegion)
                    ? "bg-emerald-200 text-black"
                    : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                )}
              >
                NEM (all)
              </button>
              {ALL_EMISSION_REGIONS.map((r) => {
                const active = r === region;
                return (
                  <button
                    key={r}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setRegion(r)}
                    data-testid={`region-${r}`}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                      active
                        ? "bg-emerald-200 text-black"
                        : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                    )}
                  >
                    {r}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      {/* ── KPI row ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi
          icon={Factory}
          label="Total emissions"
          value={currentTotals ? formatTco2e(currentTotals.emissions) : "—"}
          hint={periodDef.label}
        />
        <Kpi
          icon={Gauge}
          label="Grid intensity"
          value={currentTotals?.generation ? formatIntensity((currentTotals.emissions / currentTotals.generation)) : "—"}
          hint="kgCO₂e per MWh served"
        />
        <Kpi
          icon={Leaf}
          label="Renewable share"
          value={renewablePct != null ? `${renewablePct.toFixed(1)}%` : "—"}
          hint="based on grid generation mix"
        />
        <Kpi
          icon={vsPriorPct == null || vsPriorPct >= 0 ? TrendingUp : TrendingDown}
          label="vs prior period"
          value={vsPriorPct != null ? `${vsPriorPct >= 0 ? "+" : ""}${vsPriorPct.toFixed(1)}%` : "—"}
          hint={vsPriorPct == null ? "no prior-period data yet" : vsPriorPct >= 0 ? "higher than last period" : "lower than last period"}
          tone={vsPriorPct == null ? undefined : vsPriorPct >= 0 ? "up" : "down"}
        />
      </div>

      {/* ── Timeseries + Fuel donut ──────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-200" />
              {region} emissions · {periodDef.label}
            </span>
          }
        >
          <LineChart
            series={[
              {
                name: "kgCO₂e",
                data: (currentPoints ?? []).map((p) => p.total_emissions_kgco2e ?? 0),
                color: "rgba(132,204,22,0.95)",
                fill: true,
              },
            ]}
            labels={(currentPoints ?? []).map((p, i, arr) => {
              const stride = Math.max(1, Math.floor(arr.length / 6));
              if (i === 0 || i === arr.length - 1 || i % stride === 0) {
                return new Date(p.bucket).toLocaleDateString("en-AU", {
                  day: "2-digit",
                  month: "short",
                });
              }
              return "";
            })}
            height={240}
          />
          {peakTrough && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/45">
              <div>
                Peak: {new Date(peakTrough.peak.bucket).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
                {formatTco2e(peakTrough.peak.total_emissions_kgco2e)}
              </div>
              <div>
                Trough: {new Date(peakTrough.trough.bucket).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
                {formatTco2e(peakTrough.trough.total_emissions_kgco2e)}
              </div>
            </div>
          )}
        </Card>

        <Card title="Fuel mix" subtitle="Grid electricity">
          <div className="flex flex-col items-center gap-3">
            <DonutChart
              data={(donutMix?.items.slice(0, 6) ?? []).map((f) => ({
                label: formatFuelType(f.fuel_type),
                value: f.total_emissions_kgco2e,
                color: fuelColor(f.fuel_type),
              }))}
              size={170}
              thickness={20}
              centerLabel={donutMix ? formatTco2e(donutMix.total_emissions_kgco2e) : "—"}
              centerSub="kgCO₂e"
            />
            <div className="w-full space-y-1.5">
              {(donutMix?.items.slice(0, 6) ?? []).map((f) => (
                <div key={f.fuel_type} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: fuelColor(f.fuel_type) }} />
                    <span className="text-white/70">{formatFuelType(f.fuel_type)}</span>
                  </span>
                  <span className="text-white">
                    {f.pct_of_total_generation.toFixed(0)}%{" "}
                    <span className="text-white/40">({formatTco2e(f.total_emissions_kgco2e)})</span>
                  </span>
                </div>
              ))}
              {donutMix == null && (
                <p className="text-center text-xs text-white/40">No fuel mix data available.</p>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* ── Region table ────────────────────────────────────── */}
      <Card title="Per-region emissions" subtitle={`${periodDef.label} · Scope 2 (location-based)`}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="emissions-region-table">
            <thead>
              <tr className="border-b border-white/5 text-left text-[10px] uppercase tracking-wider text-white/40">
                <th className="px-3 py-2">Region</th>
                <th className="px-3 py-2 text-right">Energy (MWh)</th>
                <th className="px-3 py-2 text-right">tCO₂e (Scope 2)</th>
                <th className="px-3 py-2 text-right">kgCO₂e / MWh</th>
                <th className="px-3 py-2 text-right">Share of NEM</th>
                <th className="px-3 py-2 text-right">Renewable %</th>
                <th className="px-3 py-2 text-right">vs NEM avg</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {regionRows == null ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center font-sans text-white/40">
                    No region data available — is forecast-api running?
                  </td>
                </tr>
              ) : (
                regionRows.map((r) => (
                  <tr
                    key={r.region}
                    className="border-t border-white/5 transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-3 py-2 font-sans text-white">{r.region}</td>
                    <td className="px-3 py-2 text-right text-white/80">
                      {Math.round(r.energy_mwh).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-right text-lime-100">
                      {(r.emissions_kgco2e / 1000).toFixed(1)}
                    </td>
                    <td className="px-3 py-2 text-right text-white/80">
                      {r.intensity_kgco2e_per_mwh != null ? Math.round(r.intensity_kgco2e_per_mwh) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-white/80">{r.share_of_nem_pct.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right text-emerald-100">
                      {r.renewable_pct != null ? `${r.renewable_pct.toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={cn(
                          "rounded-md border px-2 py-0.5 text-[10px] font-medium font-sans",
                          r.vs_nem_avg === "cleaner" && "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
                          r.vs_nem_avg === "dirtier" && "border-rose-300/40 bg-rose-300/10 text-rose-200",
                          r.vs_nem_avg === "even" && "border-white/10 bg-white/5 text-white/60",
                        )}
                      >
                        {r.vs_nem_avg}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
            {nemMix && (
              <tfoot>
                <tr className="border-t-2 border-white/10 bg-white/[0.02] font-sans text-sm font-semibold">
                  <td className="px-3 py-3 text-white">NEM (total)</td>
                  <td className="px-3 py-3 text-right text-white">
                    {Math.round(nemMix.total_generation_mwh).toLocaleString()}
                  </td>
                  <td className="px-3 py-3 text-right text-lime-100">
                    {formatTco2e(nemMix.total_emissions_kgco2e)}
                  </td>
                  <td className="px-3 py-3 text-right text-white">
                    {nemMix.total_generation_mwh > 0
                      ? Math.round(nemMix.total_emissions_kgco2e / nemMix.total_generation_mwh)
                      : "—"}
                  </td>
                  <td className="px-3 py-3 text-right text-white">100%</td>
                  <td className="px-3 py-3 text-right text-emerald-100">
                    {(() => {
                      const renewableGen = nemMix.items
                        .filter((i) => i.is_renewable)
                        .reduce((s, i) => s + i.total_generation_mwh, 0);
                      return nemMix.total_generation_mwh > 0
                        ? `${((renewableGen / nemMix.total_generation_mwh) * 100).toFixed(0)}%`
                        : "—";
                    })()}
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>

      {/* ── Forecast projection ─────────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-emerald-200" />
            {forecast ? `Next ${forecast.horizon} emissions projection` : "Emissions projection"}
          </span>
        }
        actions={
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/55">
            {region}
          </span>
        }
      >
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <LineChart
              series={[
                {
                  name: forecast ? `kgCO₂e / ${forecast.interval}` : "kgCO₂e",
                  data: (forecast?.points ?? []).map((p) => p.p50_kgco2e),
                  color: "rgba(168,85,247,0.95)",
                  fill: true,
                },
              ]}
              labels={(forecast?.points ?? []).map((p, i, arr) => {
                const stride = Math.max(1, Math.floor(arr.length / 6));
                if (i === 0 || i === arr.length - 1 || i % stride === 0) {
                  return new Date(p.ts).toLocaleTimeString("en-AU", {
                    hour: "2-digit",
                    minute: "2-digit",
                    timeZone: "Australia/Sydney",
                  });
                }
                return "";
              })}
              height={200}
            />
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Projected total
              </div>
              <div className="mt-1 text-2xl font-bold text-white">
                {forecast ? formatTco2e(forecast.points.reduce((s, p) => s + p.p50_kgco2e, 0)) : "—"}
              </div>
              <div className="text-[10px] text-white/40">{forecast ? `next ${forecast.horizon}` : "—"}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Method
              </div>
              <p className="mt-1 text-[11px] text-white/55">
                Demand forecast (P10/P50/P90) × the region&apos;s current
                carbon intensity, held constant across the horizon —
                not a learned emissions model. Intensity can shift within
                the horizon (e.g. solar dropping off at dusk), so this is
                a near-term approximation, from{" "}
                <code className="rounded bg-black/30 px-1 font-mono text-lime-100">GET /v1/emissions/forecast</code>.
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* ── Methodology footnote ────────────────────────────── */}
      <button
        type="button"
        onClick={() => setShowMethodology((s) => !s)}
        className="flex w-full items-center gap-2 rounded-md border border-white/5 bg-white/[0.02] px-3 py-2 text-xs text-white/55 transition-colors hover:bg-white/5"
        aria-expanded={showMethodology}
        data-testid="methodology-toggle"
      >
        <ChevronDown className={cn("h-3 w-3 transition-transform", !showMethodology && "-rotate-90")} />
        Quick methodology &amp; emission factors{" "}
        <a
          href="/dashboard/carbon/methodology/"
          className="ml-auto text-emerald-100 hover:text-emerald-100"
        >
          Open the full methodology page →
        </a>
      </button>
      {showMethodology && (
        <Card>
          <div className="space-y-3 text-xs text-white/60">
            <div>
              <h4 className="text-sm font-semibold text-white">Scope 2 (location-based)</h4>
              <p className="mt-1">
                Energy served × grid intensity at the point of
                consumption, generation-weighted (<code className="rounded bg-black/30 px-1 font-mono text-lime-100">sum(emissions) / sum(generation)</code>{" "}
                over the period, not a plain average of each interval's
                already-weighted intensity). Reported per region from the
                warehouse&apos;s <code className="rounded bg-black/30 px-1 font-mono text-lime-100">fct_carbon_intensity</code> mart.
              </p>
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Effective emission factors this period</h4>
              <p className="mt-1 text-white/40">
                Derived from real generation + emissions totals per fuel
                (kgCO₂e ÷ MWh, {periodDef.label.toLowerCase()}, NEM-wide) — not a
                static lookup table.
              </p>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-3">
                {nemMix?.items.map((f) => (
                  <div key={f.fuel_type} className="flex items-center justify-between border-b border-white/5 py-1">
                    <span className="font-mono text-white/55">{formatFuelType(f.fuel_type)}</span>
                    <span className="font-mono text-white/80">
                      {f.total_generation_mwh > 0
                        ? Math.round(f.total_emissions_kgco2e / f.total_generation_mwh)
                        : "—"}
                    </span>
                  </div>
                ))}
                {nemMix == null && <p className="text-white/40">No data available.</p>}
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Data sources</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-white/55">
                <li>AEMO NEM dispatch (5-min, resampled to 30-min)</li>
                <li>AEMO WEM market data (30-min)</li>
                <li>BoM weather observations (hourly, 6 stations)</li>
                <li>OpenElectricity generation mix (5-min NEM, 30-min WEM)</li>
                <li>AEMO public holidays calendar (annual snapshot)</li>
              </ul>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            {label}
          </div>
          <div className="mt-1 text-xl font-bold text-white">{value}</div>
          {hint && <div className="mt-0.5 text-[10px] text-white/40">{hint}</div>}
        </div>
        <Icon
          className={cn(
            "h-4 w-4",
            tone === "up" && "text-rose-400",
            tone === "down" && "text-emerald-200",
            !tone && "text-white/40",
          )}
        />
      </div>
    </Card>
  );
}
