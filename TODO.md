# PreProcessing

> Turns the 5 raw sources into one 30-min feature table. See
> `HYBRID_ML_PIPELINE_AND_MODEL_TRAINING_SPEC.md` for the full design.

- [ ] **Build the 30-min master timeline, starting 2025-08-01.** Every
  region (NSW1, QLD1, VIC1, SA1, TAS1 for NEM, plus the single WEM zone)
  gets its own row on this shared half-hourly spine — this is what
  everything else in the pipeline joins onto.
- [ ] **Downsample AEMO's 5-min dispatch data onto the spine.** Both NEM
  and WEM publish every 5 minutes, so each 30-min slot needs to fold 6
  raw observations into one: mean or total for energy-type quantities
  (generation, demand), average or last-value for instantaneous ones
  (price, frequency).
- [ ] **Map BoM's 30-min observations straight across.** No
  interpolation needed here — BoM is already on our target grain.
- [ ] **Broadcast the daily public-holiday flag across all 48 slots
  that day.** `is_public_holiday` is a per-day fact; every half-hour
  interval in that day should inherit it.
- [ ] **Sync only the final, curated feature table to NeonDB.** Keep
  raw/intermediate steps in local DuckDB; `model_feature_store`
  (Postgres, NeonDB) should only ever hold the finished product.
- [ ] **Guardrail: never silently zero-fill missing values.** A true
  gap is not the same as "zero renewable generation" — this is
  especially easy to get wrong for `renewable_proportion`.
- [ ] **Guardrail: fall back to OpenElectricity when AEMO is missing.**
  Wire this in as the documented recovery path for gaps in the primary
  NEM/WEM feed, not an afterthought.


# Feature selection

> The 5-step statistical gauntlet every candidate feature has to survive
> before it's allowed into the model — each step should be scriptable
> and re-runnable, not a one-off notebook exercise.

- [ ] **Step 1 — Structural hygiene.** Drop obvious leakage/metadata
  columns (`ingest_run_id` and friends), handle missing blocks, and
  prune zero-variance columns that Australia's fuel mix will never
  populate (`nuclear_mw`, `geothermal_mw`).
- [ ] **Step 2 — Mutual Information ranking against `demand_mw`.** MI
  catches non-linear relationships (e.g. price spikes) that a plain
  correlation would miss. Drop the bottom 15–20% of features by MI
  score.
- [ ] **Step 3 — PACF-driven lag selection.** Run the Partial
  Autocorrelation Function on `demand_mw` and pick lag steps that are
  actually statistically justified, instead of guessing round numbers.
- [ ] **Step 4 — TreeSHAP + LightGBM multicollinearity pruning.** Fit a
  proxy LightGBM model, rank features by global TreeSHAP importance,
  and drop redundant macro aggregates while keeping the granular
  per-fuel breakdown.
- [ ] **Step 5 — TFT variable-selection gating.** Run the surviving
  features through the TFT's own Variable Selection Network and
  permanently retire anything that gets near-zero attention across
  every forecast horizon.


# Feature Engineering

- [ ] **Generate demand lag features at 1, 2, 48, and 336 steps** (30
  min, 1 hour, 1 day, and 1 week back, at the 30-min grain).
- [ ] **Generate rolling-window stats: mean, median, max, min, std.**
- [ ] **Drop the raw, un-engineered columns once their derived
  lag/rolling features exist** — don't feed the model both forms.


# Predictive model

- [ ] **Stand up the LSTM.** Full backbone, full head, baseline LR
  `1e-3`.
- [ ] **Stand up the TFT.** VSN + attention + decoder backbone, with an
  adaptive head.
- [ ] **Stand up TimesFM.** Frozen transformer backbone, head-only
  training.
- [ ] **Wire the monthly retrain schedule.** Auto-trigger on the 1st of
  every month at 00:00 AEST, plus a manual trigger through the admin
  API for out-of-cycle runs.


# Fine tuning

- [ ] **LSTM monthly fine-tune.** LR `5e-5 → 1e-4`, 2–5 epochs, both
  backbone and head trainable.
- [ ] **TFT monthly fine-tune.** LR `1e-5`, 2–3 epochs, static
  embeddings (`region`, `network_code`) frozen — only VSN/attention/
  decoder adapt.
- [ ] **TimesFM monthly fine-tune.** Very small LR, 1–2 epochs,
  transformer backbone stays frozen, only the head trains.
- [ ] **Feed each run from the new 30-min data buffer** accumulated
  since the previous fine-tune, not the full historical set.


# Validation

- [ ] **Hold out the last 3–5 days of data, untouched by fine-tuning,**
  as the promotion gate for every candidate model.
- [ ] **Score candidates on MAE + RMSE against `demand_mw`.**
- [ ] **Enforce the promote/rollback guardrail:** a candidate only
  replaces production if its holdout MAE is ≤ production's MAE;
  otherwise it's rejected automatically and production keeps serving —
  no manual rollback step needed.


# Normalization Constraint Layer:

- [ ] **Build the per-fuel rescaling layer for `source_breakdown_mw`.**
  16 fuel types come out of the per-fuel LightGBM ensemble
  independently; rescale them so they sum back to
  `total_demand_mw.p50` instead of trusting each fuel model's raw
  output in isolation.


# Deterministic Carbon Accounting

- [ ] **Compute carbon metrics deterministically — no ML in this
  path.** `predicted_total_carbon_kgco2e`, emissions intensity, and
  renewable proportion should all be derived straight from the fuel
  mix using IPCC AR5 and AEMO NGES emission factors, not predicted by
  a model.


# API & Registry Serving

- [ ] **Serve the four JSON blocks as one decoupled response:**
  `total_demand_mw` (p10/p50/p90 from TFT/LSTM/TimesFM),
  `source_breakdown_mw` (post-normalization, 16 fuel types),
  `carbon_metrics` (deterministic), and `weather_context` (live BoM
  temp/humidity/wind for explainability — current conditions only, not
  a forecast).
- [ ] **Register and promote every model through the MLflow registry**
  (`/var/lib/ecolens/mlflow.db`), gated by the Validation section's
  promote/rollback decision — nothing reaches serving without going
  through that gate.
