/**
 * /dashboard/carbon/methodology — calculation transparency.
 *
 * Shows users exactly how emissions numbers are calculated, with:
 *   - The full calculation chain (raw data → warehouse → factors → output)
 *   - All data sources with licenses, URLs, and what each contributes
 *   - Every emission factor with its bibliographic source
 *   - Three worked examples (Scope 2 basic, Scope 1 mix, what-if scenario)
 *
 * The page is a mix of:
 *   - Static content (chain, sources, factors) - from `src/lib/methodology.ts`
 *   - Dynamic content (per-region trace) - placeholder showing the structure
 *     until the live `/v1/emissions/trace` endpoint is wired up.
 *
 * In production, the page would call `/v1/emissions/trace?region=...&limit=5`
 * to get the actual numbers from the warehouse.
 */
"use client";

import { useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Calculator,
  ChevronRight,
  Database,
  ExternalLink,
  Factory,
  FileText,
  Gauge,
  Lightbulb,
  Link2,
  ListChecks,
  Network,
  Sigma,
  Sparkles,
  TrendingDown,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";
import {
  ALL_EMISSION_REGIONS,
  formatIntensity,
  type EmissionRegion,
} from "@/lib/emissions";
import {
  CALCULATION_CHAIN,
  DATA_SOURCES,
  FACTORS_WITH_CITATIONS,
  WORKED_EXAMPLES,
  type ChainStep,
  type DataSource,
  type WorkedExample,
} from "@/lib/methodology";

const LAYER_ICONS = {
  ingestion:     Database,
  warehouse:     Network,
  calculation:   Calculator,
  presentation:  Sparkles,
};

const LAYER_COLORS = {
  ingestion:    "border-sky-400/20 bg-sky-500/5",
  warehouse:    "border-purple-400/20 bg-purple-500/5",
  calculation:  "border-emerald-200/20 bg-emerald-300/5",
  presentation: "border-lime-100/20 bg-lime-100/5",
};

const SOURCE_TYPE_COLORS: Record<DataSource["type"], string> = {
  primary:    "bg-emerald-300/10 text-emerald-100 border-emerald-200/20",
  secondary:  "bg-sky-500/10 text-sky-200 border-sky-400/20",
  regulatory: "bg-purple-500/10 text-purple-200 border-purple-400/20",
  reference:  "bg-amber-500/10 text-amber-200 border-amber-400/20",
};

export default function EmissionsMethodologyPage() {
  const [activeExample, setActiveExample] = useState<string>(WORKED_EXAMPLES[0].id);
  const [traceRegion, setTraceRegion] = useState<EmissionRegion>("NSW1");
  const [showTrace, setShowTrace] = useState(false);

  const example = WORKED_EXAMPLES.find((e) => e.id === activeExample) ?? WORKED_EXAMPLES[0];

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white">How emissions are calculated</h1>
            <span
              data-testid="methodology-source"
              className="rounded-full border border-emerald-200/20 bg-emerald-300/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-100"
            >
              auditable
            </span>
          </div>
          <p className="mt-1 text-sm text-white/55">
            The full data lineage, emission factors with citations, and worked
            examples so you can verify every number on the emissions dashboard.
          </p>
        </div>
        <a
          href="/dashboard/carbon/"
          className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-white/70 hover:bg-white/10 hover:text-white"
        >
          <ChevronRight className="h-3 w-3 rotate-180" /> Back to emissions
        </a>
      </div>

      {/* ── 6-step calculation chain ────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-emerald-200" />
            The calculation chain (data lineage)
          </span>
        }
        subtitle="From raw AEMO/BoM signals to the number on the dashboard"
      >
        <div className="space-y-3" data-testid="calculation-chain">
          {CALCULATION_CHAIN.map((step, idx) => (
            <ChainStepCard key={step.step} step={step} isLast={idx === CALCULATION_CHAIN.length - 1} />
          ))}
        </div>
      </Card>

      {/* ── Live trace (mock for now, real once API is wired) ── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Sigma className="h-4 w-4 text-emerald-200" />
            Verify a real number
          </span>
        }
        subtitle="Pick a region and we'll show you the actual warehouse values that went into the calculation"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Region
              </label>
              <select
                value={traceRegion}
                onChange={(e) => setTraceRegion(e.target.value as EmissionRegion)}
                data-testid="trace-region"
                className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              >
                {ALL_EMISSION_REGIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Time window
              </label>
              <select
                defaultValue="last_1h"
                data-testid="trace-window"
                className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm text-white focus:border-emerald-200/60 focus:outline-none"
              >
                <option value="last_1h">Last 1 hour (2 intervals)</option>
                <option value="last_24h">Last 24 hours (48 intervals)</option>
                <option value="last_7d">Last 7 days (336 intervals)</option>
              </select>
            </div>
            <button
              type="button"
              onClick={() => setShowTrace(true)}
              data-testid="run-trace"
              className="inline-flex items-center gap-1.5 rounded-md bg-lime-100 px-3 py-1.5 text-sm font-semibold text-black hover:bg-lime-100"
            >
              Run trace <ArrowRight className="h-3 w-3" />
            </button>
          </div>
          {showTrace ? <TraceMockup region={traceRegion} /> : (
            <p className="text-xs text-white/45">
              The trace calls <code className="rounded bg-black/30 px-1 font-mono text-lime-100">GET /v1/emissions/trace?region={traceRegion}&amp;limit=5</code>{" "}
              and returns the raw warehouse values, applied emission factors,
              and per-interval math (e.g. <code className="font-mono">8000 MW × 640 kg/MWh × 0.5h = 2,560,000 kgCO₂e</code>).
            </p>
          )}
        </div>
      </Card>

      {/* ── Worked examples ─────────────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Calculator className="h-4 w-4 text-emerald-200" />
            Worked examples
          </span>
        }
        subtitle="Verify the math by hand"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Worked example">
            {WORKED_EXAMPLES.map((ex) => (
              <button
                key={ex.id}
                type="button"
                role="tab"
                aria-selected={activeExample === ex.id}
                onClick={() => setActiveExample(ex.id)}
                data-testid={`example-${ex.id}`}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  activeExample === ex.id
                    ? "bg-emerald-200 text-black"
                    : "border border-white/10 bg-white/[0.04] text-white/70 hover:bg-white/10 hover:text-white",
                )}
              >
                {ex.scope === "scope2" ? "Scope 2" : ex.scope === "scope1" ? "Scope 1" : "What-if"} · {ex.region}
              </button>
            ))}
          </div>
          <WorkedExampleView example={example} />
        </div>
      </Card>

      {/* ── Emission factors with sources ──────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-emerald-200" />
            Emission factors &amp; citations
          </span>
        }
        subtitle="Every kgCO₂e/MWh value used in the calculation, with its bibliographic source"
      >
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="factors-table">
            <thead>
              <tr className="border-b border-white/5 text-left text-[10px] uppercase tracking-wider text-white/40">
                <th className="px-3 py-2">Factor</th>
                <th className="px-3 py-2 text-right">Value</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Scope</th>
                <th className="px-3 py-2">Notes</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {Object.entries(FACTORS_WITH_CITATIONS).map(([k, f]) => (
                <tr
                  key={k}
                  className="border-t border-white/5 transition-colors hover:bg-white/[0.02]"
                  data-testid={`factor-row-${k}`}
                >
                  <td className="px-3 py-2 font-sans text-white">{k}</td>
                  <td className="px-3 py-2 text-right text-lime-100">
                    {formatIntensity(f.factor)}
                  </td>
                  <td className="px-3 py-2 font-sans text-white/70">
                    {f.url ? (
                      <a href={f.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-emerald-100 hover:text-emerald-100">
                        {f.source} <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (
                      f.source
                    )}
                  </td>
                  <td className="px-3 py-2 font-sans text-white/60">{f.scope}</td>
                  <td className="px-3 py-2 font-sans text-[11px] text-white/55">{f.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Data sources ────────────────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-emerald-200" />
            Data sources
          </span>
        }
        subtitle="Every input dataset, with its license and what it contributes"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="sources-grid">
          {DATA_SOURCES.map((s) => (
            <SourceCard key={s.id} source={s} />
          ))}
        </div>
      </Card>

      {/* ── Provenance / limitations ────────────────────────── */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-amber-300" />
            What's NOT in scope
          </span>
        }
      >
        <div className="space-y-3 text-sm text-white/65">
          <p>
            <strong className="text-white">Scope 3 (value chain):</strong> Not
            currently modeled. The GHG Protocol&apos;s Scope 3 includes
            purchased goods, transport, employee commute, use-of-sold-product,
            and end-of-life. We&apos;d need supplier-level data to add this.
          </p>
          <p>
            <strong className="text-white">Market-based Scope 2:</strong> We
            report <em>location-based</em> Scope 2 (the grid&apos;s average
            intensity). The alternative is <em>market-based</em> Scope 2, which
            subtracts the renewable attribute of any GreenPower / LGCs you
            purchased. We can add a market-based view if you tell us your RECs.
          </p>
          <p>
            <strong className="text-white">Direct facility-level Scope 1:</strong>{" "}
            Our Scope 1 is <em>fuel-attributed</em> (i.e. the share of grid
            generation we can attribute to our demand). For facility-level
            Scope 1 (combustion of diesel, gas, refrigerants on-site), we
            combine supplier disclosures and our own metering here.
          </p>
          <p>
            <strong className="text-white">Reconciliation cadence:</strong>{" "}
            Supplier disclosures are annual; our dashboard rolls up monthly.
            Expect a small divergence at year-end until disclosures land.
          </p>
        </div>
      </Card>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Sub-components
// ────────────────────────────────────────────────────────────────────
function ChainStepCard({ step, isLast }: { step: ChainStep; isLast: boolean }) {
  const Icon = LAYER_ICONS[step.layer];
  return (
    <div data-testid={`chain-step-${step.step}`}>
      <div className={cn("rounded-lg border p-4", LAYER_COLORS[step.layer])}>
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/5 text-sm font-mono text-emerald-100">
            {step.step}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-baseline gap-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-white">
                <Icon className="h-3.5 w-3.5 text-emerald-100" />
                {step.name}
              </h3>
              <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-white/60">
                {step.layer}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
              <Field label="Source" value={step.source} />
              <Field label="Output" value={step.output} />
            </div>
            <p className="mt-2 text-[11px] text-white/60">{step.details}</p>
            <div className="mt-2 text-[10px] text-white/40">
              <span className="font-mono">typical latency:</span> {step.typical_latency}
            </div>
          </div>
        </div>
      </div>
      {!isLast && (
        <div className="ml-4 my-1 flex h-6 items-center border-l border-dashed border-white/10 pl-4 text-white/30">
          <ArrowRight className="h-3 w-3" />
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">{label}</div>
      <div className="mt-0.5 text-xs text-white/80">{value}</div>
    </div>
  );
}

function SourceCard({ source }: { source: DataSource }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-lg border border-white/5 bg-white/[0.02] p-3 transition-colors hover:border-white/10 hover:bg-white/[0.04]"
      data-testid={`source-${source.id}`}
    >
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-semibold text-white">{source.name}</h4>
        <span
          className={cn(
            "rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
            SOURCE_TYPE_COLORS[source.type],
          )}
        >
          {source.type}
        </span>
      </div>
      <div className="mt-1.5 text-[11px] text-white/65">{source.note}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-white/40">
        <span>📅 {source.cadence}</span>
        <span>📜 {source.license}</span>
        <span className="inline-flex items-center gap-0.5 text-emerald-100">
          visit <ExternalLink className="h-2.5 w-2.5" />
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {source.fields.slice(0, 4).map((f) => (
          <span key={f} className="rounded-sm bg-white/5 px-1.5 py-0.5 font-mono text-[9px] text-white/55">
            {f}
          </span>
        ))}
        {source.fields.length > 4 && (
          <span className="rounded-sm bg-white/5 px-1.5 py-0.5 font-mono text-[9px] text-white/55">
            +{source.fields.length - 4} more
          </span>
        )}
      </div>
    </a>
  );
}

function WorkedExampleView({ example }: { example: WorkedExample }) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4" data-testid={`example-${example.id}-detail`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold text-white">{example.title}</h3>
        <span
          className={cn(
            "rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
            example.scope === "scope2" ? "bg-sky-500/10 text-sky-200 border-sky-400/20" :
            example.scope === "scope1" ? "bg-amber-500/10 text-amber-200 border-amber-400/20" :
            "bg-purple-500/10 text-purple-200 border-purple-400/20",
          )}
        >
          {example.scope}
        </span>
        <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-white/70">
          {example.region}
        </span>
      </div>
      <p className="mt-1.5 text-xs text-white/60">{example.description}</p>

      <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Inputs</div>
          <div className="mt-1.5 space-y-1">
            {example.inputs.map((inp, i) => (
              <div key={i} className="flex items-center justify-between gap-2 rounded border border-white/5 bg-white/[0.02] px-2 py-1.5 text-xs">
                <span className="text-white/65">{inp.label}</span>
                <span className="font-mono text-white">
                  {inp.value} <span className="text-white/40">{inp.unit}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">Step-by-step</div>
          <div className="mt-1.5 space-y-1.5">
            {example.steps.map((step, i) => (
              <div key={i} className="rounded border border-white/5 bg-white/[0.02] p-2 font-mono text-[11px]">
                <div className="text-white/65">{step.math}</div>
                <div className="mt-0.5 text-emerald-100">→ {step.result}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 rounded-md border border-emerald-200/20 bg-emerald-300/5 p-2.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-100">Final answer</div>
        <div className="mt-0.5 text-sm text-white">{example.finalAnswer}</div>
      </div>
    </div>
  );
}

/**
 * Mock trace mockup (placeholder until live API is wired up).
 * Shows the structure of what a real trace response looks like.
 */
function TraceMockup({ region }: { region: EmissionRegion }) {
  return (
    <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4" data-testid="trace-result">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
        Sample trace for {region} (last 1h, first 2 intervals)
      </div>
      <div className="mt-2 space-y-2 text-xs font-mono text-white/70">
        <div className="rounded border border-emerald-200/20 bg-emerald-300/5 p-2.5">
          <div className="text-emerald-100">▸ Interval 1: 2026-07-22T13:00:00Z</div>
          <div className="mt-1 text-white/65">  raw: demand_mw=7842, intensity=638, coal_black=3200, gas_ccgt=1200, wind=900</div>
          <div className="text-white/65">  scope2: 7842 × 638 × 0.5 = <span className="text-lime-100">2,501,598 kgCO₂e</span></div>
          <div className="text-white/65">  scope1: coal_black (1,312,000) + gas_ccgt (222,000) + wind (4,500) = <span className="text-lime-100">1,538,500 kgCO₂e</span></div>
        </div>
        <div className="rounded border border-emerald-200/20 bg-emerald-300/5 p-2.5">
          <div className="text-emerald-100">▸ Interval 2: 2026-07-22T13:30:00Z</div>
          <div className="mt-1 text-white/65">  raw: demand_mw=8127, intensity=642, coal_black=3400, gas_ccgt=1300, wind=850</div>
          <div className="text-white/65">  scope2: 8127 × 642 × 0.5 = <span className="text-lime-100">2,609,167 kgCO₂e</span></div>
          <div className="text-white/65">  scope1: coal_black (1,394,000) + gas_ccgt (240,500) + wind (4,250) = <span className="text-lime-100">1,638,750 kgCO₂e</span></div>
        </div>
      </div>
      <div className="mt-3 rounded-md border border-white/5 bg-white/5 p-2.5 text-[11px] text-white/55">
        <div>When the <code className="rounded bg-black/30 px-1 font-mono text-lime-100">/v1/emissions/trace</code> endpoint is wired up, this section will show the real warehouse values from <code className="rounded bg-black/30 px-1 font-mono text-lime-100">fact_demand_30min</code> for the selected region and time window.</div>
      </div>
    </div>
  );
}
