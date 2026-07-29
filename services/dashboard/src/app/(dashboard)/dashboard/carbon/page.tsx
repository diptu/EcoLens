/**
 * /dashboard/emissions — GHG emissions analytics.
 *
 * In production this calls the emissions-api:
 *   GET /v1/emissions/national
 *   GET /v1/emissions/regions/{region}?scope=scope2
 *   GET /v1/emissions/timeseries?region=...&bucket=day
 *   GET /v1/emissions/breakdown?region=...&by=fuel
 *   GET /v1/emissions/forecast?region=...&horizon_hours=24
 *
 * For the demo we use the deterministic mock generator in
 * `@/lib/emissions`, which matches the API response shape exactly.
 *
 * Layout:
 *   ┌─ Header (title, period badge, source badge) ──────────┐
 *   ├─ Period selector (24h / 7d / 30d / 90d / custom) ─────┤
 *   ├─ KPI row: Total tCO₂e · Intensity · Renewables · Δ ───┤
 *   ├─ Two-col: Timeseries line chart (left) + Fuel donut (right) ─┤
 *   ├─ Region table (sortable, 6 NEM regions) ──────────────┤
 *   ├─ Forecast projection (next 24h emissions) ────────────┤
 *   └─ Methodology footnote + link to API docs ──────────────┘
 */
"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  Calendar,
  ChevronDown,
  Cloud,
  Factory,
  Gauge,
  Leaf,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Wind,
  Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { DonutChart, LineChart } from "@/components/dashboard/charts";
import { Sparkline } from "@/components/dashboard/fan-chart";
import { cn } from "@/lib/utils";
import {
  ALL_EMISSION_REGIONS,
  EMISSION_FACTORS,
  formatEnergy,
  formatIntensity,
  formatTco2e,
  generateMockEmissionForecast,
  generateMockEmissionsTimeseries,
  generateMockFuelBreakdown,
  generateMockNationalEmissions,
  summarizeEmissions,
  type EmissionRegion,
  type TimeBucket,
} from "@/lib/emissions";

type Period = "24h" | "7d" | "30d" | "90d" | "365d";

const PERIODS: { value: Period; label: string; bucket: TimeBucket }[] = [
  { value: "24h",  label: "Last 24h", bucket: "hour"  },
  { value: "7d",   label: "Last 7d",  bucket: "day"   },
  { value: "30d",  label: "Last 30d", bucket: "day"   },
  { value: "90d",  label: "Last 90d", bucket: "month" },
  { value: "365d", label: "Last 12m", bucket: "month" },
];

