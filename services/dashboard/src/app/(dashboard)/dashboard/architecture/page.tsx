/**
 * /dashboard/architecture — Platform Architecture & Technical Overview.
 *
 * Visual end-to-end walkthrough of the ecoLens platform: how data flows from
 * external energy APIs all the way through to the dashboard the user is
 * looking at. Splits the architecture into 5 sections (one per tab):
 *
 *   1. Pipeline Overview  — 4-stage horizontal flow (Ingest → Warehouse → Model → Frontend)
 *   2. Anomaly Detection  — statistical + ML approach, flag-not-remove
 *   3. ML Lifecycle       — LSTM + TFT + TimesFM, conformal calibration, MLflow
 *   4. Storage Strategy   — DuckDB staging, raw.* + dbt, PostgreSQL warehouse
 *   5. Frontend & API     — Next.js 14, REST decoupling, visualisation
 */
"use client";

import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Beaker,
  Brain,
  CheckCircle2,
  CircleDashed,
  Clock,
  Cpu,
  Database,
  FileCode2,
  FileText,
  Filter,
  Gauge,
  GitBranch,
  HardDrive,
  Leaf,
  LineChart,
  MessageSquare,
  Network,
  Radio,
  RefreshCw,
  Shield,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Workflow,
  Zap,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { cn } from "@/lib/utils";

// ───────────────────────────────────────────────────────────────────────
// Tab content
// ───────────────────────────────────────────────────────────────────────

type TabId = "pipeline" | "anomaly" | "ml" | "storage" | "frontend";

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: "pipeline",   label: "Pipeline Overview", icon: <Workflow className="h-3.5 w-3.5" /> },
  { id: "anomaly",    label: "Anomaly Detection", icon: <ShieldCheck className="h-3.5 w-3.5" /> },
  { id: "ml",         label: "ML Lifecycle",      icon: <Brain className="h-3.5 w-3.5" /> },
  { id: "storage",    label: "Storage Strategy",  icon: <Database className="h-3.5 w-3.5" /> },
  { id: "frontend",   label: "Frontend & API",    icon: <LineChart className="h-3.5 w-3.5" /> },
];

// ───────────────────────────────────────────────────────────────────────
// Reusable primitives
// ───────────────────────────────────────────────────────────────────────

function StageCard({
  icon,
  title,
  subtitle,
  accent,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  accent: "sky" | "purple" | "amber" | "emerald" | "lime";
  children: React.ReactNode;
}) {
  const accentMap: Record<string, string> = {
    sky:     "border-sky-400/30 bg-sky-500/[0.04] text-sky-200",
    purple:  "border-purple-400/30 bg-purple-500/[0.04] text-purple-200",
    amber:   "border-amber-400/30 bg-amber-500/[0.04] text-amber-200",
    emerald: "border-emerald-300/30 bg-emerald-500/[0.04] text-emerald-100",
    lime:    "border-lime-200/30 bg-lime-200/[0.04] text-lime-100",
  };
  return (
    <div className={cn("rounded-xl border p-4", accentMap[accent])}>
      <div className="mb-2 flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg border border-current/30 bg-current/[0.06]">
          {icon}
        </span>
        <div>
          <div className="text-sm font-semibold text-white">{title}</div>
          <div className="text-[11px] text-white/50">{subtitle}</div>
        </div>
      </div>
      <div className="space-y-1.5 text-[12px] text-white/70">{children}</div>
    </div>
  );
}

function FlowArrow({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-1 text-white/30">
      <ArrowRight className="h-5 w-5" />
      {label && <span className="text-[10px] uppercase tracking-wider text-white/40">{label}</span>}
    </div>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
      <span className="text-white/75">{children}</span>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-emerald-100">
      {children}
    </code>
  );
}

function MetricRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-white/5 py-1.5 text-[12px] last:border-0">
      <span className="text-white/55">{k}</span>
      <span className="font-mono text-white/90">{v}</span>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Tab 1: Pipeline Overview
// ───────────────────────────────────────────────────────────────────────

