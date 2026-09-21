/**
 * /blog — Engineering Blog.
 *
 * Full-length post ("From Energy Data to Carbon-Aware Forecasts: Building
 * EcoLens"), following the article's own nine-section structure plus its
 * conclusion, laid out as an illustrated engineering write-up mirroring
 * docs/blog/blog.png (big-picture architecture figure, data pipeline,
 * model comparison, LSTM + uncertainty diagram with a softplus equation,
 * pruning/calibration cards, result charts, closing payoff banner) but
 * rebuilt with this app's own dark theme + component library instead of
 * the static infographic image.
 *
 * 2026-09-18: expanded from a condensed/illustrated summary to the full
 * article text (every paragraph, list, table, and formula from the
 * source post), while keeping the existing shared building blocks and
 * inline SVG diagrams local to this page.
 *
 * Lives in `app/(dashboard)/blog` — like /architecture, it's a content
 * page that inherits the Sidebar/Topbar shell from
 * `(dashboard)/layout.tsx` (see that group's NAV_ITEMS in
 * `components/dashboard/sidebar.tsx`) rather than the marketing
 * Navbar/Footer shell `(inner)/layout.tsx` gives /resources.
 *
 * Composed almost entirely from shared building blocks also used by
 * /resources (PageHero, StepFlow, FeatureGrid, StatGrid, CtaBanner)
 * plus a handful of small inline SVG diagrams local to this page.
 */
import { PageHero } from "@/components/sections/page-hero";
import { StepFlow, type Step } from "@/components/sections/step-flow";
import { FeatureGrid, type FeatureGridItem } from "@/components/sections/feature-grid";
import { StatGrid } from "@/components/sections/stat-grid";
import { CtaBanner } from "@/components/sections/cta-banner";

export const metadata = {
  title: "Engineering Blog — EcoLens",
  description:
    "How EcoLens turns constantly changing electricity data into predictions — and why trustworthy forecasting requires more than choosing a sophisticated model.",
};

