/**
 * /architecture — Time Series Energy Demand Forecasting.
 *
 * Pixel-styled 2026-09-12 (explicit request, "should look exactly
 * like" the reference infographic) -- unlike every earlier pass on
 * this page, this one deliberately breaks from the dashboard's global
 * dark theme (`bg-[#050a08]`, set by `(dashboard)/layout.tsx`) and
 * renders a self-contained light "poster" matching the reference's own
 * palette, wrapped in its own rounded container so the surrounding
 * sidebar/topbar chrome -- outside this page's control -- stays the
 * app's normal dark theme. A short dark-theme footer line below the
 * poster still points to `docs/architecture/model-architecture.md` for
 * the deeper technical detail (LSTM gate math, DemandTFT, conformal
 * calibration) this page itself dropped in the prior pass.
 *
 * 2026-09-17: the hand-built multi-stage flow diagram (StageCard /
 * InnerBox / ShapeNote chain) was swapped for a static diagram image.
 * First pass used a generic stock `model.jpeg` (input/hidden/output
 * neural net, not specific to this model); replaced same-day with a
 * generated `public/images/model-architecture.png` in the same visual
 * style but depicting DemandLSTM's actual shapes.
 *
 * 2026-09-18: swapped again for the computational-graph diagram that
 * matches `docs/architecture/demand-lstm-architecture.png` --
 * regenerated straight from a real, instantiated `DemandLSTMSkeleton`
 * module by `services/forecast-api/scripts/model_skeleton.py` (see
 * that script's own docstring), so it can't hand-transcribe-drift from
 * `app/models/ml.py`'s real `DemandLSTM.forward` the way the prior
 * matplotlib poster could. Regenerate with
 * `uv run python scripts/model_skeleton.py` from
 * `services/forecast-api/` and copy the output here (and to
 * `docs/architecture/`) whenever `DemandLSTM.forward` changes. The
 * five-card summary row below it carries the same real numbers,
 * traced to `app/models/ml.py` (`DemandLSTM.__init__`/`forward`) and
 * `app/core/config.py` (`model_demand_lookback=24`,
 * `model_demand_horizon=48`, `model_hidden_size=128`,
 * `model_dropout=0.25`).
 */
"use client";

import Image from "next/image";
import Link from "next/link";
import {
  Boxes,
  Cog,
  Cpu,
  Info,
  Leaf,
  Link2,
  Minus,
  Plus,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";

function GlanceCard({
  icon: Icon,
  title,
  lines,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  lines: string[];
}) {
  return (
    <div className="rounded-xl border border-[#c7d9f7] bg-white/70 p-3.5">
      <div className="flex items-center gap-1.5">
        <Icon className="h-4 w-4 text-[#1e3a8a]" />
        <div className="text-[12.5px] font-bold text-[#1e3a8a]">{title}</div>
      </div>
      <ul className="mt-2 space-y-1.5">
        {lines.map((line) => (
          <li key={line} className="flex items-start gap-1.5 text-[11px] leading-snug text-[#3b5998]">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#1e3a8a]/50" />
            {line}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ArchitecturePage() {
  return (
    <div className="space-y-4">
      <div className="rounded-3xl bg-gradient-to-br from-[#eef4fc] to-[#f8fbfe] p-5 md:p-7">
        {/* Header */}
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-3">
            <span className="relative grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[#eaf2ff] ring-1 ring-[#c7d9f7]">
              <Leaf className="absolute h-5 w-5 -translate-x-1 -translate-y-0.5 text-[#22c55e]" />
              <Zap className="absolute h-5 w-5 translate-x-1 translate-y-0.5 fill-[#2563eb] text-[#2563eb]" />
            </span>
            <div className="text-left">
              <h1 className="text-[26px] font-extrabold leading-tight text-[#152452] md:text-[30px]">
                Time Series Energy Demand Forecasting
              </h1>
              <p className="text-[15px] font-bold text-[#3b6fd6] md:text-[17px]">Model Architecture (DemandLSTM)</p>
            </div>
          </div>
          <p className="max-w-2xl text-[12.5px] text-[#5c6b84]">
            A multi-horizon deep learning model with quantile regression and attention for reliable
            energy demand forecasting.
          </p>
        </div>

        {/* Architecture diagram */}
        <div className="mt-5 flex justify-center rounded-2xl border border-[#c7d9f7] bg-white/70 p-4 md:p-6">
          <Image
            src="/images/model-architecture.png"
            alt="Computational graph of the DemandForecast (DemandLSTM) model: input tensor feeds a 2-layer, 128-unit LSTM with dropout 0.25, into an AttentionPool mechanism (score head, softmax, weighted sum) producing a context vector, into a Head Dropout (0.25) that feeds three parallel Linear heads -- Lower Spread, Point, and Upper Spread -- whose softplus-bounded spreads combine with the point value into P10, P50, and P90 forecasts"
            width={1536}
            height={1024}
            className="h-auto w-full max-w-4xl rounded-lg"
            priority
          />
        </div>

        {/* Five-card summary row */}
        <div className="mt-4 rounded-2xl border border-[#c7d9f7] bg-[#eaf2ff]/60 p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <GlanceCard
              icon={Cog}
              title="Key Model Details"
              lines={[
                "Multi-horizon forecasting (48 steps)",
                "2-layer LSTM (128 units each)",
                "Attention-based pooling",
                "Head dropout (rate = 0.25)",
                "3 parallel heads (P10, P50, P90)",
              ]}
            />
            <GlanceCard icon={Boxes} title="Input Shape" lines={["(batch_size, 24, 37)", "24 lookback steps", "37 features"]} />
            <GlanceCard
              icon={Cpu}
              title="Model Outputs"
              lines={["P10 (lower bound)", "P50 (median prediction)", "P90 (upper bound)", "Each: (batch_size, 48)"]}
            />
            <GlanceCard
              icon={TrendingUp}
              title="Why It Works"
              lines={[
                "LSTM captures temporal patterns",
                "Attention focuses on important timesteps",
                "Quantile regression provides uncertainty",
                "Softplus ensures non-negative spread",
              ]}
            />
            <GlanceCard icon={Target} title="Use Case" lines={["Reliable and accurate energy demand forecasts for better planning and operations."]} />
          </div>
        </div>

        {/* Lookback-vs-horizon note */}
        <div className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 rounded-2xl border border-[#c7d9f7] bg-[#eaf2ff]/60 px-4 py-3 text-center text-[11px] text-[#3b5998]">
          <span className="flex items-center gap-1.5">
            <Info className="h-3.5 w-3.5 text-[#1e3a8a]" />
            <span className="font-bold text-[#1e3a8a]">Note:</span>
            <Plus className="h-3 w-3 text-[#3b5998]/50" />
            <Minus className="h-3 w-3 -ml-1 text-[#3b5998]/50" />
            P10 ≤ P50 ≤ P90 (guaranteed by construction, because spread heads use softplus)
          </span>
          <span className="text-[#3b5998]/30">|</span>
          <span>24 = lookback (input sequence length)</span>
          <span className="text-[#3b5998]/30">|</span>
          <span>48 = forecast horizon (output length)</span>
        </div>
      </div>

      {/* Footer -- back in the app's normal dark theme, outside the poster */}
      <p className="flex items-center gap-1.5 pt-1 text-[11px] text-white/30">
        <Link2 className="h-3 w-3" />
        The full byte-level architecture detail (LSTM gate equations, DemandTFT, conformal
        calibration) lives in{" "}
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
