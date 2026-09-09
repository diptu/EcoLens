/**
 * /architecture — End-to-End Model Architecture.
 *
 * Purely presentational — no live data fetches, no loading states. The
 * 7-stage flow (data sources → ingestion → warehouse → training →
 * registry → serving → dashboard), the registered-model table, the
 * services/ports, and the "honest gaps" section are all a direct
 * rendering of `docs/architecture/model-architecture.md` (the
 * repo-root doc this page is kept in sync with) — every real name
 * (`ml/train.py`, `training.trigger`, `lstm_demand`, `:8003`, ...) is
 * copied from there, not re-derived or guessed independently. Built
 * from a reference infographic (`ChatGPT Image Sep 9, 2026, 06_52_10
 * PM.png`) for the section layout/flow, adapted to this dashboard's
 * own dark theme and `Card`/`Pill` components rather than the
 * reference's literal light-theme colors — same "match structure, not
 * literal pixels" precedent Analytics & Forecast's own reference image
 * followed.
 *
 * The "Deep Learning Model Architecture" section (between Model
 * Training and MLflow Model Registry) has the same "match layout,
 * verify every number" treatment against a second reference image
 * (`ChatGPT Image Sep 9, 2026, 07_05_18 PM.png`) — several of that
 * image's specific numbers turned out not to match `app/models/ml.py`'s
 * real `DemandLSTM` (it depicts two *different*-sized LSTM layers, 128
 * then 64, and 3 independent symmetric quantile heads; the real model
 * is a single 2-layer stacked `nn.LSTM` at 128 hidden units on both
 * layers, and a point head plus two structurally non-negative spread
 * heads, not 3 independent heads) — this section uses the real ones
 * instead, read directly from `app/models/ml.py`,
 * `app/service/ml/features.py`, and `app/service/ml/train.py`.
 *
 * "LSTM Cell — inside one time step" is a third reference pass
 * (`Gemini_Generated_Image_36bx5h36bx5h36bx.jpeg`) — that image was
 * mostly fake chrome around a generic template (a browser/Miro-
 * whiteboard mockup, garbled "Deploymention"/"Monitoringr" labels,
 * non-real "BDN"/"Ms" data-source icons matching nothing in this
 * codebase), so none of that was carried over. The one real, useful,
 * verifiable thing in it was the gate-level LSTM cell view — added
 * here using the standard `nn.LSTM` equations (Hochreiter &
 * Schmidhuber 1997, universal, not repo-specific), consistent with the
 * tensor shapes already established as real.
 *
 * **Rescoped 2026-09-09** (explicit request): this section now covers
 * only the "Train model (PyTorch) — DemandLSTM / DemandTFT" and
 * "Conformal calibration (CQR)" steps from the Model Training flow
 * above — the Input Features / Feature Engineering sub-sections it
 * used to also carry (both real, just belonging to that flow's earlier
 * "Load data"/"Build features" steps, not "Train model") were removed
 * for scope, not accuracy. `DemandTFT`'s own real architecture
 * (`app/models/tft.py` — Variable Selection Networks, encoder/decoder
 * LSTMs, gated skip connection, static enrichment, interpretable
 * multi-head attention, the same point+2-spread-head output contract
 * as `DemandLSTM`) was added at the same time, since "Train model"
 * names both architectures and only `DemandLSTM`'s had been diagrammed
 * before this pass.
 *
 * The LSTM card's layer-by-layer tensor-shape flow (Input →
 * Layer 1 → Layer 2 → `lstm_out`) is a fourth reference pass
 * (`Gemini_Generated_Image_p848d3p848d3p848.jpeg`) — same fake
 * browser/Miro chrome as the third image, but its core content (a
 * layer-by-layer shape breakdown) was worth verifying rather than
 * discarding outright. Its specific `h_n`/`c_n` shapes turned out
 * wrong: it showed `(B,24,37)`/`(B,24,128)`; a real
 * `nn.LSTM(input_size=37, hidden_size=128, num_layers=2)` call
 * (verified live via `forecast-api`'s own `.venv` PyTorch, not assumed)
 * returns `(num_layers, B, hidden_size)` = `(2, B, 128)` for each —
 * corrected here. More to the point, `DemandLSTM.forward` never uses
 * `h_n`/`c_n` at all (`lstm_out, _ = self.lstm(x)`) — shown as a
 * real, called-out detail rather than silently included as if it fed
 * something downstream.
 *
 * "Neural Network Fundamentals" (right before the DemandLSTM
 * subsection) started as a fifth reference pass -- a generic textbook
 * "Neural Network Architecture" diagram (a plain fully-connected
 * input/hidden/output-layer network + a single node's z=Σw·x+b -> f(z)
 * computation) -- reproduced with two real corrections: the `nn.Linear`
 * building block framing (not a claim `DemandLSTM`/`DemandTFT`
 * themselves are feedforward, both are recurrent) and the 4 real
 * activation functions this codebase actually uses in place of a
 * generic unlabeled "f(z)" (σ/tanh/softplus/softmax, checked against
 * `app/models/ml.py`/`tft.py`).
 *
 * **Rebuilt 2026-09-09** (explicit follow-up request) to use our own
 * `DemandLSTM`'s real layer sizes (Input F=37, Hidden 128×2 stacked
 * layers, Output 3 heads) instead of a generic 4-3-2 network, and
 * extended with a real input → hidden → output → calibration flow plus
 * a real pruning explanation. Pruning (`ml/prune.py`'s `compact_lstm`)
 * is drawn as a branch off the Hidden box, not inline in the main
 * arrow chain — it's a real, LSTM-only, between-training-runs weight-
 * compaction operation on an already-registered version (ranks the 128
 * units by L-norm importance, grouped correctly across each unit's 4
 * non-contiguous gate-block rows, physically drops the lowest-ranked
 * ones' rows *and* columns, then recovery-fine-tunes — a real
 * `keep_fraction=0.5` example run is 128→64 units), not a step that
 * runs on every single inference the way the rest of the chain does.
 *
 * Route history: this replaces the old `/dashboard/architecture` (a
 * different, tabbed "Pipeline Overview/Anomaly Detection/ML Lifecycle/
 * Storage Strategy/Frontend & API" page, disabled 2026-09-09 as
 * redundant) — that route now redirects here rather than 404ing, since
 * "Architecture" is a real concept in this app again, just with
 * different, more specific content this time.
 */
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  Bell,
  BookOpen,
  Boxes,
  Calendar,
  CheckCircle2,
  Cloud,
  Cpu,
  Database,
  Eye,
  FileCode2,
  FileText,
  GitBranch,
  Layers,
  Link2,
  Minus,
  Monitor,
  Network,
  Percent,
  Plus,
  Radio,
  Server,
  ShieldCheck,
  Sigma,
  Sparkles,
  Timer,
  Upload,
  Workflow,
} from "lucide-react";