export default function BlogPage() {
  return (
    <main>
      <PageHero
        breadcrumb={[{ label: "Home", href: "/" }, { label: "Blog" }]}
        badge="Engineering Blog"
        title="From Energy Data to Carbon-Aware Forecasts:"
        highlight="Building EcoLens"
        subtitle="How EcoLens turns constantly changing electricity data into predictions — and why trustworthy forecasting requires more than choosing a sophisticated model."
        meta={<PostMeta />}
        visual={
          <StatGrid
            stats={[
              { value: 6, label: "Electricity regions covered", icon: <GlobeIcon /> },
              { value: 4, label: "Forecasting models evaluated", icon: <BrainIcon /> },
              { value: 80, suffix: "%", label: "Target prediction-interval coverage", icon: <TargetIcon /> },
              { value: 5, suffix: "%+", label: "Minimum size cut required to promote a pruned model", icon: <ScaleIcon /> },
            ]}
          />
        }
      />

      {/* The Big Picture */}
      <section className="py-16 md:py-20">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker title="The Big Picture" />
          <div className="mt-6 grid grid-cols-1 gap-10 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <p className="text-base leading-relaxed text-white/70">
                Imagine opening an energy dashboard and seeing a forecast that says electricity demand will
                reach 9,000 megawatts tomorrow evening.
              </p>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                That number may look simple. But behind it are several difficult questions:
              </p>
              <BulletListPlain
                items={[
                  "Where did the data come from?",
                  "Can we trust the latest measurements?",
                  "What patterns does the model recognize?",
                  "How certain is the prediction?",
                  "Does the model need to be this large?",
                  "And what happens if its uncertainty estimates become unreliable?",
                ]}
              />
              <p className="mt-4 text-base leading-relaxed text-white/70">
                These questions matter because electricity demand is never static. It changes throughout the
                day, follows weekly routines, responds to weather, varies across regions, and reacts to market
                conditions. Predicting it accurately is not simply a matter of drawing a line into the future.
                It requires a complete system for collecting data, learning patterns, measuring uncertainty,
                and delivering reliable results.
              </p>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                This is the problem EcoLens is designed to address.
              </p>
              <Callout>
                EcoLens is a near-real-time energy intelligence platform focused on electricity-demand
                forecasting and carbon-aware analysis. It collects energy-market data, transforms it into
                structured time-series datasets, trains and evaluates multiple forecasting models, and makes
                predictions available through an API and dashboard.
              </Callout>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                But the platform&apos;s work does not end when a model produces a forecast.
              </p>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                EcoLens also asks whether the model can be made smaller without losing accuracy, whether its
                uncertainty intervals deserve to be trusted, and whether its behavior remains reliable as
                real-world conditions change.
              </p>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                Behind a single &ldquo;next 24 hours of demand&rdquo; chart are multiple models,
                data-processing stages, optimization experiments, calibration mechanisms, and operational
                safeguards.
              </p>
              <p className="mt-4 text-base leading-relaxed text-white/70">
                This article explains how those pieces fit together.
              </p>
            </div>
            <div className="lg:col-span-3">
              <ArchitectureDiagram />
            </div>
          </div>
        </div>
      </section>

      {/* 1. Before Prediction Comes Data */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={1} title="Before Prediction Comes Data" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A forecasting model cannot work directly with a messy stream of market observations.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Before it can predict tomorrow&apos;s electricity demand, the platform must establish what happened
            today — and ensure that the historical record is trustworthy.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens integrates energy data from sources such as the Australian Energy Market Operator (AEMO)
            and OpenElectricity. It is designed to work with multiple electricity regions, including:
          </p>
          <BulletListPlain
            items={[
              "New South Wales — NSW1",
              "Queensland — QLD1",
              "Victoria — VIC1",
              "South Australia — SA1",
              "Tasmania — TAS1",
              "Western Australia's WEM/SWIS data, where available",
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Each region has its own generation mix, weather conditions, consumption habits, and market
            behavior. A forecasting approach that performs well in one region may not perform equally well in
            another.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The data pipeline therefore handles several responsibilities:
          </p>

          <div className="mt-10">
            <StepFlow heading="" steps={PIPELINE_STEPS} className="py-0" />
          </div>

          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The platform combines analytical and operational technologies, including DuckDB, PostgreSQL-based
            data marts, Redis, and object storage. dbt transformations help organize data into reusable
            analytical tables, while scheduled ingestion processes keep the system updated.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            For a non-technical reader, this is similar to preparing ingredients before cooking. Even the best
            recipe cannot produce a good meal if the ingredients are missing, mislabeled, or inconsistent.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            For a technical reader, the principle is equally important:
          </p>
          <Callout>
            Every model should receive clean, consistently structured data, regardless of where that data
            originated.
          </Callout>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A forecast is only as dependable as the data pipeline supporting it.
          </p>
        </div>
      </section>

      {/* 2. Why EcoLens Uses Multiple Forecasting Models */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={2} title="Why EcoLens Uses Multiple Forecasting Models" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">There is no universally best forecasting model.</p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A simple statistical method can outperform a sophisticated neural network when demand is highly
            regular. A deep-learning model may discover nonlinear relationships that a simple baseline cannot.
            A pretrained foundation model may generalize well to unfamiliar datasets, but still lack the
            domain-specific information needed for a production energy application.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Instead of assuming that one architecture must win, EcoLens evaluates four different approaches:
          </p>
        </div>

        <div className="mt-10">
          <FeatureGrid heading="" items={MODEL_ITEMS} columns={2} className="pb-8 pt-0" />
        </div>

        <div className="mx-auto max-w-7xl px-6 pb-4">
          <p className="mx-auto max-w-3xl text-base leading-relaxed text-white/70">
            Although their internal mechanisms differ, they are evaluated through a common conceptual
            interface:
          </p>
          <div className="mx-auto mt-4 max-w-2xl rounded-xl border border-amber-300/20 bg-amber-300/5 px-5 py-3 text-center">
            <code className="text-sm text-amber-200">predict(history, horizon) → (p10, p50, p90)</code>
          </div>
          <p className="mx-auto mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Here, <code className="text-lime-100">history</code> is the observed demand,{" "}
            <code className="text-lime-100">horizon</code> is the number of future time steps, and P10, P50,
            and P90 represent lower, central, and upper forecast estimates.
          </p>
          <p className="mx-auto mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            This common structure allows the rest of the application to work with different models without
            understanding every internal detail.
          </p>
          <p className="mx-auto mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It also creates a more disciplined comparison.
          </p>
          <p className="mx-auto mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Rather than asking, &ldquo;Which model sounds most advanced?&rdquo; EcoLens can ask:
          </p>
          <Callout tone="amber">
            Which model produces useful predictions, communicates uncertainty reliably, and operates at a
            reasonable cost?
          </Callout>
        </div>
      </section>

      {/* 3. Seasonal Naive */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={3} title="Seasonal Naive: The Simple Model That Should Never Be Ignored" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The Seasonal Naive model is intentionally straightforward.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It assumes that the future will resemble a corresponding period in the past. If electricity demand
            follows a strong weekly pattern, the forecast for Monday at 2:00 p.m. might begin with demand
            observed during a previous Monday at 2:00 p.m.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The seasonal period depends on the dataset&apos;s sampling frequency and the recurring pattern
            being modeled. It might represent one day, one week, or another operational cycle.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Its value is not sophistication. Its value is comparison.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            If an LSTM produces lower forecast error than Seasonal Naive, that suggests the neural network is
            learning something beyond ordinary repetition. If it performs worse, the added complexity may not
            be justified.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Seasonal Naive can also serve as a potential fallback when a machine-learning model fails a health
            check or encounters invalid inputs.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            However, it cannot naturally understand sudden structural changes, unusual weather, market
            disruptions, long-term trends, or complex interactions between external variables.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It is not intended to be the most intelligent model.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It is intended to establish a reliable reference point.
          </p>
          <Callout>In forecasting, simplicity is not the enemy. Unmeasured complexity is.</Callout>
        </div>
      </section>

      {/* 4. LSTM */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={4} title="LSTM: The Current Production Forecaster" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens&apos;s current production deep-learning model is an LSTM, or Long Short-Term Memory
            network.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            LSTMs are designed for sequential data. They process observations in order and maintain internal
            representations of earlier time steps, making them suitable for electricity demand forecasting.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Demand may rise after people wake up, peak during working hours, change in the evening, or behave
            differently during holidays. Recent demand can also provide clues about what happens next.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The EcoLens LSTM uses a two-layer recurrent encoder:
          </p>

          <div className="mt-10">
            <LstmDiagram />
          </div>

          <p className="mt-6 max-w-3xl text-base leading-relaxed text-white/70">
            The first layer processes the input sequence, while the second learns a higher-level representation
            of the temporal patterns.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            After encoding, the model applies attention pooling. This allows it to assign different importance
            to different historical observations rather than relying only on the final recurrent state.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            For example, a recent demand spike, a similar time from the previous day, or a recurring weekly
            pattern may matter differently depending on the forecast context.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">Predicting uncertainty</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens does not only predict one number. Its LSTM produces a central forecast alongside lower and
            upper uncertainty estimates.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">Conceptually:</p>
          <EquationCard
            lines={[
              "P10 = point forecast − positive lower spread",
              "P50 = point forecast",
              "P90 = point forecast + positive upper spread",
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Positive spread transformations, such as softplus, help ensure that the predicted spreads remain
            non-negative.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The model is trained using quantile-oriented objectives, including pinball loss. Conformal
            calibration is then used to improve the reliability of the resulting prediction intervals.
          </p>

          <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-5">
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 lg:col-span-3">
              <p className="text-xs font-medium uppercase tracking-wider text-emerald-100">Keeping the spread valid</p>
              <p className="mt-2 text-sm leading-relaxed text-white/70">
                To keep P10 and P90 from ever crossing P50 the wrong way, the spread around the central
                forecast is passed through <strong className="text-white">softplus</strong>, which guarantees a
                non-negative width no matter what raw value the network outputs.
              </p>
              <EquationCard
                lines={[
                  "softplus(s) = ln( 1 + eˢ )",
                  "P10 = P50 − softplus(s_lo)     P90 = P50 + softplus(s_hi)",
                ]}
              />
              <p className="mt-3 text-xs text-white/50">
                softplus(s) is always positive, so the network can output any real-valued spread and still be
                guaranteed a valid P10–P90 interval around P50.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 lg:col-span-2">
              <p className="text-xs font-medium uppercase tracking-wider text-emerald-100">Softplus vs. ReLU</p>
              <p className="mt-2 text-sm text-white/60">
                Unlike ReLU, softplus stays smooth and strictly positive near zero — important when the spread
                head is still learning.
              </p>
              <SoftplusChart />
            </div>
          </div>

          <p className="mt-8 max-w-3xl text-base leading-relaxed text-white/70">
            The LSTM is currently selected for production because it offers a practical balance between
            forecasting capability, computational cost, implementation maturity, serving simplicity, and
            operational reliability.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            That does not mean it is permanently the best model.
          </p>
          <Callout>It means it is the model that has currently earned its place in the production pipeline.</Callout>
        </div>
      </section>

      {/* 5. TFT and TimesFM */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={5} title="TFT and TimesFM: Testing Whether More Complexity Creates More Value" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The Temporal Fusion Transformer (TFT) is a more expressive forecasting architecture that combines
            recurrent components, attention, variable selection, gated residual connections, and static
            enrichment.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It is designed to work with different types of information, including historical observations,
            known future inputs, and static context.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens includes a hand-rolled TFT implementation as an alternative to the LSTM. Its static
            enrichment pathway exists conceptually, although the current static context is represented by a
            zero vector rather than a rich learned regional embedding.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The TFT is trained and evaluated independently, but it is not currently the sole production-serving
            model. A model can train successfully and still require additional validation before deployment.
            Accuracy, latency, resource usage, failure behavior, and reproducibility all matter.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The fourth approach is TimesFM, a pretrained time-series foundation model developed by Google.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            TimesFM is used primarily in a zero-shot or frozen-checkpoint configuration. It offers an
            opportunity to test whether broad pretrained temporal knowledge can transfer to electricity demand
            without extensive task-specific training.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            However, its current setup primarily uses raw demand history rather than the full set of
            EcoLens&apos;s domain-specific features. It may not directly incorporate weather forecasts,
            regional metadata, market variables, or operational constraints.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            TimesFM is therefore valuable as an experimental benchmark — not an automatic replacement for a
            specialized production model.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The underlying principle is the same for both architectures:
          </p>
          <Callout>Complexity is valuable only when evaluation demonstrates that it earns its cost.</Callout>
        </div>
      </section>

      {/* 6. Making the Model Smaller */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={6} title="Making the Model Smaller Without Making It Wrong" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Once a forecasting model works, another question becomes important:
          </p>
          <Callout tone="amber">Does it need to be this large?</Callout>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens&apos;s production DemandLSTM has 128 hidden units per layer. That configuration was
            selected empirically, but model size should not become a permanent assumption simply because it
            worked once.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A smaller model could be cheaper to store, load, and run. But reducing capacity can also damage
            accuracy. EcoLens therefore approaches pruning as an experiment that must be measured — not as an
            optimization that is automatically considered successful.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">Why structured pruning matters</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens&apos;s pruning work is scoped to the LSTM. The TFT&apos;s interconnected
            variable-selection, gated-residual, and attention structure makes correct structural compaction
            substantially more complicated. TimesFM is also out of scope because it is used as a frozen
            foundation-model checkpoint.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The implementation performs structured pruning, meaning it removes complete logical hidden units
            rather than merely setting individual weights to zero.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">This distinction matters.</p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Zero-masking leaves the model physically the same size. The tensor still occupies the same storage,
            and dense hardware may not run faster simply because some values are zero.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens instead performs physical compaction: it rebuilds a smaller model and copies only the
            surviving weights.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">How units are selected</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            The pruning process ranks hidden units using L2-norm importance scores. It considers both:
          </p>
          <BulletListPlain
            items={["How strongly a unit is computed.", "How strongly that unit feeds into other units."]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            This matters because a unit can be important as an input to other units even if its own outgoing
            computation appears relatively small.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The compaction process updates the affected recurrent weights, biases, attention layer, and
            forecasting heads. It also returns the original indices of the surviving units, making the decision
            auditable.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A basic correctness invariant is tested: when the keep fraction is 1.0 and nothing is pruned, the
            compacted model must reproduce the original weights exactly.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">The pruning gate</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            Compaction alone is not enough. EcoLens runs a complete pipeline:
          </p>
          <OrderedList
            items={[
              "Load a registered LSTM version.",
              "Compact it structurally.",
              "Measure parameter count, artifact size, and CPU inference latency.",
              "Fine-tune the compacted model to recover lost capacity.",
              "Re-evaluate it through the same walk-forward harness.",
              "Check whether the result passes both efficiency and accuracy requirements.",
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The efficiency gate requires the artifact to be at least 5% smaller and not more than 10% slower. A
            separate accuracy check requires recovered walk-forward MAPE regression to remain within a default
            1% tolerance of the unpruned version.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Even when the gate passes, the recovered model is registered to MLflow with a{" "}
            <code className="text-lime-100">prune_gate_passed</code> tag but is not automatically promoted to
            Production.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            If pruning fails, the result is recorded honestly:
          </p>
          <Callout>&ldquo;Pruning was not worth it at this model size.&rdquo;</Callout>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            That is a useful engineering result, not something to hide.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">A lesson from recovery</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            The pruning experiment also exposed a practical issue: recovery fine-tuning needs enough time to
            relearn after a structural cut.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            At a 50% keep fraction, three recovery epochs produced a severe relative walk-forward MAPE
            regression of +131.2%. Fifteen epochs recovered performance to better than the unpruned version,
            reaching approximately −21.1% relative regression. The current default was subsequently increased
            to 20 recovery epochs.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">The lesson is broader than pruning:</p>
          <Callout>
            An optimization is not complete when the code runs. It is complete when the resulting system has
            been measured.
          </Callout>
        </div>
      </section>

      {/* 7. Conformal Calibration */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={7} title="Conformal Calibration: Making the Uncertainty Band More Trustworthy" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A forecast interval labeled P10–P90 may sound like an 80% confidence range. But raw
            quantile-regression outputs do not automatically guarantee that the true value will fall inside
            that interval 80% of the time.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A model can have low pinball loss and still produce intervals that are too narrow.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens addresses this with Conformalized Quantile Regression (CQR).
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">How CQR works</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            CQR uses a held-out calibration split that the model did not train on.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            For each calibration sample, it measures how far the actual value falls outside the raw prediction
            interval:
          </p>
          <EquationCard lines={["scores = np.maximum(lo_cal - y_cal, y_cal - hi_cal)"]} />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It then calculates a calibrated quantile of these nonconformity scores and uses that value to
            adjust future intervals:
          </p>
          <EquationCard lines={["calibrated_low = raw_low - q", "calibrated_high = raw_high + q"]} />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            In simple terms, if the model&apos;s original interval was too narrow on held-out data, the
            calibration layer widens it by an amount supported by that evidence.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens persists the calibration result as an MLflow artifact, allowing serving to load and apply
            it automatically.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">Why order matters</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens applies regional bias correction before conformal calibration.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            This is deliberate. Conformal calibration adjusts interval width around the model&apos;s central
            forecast; it does not fix a forecast that is systematically shifted too high or too low.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Bias correction addresses the center first. Conformal calibration then measures how much
            uncertainty remains around that corrected center.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Coverage is computed and logged for both raw and calibrated intervals so the result can be
            inspected rather than assumed.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">The important limitation</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            Conformal coverage guarantees rely on assumptions such as exchangeability. Chronological
            time-series data does not strictly satisfy this assumption when demand patterns shift over time.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            That means CQR is not a magical guarantee under every deployment condition. If the data
            distribution changes substantially, its historical calibration may no longer describe current
            reality.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It also cannot fix a systematically mis-centered forecast. That requires better modeling or bias
            correction.
          </p>
        </div>
      </section>

      {/* 8. Adaptive Calibration */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={8} title="Adaptive Calibration: Responding to Drift After Deployment" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Static calibration is calculated at training time. But real-world demand volatility can change
            after the model is deployed.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens therefore includes an adaptive calibration layer inspired by Adaptive Conformal Inference.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            For each model-and-region pair, the system maintains a scalar multiplier in Redis. When a served
            forecast is later reconciled against the actual observed demand, the multiplier is updated based on
            whether the outcome fell inside the predicted interval.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">Conceptually:</p>
          <EquationCard
            lines={[
              "miss = 0.0 if covered else 1.0",
              "updated = current + step_size * (miss - target_alpha)",
              "updated = min(max(updated, MIN_SCALE), MAX_SCALE)",
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A miss gradually pushes the scale upward, widening future intervals. A hit nudges it downward.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The scale is bounded between 0.5 and 3.0, preventing it from collapsing toward zero or expanding
            without limit. The update step is deliberately small, allowing the system to respond gradually
            rather than overreact to a short streak of unusual outcomes.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The adaptive layer is not intended to replace the model. It addresses a different problem:
          </p>
          <BulletListPlain
            items={[
              "Adaptive calibration: The model is still appropriate, but its uncertainty needs adjustment.",
              "Forecast-quality circuit breaker: The model's behavior has deteriorated enough that the system should fall back to a simpler method.",
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            This separation is important. Not every calibration issue requires replacing the entire
            forecasting model.
          </p>

          <h3 className="mt-10 text-lg font-semibold text-white">What the regional results revealed</h3>
          <p className="mt-3 max-w-3xl text-base leading-relaxed text-white/70">
            Walk-forward evaluation on real warehouse data showed uneven coverage before calibration and
            tuning:
          </p>
          <DataTable
            headers={["Region", "Coverage", "Bias (P50 − actual, MW)"]}
            rows={[
              ["NSW1", "0.833", "−98.9"],
              ["QLD1", "0.771", "−343.1"],
              ["VIC1", "0.776", "+57.3"],
              ["SA1", "0.891", "−27.5"],
              ["TAS1", "0.984", "+88.4"],
              ["WEM", "0.865", "+20.9"],
            ]}
          />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">The target coverage was 80%.</p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            These results show why a single global correction is insufficient. Bias varies in both direction
            and magnitude across regions.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Per-region bias correction helped substantially in some cases. NSW1 and TAS1, for example, moved to
            within approximately 6 MW of zero bias in the follow-up experiment. But other regions became worse,
            suggesting that a small calibration split — roughly 25–27 rows per region — was not always stable
            enough to estimate persistent regional bias.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            That result is not a failure of the experiment. It is evidence that calibration must be evaluated
            carefully, especially when data is limited and behavior changes over time.
          </p>
        </div>
      </section>

      {/* 9. One Evaluation Framework */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker n={9} title="One Evaluation Framework and a Reliable Production Circuit" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            All these mechanisms depend on consistent evaluation.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens uses a shared walk-forward harness to compare models under conditions that resemble real
            forecasting. The process measures central forecast accuracy, quantile loss, interval coverage,
            interval width, regional stability, and performance across different horizons.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            This same discipline extends to pruning and calibration.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A smaller model is not accepted merely because its parameter count decreases. It must also preserve
            accuracy and meet latency requirements.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A calibrated interval is not trusted merely because a correction formula was applied. Its empirical
            coverage must be measured.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            And a model is not promoted to production merely because it exists in the codebase.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The operational system must also handle missing observations, delayed ingestion, invalid values,
            model-loading failures, distribution changes, resource constraints, API timeouts, and regional
            outages.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens includes components for scheduled ingestion, transformation, model training, registration,
            serving, caching, monitoring, logging, metrics, tracing, and alerting.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            A future forecast-quality circuit breaker can reject outputs containing NaN values, impossible
            negative demand, implausible jumps, severe drift, excessively wide intervals, or failed health
            checks — and fall back to the Seasonal Naive baseline when necessary.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            The goal is not to pretend that models never fail.
          </p>
          <Callout>The goal is to make failure detectable, bounded, and recoverable.</Callout>
        </div>
      </section>

      {/* Conclusion */}
      <section className="border-t border-white/5 py-20 md:py-24">
        <div className="mx-auto max-w-7xl px-6">
          <SectionKicker title="Conclusion: Forecasting Should Be Earned" />
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            EcoLens is not built around the assumption that the newest or most complicated model must be the
            best one.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Its architecture combines a simple baseline, a production LSTM, a more advanced Temporal Fusion
            Transformer, and a pretrained foundation model. Each offers a different trade-off between
            simplicity, expressiveness, generalization, uncertainty estimation, and operational cost.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            But the platform goes further than model selection.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It asks whether the production LSTM can be physically reduced in size without sacrificing
            meaningful accuracy. It uses structured pruning, recovery fine-tuning, and explicit efficiency
            gates to answer that question.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It asks whether uncertainty intervals deserve to be trusted. It uses conformalized quantile
            regression to calibrate them against held-out evidence, then uses adaptive calibration to respond
            to drift after deployment.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            And it records when these mechanisms do not work as hoped.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">That is the common thread.</p>
          <Callout>
            Compute a real before-and-after. Compare it against a real threshold. Register the result. Keep
            production promotion deliberate.
          </Callout>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            Ultimately, a forecasting model should not enter production because it is fashionable, complex, or
            impressive on paper.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            It should enter production because it has demonstrated that it can produce useful predictions,
            communicate uncertainty honestly, operate reliably, and improve the decisions the platform is
            designed to support.
          </p>
          <p className="mt-4 max-w-3xl text-base leading-relaxed text-white/70">
            That is the standard EcoLens is working toward:
          </p>
        </div>
      </section>

      {/* The Payoff */}
      <CtaBanner
        badge="The Payoff"
        heading="Not just predicting energy demand,"
        highlight={<span className="block text-lime-100">but building a dependable foundation for carbon-aware energy intelligence.</span>}
        body="EcoLens combines a simple baseline, a production LSTM, a more expressive transformer, and a pretrained foundation model — then makes each one earn its place with a real before-and-after, measured against a real threshold."
        features={[
          "Structured pruning gated on size and accuracy",
          "Conformal + adaptive calibration for honest uncertainty",
          "Shared walk-forward evaluation across every model",
        ]}
      />
    </main>
  );
}

/* ─────────────────  Content data  ───────────────── */

const PIPELINE_STEPS: Step[] = [
  { number: 1, title: "Ingest", body: "Collect new observations at regular intervals.", icon: <IngestIcon /> },
  { number: 2, title: "Normalize", body: "Standardize timestamps and regional identifiers.", icon: <NormalizeIcon /> },
  { number: 3, title: "Validate", body: "Detect missing, duplicated, or abnormal records.", icon: <ValidateIcon /> },
  { number: 4, title: "Build Sequences", body: "Construct historical demand sequences.", icon: <TrendIcon /> },
  { number: 5, title: "Generate Features", body: "Produce the features forecasting models use.", icon: <TransformIcon /> },
  { number: 6, title: "Store", body: "Persist processed data for training, evaluation, and serving.", icon: <DbIcon /> },
];

const MODEL_ITEMS: FeatureGridItem[] = [
  {
    title: "Seasonal Naive",
    body: "A simple historical baseline. Its value isn't sophistication — it's comparison, and a fallback when a model fails a health check.",
    icon: <TrendIcon />,
    visual: null,
  },
  {
    title: "LSTM (production)",
    body: "The current production deep-learning model. A two-layer recurrent encoder with attention pooling, currently selected for production.",
    icon: <BrainIcon />,
    visual: null,
  },
  {
    title: "Temporal Fusion Transformer",
    body: "A more expressive architecture under evaluation — recurrence, attention, variable selection, and gated residual connections.",
    icon: <LayersIcon />,
    visual: null,
  },
  {
    title: "TimesFM",
    body: "A pretrained time-series foundation model used in zero-shot experiments, testing whether broad pretrained knowledge transfers to electricity demand.",
    icon: <SparkleIcon />,
    visual: null,
  },
];

/* ─────────────────  Small local components  ───────────────── */

function PostMeta() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-white/50">
      <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-white/70">Engineering</span>
      <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-white/70">Forecasting &amp; ML</span>
      <span>20 min read</span>
    </div>
  );
}

function SectionKicker({ n, title }: { n?: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      {n !== undefined && (
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-emerald-200/30 bg-emerald-200/10 text-sm font-bold text-emerald-100">
          {n}
        </span>
      )}
      <h2 className="text-2xl font-bold text-white md:text-3xl">{title}</h2>
    </div>
  );
}

/** Plain bulleted list for prose passages (as opposed to FeatureGrid bullets). */
function BulletListPlain({ items }: { items: string[] }) {
  return (
    <ul className="mt-4 max-w-3xl space-y-2">
      {items.map((item) => (
        <li key={item} className="flex items-start gap-2.5 text-base leading-relaxed text-white/70">
          <span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-lime-100/70" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Numbered list for ordered processes (e.g. the pruning gate pipeline). */
function OrderedList({ items }: { items: string[] }) {
  return (
    <ol className="mt-4 max-w-3xl space-y-2.5">
      {items.map((item, i) => (
        <li key={item} className="flex items-start gap-3 text-base leading-relaxed text-white/70">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-emerald-200/30 bg-emerald-200/10 text-xs font-bold text-emerald-100">
            {i + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

/** Pull-quote style callout for standalone one- or two-line statements. */
function Callout({ children, tone = "emerald" }: { children: React.ReactNode; tone?: "emerald" | "amber" }) {
  const toneClass =
    tone === "amber"
      ? "border-amber-300/20 bg-amber-300/5 text-amber-100/90"
      : "border-emerald-200/20 bg-emerald-200/5 text-white/80";
  return (
    <div className={`mt-4 max-w-3xl rounded-2xl border p-4 text-sm leading-relaxed ${toneClass}`}>
      {children}
    </div>
  );
}

/** Simple dark-themed data table (used for the regional coverage/bias results). */
function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="mt-4 max-w-2xl overflow-x-auto rounded-2xl border border-white/10">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-white/10 bg-white/[0.03]">
            {headers.map((h) => (
              <th key={h} className="px-4 py-2.5 text-left font-semibold text-white/80">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i < rows.length - 1 ? "border-b border-white/5" : ""}>
              {row.map((cell, j) => (
                <td key={j} className={j === 0 ? "px-4 py-2.5 text-white/80" : "px-4 py-2.5 font-mono text-white/60"}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Equation display — mono, larger type, for the softplus / CQR / calibration formulas. */
function EquationCard({ lines }: { lines: string[] }) {
  return (
    <div className="mt-4 max-w-3xl space-y-2 rounded-xl border border-white/10 bg-[#0a1410] p-4">
      {lines.map((line) => (
        <p key={line} className="overflow-x-auto whitespace-pre font-mono text-sm text-lime-100 sm:text-base">
          {line}
        </p>
      ))}
    </div>
  );
}

/** "EcoLens End-to-End Architecture" figure. */
function ArchitectureDiagram() {
  const sources = [
    { title: "External Sources", subtitle: "AEMO, OpenElectricity", icon: <PlugIcon /> },
    { title: "Ingestion", subtitle: "Celery + APIs", icon: <IngestIcon /> },
    { title: "Staging", subtitle: "DuckDB", icon: <DbIcon /> },
    { title: "Warehouse", subtitle: "PostgreSQL + dbt", icon: <WarehouseIcon /> },
    { title: "Analytics-Ready Data", subtitle: "Curated tables", icon: <TableIcon /> },
  ];
  const serving = [
    { title: "Forecasting", subtitle: "Multiple models", icon: <BrainIcon /> },
    { title: "Carbon Insights", subtitle: "Gen mix + intensity", icon: <LeafIcon /> },
    { title: "API & Services", subtitle: "REST", icon: <ApiIcon /> },
    { title: "Dashboard", subtitle: "Next.js", icon: <MonitorIcon /> },
  ];
  const stack = ["DuckDB", "PostgreSQL", "Redis", "Object Storage", "Celery", "RabbitMQ", "dbt"];

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 md:p-6">
      <p className="text-xs font-medium uppercase tracking-wider text-emerald-100">
        EcoLens End-to-End Architecture
      </p>
      <DiagramRow nodes={sources} />
      <div className="my-2 flex justify-center text-white/30">
        <DownArrow />
      </div>
      <DiagramRow nodes={serving} tone="accent" />
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-white/5 pt-4">
        {stack.map((s) => (
          <span
            key={s}
            className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-white/60"
          >
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}

function DiagramRow({
  nodes,
  tone = "default",
}: {
  nodes: Array<{ title: string; subtitle: string; icon: React.ReactNode }>;
  tone?: "default" | "accent";
}) {
  return (
    <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-0">
      {nodes.map((node, i) => (
        <div key={node.title} className="flex flex-1 items-center">
          <div
            className={
              "flex w-full flex-col items-center gap-1.5 rounded-xl border p-3 text-center " +
              (tone === "accent"
                ? "border-emerald-200/20 bg-emerald-200/5"
                : "border-white/10 bg-[#0a1410]")
            }
          >
            <span
              className={
                "grid h-8 w-8 place-items-center rounded-md " +
                (tone === "accent" ? "bg-emerald-200/15 text-emerald-100" : "bg-white/5 text-lime-100")
              }
            >
              {node.icon}
            </span>
            <p className="text-[11px] font-semibold text-white">{node.title}</p>
            <p className="text-[10px] text-white/50">{node.subtitle}</p>
          </div>
          {i < nodes.length - 1 && (
            <span className="mx-1 hidden shrink-0 text-white/25 sm:block">
              <RightArrow />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/** LSTM encoder → attention → forecasting-heads chain. */
function LstmDiagram() {
  const chain = [
    { title: "Historical Demand", icon: <TrendIcon /> },
    { title: "LSTM Layer 1", icon: <LayersIcon /> },
    { title: "LSTM Layer 2", icon: <LayersIcon /> },
    { title: "Attention Pooling", icon: <FocusIcon /> },
    { title: "Forecasting Heads", icon: <SplitIcon /> },
  ];
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5 md:p-6">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        {chain.map((node, i) => (
          <div key={node.title} className="flex flex-1 items-center">
            <div className="flex w-full flex-col items-center gap-1.5 rounded-xl border border-white/10 bg-[#0a1410] p-3 text-center">
              <span className="grid h-8 w-8 place-items-center rounded-md bg-white/5 text-lime-100">
                {node.icon}
              </span>
              <p className="text-[11px] font-semibold text-white">{node.title}</p>
            </div>
            <span className="mx-1 hidden shrink-0 text-white/25 lg:block">
              <RightArrow />
            </span>
          </div>
        ))}
        <div className="mt-2 flex shrink-0 gap-2 lg:mt-0">
          {["P10", "P50", "P90"].map((p) => (
            <span
              key={p}
              className="grid h-11 w-11 place-items-center rounded-full border border-amber-300/30 bg-amber-300/10 text-xs font-bold text-amber-200"
            >
              {p}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Softplus vs ReLU mini line chart. */
function SoftplusChart() {
  const width = 220;
  const height = 120;
  const xs = Array.from({ length: 41 }, (_, i) => -4 + (i * 8) / 40);
  const toXY = (x: number, y: number) => {
    const px = ((x + 4) / 8) * width;
    const py = height - (Math.min(y, 4.2) / 4.2) * height;
    return `${px},${py}`;
  };
  const softplusPath = xs.map((x) => toXY(x, Math.log(1 + Math.exp(x)))).join(" ");
  const reluPath = xs.map((x) => toXY(x, Math.max(0, x))).join(" ");

  return (
    <div className="mt-4 rounded-xl border border-white/10 bg-[#0a1410] p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-28 w-full">
        <line x1="0" y1={height} x2={width} y2={height} stroke="rgba(255,255,255,0.15)" strokeWidth="1" />
        <line
          x1={toXY(0, 0).split(",")[0]}
          y1="0"
          x2={toXY(0, 0).split(",")[0]}
          y2={height}
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="1"
        />
        <polyline points={reluPath} fill="none" stroke="#f59e0b" strokeWidth="2" strokeDasharray="4 3" />
        <polyline points={softplusPath} fill="none" stroke="#a3e635" strokeWidth="2.2" />
      </svg>
      <div className="mt-2 flex items-center gap-4 text-[11px] text-white/60">
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded bg-lime-100" /> Softplus
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded border-t border-dashed border-amber-400" /> ReLU
        </span>
      </div>
    </div>
  );
}

/* ─────────────────  Icons (local, matches app's icon style)  ───────────────── */

function GlobeIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></svg>; }
function BrainIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M9 4a3 3 0 00-3 3v2a3 3 0 00-2 5 3 3 0 002 5v2a3 3 0 003 3 3 3 0 003-3V4a3 3 0 00-3 0z" strokeLinejoin="round" /></svg>; }
function TargetIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /></svg>; }
function ScaleIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3v18M5 7l7-4 7 4M5 7v4a2 2 0 002 2h6a2 2 0 002-2V7" /></svg>; }
function LeafIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5"><path d="M17 8C8 10 5.9 16.17 3.82 21.34L5.71 22l1-2.3C7.39 19.89 8 20 8.5 20c5 0 9-4 9-10V8h-.5c-.3 0-.5.2-.5.5 0 .2 0 .4.1.5L17 8z" /></svg>; }
function IngestIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3v12m0 0l-4-4m4 4l4-4" strokeLinecap="round" strokeLinejoin="round" /><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" strokeLinecap="round" /></svg>; }
function NormalizeIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M4 6h16M4 12h10M4 18h13" strokeLinecap="round" /></svg>; }
function ValidateIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3l8 3v5c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-3z" strokeLinejoin="round" /><path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function TransformIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M4 7h11l-3-3M20 17H9l3 3" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function DbIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></svg>; }
function WarehouseIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 10l9-6 9 6v9a1 1 0 01-1 1H4a1 1 0 01-1-1v-9z" strokeLinejoin="round" /><path d="M9 20v-6h6v6" /></svg>; }
function TableIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 4v16" /></svg>; }
function ApiIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M7 18a4 4 0 010-8 6 6 0 0111.5 1.5A4 4 0 0118 18H7z" strokeLinejoin="round" /></svg>; }
function MonitorIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4" strokeLinecap="round" /></svg>; }
function PlugIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 01-10 0V7z" strokeLinejoin="round" /><path d="M12 16v5" strokeLinecap="round" /></svg>; }
function TrendIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M3 17l4-4 3 3 7-7M14 6h4v4" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function LayersIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M12 3l9 5-9 5-9-5 9-5z" strokeLinejoin="round" /><path d="M3 13l9 5 9-5" strokeLinejoin="round" /></svg>; }
function SparkleIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5"><path d="M12 2l1.8 5.2L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.8L12 2z" /></svg>; }
function FocusIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><circle cx="12" cy="12" r="3" /><path d="M3 8V5a2 2 0 012-2h3M21 8V5a2 2 0 00-2-2h-3M3 16v3a2 2 0 002 2h3M21 16v3a2 2 0 01-2 2h-3" strokeLinecap="round" /></svg>; }
function SplitIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5"><path d="M6 4v6c0 2 1 3 3 3h6c2 0 3-1 3-3V4M12 13v7" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function RightArrow() { return <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 8h11m0 0L9 4m4 4l-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function DownArrow() { return <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 2v11m0 0L4 9m4 4l4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