function PipelineTab() {
  return (
    <div className="space-y-6">
      <Card
        title="End-to-end pipeline"
        subtitle="From external energy APIs to the dashboard in front of you — decoupled, event-driven, fully auditable."
      >
        {/* Horizontal flow */}
        <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
          <StageCard
            icon={<Radio className="h-4 w-4" />}
            title="1. Ingestion"
            subtitle="Every 5 min · 9 sources"
            accent="sky"
          >
            <Bullet>Scheduled cron fetches external REST APIs</Bullet>
            <Bullet>9 data sources (AEMO NEM/WEM, BoM, Open-Meteo, …)</Bullet>
            <Bullet>Stages into <Code>DuckDB</Code> for fast local processing</Bullet>
            <Bullet>Publishes <Code>new_data</Code> event to RabbitMQ</Bullet>
          </StageCard>

          <FlowArrow label="event" />

          <StageCard
            icon={<Network className="h-4 w-4" />}
            title="2. Warehousing"
            subtitle="RabbitMQ + dbt + Postgres"
            accent="purple"
          >
            <Bullet><Code>new_data</Code> event triggers dbt flow</Bullet>
            <Bullet>Raw data copied to <Code>raw.*</Code> schema (untouched)</Bullet>
            <Bullet>dbt models build <Code>stg → int → mart</Code> layers</Bullet>
            <Bullet>Curated tables land in PostgreSQL (NeonDB)</Bullet>
          </StageCard>

          <FlowArrow label="features" />

          <StageCard
            icon={<Brain className="h-4 w-4" />}
            title="3. Predictive Modeling"
            subtitle="LSTM · TFT · TimesFM"
            accent="amber"
          >
            <Bullet>4-model ensemble, all producing P10/P50/P90</Bullet>
            <Bullet>Online + incremental learning on streaming data</Bullet>
            <Bullet>Conformal calibration self-corrects intervals</Bullet>
            <Bullet>MLflow tracks experiments, versions, artifacts</Bullet>
          </StageCard>

          <FlowArrow label="API" />

          <StageCard
            icon={<LineChart className="h-4 w-4" />}
            title="4. Frontend"
            subtitle="Next.js 14 · REST APIs"
            accent="emerald"
          >
            <Bullet>Dashboard BFF calls internal services via REST</Bullet>
            <Bullet>Real-time KPIs, forecast charts, carbon insights</Bullet>
            <Bullet>LazyMotion + GSAP for animated visualisations</Bullet>
            <Bullet>This page is the result of that whole chain</Bullet>
          </StageCard>
        </div>
      </Card>

      {/* Two key questions */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="What does the platform answer?" badge={<span className="rounded-md border border-emerald-200/30 bg-emerald-200/10 px-2 py-0.5 text-[10px] text-emerald-100">CORE QUESTIONS</span>}>
          <div className="space-y-3 text-[13px] text-white/75">
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Q1</div>
              <div className="font-medium text-white">How much electricity will be needed over the next 24 hours?</div>
              <p className="mt-1 text-white/60">Probabilistic demand forecast — P10 (conservative), P50 (expected), P90 (peak). Decomposed by NEM region (NSW1, QLD1, VIC1, SA1, TAS1) and WEM.</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Q2</div>
              <div className="font-medium text-white">How clean will that electricity be, based on the expected generation mix?</div>
              <p className="mt-1 text-white/60">Forecast contribution of coal, gas, wind, solar, hydro, and battery. Translated into carbon intensity (gCO₂e/kWh) and total emissions.</p>
            </div>
          </div>
        </Card>

        <Card title="Latency budget (typical)">
          <div className="space-y-1">
            <MetricRow k="Source fetch (AEMO NEM)" v="~480 ms" />
            <MetricRow k="Anomaly detection (per record)" v="< 5 ms" />
            <MetricRow k="dbt warehouse build" v="2-5 min" />
            <MetricRow k="Feature engineering for ML" v="< 30 s" />
            <MetricRow k="Model inference (4 models)" v="~50 ms" />
            <MetricRow k="Conformal calibration" v="< 10 ms" />
            <MetricRow k="API response (cached)" v="5 ms" />
            <MetricRow k="API response (uncached)" v="80-200 ms" />
            <MetricRow k="Dashboard render" v="< 100 ms" />
            <MetricRow k="Total end-to-end" v="≈ 5-7 min (ingest → user)" />
          </div>
        </Card>
      </div>

      <Card title="Why this architecture works" subtitle="Decoupled, event-driven, auditable.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-emerald-200/15 bg-emerald-200/[0.03] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-emerald-100">
              <GitBranch className="h-4 w-4" /> Decoupled stages
            </div>
            <p className="text-[12px] text-white/65">
              Ingestion never blocks on warehousing. If the warehouse is rebuilding, new data still keeps flowing. The event bus (RabbitMQ) absorbs the dependency.
            </p>
          </div>
          <div className="rounded-lg border border-sky-400/15 bg-sky-500/[0.03] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-sky-200">
              <Clock className="h-4 w-4" /> Near-real-time
            </div>
            <p className="text-[12px] text-white/65">
              Forecasts are updated every 5 min. Anomalies are flagged within seconds of arrival. The dashboard cache is 30-60 s — fresh enough to act on.
            </p>
          </div>
          <div className="rounded-lg border border-amber-400/15 bg-amber-500/[0.03] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-amber-200">
              <ShieldCheck className="h-4 w-4" /> Fully auditable
            </div>
            <p className="text-[12px] text-white/65">
              Raw data is stored exactly as received. dbt models are version-controlled in git. Every transformation has lineage back to the source.
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Tab 2: Anomaly Detection
// ───────────────────────────────────────────────────────────────────────

function AnomalyTab() {
  return (
    <div className="space-y-6">
      <Card
        title="Statistical + ML anomaly detection"
        subtitle="Two independent signals, worse-of-the-two wins. Flag, never remove."
      >
        <div className="space-y-3 text-[13px] text-white/75">
          <p>
            Energy systems occasionally produce unusual readings. Some are caused by sensor failures, communication issues, or incomplete API responses. Others represent genuine operational events — sudden demand spikes, unexpected renewable generation changes.
          </p>
          <p>
            The platform scores every ingested record with two independent signals — a <span className="font-medium text-white">statistical</span> per-batch z-score and an <span className="font-medium text-white">ML</span> IsolationForest — and keeps whichever signal scored worse for that row. A row that clears both at once is the highest-confidence case (<code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">hybrid</code>). The score plus an explanation flows through to downstream systems.
          </p>
          <p className="text-white/55">
            <span className="font-medium text-amber-200">Rule-based checks (out-of-range bounds, missing-value flagging) were retired 2026-08-12.</span> Live-observed cost: the missing-value check alone accounted for 121K/150K+ flagged rows, the large majority structurally expected rather than anomalous (e.g. WEM only publishes <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">price_mwh</code> on the :00/:30 marks, so 5/6 of every WEM batch was flagged on a column that was never going to have a value). Historical rows flagged under that check are kept as-is; nothing new lands there going forward.
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Statistical checks" subtitle="Per-batch z-score, self-contained.">
          <div className="space-y-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Per-batch z-score</div>
              <p className="text-[12px] text-white/70">
                Each numeric column (demand, price, temperature, wind speed…) is scored against its own mean/std within the current fetch — no historical baseline query, no trained model artifact. Records with z &gt; 4.0 are candidates.
              </p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Lightweight, local</div>
              <p className="text-[12px] text-white/70">
                Deliberately cheap and self-contained — complementary to the ML signal's actual trained model, not a replacement for it.
              </p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">High-confidence gate</div>
              <p className="text-[12px] text-white/70">
                Clearing z &gt; 4.0 is necessary but not sufficient — the winning signal's combined score must also exceed 0.98 to actually get persisted.
              </p>
            </div>
          </div>
        </Card>

        <Card title="ML-based detection" subtitle="Per-source IsolationForest.">
          <div className="space-y-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Trained per source</div>
              <p className="text-[12px] text-white/70">
                A scikit-learn <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">IsolationForest</code> per ingest source (e.g. <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">aemo_nem</code>, <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">bom</code>), fit against that source's accumulated DuckDB staging history over the same numeric columns the statistical check scans.
              </p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Manual retraining</div>
              <p className="text-[12px] text-white/70">
                Retrained via <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">ecolens-ingestion train-anomaly-model &lt;source&gt;</code>, not on an automatic schedule — an operator decides when. A source with no model yet just runs on the statistical signal alone (expected, not an error).
              </p>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Persisted to R2</div>
              <p className="text-[12px] text-white/70">
                Model artifacts (<code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">models/anomaly/{"{source}"}.joblib</code>) live in Cloudflare R2, same as every other artifact this platform produces.
              </p>
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="Flag, never remove"
        subtitle="Why we keep every record — even the suspicious ones."
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-emerald-200/15 bg-emerald-200/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-emerald-100">1. Audit trail</div>
            <p className="text-[12px] text-white/65">
              If a model trains on cleaned data and then produces a wrong number, you can't trace back to the original record. Flagged records preserve that lineage.
            </p>
          </div>
          <div className="rounded-lg border border-sky-400/15 bg-sky-500/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-sky-200">2. Real events</div>
            <p className="text-[12px] text-white/65">
              A demand spike at 6pm on a heatwave day looks like an outlier — but it's the most operationally important record of the day. The flag is context, not a verdict.
            </p>
          </div>
          <div className="rounded-lg border border-amber-400/15 bg-amber-500/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-amber-200">3. Retrain on truth</div>
            <p className="text-[12px] text-white/65">
              Anomaly score feeds back into the ML training pipeline. Models learn to handle genuine grid events without being skewed by sensor noise.
            </p>
          </div>
        </div>
        <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.02] p-3">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-white/50">Anomaly output structure (real `meta.anomalies` row shape)</div>
          <pre className="overflow-x-auto rounded border border-white/10 bg-black/40 p-3 font-mono text-[11px] text-emerald-100">{`{
  "source":            "aemo_nem",
  "anomaly_score":     0.99,
  "anomaly_reason":    "statistical_outlier:demand_mw(z=8.1)",
  "metric":            "demand_mw",
  "value":             12400.0,
  "z_score":           8.1,
  "expected_low":      4200.0,
  "expected_high":     8600.0,
  "rule_based_score":  null,
  "statistical_score": 0.99,
  "ml_score":          null,
  "row_snapshot":      { "...": "every column of the flagged row" }
}`}</pre>
          <p className="mt-2 text-[11px] text-white/50">
            <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">rule_based_score</code> is always <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">null</code> on any row detected today — the column stays on real historical rows from before the 2026-08-12 retirement, never populated on a new one. <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">statistical_score</code>/<code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">ml_score</code> record each signal's own score independently (either can be <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">null</code> if that signal didn't fire) — a row where both fire is the <code className="rounded bg-black/30 px-1 font-mono text-[11px] text-lime-100">hybrid</code> case.
          </p>
        </div>
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Tab 3: ML Lifecycle
// ───────────────────────────────────────────────────────────────────────

function MlTab() {
  return (
    <div className="space-y-6">
      <Card
        title="Predictive modeling"
        subtitle="Probabilistic forecasts with self-correcting uncertainty ranges."
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-sky-400/20 bg-sky-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-sky-200">
              <Cpu className="h-4 w-4" /> LSTM
            </div>
            <p className="text-[12px] text-white/65">
              2-layer LSTM with attention pooling. Trained from scratch on NEM/WEM warehouse data. Best for long-term temporal patterns.
            </p>
          </div>
          <div className="rounded-lg border border-purple-400/20 bg-purple-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-purple-200">
              <Brain className="h-4 w-4" /> TFT
            </div>
            <p className="text-[12px] text-white/65">
              Temporal Fusion Transformer — variable selection networks + multi-horizon outputs. Highest accuracy per evaluation.
            </p>
          </div>
          <div className="rounded-lg border border-amber-400/20 bg-amber-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-medium text-amber-200">
              <Sparkles className="h-4 w-4" /> TimesFM
            </div>
            <p className="text-[12px] text-white/65">
              Google's foundation model, frozen backbone + lightweight calibration head. Robust to concept drift.
            </p>
          </div>
        </div>
        <div className="mt-3 rounded-lg border border-emerald-200/20 bg-emerald-200/[0.03] p-3">
          <div className="mb-1 flex items-center gap-2 text-sm font-medium text-emerald-100">
            <Shield className="h-4 w-4" /> Seasonal-naïve (fallback)
          </div>
          <p className="text-[12px] text-white/65">
            Last-week-same-hour baseline. Always available, zero dependencies. Auto-engages if all 3 ML models fail or the model registry is unreachable.
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Probabilistic forecasts" subtitle="P10 · P50 · P90.">
          <div className="space-y-3 text-[13px] text-white/75">
            <p>
              Instead of guessing a single fixed number, every model emits a range of outcomes: <span className="font-medium text-white">P10 (conservative)</span>, <span className="font-medium text-white">P50 (expected)</span>, <span className="font-medium text-white">P90 (peak)</span>. Decision-makers can plan for both best-case and worst-case scenarios.
            </p>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">Example — NSW1 next 4 hours</div>
              <div className="grid grid-cols-3 gap-2 text-center text-[12px]">
                <div className="rounded border border-sky-400/30 bg-sky-500/10 p-2">
                  <div className="text-[10px] uppercase text-sky-200">P10</div>
                  <div className="font-mono text-sm text-white">7,420 MW</div>
                </div>
                <div className="rounded border border-emerald-300/30 bg-emerald-300/10 p-2">
                  <div className="text-[10px] uppercase text-emerald-100">P50</div>
                  <div className="font-mono text-sm text-white">8,650 MW</div>
                </div>
                <div className="rounded border border-amber-300/30 bg-amber-300/10 p-2">
                  <div className="text-[10px] uppercase text-amber-200">P90</div>
                  <div className="font-mono text-sm text-white">9,910 MW</div>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-white/55">
                P10 = 10% chance demand is below 7,420. P90 = 90% chance demand is below 9,910. P50 is the median.
              </p>
            </div>
          </div>
        </Card>

        <Card title="Conformal calibration" subtitle="Self-correcting uncertainty.">
          <div className="space-y-3 text-[13px] text-white/75">
            <p>
              Models don't know what they don't know. A raw P90 from a neural network can be miscalibrated. Conformal calibration wraps every forecast with a post-hoc correction that <span className="font-medium text-white">guarantees</span> 80% of true values fall within the P10-P90 band.
            </p>
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 font-mono text-[11px] text-emerald-100">
              {`coverage_actual = # of trues in P10-P90 / # of forecasts
target = 0.80

if coverage_actual < 0.78:
  widen interval by 1.05× (slight expansion)
elif coverage_actual > 0.82:
  tighten interval by 0.97× (slight contraction)
else:
  no change (well-calibrated)

→ Checked every 6h on the last 500 forecasts.`}
            </div>
            <p className="text-[12px] text-white/65">
              If MAPE spikes above 8% or the calibration drifts for 3 consecutive checks, the system <span className="font-medium text-white">auto-falls back</span> to the seasonal-naïve baseline and pages an admin.
            </p>
          </div>
        </Card>
      </div>

      <Card title="Online + incremental learning" subtitle="No full retrain on every data shift.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="mb-1 text-sm font-medium text-white">Continuous adaptation</div>
            <p className="text-[12px] text-white/65">
              Models learn long-term patterns from the warehouse, then continuously tweak their internal weights using incoming streaming data. Concept drift is handled in-place.
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="mb-1 text-sm font-medium text-white">Full retrain schedule</div>
            <p className="text-[12px] text-white/65">
              A full LSTM / TFT rebuild happens every 6 hours if drift exceeds a threshold, or weekly on Sunday at 02:00 UTC. MLflow records every run with metrics + dataset hash.
            </p>
          </div>
        </div>
      </Card>

      <Card
        title="Model lifecycle with MLflow"
        subtitle="Experiment tracking · versioning · artifact storage · validation · deployment."
      >
        <div className="overflow-x-auto">
          <div className="flex min-w-[720px] items-stretch gap-2">
            {[
              { icon: <Beaker className="h-4 w-4" />, title: "Experiment", desc: "Parameters + metrics + dataset hash" },
              { icon: <FileText className="h-4 w-4" />, title: "Version", desc: "Immutable model artifact + signature" },
              { icon: <ShieldCheck className="h-4 w-4" />, title: "Validate", desc: "MAPE < 8%, P10-P90 coverage ≥ 78%" },
              { icon: <RefreshCw className="h-4 w-4" />, title: "Promote", desc: "Atomic hot-swap in forecast-api" },
              { icon: <Activity className="h-4 w-4" />, title: "Monitor", desc: "Live MAPE, calibration drift, fallback rate" },
            ].map((step, i, arr) => (
              <div key={step.title} className="flex flex-1 items-stretch gap-2">
                <div className="flex-1 rounded-lg border border-emerald-200/20 bg-emerald-200/[0.03] p-3">
                  <div className="mb-1 flex items-center gap-2 text-sm font-medium text-emerald-100">
                    <span className="grid h-6 w-6 place-items-center rounded-full border border-emerald-200/30 bg-emerald-200/10 text-[10px] text-emerald-100">
                      {i + 1}
                    </span>
                    {step.icon}
                    {step.title}
                  </div>
                  <p className="text-[11px] text-white/65">{step.desc}</p>
                </div>
                {i < arr.length - 1 && (
                  <div className="flex items-center text-white/30">
                    <ArrowRight className="h-4 w-4" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.02] p-3">
          <p className="text-[12px] text-white/65">
            Old models are <span className="font-medium text-white">never immediately removed</span>. They're kept hot for 24 hours so a bad new model can be reverted with a single MLflow call. After 24h, the old artifact is archived (still queryable, no longer loaded).
          </p>
        </div>
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Tab 4: Storage Strategy
// ───────────────────────────────────────────────────────────────────────

function StorageTab() {
  return (
    <div className="space-y-6">
      <Card
        title="Layered storage strategy"
        subtitle="Three stores, each picked for what it does best."
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-sky-400/20 bg-sky-500/[0.04] p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-sky-200">
              <HardDrive className="h-4 w-4" /> DuckDB (local)
            </div>
            <p className="text-[12px] text-white/65">
              High-performance local analytical store. Used by the ingestion layer to stage historical operational data and by the warehousing pipeline as the <span className="font-medium text-white">dbt execution engine</span> before curated datasets sync to PostgreSQL.
            </p>
            <div className="mt-2 space-y-1 text-[11px] text-white/50">
              <div>• In-process, single-file</div>
              <div>• Sub-second analytical queries</div>
              <div>• Zero infrastructure overhead</div>
            </div>
          </div>
          <div className="rounded-lg border border-purple-400/20 bg-purple-500/[0.04] p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-purple-200">
              <Database className="h-4 w-4" /> PostgreSQL (NeonDB)
            </div>
            <p className="text-[12px] text-white/65">
              Serverless managed PostgreSQL. Holds the full <Code>raw.*</Code> audit copy + dbt-curated marts. Auto-scales with demand, zero ops.
            </p>
            <div className="mt-2 space-y-1 text-[11px] text-white/50">
              <div>• Branching for isolated dbt runs</div>
              <div>• Auto-suspend on idle (cost control)</div>
              <div>• Free tier covers the entire workload</div>
            </div>
          </div>
          <div className="rounded-lg border border-emerald-200/20 bg-emerald-300/[0.04] p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-100">
              <FileCode2 className="h-4 w-4" /> dbt (transformation)
            </div>
            <p className="text-[12px] text-white/65">
              SQL organised into modular, reusable models with dependency management + built-in tests + documentation. Version-controlled in git.
            </p>
            <div className="mt-2 space-y-1 text-[11px] text-white/50">
              <div>• 6 source freshness tests</div>
              <div>• 12 model-level tests</div>
              <div>• Auto-generated docs site</div>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Schema layers" subtitle="raw → stg → int → mart.">
        <div className="space-y-2">
          {[
            {
              name: "raw.*",
              color: "sky",
              desc: "Untouched copy of what arrived from the source API. Full audit trail. Never modified by dbt.",
              example: "raw.aemo_nem_dispatch_30min, raw.bom_observations_30min, raw.open_meteo_hourly",
            },
            {
              name: "stg_*",
              color: "purple",
              desc: "Cleaned, typed, renamed. One stg model per source. Light transformations only (casts, null handling).",
              example: "stg_aemo_nem_dispatch, stg_bom_observations, stg_open_meteo",
            },
            {
              name: "int_*",
              color: "amber",
              desc: "Intermediate joins and feature engineering. Joins across stg models. Adds derived columns (rolling means, lags).",
              example: "int_demand_with_weather, int_generation_mix_normalized",
            },
            {
              name: "mart_*",
              color: "emerald",
              desc: "Final business-ready tables. Aggregated, conformed, optimised for read patterns. Powers ML features, dashboards, reports.",
              example: "mart_demand_30min, mart_forecast_accuracy, mart_carbon_intensity_24h, mart_renewable_mix",
            },
          ].map((l) => {
            const colorMap: Record<string, string> = {
              sky:     "border-sky-400/25 bg-sky-500/[0.04]",
              purple:  "border-purple-400/25 bg-purple-500/[0.04]",
              amber:   "border-amber-400/25 bg-amber-500/[0.04]",
              emerald: "border-emerald-300/25 bg-emerald-300/[0.04]",
            };
            const textMap: Record<string, string> = {
              sky:     "text-sky-200",
              purple:  "text-purple-200",
              amber:   "text-amber-200",
              emerald: "text-emerald-100",
            };
            return (
              <div key={l.name} className={cn("rounded-lg border p-3", colorMap[l.color])}>
                <div className="flex items-baseline gap-3">
                  <code className={cn("font-mono text-sm", textMap[l.color])}>{l.name}</code>
                  <span className="text-[12px] text-white/65">{l.desc}</span>
                </div>
                <div className="mt-1.5 font-mono text-[11px] text-white/45">{l.example}</div>
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="Event-driven decoupling" subtitle="RabbitMQ between ingestion and warehouse.">
        <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
          <div className="rounded-lg border border-sky-400/25 bg-sky-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-sky-200">
              <Radio className="h-4 w-4" /> Ingestion
            </div>
            <p className="text-[12px] text-white/65">
              Every 5 min cron fetches AEMO + BoM + … stages into DuckDB. Publishes <Code>new_data</Code> event to RabbitMQ.
            </p>
          </div>
          <div className="flex items-center text-white/30">
            <ArrowRight className="h-5 w-5" />
          </div>
          <div className="rounded-lg border border-amber-400/25 bg-amber-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-amber-200">
              <MessageSquare className="h-4 w-4" /> RabbitMQ
            </div>
            <p className="text-[12px] text-white/65">
              Three queues: <Code>new_data</Code>, <Code>warehouse_ready</Code>, <Code>anomaly_alert</Code>. Decouples producers from consumers.
            </p>
          </div>
          <div className="flex items-center text-white/30">
            <ArrowRight className="h-5 w-5" />
          </div>
          <div className="rounded-lg border border-emerald-300/25 bg-emerald-300/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-emerald-100">
              <Database className="h-4 w-4" /> Warehousing
            </div>
            <p className="text-[12px] text-white/65">
              Picks up <Code>new_data</Code> event → copies DuckDB → <Code>raw.*</Code> → runs dbt → publishes <Code>warehouse_ready</Code>.
            </p>
          </div>
        </div>
        <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.02] p-3">
          <p className="text-[12px] text-white/65">
            <span className="font-medium text-white">Why decouple?</span> If dbt is running a heavy backfill and the warehouse is rebuilding, ingestion never blocks. New data keeps arriving. The event bus absorbs the dependency, and a backpressure signal (queue depth) gracefully slows the consumer without dropping events.
          </p>
        </div>
      </Card>

      <Card title="Why not BigQuery / Redshift / Snowflake?" subtitle="Sized for the actual workload.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-emerald-200/15 bg-emerald-200/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-emerald-100">For this platform</div>
            <ul className="space-y-1.5 text-[12px] text-white/70">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                5-min grain × 6 NEM regions × 9 sources = manageable volume
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                PostgreSQL on NeonDB is more than fast enough
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Branching + auto-suspend = cost control
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Zero ops, no DBA, fits a $6/mo VPS budget
              </li>
            </ul>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="mb-1 text-sm font-medium text-white">When to upgrade</div>
            <ul className="space-y-1.5 text-[12px] text-white/70">
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If 30-min grain × 5-min markets × global substation-level data
              </li>
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If forecast models need to read 100+ TB of history in one query
              </li>
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If concurrent analyst count exceeds ~50
              </li>
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If ML feature engineering needs columnar MPP for &gt; 1B rows
              </li>
            </ul>
          </div>
        </div>
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Tab 5: Frontend & API
// ───────────────────────────────────────────────────────────────────────

function FrontendTab() {
  return (
    <div className="space-y-6">
      <Card
        title="Frontend & API"
        subtitle="The dashboard is one of many possible clients."
      >
        <div className="grid grid-cols-1 items-stretch gap-3 lg:grid-cols-[1fr_auto_1fr]">
          <div className="rounded-lg border border-sky-400/25 bg-sky-500/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-sky-200">
              <Cpu className="h-4 w-4" /> Backend services
            </div>
            <p className="text-[12px] text-white/65">
              4 services: <Code>forecast-api</Code>, <Code>ingestion</Code>, <Code>warehouse</Code>, <Code>observability</Code>, plus the dashboard's Next.js BFF. Each owns its own data and is independently deployable.
            </p>
            <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11px]">
              <div className="rounded border border-sky-400/20 bg-sky-500/[0.04] px-2 py-1">
                <span className="text-sky-200">forecast-api</span>
                <div className="text-white/55">port 8000</div>
              </div>
              <div className="rounded border border-purple-400/20 bg-purple-500/[0.04] px-2 py-1">
                <span className="text-purple-200">ingestion</span>
                <div className="text-white/55">port 8003</div>
              </div>
              <div className="rounded border border-amber-300/20 bg-amber-500/[0.04] px-2 py-1">
                <span className="text-amber-200">warehouse</span>
                <div className="text-white/55">port 8004</div>
              </div>
              <div className="rounded border border-emerald-300/20 bg-emerald-300/[0.04] px-2 py-1">
                <span className="text-emerald-100">observability</span>
                <div className="text-white/55">Grafana :3002</div>
              </div>
            </div>
          </div>

          <div className="flex items-center text-white/30">
            <ArrowRight className="h-5 w-5" />
          </div>

          <div className="rounded-lg border border-emerald-300/25 bg-emerald-300/[0.04] p-3">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-emerald-100">
              <LineChart className="h-4 w-4" /> Dashboard (this app)
            </div>
            <p className="text-[12px] text-white/65">
              Next.js 14 (App Router, static export, CDN-deployable). LazyMotion + GSAP for animated visualisations. shadcn/ui + Tailwind for components. Trailing slashes for clean URLs.
            </p>
            <div className="mt-2 space-y-1 text-[11px] text-white/55">
              <div>• 14 dashboard pages + login</div>
              <div>• Internal BFF proxies to backend services</div>
              <div>• 30-60s Redis cache on read endpoints</div>
              <div>• Browser never touches the data warehouse directly</div>
            </div>
          </div>
        </div>
      </Card>

      <Card title="Why REST, not GraphQL or gRPC?" subtitle="Decoupled frontend from backend implementation.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-emerald-200/15 bg-emerald-200/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-emerald-100">REST wins</div>
            <ul className="space-y-1.5 text-[12px] text-white/70">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Each backend service owns its data + endpoints
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Frontend talks to whichever service owns the data
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Easy to add another client (CLI, mobile, BI tool)
              </li>
            </ul>
          </div>
          <div className="rounded-lg border border-amber-400/15 bg-amber-500/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-amber-200">Frontend benefits</div>
            <ul className="space-y-1.5 text-[12px] text-white/70">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                No direct DB access — backend can change schema freely
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Backend retries, caching, pagination are transparent
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-200" />
                Auth + authorisation enforced server-side
              </li>
            </ul>
          </div>
          <div className="rounded-lg border border-purple-400/15 bg-purple-500/[0.03] p-3">
            <div className="mb-1 text-sm font-medium text-purple-200">When to revisit</div>
            <ul className="space-y-1.5 text-[12px] text-white/70">
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If a page needs 8+ endpoints in one render (over-fetch)
              </li>
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If mobile clients need bandwidth optimisation
              </li>
              <li className="flex items-start gap-2">
                <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-white/40" />
                If many UI permutations make static endpoints too rigid
              </li>
            </ul>
          </div>
        </div>
      </Card>

      <Card title="Visualisation strategy" subtitle="Data is easier to read when it's drawn, not tabulated.">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-center">
            <LineChart className="mx-auto mb-1 h-5 w-5 text-emerald-100" />
            <div className="text-[11px] font-medium text-white">Timeseries</div>
            <div className="text-[10px] text-white/55">Demand, emissions, intensity</div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-center">
            <BarChart3 className="mx-auto mb-1 h-5 w-5 text-emerald-100" />
            <div className="text-[11px] font-medium text-white">By-source breakdown</div>
            <div className="text-[10px] text-white/55">Coal / gas / wind / solar</div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-center">
            <TrendingUp className="mx-auto mb-1 h-5 w-5 text-emerald-100" />
            <div className="text-[11px] font-medium text-white">Fan charts</div>
            <div className="text-[10px] text-white/55">P10–P90 with P50 line</div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-center">
            <Filter className="mx-auto mb-1 h-5 w-5 text-emerald-100" />
            <div className="text-[11px] font-medium text-white">Sparklines</div>
            <div className="text-[10px] text-white/55">Compact trend in tables</div>
          </div>
        </div>
        <p className="mt-3 text-[12px] text-white/65">
          Every chart uses <span className="font-medium text-white">useReducedMotion()</span> and respects the user's system motion preference. Animations are spring-eased, never linear, so they feel natural. Hover tooltips show the underlying numbers so users can verify what they're seeing.
        </p>
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Page
// ───────────────────────────────────────────────────────────────────────

export default function ArchitecturePage() {
  const [active, setActive] = useState<TabId>("pipeline");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <span className="text-emerald-100">
            <Workflow className="h-6 w-6" />
          </span>
          Platform Architecture
        </h1>
        <p className="mt-1 text-sm text-white/60">
          How ecoLens works end-to-end — from external energy APIs to the dashboard in front of you.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1 border-b border-white/5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t.id)}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
              active === t.id
                ? "border-emerald-200 text-emerald-100"
                : "border-transparent text-white/60 hover:text-white",
            )}
            data-testid={`arch-tab-${t.id}`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {active === "pipeline"  && <PipelineTab />}
      {active === "anomaly"   && <AnomalyTab />}
      {active === "ml"        && <MlTab />}
      {active === "storage"   && <StorageTab />}
      {active === "frontend"  && <FrontendTab />}
    </div>
  );
}