import { Card } from "@/components/dashboard/card";
import { Pill } from "@/components/dashboard/data-table";
import { cn } from "@/lib/utils";

type Accent = "sky" | "emerald" | "amber" | "purple" | "lime" | "rose";

const ACCENT_BORDER: Record<Accent, string> = {
  sky: "border-sky-400/25",
  emerald: "border-emerald-200/25",
  amber: "border-amber-400/25",
  purple: "border-purple-400/25",
  lime: "border-lime-200/25",
  rose: "border-rose-400/25",
};
const ACCENT_BADGE: Record<Accent, string> = {
  sky: "border-sky-400/40 bg-sky-400/10 text-sky-300",
  emerald: "border-emerald-200/40 bg-emerald-200/10 text-emerald-100",
  amber: "border-amber-400/40 bg-amber-400/10 text-amber-300",
  purple: "border-purple-400/40 bg-purple-400/10 text-purple-300",
  lime: "border-lime-200/40 bg-lime-200/10 text-lime-100",
  rose: "border-rose-400/40 bg-rose-400/10 text-rose-300",
};

const STAGES: { n: number; label: string; accent: Accent }[] = [
  { n: 1, label: "Data Sources", accent: "sky" },
  { n: 2, label: "Ingestion", accent: "emerald" },
  { n: 3, label: "Warehouse", accent: "amber" },
  { n: 4, label: "Training", accent: "purple" },
  { n: 5, label: "Registry", accent: "lime" },
  { n: 6, label: "Serving", accent: "sky" },
  { n: 7, label: "Dashboard", accent: "purple" },
];

function SectionBadge({ n, accent }: { n: number; accent: Accent }) {
  return (
    <span
      className={cn(
        "grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs font-bold",
        ACCENT_BADGE[accent],
      )}
    >
      {n}
    </span>
  );
}

function MiniBox({
  icon: Icon,
  label,
  sub,
  accent = "emerald",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  sub?: string;
  accent?: Accent;
}) {
  return (
    <div className={cn("rounded-lg border bg-white/[0.02] px-3 py-2.5", ACCENT_BORDER[accent])}>
      <Icon className={cn("h-4 w-4", ACCENT_BADGE[accent].split(" ").pop())} />
      <div className="mt-1.5 text-xs font-semibold text-white">{label}</div>
      {sub && <div className="mt-0.5 text-[10.5px] leading-snug text-white/50">{sub}</div>}
    </div>
  );
}

function FlowStep({ icon: Icon, label }: { icon: React.ComponentType<{ className?: string }>; label: string }) {
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-[11px] text-white/80">
      <Icon className="h-3.5 w-3.5 text-white/50" />
      {label}
    </div>
  );
}

function FlowArrow() {
  return <ArrowRight className="h-3.5 w-3.5 shrink-0 text-white/25" />;
}

