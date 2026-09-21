# The Four Forecasters Behind EcoLens's Demand Predictions

Every "next 24 hours of demand" number on the EcoLens dashboard comes out of `services/forecast-api`, and behind that one number sit four genuinely different forecasting approaches, not one. This document walks through each of them: a seasonal-naive baseline, a production LSTM, a hand-rolled Temporal Fusion Transformer, and a zero-shot foundation model called TimesFM — what each one is, why it was chosen over the alternatives, how its architecture is actually built, why that architecture looks the way it does, and where the real, honest gaps still are.

If [`docs/architecture/model-architecture.md`](../architecture/model-architecture.md) is the map of the whole pipeline (ingestion → warehouse → training → MLflow → serving), this document zooms into one box on that map — the four architectures competing inside "MODEL TRAINING" — and explains the reasoning behind each.

One thing worth saying up front, because it shapes everything below: as of today, only one of these four is actually live. `GET /v1/forecast` reads from exactly one model — the LSTM. The other three are real, trained, and evaluated through the same harness, but not wired into what a dashboard visitor actually sees yet. That's a deliberate, recorded decision, not an oversight, and the reasoning behind it is worth understanding before diving into each model individually.

---

## At a Glance

| Model | Type | Training | Real status |
|---|---|---|---|
| **Seasonal Naive** | Statistical baseline (no learned weights) | None — a pure function over history | Not served live, but the yardstick every other model is judged against, and the circuit-breaker fallback when the LSTM's quality trips |
| **LSTM** (`DemandLSTM`) | Recurrent neural network + attention pooling | Full PyTorch training loop, per-region scaling, conformal calibration | **Production** — the only architecture `GET /v1/forecast` serves |
| **TFT** (`DemandTFT`) | Temporal Fusion Transformer (hand-rolled) | Same training/evaluation harness as LSTM, one model per region | Registered and evaluated, reachable from the offline Model Comparison view — not reachable from live serving |
| **TimesFM** | Pretrained time-series foundation model (Google, 200M params) | Zero-shot — no training loop at all | Evaluated through the same walk-forward harness, no MLflow registry entry (there's nothing of ours to version) |

---

## 1. Seasonal Naive — the honest floor

### What it is

The seasonal-naive forecaster is the simplest possible model that still deserves the name: for any point in the future, its prediction is "whatever actually happened at the same point in the cycle, `n_periods` times in the past." No weights, no gradient descent, no GPU — just indexing into history and taking percentiles.

### Why it was chosen

Every serious forecasting project needs a floor to stand on, and it needs to be a *real* one. It would be easy to accept a fancy neural network's accuracy numbers at face value, but the only way to know whether an LSTM or a Transformer is actually earning its complexity is to compare it against the simplest thing that could plausibly work. Electricity demand has strong daily and weekly seasonality — Tuesday at 6pm looks a lot like last Tuesday at 6pm — so "repeat the same phase of the cycle" is a genuinely competitive baseline in this domain, not a straw man. If a trained model can't beat this, it isn't worth serving, no matter how sophisticated it looks on paper.

### Architecture

There's no network to describe, but the design has real thought behind it:

- `period_steps` is the seasonal period expressed in **rows**, not time — 2016 rows for a 5-minute series' weekly cycle, 336 for a 30-minute series'. This matters because NEM (5-minute) and WEM (30-minute) have different native cadences, and the period has to be inferred from the data's actual timestamp spacing, not assumed from a textbook cadence.
- For each forecasted step, it pools the value from the same phase of the cycle across `n_periods` (default 8) past occurrences, then reports the **median** as P50 — not the mean, which one unusually high or low past period could skew — and the real 10th/90th percentiles of that pool as P10/P90.
- That last point is deliberate: the uncertainty band isn't a fixed ±X% guess. It's *empirically* how much that specific point in the cycle has actually varied historically, so it's naturally wider around a volatile evening peak and narrower around a quiet overnight trough.

### How it's used

Two real jobs, not one:

1. **The comparison baseline.** Every walk-forward evaluation (`evaluate_and_log`, `evaluate_tft_and_log`, `evaluate_timesfm_and_log`) runs the seasonal-naive forecaster over the exact same rolling origins as whatever candidate model it's scoring, so "did this LSTM/TFT/TimesFM run actually help" always has an honest, same-conditions comparison sitting next to it.
2. **The circuit-breaker fallback.** When the LSTM's real-world forecast quality trips the forecast-quality circuit breaker (more on that below), `GET /v1/forecast` is designed to fall back to serving this baseline instead of a broken neural network's output — a working forecast, even a simple one, beats a confidently wrong one.

### What could be improved

- It pools raw history without any recency weighting — a period from eight weeks ago counts exactly as much as one from last week, even though demand patterns do drift over a season. A recency-weighted variant would likely tighten the P10/P90 band without much extra complexity.
- The circuit-breaker fallback described above is the *intended* design, but the real trip condition it depends on — a job that persists what was actually served and reconciles it against real demand once it lands — isn't fully wired up end-to-end yet. The baseline model itself is ready; the plumbing that would actually route traffic to it during a real incident isn't finished.

---

## 2. LSTM — the model actually running in production

### What it is

`DemandLSTM` is a recurrent neural network trained on engineered features (calendar signals, weather, cross-region context, lag/rolling statistics) to predict P10/P50/P90 demand for the next `horizon` steps. It's the only architecture behind `GET /v1/forecast` today.

### Why it was chosen

An LSTM is a well-understood, comparatively cheap architecture for sequence data with this shape — one input window per prediction, no need for the heavier machinery (variable selection networks, static covariates, multi-head attention) a Transformer-style model brings. Training happens with plain PyTorch (`torch.optim`), deliberately not PyTorch Lightning: the training loop is a single model on a single, GPU-optional device with no distributed training, and Lightning's abstraction wasn't judged to be pulling its weight as a new dependency for a job this straightforward. That same reasoning is why the LSTM was already registered and already promoted to Production by the time TFT and TimesFM were built — there was no recorded, logged walk-forward comparison showing either of the newer architectures actually beats it, so the simpler, already-proven model kept its job rather than being swapped out speculatively.

### Architecture

```
input window (lookback, n_features)
        │
        ▼
   nn.LSTM (hidden_size=128, num_layers=2, dropout=0.2)
        │
        ▼
   AttentionPool  ── softmax-weighted sum over every timestep's
        │             hidden state, not just the last one
        ▼
   Dropout (head_dropout)
        │
   ┌────┼────┐
   ▼    ▼    ▼
 point lower upper   ── three linear heads
   │    │    │
   │  softplus softplus
   │    │    │
   ▼    ▼    ▼
  P50 = point
  P10 = point − softplus(lower)
  P90 = point + softplus(upper)
```

A few choices here are worth explaining:

- **Attention pooling instead of the LSTM's last hidden state.** A plain LSTM forecaster often just uses the final timestep's hidden state as "the summary" of the whole lookback window. `AttentionPool` instead learns a per-timestep score, softmaxes it into weights, and takes a weighted sum across the *entire* sequence — letting the model decide which parts of the lookback window actually matter for this particular prediction, rather than assuming the most recent point is always the most informative one.
- **The `point ± softplus(spread)` parameterization for P10/P90.** This isn't a stylistic choice — it structurally guarantees `p10 <= p50 <= p90` for every prediction, because `softplus` is always non-negative. A model that predicted the three quantiles independently could, in principle, output a P10 above its own P50, which makes no sense for a forecast interval. This design makes that impossible by construction.
- **Dropout on the attention output, not just inside the LSTM.** This one has a real bug story behind it: for a while, `nn.LSTM`'s own internal dropout was the *only* regularization anywhere in the forward pass — the attention pooling and all three output heads had none, meaning nothing regularized the exact point where the model commits to its final prediction. Adding a dropout layer right after attention pooling (reusing the same dropout rate, adding zero new parameters) fixed that gap without touching the model's saved-weights format at all.

### How it's used

Feature engineering (`build_features`) has to be reproduced byte-for-byte at inference time — calendar cyclical encodings, weather-derived comfort features, cross-region demand share, lag/rolling statistics, and a one-hot region block. That last piece matters more than it might look: an early version trained across all five NEM regions with no region signal at all scored 76.79% test MAPE, against 3.73% for a single-region model — Tasmania's demand shape genuinely differs from New South Wales's in ways that per-region *scaling* alone can't fix, so the model needed an explicit signal telling it which region's dynamics it's looking at. Target scaling is per-region for the same underlying reason: NSW1 sits around 8,700 MW and TAS1 around 1,100 MW, and a single shared scaler let the larger regions dominate, quietly starving the smaller ones of the precision they needed.

Training minimizes pinball loss (not Huber) on all three quantile heads — P50's own loss term switched from Huber to true pinball(0.5) after real walk-forward bias as large as -343 MW was measured, because Huber trains toward the conditional *mean*, not the median, and did so unevenly once target scaling went per-region. On top of the raw quantile heads sits **conformalized quantile regression (CQR)**: a held-out calibration split (disjoint from both training and the validation split early-stopping watches) measures exactly how wrong the raw P10/P90 band was, and widens it by precisely that much — turning "the model's own quantile heads, for whatever they're worth" into an interval with a real, finite-sample coverage guarantee. A per-region bias correction sits alongside that, applied before conformal calibration, so a region with a persistent one-directional error gets that corrected first rather than papered over by a wider interval.

Once trained, a version is registered in MLflow at stage `None`. Promotion to `Production` is a deliberate, separate action — never automatic on a green training run — gated on the walk-forward backtest against the seasonal-naive baseline. A background task polls for a new Production version and swaps the served bundle atomically, with no restart.

### What could be improved

- The model is weather-*observation*-blind about the future, not weather-*forecast*-aware — `temp_c` and friends are BoM readings of what already happened, not a live weather forecast feed. This is an explicit, out-of-scope gap: predicting tomorrow's demand using only today's weather leaves real accuracy on the table that a genuine weather-forecast input could recover.
- It's the sole served architecture by circumstance more than by a rigorous, logged head-to-head against TFT — a real comparison is on record as still-open work, not a decision made and closed.
- The forecast-quality circuit breaker that would fall back to the seasonal-naive model during a real incident is only half-built (see the Seasonal Naive section above) — the LSTM currently has no automatic safety net in production if its real-world accuracy quietly degrades.

---

## 3. Temporal Fusion Transformer — built, evaluated, not yet on stage

### What it is

`DemandTFT` is a hand-rolled implementation of the Temporal Fusion Transformer (Lim et al., 2019) — an architecture purpose-built for interpretable multi-horizon forecasting, combining variable selection, recurrent encoding, and self-attention in one model.

### Why it was chosen — and why hand-rolled

TFT is a natural next step past the LSTM: it lets the model learn *which* input variables matter at *which* timestep, rather than treating every feature as equally relevant everywhere, and it produces attention weights that are genuinely interpretable, not just a black box. The bigger decision, recorded explicitly rather than left implicit, was *how* to build it. The obvious path — adopting the `pytorch-forecasting` library's own `TemporalFusionTransformer` — was rejected because that library hard-requires PyTorch Lightning as a dependency, and this codebase had already deliberately rejected Lightning for the LSTM ("Lightning's abstraction isn't pulling its weight as a new dependency"). Pulling it in through TFT would have silently reintroduced exactly the dependency already ruled out, for a second model, without ever revisiting that original decision. Hand-rolling kept the codebase consistent with itself.

The other explicit decision: TFT is trained **one model per region**, mirroring the LSTM's own convention, rather than one joint multi-region model with region as a static covariate. That's the lower-risk, more consistent choice given how every other model here is trained and evaluated — but it has a real architectural consequence worth being upfront about: with region fixed per model instance, there's nothing series-varying left to feed as a static covariate. The static-enrichment layer stays in the architecture (a real, paper-faithful shape) so a future multi-region TFT could wire real static inputs in without restructuring the module, but today it's always fed a zero vector — a documented no-op, not silently pretended to be doing something.

### Architecture

```
encoder features (lookback)          decoder features (horizon)
observed-past + known-future          known-future only
        │                                     │
        ▼                                     ▼
 Variable Selection Network          Variable Selection Network
        │                                     │
        ▼                                     ▼
   LSTM encoder ──────hidden/cell state──────► LSTM decoder
        │                                     │
        └───────────────concat────────────────┘
                         │
              gated skip connection (GLU + LayerNorm)
                         │
              static enrichment (GRN; zero context in v0)
                         │
        interpretable multi-head self-attention
        (causal-masked, shared value projection across heads)
                         │
              gated skip connection (GLU + LayerNorm)
                         │
           position-wise feed-forward (GRN)
                         │
     gated residual from the PRE-attention representation
                         │
                 three heads: point / lower / upper
             (same point ± softplus(spread) parameterization
                       DemandLSTM uses)
```

The building blocks are the paper's, faithfully:

- **Gated Linear Units (GLU)** sit on every skip connection. A GLU projects to twice the target size, splits it in half, and uses one half to sigmoid-gate the other — letting the network learn to suppress an entire sub-block's contribution when it isn't useful for a given input, rather than always adding its full output unconditionally.
- **Gated Residual Networks (GRN)** are the model's core repeated unit: an ELU-activated two-layer MLP, gated back to a residual connection via a GLU, then layer-normalized. This is reused everywhere — variable selection, static enrichment, the feed-forward block.
- **Variable Selection Networks** project each scalar input variable independently, pass it through its own GRN, and combine the results via softmax weights that are themselves learned by another GRN over the flattened input — so the model learns, per timestep, which of its input variables actually matter right now, rather than treating every input as equally relevant at every step. These weights are computed but not currently surfaced anywhere in the UI — real interpretability signal sitting unused.
- **Interpretable multi-head attention** is TFT's specific variant: each head gets its own Q/K projection, but there's a *single* value projection shared across every head, and head outputs are averaged (not concatenated). Because every head shares the same value space, averaging keeps the resulting attention weights directly comparable across heads — "how much did each head attend to each position" becomes a genuinely meaningful question, which is what gives this attention variant its name.
- **The causal mask** blocks attention from a position to anything after it in the concatenated encoder+decoder sequence, so the decoder never gets to peek at future encoder positions it shouldn't have access to.
- **The final residual skip is taken from the pre-attention representation**, not the post-attention one — matching the paper's own equation for the residual source rather than the more obvious (but subtly different) alternative.

### How it's used

TFT trains through the same pipeline as the LSTM — `log_and_register_run` treats `result.model` as a generic `nn.Module`, architecture-agnostic — and is registered in MLflow as its own model (`lstm_demand_tft`). It's evaluated through the exact same walk-forward harness (`evaluate_tft_and_log`) against the same seasonal-naive baseline, over the same regions, and its results are visible in the dashboard's offline Model Comparison view. What it is *not* is reachable from `GET /v1/forecast` — there is no `architecture` query parameter, no live A/B path, nothing that routes real traffic to it. It exists entirely in the "trained, evaluated, benchmarked" world, not the "serving real dashboard requests" one.

### What could be improved

- The single biggest gap is exactly the one named above for the LSTM: there's no logged, decisive walk-forward comparison establishing that TFT actually beats the LSTM enough to justify the switch and its added complexity. Until that comparison exists and is decisive, keeping TFT off live serving is the conservative, defensible choice — but it also means a potentially better model is sitting idle.
- The per-region training decision means TFT currently gets zero benefit from its own static-enrichment machinery — a real, working piece of the architecture that contributes nothing today. A multi-region variant with region as a genuine static covariate is the natural way to make that investment pay off, but it's a real design change, not a config flag.
- The variable-selection weights this architecture already computes for genuine interpretability aren't surfaced to a dashboard or an analyst anywhere yet — a real, already-available signal going unused.

---

## 4. TimesFM — the zero-shot outsider

### What it is

TimesFM is Google's pretrained time-series foundation model — a ~200-million-parameter transformer trained on a huge variety of time series, wrapped here as an adapter that plugs into the same `Forecaster` protocol as the LSTM and TFT. Unlike either of them, there's no training loop at all: the checkpoint is downloaded once, compiled, and used directly.

### Why it was chosen

The appeal of a foundation model is exactly its zero-shot nature: no training data curation, no hyperparameter search, no region-specific model to maintain — just point it at a series and ask for a forecast. That makes it a fundamentally different kind of comparison point than the LSTM or TFT: not "a better-tuned custom model," but "how much does custom training actually buy us over a general-purpose model that's never seen this grid's data before?" That's a real, useful question to have an honest answer to, which is why it was worth building the adapter even without any expectation of training it further.

Two honesty notes are baked into the implementation rather than glossed over. First, the original plan named TimesFM 2.0 (`google/timesfm-2.0-500m-pytorch`) as the target checkpoint, but the installable package at build time only shipped TimesFM 2.5's default checkpoint (`google/timesfm-2.5-200m-pytorch`, 200M params, not 500M) — the plan's own explicit allowance for "the current recommended checkpoint at implementation time" is what's actually running, pinned to an exact HuggingFace commit SHA rather than a floating reference, so a future upstream change can't silently alter this adapter's accuracy out from under it. Second, the older API's `freq` bucket parameter (a common source of silent accuracy loss if set wrong) doesn't exist in the installed 2.5 API at all — the real analogous risk in this version is `max_context` being too small to see a full day of history, which is why it's set generously above both NEM's 5-minute cadence (needs ≥288 steps) and WEM's 30-minute cadence (needs ≥48).

### Architecture

There's no custom network to design here — the architecture is Google's pretrained transformer, used as-is. What *is* real engineering work is the adapter around it:

- **Univariate only, by design.** TimesFM feeds only the raw demand series (`TARGET_COLUMN`), not the full engineered `FEATURE_COLUMNS` set the LSTM trains on. The SDK does expose a covariate-aware forecasting path, but it's deliberately unused here, matching the "no training step" framing of this evaluation phase — meaning TimesFM's forecasts are honestly weather- and generation-mix-blind in a way the LSTM's aren't, a real, disclosed asymmetry rather than an implied equivalence.
- **Output patch rounding.** The compiled model silently rounds any requested `max_horizon` up to the nearest multiple of its 128-step output patch size — asking for 64 quietly gets you a model compiled for 128. The adapter mirrors this rounding itself so its own "can I forecast this horizon" check matches what the compiled model will actually accept, instead of rejecting a valid request the model would have happily handled.
- **Decile-based quantiles.** The model's real output is a `(batch, horizon, 10)` tensor — column 0 is a mean estimate, columns 1–9 are the deciles 0.1 through 0.9. P10/P50/P90 are read from columns 1, 5, and 9 respectively — verified directly against a real forecast (column 5's values matched the model's own separately-reported median exactly) rather than assumed from documentation, since the `timesfm` package doesn't document this column layout as a stable public contract.
- **A process-wide singleton, not a fresh load per call.** Loading and compiling a 200M-parameter checkpoint is expensive — a real download the first time, a real compile step every time. This matters more than it sounds: a real out-of-memory kill was observed in production when a long-running training worker downloaded and compiled a *second* full checkpoint for a subsequent correction job immediately after finishing the first, because each call site loaded fresh instead of reusing what was already resident. Caching the loader to hold exactly one compiled model in memory fixed both the redundant work and the memory blowup, at the cost of a one-time recompile if the configuration genuinely changes.

### How it's used

Wrapped as `TimesFMForecaster`, it satisfies the exact same `Forecaster` protocol the LSTM and TFT do, so it plugs into `evaluate_walk_forward` with zero changes to the harness itself — the whole point of building that harness model-agnostic in the first place. `evaluate_timesfm_and_log` runs it through the same walk-forward backtest and the same seasonal-naive baseline comparison, tagging its MLflow evaluation run with the exact HuggingFace repo and revision used, since there's no registered model version to pin the comparison to otherwise. It has no MLflow Model Registry entry at all — there's nothing *this project* produced to version, since the weights are frozen and Google's, not trained here.

### What could be improved

- The covariate path exists in the underlying model but is unused — a real, deliberate scope cut for this phase, not a limitation of TimesFM itself. A covariate-aware evaluation (feeding weather and generation mix the way the LSTM does) is real future work that could materially change how the comparison looks.
- Zero-shot also means zero domain adaptation — it has never seen this grid's actual demand patterns, holidays, or regional quirks. Whether that's a fair fight against a model trained specifically on this data, or an unfair one favoring the custom model, is exactly the kind of question the walk-forward numbers are meant to answer honestly — but doing that comparison credibly requires holding both models to the same feature-availability standard, which today they aren't.
- Like TFT, it isn't reachable from live serving, so its real value is entirely as an evaluation benchmark right now, not a production safeguard or alternative.

---

## How the Four Fit Together

All four models are honestly comparable because they share one evaluation harness. `evaluate_walk_forward` doesn't know or care which architecture it's scoring — it only needs something that satisfies the `Forecaster` protocol (a `predict(history, horizon) -> (p10, p50, p90)` method), which is exactly why the seasonal-naive baseline, the LSTM, TFT, and TimesFM all plug into it unmodified. That's a genuinely load-bearing design decision: it's what makes "did this new architecture actually help" a real, checkable question instead of an assumption, for every model added past the first.

A runtime ensemble across architectures (`blend.py`, an inverse-recent-error weighting scheme) existed at one point and was deliberately removed once it became clear it had zero real callers — the project settled on serving exactly one architecture live rather than maintaining a blend nobody was actually using. That's consistent with the broader theme running through all four models above: real, working code exists for more sophisticated options than what's currently live, and the gap between "built and evaluated" and "serving real traffic" is a deliberate, recorded gate — a walk-forward comparison that has to exist and be decisive — not an accident of unfinished work.

## Cross-Cutting Improvements Worth Prioritizing

1. **The decisive comparison itself is the biggest missing piece.** Every one of TFT's and TimesFM's "what could be improved" sections above ultimately traces back to the same open item: a real, logged walk-forward comparison against the LSTM that's decisive enough to justify a serving change. Until that exists, "LSTM is what's live" remains a historical fact more than a chosen-on-merit outcome.
2. **The weather-forecast gap affects every architecture that could use it.** The LSTM and TFT are both trained on weather *observations*, not forecasts, and TimesFM doesn't see weather at all. A live weather-forecast feed (as opposed to BoM's after-the-fact readings) is a real, shared upgrade path that would benefit whichever architecture ends up served.
3. **The forecast-quality circuit breaker is half-built across the board.** The state machine that would fall back to the seasonal-naive baseline during a real production quality incident is implemented and unit-tested, but the reconciliation job that would actually trigger it — comparing what was served against what really happened — isn't wired up yet. Right now, if the served LSTM's real-world accuracy degrades, nothing automatically catches it.