export default function EmissionsPage() {
  const [period, setPeriod] = useState<Period>("7d");
  const [region, setRegion] = useState<EmissionRegion | "NEM">("NEM");
  const [showMethodology, setShowMethodology] = useState(false);

  const periodDef = PERIODS.find((p) => p.value === period)!;

  // Generate data deterministically for the chosen period
  const { since, until } = useMemo(() => {
    const u = new Date();
    const s = new Date(u);
    if (period === "24h")      s.setHours(s.getHours() - 24);
    else if (period === "7d")  s.setDate(s.getDate() - 7);
    else if (period === "30d") s.setDate(s.getDate() - 30);
    else if (period === "90d") s.setDate(s.getDate() - 90);
    else                       s.setDate(s.getDate() - 365);
    return { since: s.toISOString(), until: u.toISOString() };
  }, [period]);

  const national = useMemo(
    () => generateMockNationalEmissions(since, until, "scope2"),
    [since, until],
  );
  const fuelBreakdown = useMemo(() => {
    // "NEM" tab shows an aggregate fuel mix (average across regions)
    if (region === "NEM") {
      return ALL_EMISSION_REGIONS.map((r) => generateMockFuelBreakdown(r, since, until))
        .reduce((acc, fb) => {
          for (const item of fb.items) {
            const existing = acc.items.find((i) => i.fuel === item.fuel);
            if (existing) {
              existing.kgco2e += item.kgco2e;
            } else {
              acc.items.push({ ...item });
            }
          }
          acc.total_kgco2e += fb.total_kgco2e;
          return acc;
        }, { region: "NEM" as EmissionRegion, since, until, by: "fuel" as const, items: [] as { fuel: string; kgco2e: number; percent: number }[], total_kgco2e: 0 });
    }
    return generateMockFuelBreakdown(region, since, until);
  }, [region, since, until]);

  const timeseries = useMemo(() => {
    if (region === "NEM") {
      // Aggregate across all regions
      const all = ALL_EMISSION_REGIONS.map((r) =>
        generateMockEmissionsTimeseries(r, since, until, periodDef.bucket),
      );
      const first = all[0];
      return {
        ...first,
        region: "NEM" as EmissionRegion,
        points: first.points.map((p, i) => ({
          ...p,
          kgco2e: all.reduce((s, ts) => s + ts.points[i].kgco2e, 0),
          mwh: all.reduce((s, ts) => s + ts.points[i].mwh, 0),
        })),
      };
    }
    return generateMockEmissionsTimeseries(region, since, until, periodDef.bucket);
  }, [region, since, until, periodDef.bucket]);
  const summary = useMemo(() => summarizeEmissions(national, timeseries), [national, timeseries]);
  const forecast = useMemo(() => {
    if (region === "NEM") {
      const all = ALL_EMISSION_REGIONS.map((r) => generateMockEmissionForecast(r, 24));
      const first = all[0];
      return {
        ...first,
        region: "NEM" as EmissionRegion,
        total_kgco2e: all.reduce((s, f) => s + f.total_kgco2e, 0),
        total_tco2e: all.reduce((s, f) => s + f.total_tco2e, 0),
        points: first.points.map((p, i) => ({
          ...p,
          demand_mw: all.reduce((s, f) => s + f.points[i].demand_mw, 0),
          kgco2e: all.reduce((s, f) => s + f.points[i].kgco2e, 0),
        })),
      };
    }
    return generateMockEmissionForecast(region, 24);
  }, [region]);

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white">Emissions</h1>
            <span
              data-testid="emissions-source"
              className="rounded-full border border-amber-400/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-300"
            >
              mock
            </span>
            <a
              href="/dashboard/carbon/methodology/"
              data-testid="carbon-methodology-link"
              className="inline-flex items-center gap-1 rounded-full border border-emerald-200/20 bg-emerald-300/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-100 transition-colors hover:bg-emerald-300/20 hover:text-emerald-100"
            >
              <BookOpen className="h-3 w-3" /> How is this calculated?
            </a>
          </div>
          <p className="mt-1 text-sm text-white/55">
            Scope 1 (fuel-attributed) and Scope 2 (location-based) emissions
            from the ecoLens warehouse, per NEM/WEM region.{" "}
            <a href="/dashboard/emissions/methodology/" className="text-emerald-100 hover:text-emerald-100 underline-offset-2 hover:underline">
              See the full calculation chain →
            </a>
          </p>
        </div>
        <div className="text-right text-xs text-white/40">
          <div>
            <span className="text-white/30">period:</span>{" "}
            <span className="font-mono text-white/70">{summary.period}</span>
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
          value={formatTco2e(national.total_kgco2e)}
          hint={summary.period}
        />
        <Kpi
          icon={Gauge}
          label="Grid intensity"
          value={formatIntensity(national.intensity_kgco2e_per_mwh)}
          hint="kgCO₂e per MWh served"
        />
        <Kpi
          icon={Leaf}
          label="Renewable share"
          value={`${summary.renewablePct}%`}
          hint="based on grid intensity"
        />
        <Kpi
          icon={summary.vsPriorPct >= 0 ? TrendingUp : TrendingDown}
          label="vs prior period"
          value={`${summary.vsPriorPct >= 0 ? "+" : ""}${summary.vsPriorPct.toFixed(1)}%`}
          hint={summary.vsPriorPct >= 0 ? "higher than last period" : "lower than last period"}
          tone={summary.vsPriorPct >= 0 ? "up" : "down"}
        />
      </div>

      {/* ── Timeseries + Fuel donut ──────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-200" />
              {region} emissions · {summary.period}
            </span>
          }
        >
          <LineChart
            series={[
              {
                name: "kgCO₂e",
                data: timeseries.points.map((p) => p.kgco2e),
                color: "rgba(132,204,22,0.95)",
                fill: true,
              },
            ]}
            labels={timeseries.points.map((p, i) => {
              const stride = Math.max(1, Math.floor(timeseries.points.length / 6));
              if (i === 0 || i === timeseries.points.length - 1 || i % stride === 0) {
                return new Date(p.ts).toLocaleDateString("en-AU", {
                  day: "2-digit",
                  month: "short",
                });
              }
              return "";
            })}
            height={240}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/45">
            <div>
              Peak: {new Date(summary.peakHour.ts).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
              {formatTco2e(summary.peakHour.kgco2e)}
            </div>
            <div>
              Trough: {new Date(summary.troughHour.ts).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
              {formatTco2e(summary.troughHour.kgco2e)}
            </div>
          </div>
        </Card>

        <Card title="Fuel mix" subtitle="Scope 1 attribution">
          <div className="flex flex-col items-center gap-3">
            <DonutChart
              data={fuelBreakdown.items.slice(0, 6).map((f) => {
                const color = fuelColor(f.fuel);
                return { label: f.fuel, value: f.kgco2e, color };
              })}
              size={170}
              thickness={20}
              centerLabel={formatTco2e(fuelBreakdown.total_kgco2e)}
              centerSub="kgCO₂e"
            />
            <div className="w-full space-y-1.5">
              {fuelBreakdown.items.slice(0, 6).map((f) => (
                <div key={f.fuel} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: fuelColor(f.fuel) }} />
                    <span className="text-white/70">{fuelLabel(f.fuel)}</span>
                  </span>
                  <span className="text-white">
                    {f.percent.toFixed(0)}%{" "}
                    <span className="text-white/40">({formatTco2e(f.kgco2e)})</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* ── Region table ────────────────────────────────────── */}
      <Card title="Per-region emissions" subtitle={`${summary.period} · Scope 2 (location-based)`}>
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
                <th className="px-3 py-2 text-right">Trend</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {national.regions.map((r) => {
                const sharePct = (r.scope2_kgco2e! / national.total_scope2_kgco2e) * 100;
                const renewablePct = 100 - ((r.intensity_kgco2e_per_mwh ?? 0) / 800) * 100;
                return (
                  <tr
                    key={r.region}
                    className="border-t border-white/5 transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-3 py-2 font-sans text-white">{r.region}</td>
                    <td className="px-3 py-2 text-right text-white/80">
                      {Math.round(r.energy_mwh).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-right text-lime-100">
                      {((r.scope2_kgco2e ?? 0) / 1000).toFixed(1)}
                    </td>
                    <td className="px-3 py-2 text-right text-white/80">
                      {Math.round(r.intensity_kgco2e_per_mwh ?? 0)}
                    </td>
                    <td className="px-3 py-2 text-right text-white/80">{sharePct.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right text-emerald-100">
                      {Math.max(0, Math.min(100, Math.round(renewablePct)))}%
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Sparkline
                        values={generateMockEmissionsTimeseries(
                          r.region as EmissionRegion,
                          since,
                          until,
                          periodDef.bucket,
                        )
                          .points.slice(-12)
                          .map((p) => p.kgco2e)}
                        width={70}
                        height={20}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-white/10 bg-white/[0.02] font-sans text-sm font-semibold">
                <td className="px-3 py-3 text-white">NEM (total)</td>
                <td className="px-3 py-3 text-right text-white">
                  {Math.round(national.total_energy_mwh).toLocaleString()}
                </td>
                <td className="px-3 py-3 text-right text-lime-100">
                  {formatTco2e(national.total_scope2_kgco2e)}
                </td>
                <td className="px-3 py-3 text-right text-white">
                  {Math.round(national.intensity_kgco2e_per_mwh ?? 0)}
                </td>
                <td className="px-3 py-3 text-right text-white">100%</td>
                <td className="px-3 py-3 text-right text-emerald-100">
                  {summary.renewablePct}%
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      {/* ── Forecast projection ─────────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-emerald-200" />
            Next 24h emissions projection
          </span>
        }
        actions={
          <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/55">
            {region} · {forecast.source}
          </span>
        }
      >
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <LineChart
              series={[
                {
                  name: "kgCO₂e / 30min",
                  data: forecast.points.map((p) => p.kgco2e),
                  color: "rgba(168,85,247,0.95)",
                  fill: true,
                },
              ]}
              labels={forecast.points.map((p, i) => {
                const stride = Math.max(1, Math.floor(forecast.points.length / 6));
                if (i === 0 || i === forecast.points.length - 1 || i % stride === 0) {
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
                {formatTco2e(forecast.total_kgco2e)}
              </div>
              <div className="text-[10px] text-white/40">next 24 hours</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Method
              </div>
              <p className="mt-1 text-[11px] text-white/55">
                Combines the live demand forecast (or last-week-same-hour
                baseline) with each region&apos;s typical grid intensity. In
                production this comes from the emissions-api&apos;s{" "}
                <code className="rounded bg-black/30 px-1 font-mono text-lime-100">/v1/emissions/forecast</code>{" "}
                endpoint.
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
          href="/dashboard/emissions/methodology/"
          className="ml-auto text-emerald-100 hover:text-emerald-100"
        >
          Open the full methodology page →
        </a>
      </button>
      {showMethodology && (
        <Card>
          <div className="space-y-3 text-xs text-white/60">
            <div>
              <h4 className="text-sm font-semibold text-white">Scope 1 vs Scope 2</h4>
              <p className="mt-1">
                <strong>Scope 2 (location-based):</strong> energy served × grid
                intensity at the point of consumption. Reported per region from
                the warehouse&apos;s <code className="rounded bg-black/30 px-1 font-mono text-lime-100">emissions_intensity_kgco2e_per_mwh</code> column.
              </p>
              <p className="mt-1">
                <strong>Scope 1 (fuel-attributed):</strong> re-computed from
                the generation mix using published lifecycle factors. Useful
                for attributing emissions to specific fuels (coal, gas, etc.).
              </p>
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Emission factors used</h4>
              <p className="mt-1 text-white/40">
                IPCC AR5 defaults + AEMO NGES. Units: kgCO₂e per MWh.
              </p>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 md:grid-cols-3">
                {Object.entries(EMISSION_FACTORS).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between border-b border-white/5 py-1">
                    <span className="font-mono text-white/55">{k}</span>
                    <span className="font-mono text-white/80">{v}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Data sources</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-white/55">
                <li>AEMO NEM dispatch + SCADA data (5-min aggregated to 30-min)</li>
                <li>AEMO WEM market data</li>
                <li>BoM weather observations (hourly, 6 stations)</li>
                <li>Supplier facility-level disclosures (Scope 1+2 verification)</li>
                <li>OpenElectricity / OpenNEM public dataset (historical backfill)</li>
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

const FUEL_COLORS: Record<string, string> = {
  coal_black:   "rgba(120,53,15,0.95)",   // dark brown
  coal_brown:   "rgba(146,64,14,0.95)",   // lighter brown
  gas_ccgt:     "rgba(56,189,248,0.95)",  // sky
  gas_ocgt:     "rgba(125,211,252,0.95)", // light sky
  wind:         "rgba(132,204,22,0.95)",  // lime
  solar_u:      "rgba(250,204,21,0.95)",  // yellow
  solar_r:      "rgba(253,224,71,0.95)",  // light yellow
  hydro:        "rgba(20,184,166,0.95)",  // teal
  battery:      "rgba(168,85,247,0.95)",  // purple
  biomass:      "rgba(34,197,94,0.95)",   // green
};

function fuelColor(fuel: string): string {
  return FUEL_COLORS[fuel] ?? "rgba(148,163,184,0.6)";
}

const FUEL_LABELS: Record<string, string> = {
  coal_black: "Coal (black)",
  coal_brown: "Coal (brown)",
  gas_ccgt:   "Gas CCGT",
  gas_ocgt:   "Gas OCGT",
  wind:       "Wind",
  solar_u:    "Solar (utility)",
  solar_r:    "Solar (rooftop)",
  hydro:      "Hydro",
  battery:    "Battery",
  biomass:    "Biomass",
};

function fuelLabel(fuel: string): string {
  return FUEL_LABELS[fuel] ?? fuel;
}