export default function ArchitecturePage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <Workflow className="h-6 w-6 text-emerald-100" />
            End-to-End Model Architecture
          </h1>
          <p className="mt-1 text-sm text-white/60">
            From real electricity-market data to a served demand forecast — every stage below is
            real, verified against the live code in <code className="rounded bg-black/30 px-1 font-mono text-[11px]">services/ingestion/</code>,{" "}
            <code className="rounded bg-black/30 px-1 font-mono text-[11px]">services/waerehouse/</code>, and{" "}
            <code className="rounded bg-black/30 px-1 font-mono text-[11px]">services/forecast-api/</code>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {STAGES.map((s, i) => (
            <span key={s.n} className="flex items-center gap-1.5">
              <Pill color={s.accent}>
                {s.n}. {s.label}
              </Pill>
              {i < STAGES.length - 1 && <ArrowRight className="h-3 w-3 text-white/20" />}
            </span>
          ))}
        </div>
      </div>

      {/* 1. Real Data Sources */}
      <Card
        className={cn("border", ACCENT_BORDER.sky)}
        title={
          <span className="flex items-center gap-2.5">
            <SectionBadge n={1} accent="sky" /> Real Data Sources
          </span>
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <MiniBox icon={Radio} label="AEMO NEM Web" sub="dispatch, 5-min, archive" accent="sky" />
          <MiniBox icon={Radio} label="AEMO WEM" sub="WA balancing market" accent="sky" />
          <MiniBox icon={Cloud} label="Bureau of Meteorology" sub="Open-Meteo ERA5 archive" accent="sky" />
          <MiniBox icon={Network} label="OpenElectricity" sub="network mix + emissions API" accent="sky" />
          <MiniBox icon={Calendar} label="AEMO Public Holidays" sub="annual snapshot" accent="sky" />
        </div>
      </Card>

      {/* 2. Ingestion */}
      <Card
        className={cn("border", ACCENT_BORDER.emerald)}
        title={
          <span className="flex items-center gap-2.5">
            <SectionBadge n={2} accent="emerald" /> Ingestion
          </span>
        }
        subtitle="services/ingestion — FastAPI :8003 + Celery worker/beat"
      >
        <div className="flex flex-wrap items-center gap-2">
          <FlowStep icon={Upload} label="Fetch from APIs" />
          <FlowArrow />
          <FlowStep icon={CheckCircle2} label="Validate & parse" />
          <FlowArrow />
          <FlowStep icon={ShieldCheck} label="Hybrid anomaly scan (z-score + isolation forest)" />
          <FlowArrow />
          <FlowStep icon={Database} label="Stage in DuckDB (shared)" />
          <FlowArrow />
          <FlowStep icon={Boxes} label="Upload to object storage (R2 / MinIO)" />
          <FlowArrow />
          <FlowStep icon={Bell} label="Publish landed-event to RabbitMQ" />
        </div>
        <p className="mt-3 text-[11px] text-white/40">
          &quot;Flag, never remove&quot; — anomalies are surfaced, not silently dropped from the real
          dataset.
        </p>
      </Card>

      {/* 3. Warehouse */}
      <Card
        className={cn("border", ACCENT_BORDER.amber)}
        title={
          <span className="flex items-center gap-2.5">
            <SectionBadge n={3} accent="amber" /> Warehouse
          </span>
        }
        subtitle="services/waerehouse — FastAPI :8004 + RabbitMQ consumer"
      >
        <div className="flex flex-wrap items-center gap-2">
          <FlowStep icon={Bell} label="Consume from RabbitMQ" />
          <FlowArrow />
          <FlowStep icon={Database} label="asyncpg COPY into Postgres raw.* (ON CONFLICT DO NOTHING)" />
          <FlowArrow />
          <FlowStep icon={FileText} label="meta._ingest_log" />
          <FlowArrow />
          <FlowStep icon={Layers} label="dbt build (staging → intermediate → marts)" />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Staging</div>
            <ul className="mt-1.5 space-y-0.5 font-mono text-[11px] text-white/70">
              <li>stg_aemo_nem_dispatch</li>
              <li>stg_aemo_wem_dispatch</li>
              <li>stg_openelectricity_mix</li>
              <li className="text-white/35">...</li>
            </ul>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Intermediate</div>
            <ul className="mt-1.5 space-y-0.5 font-mono text-[11px] text-white/70">
              <li>int_demand_with_weather</li>
              <li>int_carbon_intensity</li>
              <li>int_fuel_emissions</li>
            </ul>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-white/50">Marts</div>
            <ul className="mt-1.5 space-y-0.5 font-mono text-[11px] text-white/70">
              <li>fct_energy_demand</li>
              <li>fct_carbon_intensity</li>
              <li>fct_emissions_5min</li>
            </ul>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
          <Database className="h-3.5 w-3.5 text-amber-300" />
          Postgres (Neon) — <code className="font-mono">raw.*</code> / <code className="font-mono">raw_marts.*</code>
          <span className="mx-1 text-white/25">·</span>
          real-time reads (serving) + training queries
        </div>
        <p className="mt-2 text-[11px] text-white/40">
          dbt build success → publishes <code className="rounded bg-black/30 px-1 font-mono">training.trigger</code>{" "}
          (RabbitMQ, routing key <code className="rounded bg-black/30 px-1 font-mono">training.trigger</code>, queue{" "}
          <code className="rounded bg-black/30 px-1 font-mono">forecasting.training.trigger</code>)
        </p>
      </Card>

      {/* 4. Model Training */}
      <Card
        className={cn("border", ACCENT_BORDER.purple)}
        title={
          <span className="flex items-center gap-2.5">
            <SectionBadge n={4} accent="purple" /> Model Training
          </span>
        }
        subtitle="services/forecast-api — train-worker container (same image as the serving API)"
      >
        <div className="flex flex-wrap items-center gap-2">
          <FlowStep icon={Database} label="Load data (raw_marts)" />
          <FlowArrow />
          <FlowStep icon={Sparkles} label="Build features (calendar, weather, cross-region, lags)" />
          <FlowArrow />
          <FlowStep icon={Cpu} label="Train model (PyTorch) — DemandLSTM / DemandTFT" />
          <FlowArrow />
          <FlowStep icon={ShieldCheck} label="Conformal calibration (CQR)" />
          <FlowArrow />
          <FlowStep icon={Activity} label="Evaluate (walk-forward vs. BaselineForecaster)" />
          <FlowArrow />
          <FlowStep icon={GitBranch} label="Log run + register version" />
        </div>
      </Card>

      {/* Deep Learning Model Architecture — scoped deliberately narrow
          (2026-09-09, explicit request): only the "Train model (PyTorch)
          — DemandLSTM / DemandTFT" and "Conformal calibration (CQR)"
          steps from the Model Training flow above, not the whole
          pipeline -- Input Features / Feature Engineering (real, but
          those belong to "Load data"/"Build features", earlier steps
          in that same flow) were removed from here for that reason, not
          because they stopped being real.
          Every number is read directly from the real model source, not
          the reference images this section's layout has followed
          across three passes: `app/models/ml.py` (`DemandLSTM`) and
          `app/models/tft.py` (`DemandTFT`) for the two architectures,
          `app/service/ml/conformal.py` for calibration. */}
      <div className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.015] p-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold text-white">
            <Cpu className="h-5 w-5 text-emerald-100" /> Deep Learning Model Architecture
          </h2>
          <p className="mt-0.5 text-xs text-white/50">
            Scoped to two steps only: <span className="text-white/70">Train model (PyTorch) —</span>{" "}
            <code className="rounded bg-black/30 px-1 font-mono">DemandLSTM</code> /{" "}
            <code className="rounded bg-black/30 px-1 font-mono">DemandTFT</code>, and{" "}
            <span className="text-white/70">Conformal calibration (CQR)</span> that follows it
          </p>
        </div>

        {/* Neural Network Fundamentals — rebuilt 2026-09-09 (explicit
            request) around our own real DemandLSTM's real
            input/hidden/output sizes instead of a generic 4-3-2
            textbook illustration, and extended to cover the two real
            operations that sit either side of a plain forward pass:
            pruning (a real, LSTM-only, between-training-runs weight-
            compaction operation on the hidden layer -- `ml/prune.py`'s
            `compact_lstm`, not part of a single inference call) and
            conformal calibration (a real post-processing step on the
            output, already covered in its own card below -- referenced
            here to complete the flow, not duplicated in full). */}
        <Card
          className={cn("border", ACCENT_BORDER.lime)}
          title="Neural Network Fundamentals"
          subtitle="Our real DemandLSTM's own input/hidden/output sizes — not a generic textbook network"
        >
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <svg viewBox="0 0 340 210" className="w-full" role="img" aria-label="Our DemandLSTM's real input, hidden, and output layer sizes">
                {[
                  [30, 30, 170, 50], [30, 30, 170, 105], [30, 30, 170, 160],
                  [30, 75, 170, 50], [30, 75, 170, 105], [30, 75, 170, 160],
                  [30, 120, 170, 50], [30, 120, 170, 105], [30, 120, 170, 160],
                  [30, 165, 170, 50], [30, 165, 170, 105], [30, 165, 170, 160],
                  [170, 50, 310, 65], [170, 50, 310, 105], [170, 50, 310, 145],
                  [170, 105, 310, 65], [170, 105, 310, 105], [170, 105, 310, 145],
                  [170, 160, 310, 65], [170, 160, 310, 105], [170, 160, 310, 145],
                ].map(([x1, y1, x2, y2], i) => (
                  <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,0.1)" strokeWidth={1} />
                ))}
                {[30, 75, 120, 165].map((y, i) => (
                  <circle key={`in-${i}`} cx={30} cy={y} r={8} fill="#6ee7b7" />
                ))}
                <text x={30} y={192} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">···</text>
                {[50, 105, 160].map((y, i) => (
                  <circle key={`hid-${i}`} cx={170} cy={y} r={8} fill="#7dd3fc" />
                ))}
                <text x={170} y={192} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">···</text>
                {[65, 105, 145].map((y, i) => (
                  <circle key={`out-${i}`} cx={310} cy={y} r={8} fill="#fca5a5" />
                ))}
                <text x={30} y={207} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.4)">Input (F=37)</text>
                <text x={170} y={207} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.4)">Hidden (×128, ×2 layers)</text>
                <text x={310} y={207} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.4)">Output (3)</text>
              </svg>
            </div>

            <div className="flex flex-col justify-center gap-2.5">
              <div className="rounded-lg border border-lime-200/25 bg-lime-200/[0.05] p-3">
                <div className="text-[11px] font-semibold text-white/85">One node&apos;s computation</div>
                <p className="mt-1.5 font-mono text-[12px] text-lime-100">z = Σ(wᵢ·xᵢ) + b</p>
                <p className="mt-1 font-mono text-[12px] text-lime-100">output = f(z)</p>
                <p className="mt-1.5 text-[10.5px] text-white/45">
                  this is exactly what one real <code className="font-mono">nn.Linear</code> unit
                  computes — every gate/head below is built from these
                </p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                <div className="text-[11px] font-semibold text-white/80">
                  Real f — no generic unlabeled activation, this codebase uses 4:
                </div>
                <ul className="mt-1.5 space-y-1 text-[10.5px] text-white/55">
                  <li>
                    <code className="font-mono text-sky-300">σ (sigmoid)</code> — LSTM forget/input/output
                    gates
                  </li>
                  <li>
                    <code className="font-mono text-sky-300">tanh</code> — LSTM candidate values +
                    hidden-state output
                  </li>
                  <li>
                    <code className="font-mono text-sky-300">softplus</code> — every spread head
                    (guarantees a non-negative P10/P90 spread)
                  </li>
                  <li>
                    <code className="font-mono text-sky-300">softmax</code> — AttentionPool
                  </li>
                </ul>
              </div>
            </div>
          </div>

          {/* Full real flow: input -> hidden -> output -> calibration,
              with pruning called out as a real but *separate*
              operation on the hidden layer (a between-training-runs
              weight-compaction step, not part of any single forward
              pass) -- shown as a branch off Hidden rather than inline
              in the main arrow chain, so the diagram doesn't
              misrepresent pruning as something that runs on every
              inference. */}
          <div className="mt-4 border-t border-white/10 pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <MiniBox icon={Boxes} label="Input (F=37)" accent="emerald" />
              <FlowArrow />
              <MiniBox icon={Layers} label="Hidden — LSTM ×2, 128 units" accent="sky" />
              <FlowArrow />
              <MiniBox icon={GitBranch} label="Output — 3 heads (P10/P50/P90)" accent="rose" />
              <FlowArrow />
              <MiniBox icon={ShieldCheck} label="Conformal Calibration (CQR)" accent="amber" />
            </div>
            <div className="mt-2.5 flex items-start gap-2 rounded-lg border border-purple-400/20 bg-purple-400/[0.04] p-2.5">
              <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 rotate-180 text-purple-300" />
              <div className="text-[10.5px] text-white/55">
                <span className="font-semibold text-purple-200">Pruning</span> (
                <code className="font-mono">ml/prune.py</code>&apos;s <code className="font-mono">compact_lstm</code>) is a
                real operation on the <span className="text-white/75">Hidden</span> layer above, not a per-inference
                step — offline, between training runs, on an already-registered <code className="font-mono">DemandLSTM</code>{" "}
                version only (real, stated exemption: not TFT, not TimesFM). Ranks the 128 hidden units by
                L-norm importance (grouped correctly across all 4 gate blocks — a unit&apos;s row spans 4
                non-contiguous offsets in <code className="font-mono">weight_hh</code>), physically drops the
                lowest-ranked ones&apos; rows <span className="italic">and</span> columns (removing a unit&apos;s
                own output and its influence on every other unit&apos;s next-step input), then recovery-fine-tunes
                the compacted model. Real example: <code className="font-mono">keep_fraction=0.5</code> → 128 → 64
                units, a real parameter-count and on-disk-size reduction (physical compaction, not zero-masking).
              </div>
            </div>
          </div>
        </Card>

        {/* DemandLSTM */}
        <div className="rounded-xl border border-sky-400/15 bg-sky-400/[0.02] p-3">
          <div className="mb-2 flex items-center gap-2 px-1">
            <span className="rounded border border-sky-400/40 bg-sky-400/10 px-1.5 py-0.5 font-mono text-[10.5px] text-sky-300">
              DemandLSTM
            </span>
            <span className="text-[11px] text-white/40">app/models/ml.py — Production, live</span>
          </div>

          {/* Layer-by-layer tensor shapes (2026-09-09 addition) —
              empirically confirmed against a real `nn.LSTM(input_size=37,
              hidden_size=128, num_layers=2, batch_first=True)` call
              (`.venv/bin/python3`, real PyTorch, not assumed): a
              reference diagram for this same view had `h_n`/`c_n`
              shaped `(B,24,37)`/`(B,24,128)` -- wrong on both counts,
              real PyTorch returns `(num_layers, B, hidden_size)` =
              `(2, B, 128)` for each. More importantly, `DemandLSTM.
              forward` (`lstm_out, _ = self.lstm(x)`) discards `(h_n,
              c_n)` entirely -- only the full per-timestep `lstm_out`
              feeds `AttentionPool` below, so showing `h_n`/`c_n` as if
              they were a real, used output would itself be misleading
              regardless of their shape. */}
          <Card className={cn("border", ACCENT_BORDER.sky)} title="LSTM (Sequence Modeling)">
            <div className="flex flex-wrap items-center gap-2">
              <MiniBox icon={Boxes} label="Input (B, T=24, F=37)" accent="sky" />
              <FlowArrow />
              <FlowStep icon={Layers} label="LSTM Layer 1 — hidden_size=128" />
              <FlowArrow />
              <MiniBox icon={Boxes} label="(B, T=24, 128)" accent="sky" />
              <FlowArrow />
              <FlowStep icon={Layers} label="LSTM Layer 2 — hidden_size=128" />
              <FlowArrow />
              <MiniBox icon={Boxes} label="lstm_out (B, T=24, 128)" accent="sky" />
            </div>
            <p className="mt-2 text-[10.5px] text-white/40">
              dropout 0.25 applied between layers (real <code className="font-mono">TrainConfig</code>{" "}
              default — the class&apos;s own default is 0.2, tunable via <code className="font-mono">make tune</code>)
            </p>
            <div className="mt-2.5 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] p-2.5 text-[10.5px] text-white/55">
              <span className="font-semibold text-amber-200">Real, easy-to-miss detail:</span>{" "}
              <code className="font-mono">nn.LSTM</code> also returns final states{" "}
              <code className="font-mono">(h_n, c_n)</code>, each shaped{" "}
              <code className="font-mono">(num_layers=2, B, 128)</code> — but{" "}
              <code className="font-mono">DemandLSTM.forward</code> discards both (
              <code className="font-mono">lstm_out, _ = self.lstm(x)</code>). Only the full per-timestep{" "}
              <code className="font-mono">lstm_out</code> above ever reaches attention below.
            </div>
          </Card>

          <Card className={cn("border", ACCENT_BORDER.emerald)} title="Attention (always applied)">
            <div className="flex items-center gap-3">
              <div className="flex-1 rounded-lg border border-emerald-200/25 bg-emerald-200/[0.06] p-3">
                <div className="flex items-center gap-1.5 text-[12px] font-semibold text-white">
                  <Eye className="h-3.5 w-3.5 text-emerald-200" /> AttentionPool
                </div>
                <p className="mt-1 text-[10.5px] text-white/50">
                  Linear(128→1) → softmax over time steps → weighted sum
                </p>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-white/25" />
              <MiniBox icon={Boxes} label="Context Vector (B, 128)" accent="emerald" />
            </div>
            <p className="mt-2 text-[10.5px] text-white/40">
              Not gated behind a flag — every real forward pass pools the full sequence through
              this same learned attention, over <code className="font-mono">lstm_out</code>&apos;s all
              24 real time steps.
            </p>
          </Card>

          {/* LSTM cell internals — the standard gate equations `nn.LSTM`
              runs at every one of the 24 real time steps, for both of
              the 2 real stacked layers. Universal LSTM math (Hochreiter
              & Schmidhuber 1997), not repo-specific beyond the tensor
              shapes already confirmed above. */}
          <Card
            className={cn("mt-3 border", ACCENT_BORDER.sky)}
            title="LSTM Cell — inside one time step"
            subtitle="Standard nn.LSTM gate equations, run once per real time step (T=24) per stacked layer"
          >
            <div className="flex flex-wrap items-center gap-2">
              <MiniBox icon={Boxes} label="xₜ" sub="input at this step" accent="sky" />
              <MiniBox icon={Boxes} label="hₜ₋₁" sub="prev. hidden state" accent="sky" />
              <MiniBox icon={Boxes} label="Cₜ₋₁" sub="prev. cell state" accent="sky" />
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Forget gate</div>
                <p className="mt-1 font-mono text-[10.5px] text-white/55">fₜ = σ(Wf·[hₜ₋₁,xₜ]+bf)</p>
                <p className="mt-1 text-[10px] text-white/35">how much of Cₜ₋₁ to keep</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Input gate</div>
                <p className="mt-1 font-mono text-[10.5px] text-white/55">iₜ = σ(Wi·[hₜ₋₁,xₜ]+bi)</p>
                <p className="mt-1 text-[10px] text-white/35">how much new info to add</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Candidate</div>
                <p className="mt-1 font-mono text-[10.5px] text-white/55">C̃ₜ = tanh(Wc·[hₜ₋₁,xₜ]+bc)</p>
                <p className="mt-1 text-[10px] text-white/35">new candidate values</p>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/[0.02] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Output gate</div>
                <p className="mt-1 font-mono text-[10.5px] text-white/55">oₜ = σ(Wo·[hₜ₋₁,xₜ]+bo)</p>
                <p className="mt-1 text-[10px] text-white/35">how much of Cₜ to expose</p>
              </div>
            </div>
            <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div className="rounded-lg border border-sky-400/20 bg-sky-400/[0.04] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Cell state update</div>
                <p className="mt-1 font-mono text-[10.5px] text-sky-200">Cₜ = fₜ⊙Cₜ₋₁ + iₜ⊙C̃ₜ</p>
              </div>
              <div className="rounded-lg border border-sky-400/20 bg-sky-400/[0.04] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Hidden state</div>
                <p className="mt-1 font-mono text-[10.5px] text-sky-200">hₜ = oₜ⊙tanh(Cₜ)</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <MiniBox icon={Boxes} label="hₜ, Cₜ" sub="→ carried to step t+1" accent="sky" />
              <ArrowRight className="h-4 w-4 text-white/25" />
              <span className="text-[10.5px] text-white/40">
                repeated for all 24 real time steps, then for both stacked layers (hₜ from layer 1
                feeds layer 2 as its own xₜ)
              </span>
            </div>
          </Card>

          <Card
            className={cn("mt-3 border", ACCENT_BORDER.rose)}
            title="Multi-Output Head"
            subtitle="Point head + 2 spread heads — not 3 independent quantile heads"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-rose-400/25 bg-rose-400/[0.05] p-3">
                <div className="text-[12px] font-semibold text-white">Lower Spread Head</div>
                <p className="mt-1 text-[10.5px] text-white/50">
                  Linear → softplus (always ≥ 0) → pinball loss, q=0.1
                </p>
                <p className="mt-1 font-mono text-[10.5px] text-rose-200">P10 = P50 − spread</p>
              </div>
              <div className="rounded-lg border border-rose-400/25 bg-rose-400/[0.05] p-3">
                <div className="text-[12px] font-semibold text-white">Point Head</div>
                <p className="mt-1 text-[10.5px] text-white/50">Linear → pinball loss, q=0.5 (true median)</p>
                <p className="mt-1 font-mono text-[10.5px] text-rose-200">P50</p>
              </div>
              <div className="rounded-lg border border-rose-400/25 bg-rose-400/[0.05] p-3">
                <div className="text-[12px] font-semibold text-white">Upper Spread Head</div>
                <p className="mt-1 text-[10.5px] text-white/50">
                  Linear → softplus (always ≥ 0) → pinball loss, q=0.9
                </p>
                <p className="mt-1 font-mono text-[10.5px] text-rose-200">P90 = P50 + spread</p>
              </div>
            </div>
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-white/40">
              <Plus className="h-3 w-3" />
              <Minus className="h-3 w-3 -ml-1" />
              Since the spreads are structurally non-negative, P10 ≤ P50 ≤ P90 is guaranteed by
              construction, not just by training.
            </p>
          </Card>
        </div>

        {/* DemandTFT — real architecture read from app/models/tft.py's
            own module docstring + DemandTFT.__init__/forward. Hand-
            rolled (not pytorch-forecasting, to avoid reintroducing a
            PyTorch Lightning dependency this repo already rejected for
            DemandLSTM) and per-region (one model instance per NEM
            region, mirroring DemandLSTM's own convention) -- a real,
            direct consequence: this v0 has no static covariates left to
            encode once region is fixed per instance, so
            static_enrichment's real input is always a zero vector
            today, a documented no-op rather than silently implied as
            already useful. */}
        <div className="rounded-xl border border-purple-400/15 bg-purple-400/[0.02] p-3">
          <div className="mb-2 flex items-center gap-2 px-1">
            <span className="rounded border border-purple-400/40 bg-purple-400/10 px-1.5 py-0.5 font-mono text-[10.5px] text-purple-300">
              DemandTFT
            </span>
            <span className="text-[11px] text-white/40">
              app/models/tft.py — registered, experimental (hand-rolled Temporal Fusion Transformer,
              Lim et al. 2019)
            </span>
          </div>

          <Card className={cn("border", ACCENT_BORDER.purple)} title="Variable Selection → Encoder/Decoder LSTM">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-purple-400/20 bg-purple-400/[0.04] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Encoder path</div>
                <p className="mt-1 text-[10.5px] text-white/50">
                  Input (B, lookback=24, n_encoder_features) — observed-past + known-future columns
                </p>
                <p className="mt-1 text-[10.5px] text-white/50">
                  → Encoder VSN → <code className="font-mono">nn.LSTM(64, 64)</code>
                </p>
              </div>
              <div className="rounded-lg border border-purple-400/20 bg-purple-400/[0.04] p-2.5">
                <div className="text-[11px] font-semibold text-white/85">Decoder path</div>
                <p className="mt-1 text-[10.5px] text-white/50">
                  Input (B, horizon=48, n_decoder_features) — known-future columns only (never sees
                  observed-past-only features for future steps)
                </p>
                <p className="mt-1 text-[10.5px] text-white/50">
                  → Decoder VSN → <code className="font-mono">nn.LSTM(64, 64)</code>, seeded from the
                  encoder&apos;s final (h, c)
                </p>
              </div>
            </div>
          </Card>

          <Card className={cn("mt-3 border", ACCENT_BORDER.purple)} title="Static Enrichment → Interpretable Attention → Output">
            <div className="flex flex-wrap items-center gap-2">
              <FlowStep icon={GitBranch} label="Gated skip connection (GLU + LayerNorm) — seq-to-seq layer" />
              <FlowArrow />
              <FlowStep icon={Layers} label="Static enrichment (GRN) — always zero context in this v0" />
              <FlowArrow />
              <FlowStep icon={Eye} label="Interpretable multi-head self-attention (4 heads, causal-masked, shared value projection)" />
              <FlowArrow />
              <FlowStep icon={Sparkles} label="Position-wise feed-forward (GRN) + gated residual" />
              <FlowArrow />
              <FlowStep icon={GitBranch} label="Multi-Output Head — same point + 2-spread pattern as DemandLSTM" />
            </div>
            <p className="mt-2 text-[11px] text-white/40">
              Exact parity with <code className="font-mono">DemandLSTM</code>&apos;s own head shape —
              same <code className="font-mono">point_head</code>/<code className="font-mono">lower_spread_head</code>/
              <code className="font-mono">upper_spread_head</code> naming and softplus parameterisation, so both
              architectures return the identical <code className="font-mono">DemandForecast</code> contract.
            </p>
          </Card>
        </div>

        {/* Uncertainty Calibration — the real "Conformal calibration
            (CQR)" step, applied after either architecture's raw
            forward pass above. */}
        <Card
          className={cn("border", ACCENT_BORDER.amber)}
          title={
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-amber-300" /> Conformal Calibration (CQR)
            </span>
          }
          subtitle="Applied to whichever architecture served the raw forecast above — LSTM (Production) or TFT"
        >
          <div className="flex flex-wrap items-center gap-2">
            <FlowStep icon={Sigma} label="Calculate non-conformity scores (held-out calibration split)" />
            <FlowArrow />
            <FlowStep icon={Activity} label="Fit per-step quantile correction" />
            <FlowArrow />
            <FlowStep icon={Percent} label="Apply to raw P10/P90 (real coverage adjustment)" />
          </div>
          <p className="mt-2 text-[11px] text-white/40">
            Nominal target ~80% coverage (P10–P90 spans that fraction of the distribution by
            construction) — CQR (Romano/Patterson/Candès 2019) adjusts the raw interval width so the
            realized coverage on real held-out data actually matches it, not just the raw quantile
            heads&apos; unadjusted output.
          </p>
        </Card>
      </div>

      {/* 5. MLflow Model Registry */}
      <Card
        className={cn("border", ACCENT_BORDER.lime)}
        title={
          <span className="flex items-center gap-2.5">
            <SectionBadge n={5} accent="lime" /> MLflow Model Registry
          </span>
        }
      >
        <div className="mb-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-white/50">Model Stages</div>
          <div className="flex flex-wrap items-center gap-2">
            <Pill color="gray">None</Pill>
            <FlowArrow />
            <Pill color="sky">Staging</Pill>
            <FlowArrow />
            <Pill color="emerald">Production</Pill>
            <FlowArrow />
            <Pill color="gray">Archived</Pill>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/50">
              Registered Models
            </div>
            <ul className="space-y-1 font-mono text-[12px] text-white/80">
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" /> lstm_demand
                <span className="ml-1 text-[10px] font-sans text-emerald-200/70">Production</span>
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-sky-300" /> lstm_demand_tft
              </li>
              <li className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-white/30" /> energy_forecast_multi_task
              </li>
            </ul>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-[11px] text-white/60">
            Promotion is a real, deliberate CLI/API action based on the walk-forward evaluation
            above — never automatic on every training run.
          </div>
        </div>
      </Card>

      {/* 6 + 7 side by side on wide screens */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 6. Model Serving */}
        <Card
          className={cn("border", ACCENT_BORDER.sky)}
          title={
            <span className="flex items-center gap-2.5">
              <SectionBadge n={6} accent="sky" /> Model Serving
            </span>
          }
          subtitle="services/forecast-api — api container, FastAPI :8000"
        >
          <div className="rounded-lg border border-sky-400/20 bg-sky-400/[0.04] p-3">
            <ul className="space-y-1 font-mono text-[11px] text-white/70">
              <li>/v1/forecast</li>
              <li>/v1/forecast/recent-actual-vs-predicted</li>
              <li>/v1/model, /v1/model/versions</li>
              <li>/v1/model/versions/&#123;v&#125;/evaluation</li>
              <li>/v1/emissions/*, /v1/generation-mix</li>
            </ul>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <MiniBox icon={Boxes} label="ModelRegistry.bundle" sub="hot-reloaded, no restart" accent="sky" />
            <MiniBox icon={Server} label="Redis (:6379)" sub="60s TTL response cache + breaker state" accent="sky" />
          </div>
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2 text-[11px] text-white/60">
            <Timer className="h-3.5 w-3.5 text-white/40" />
            Background <code className="mx-0.5 font-mono">watch</code> task polls for a newer Production
            version (atomic bundle swap)
          </div>
        </Card>

        {/* 7. Dashboard & Users */}
        <Card
          className={cn("border", ACCENT_BORDER.purple)}
          title={
            <span className="flex items-center gap-2.5">
              <SectionBadge n={7} accent="purple" /> Dashboard &amp; Users
            </span>
          }
          subtitle="services/dashboard — Next.js, static export"
        >
          <div className="flex items-center gap-2 rounded-lg border border-purple-400/20 bg-purple-400/[0.04] p-3">
            <Monitor className="h-5 w-5 text-purple-300" />
            <span className="text-sm font-semibold text-white">Next.js Dashboard</span>
          </div>
          <ul className="mt-3 space-y-1.5 text-[12px] text-white/70">
            {["Forecasts", "Emissions", "Generation mix", "Model performance", "Data ingestion controls"].map((x) => (
              <li key={x} className="flex items-center gap-2">
                <span className="h-1 w-1 rounded-full bg-purple-300" /> {x}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] text-white/40">
            Every number fetched live from the endpoints above — no mock fallback on failure.
          </p>
        </Card>
      </div>

      {/* Fine-tune / maintenance paths */}
      <Card title="Fine-tune & maintenance paths" subtitle="Real, but separate from the primary train → register → serve cycle above">
        <div className="flex flex-wrap gap-2">
          {[
            ["ml/incremental.py / incremental_tft.py", "incremental fine-tune, triggered from Data Ingestion's \"Fine-tune\" action"],
            ["ml/prune.py", "structured pruning + fine-tune recovery"],
            ["ml/tune.py", "grid search over hidden_size / lr"],
            ["adaptive_calibration.py", "re-widens conformal intervals against what was actually served"],
            ["bias_correction.py / divergence.py / blend.py", "post-hoc correction layers"],
            ["onnx_import.py / model_import.py", "importing an externally trained bundle into the registry"],
          ].map(([name, desc]) => (
            <div key={name} className="min-w-[220px] flex-1 rounded-lg border border-white/10 bg-white/[0.02] p-3">
              <div className="font-mono text-[11px] text-emerald-100">{name}</div>
              <div className="mt-1 text-[11px] text-white/50">{desc}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Key Technologies + Key Guarantees + Companion Docs */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Key Technologies" className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
            {[
              "FastAPI", "PyTorch", "MLflow", "PostgreSQL (Neon)",
              "Redis", "RabbitMQ", "DuckDB", "dbt",
              "Celery", "MinIO / R2", "Next.js 15", "Docker",
            ].map((t) => (
              <span key={t} className="flex items-center gap-1.5 text-[12px] text-white/70">
                <FileCode2 className="h-3.5 w-3.5 text-white/30" /> {t}
              </span>
            ))}
          </div>
        </Card>

        <Card title="Companion Docs">
          <ul className="space-y-2 text-[12px]">
            <li>
              <code className="font-mono text-emerald-100">docs/data/ingestion.md</code>
              <p className="text-white/45">everything up to a RabbitMQ landed-event</p>
            </li>
            <li>
              <code className="font-mono text-emerald-100">docs/data/warehouse.md</code>
              <p className="text-white/45">raw → marts transformation</p>
            </li>
            <li>
              <code className="font-mono text-emerald-100">docs/architecture/model-architecture.md</code>
              <p className="text-white/45">the full source doc this page renders</p>
            </li>
          </ul>
        </Card>
      </div>

      <Card title="Key guarantees">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {[
            "Real-time ingestion (5 min)",
            "Anomaly detection — flag, never remove",
            "CQR uncertainty (P10 / P50 / P90)",
            "Model versioning & controlled promotion",
            "Hot model serving — no downtime",
          ].map((g) => (
            <div key={g} className="flex items-center gap-2 text-[12px] text-white/75">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-300" /> {g}
            </div>
          ))}
        </div>
      </Card>

      {/* Honest gaps */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-amber-200" /> Honest gaps
          </span>
        }
        subtitle="Not glossed over — see docs/architecture/model-architecture.md § 5 for the full detail"
      >
        <ul className="space-y-2.5 text-[12px] text-white/70">
          <li>
            <span className="font-semibold text-white/85">Forecast-quality circuit breaker</span> — the
            closed → open → half_open state machine is complete and unit-tested in isolation, but the
            real trip condition (persisting what was served at each horizon and reconciling it against
            real demand once it lands) isn&apos;t fully wired up end to end yet.
          </li>
          <li>
            <span className="font-semibold text-white/85">energy_forecast_multi_task</span> — real
            training/serving code exists, but no version has ever been registered in this environment;
            model-info lookups for it return a real &quot;not found&quot;, not a fabricated placeholder.
          </li>
          <li>
            <span className="font-semibold text-white/85">Model lookback lag</span> — LSTM/TFT training
            data ultimately traces back to AEMO NEM&apos;s own archive-publishing cadence, which can run
            tens of hours behind live independently of the dashboard&apos;s faster-updating
            OpenElectricity-sourced actual-demand line.
          </li>
        </ul>
      </Card>

      <p className="flex items-center gap-1.5 pt-1 text-[11px] text-white/30">
        <Link2 className="h-3 w-3" />
        Full detail, real service ports, and the complete ASCII flow diagrams live in{" "}
        <code className="font-mono">docs/architecture/model-architecture.md</code> at the repo root.
      </p>

      <div className="pt-2 text-center text-[11px] text-white/25">
        <Link href="/" className="hover:text-white/50">
          EcoLens
        </Link>{" "}
        · Energy Grid Intelligence &amp; Carbon Accounting
      </div>
    </div>
  );
}
