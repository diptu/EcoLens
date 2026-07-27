# PreProcessing

> Turns the 5 raw sources into one 30-min feature table. See
> `HYBRID_ML_PIPELINE_AND_MODEL_TRAINING_SPEC.md` for the full design.
> Prototyped in `services/data-pipeline/notebooks/data-pipeline.ipynb`
> against the local DuckDB store; now implemented for real as dbt
> models in `services/data-pipeline/src/ecolens/warehouse/dbt_project/`.

- [x] **Build the 30-min master timeline, starting 2025-08-01.** Done —
  `int_energy_filled_30min` builds a `dim_region` × `generate_series`
  spine, one row per region per half-hour slot, forward-filled so
  there are no gaps for `LAG()`/rolling windows to trip over.
- [x] **Downsample AEMO's 5-min dispatch data onto the spine.** Done in
  `int_energy_unified_30min` — averages NEM's 5-min per-region rows and
  WEM's own 30-min rows onto the grid. Found and fixed a real bug while
  verifying this: NEM's per-region rows only ever carry demand/price,
  never the fuel-tech mix (that only lives on AEMO's separate
  network-level `"NEM"` row) — left un-broadcast, every NEM region's
  `renewable_generation_mw` was silently reading 0 instead of real
  generation data. New `stg_aemo_nem_fueltech` model broadcasts that
  network row onto all 5 sub-regions now.
- [x] **Map BoM's 30-min observations straight across.** Already done
  in `int_energy_with_weather` — no interpolation needed, BoM's already
  on-grain.
- [x] **Broadcast the daily public-holiday flag across all 48 slots
  that day.** Already done, same model's holiday join.
- [x] **Sync only the final, curated feature table to NeonDB.** Done —
  the dbt models write straight into Postgres/NeonDB, so there's no
  separate DuckDB-export step to build, and the `raw.*` syncer
  (`ecolens.ingestion.storage.postgres.RawSyncer`, run via
  `scripts/sync_raw.py --full`) turned out to already exist; it just
  hadn't been run against this NeonDB instance yet. Full historical
  backfill (~1.03M rows across all 5 sources) run for real, then
  `dbt build` against it: `ml.ml_features_demand_v1` now holds 103,158
  real rows (verified correct against real ingested data, not seeded
  synthetic rows). Marts also now split across pre-provisioned
  `staging`/`intermediate`/`analytics`/`ml` schemas
  (`generate_schema_name.sql` + per-layer `+schema:` config) instead of
  landing in `public`.
- [ ] **Guardrail: never silently zero-fill missing values.** Still not
  a general policy — `fact_demand_30min`'s `renewable_generation_mw`
  still does `coalesce(hydro_mw, 0) + ...`; it's just no longer being
  fed NULLs by the bug above. Worth a real look at whether that
  `coalesce` should propagate NULL instead of masking it with 0.
- [x] **Guardrail: fall back to OpenElectricity when AEMO is missing.**
  Wired into `int_energy_unified_30min` — covers WEM (direct region
  match) and NEM's broadcast fuel-tech mix (same network-level grain).
  Known gap, not a bug: OpenElectricity never reports NEM below the
  whole-network level, so there's still no fallback for a missing
  NSW1/QLD1/VIC1/SA1/TAS1 *market* (demand/price) row specifically.


# Feature selection

> The 5-step statistical gauntlet every candidate feature has to survive
> before it's allowed into the model — each step should be scriptable
> and re-runnable, not a one-off notebook exercise. Steps 1–4
> prototyped in `services/data-pipeline/notebooks/data-pipeline.ipynb`
> against the real `feature_table_30min` (103k rows, 2025-08-01 →
> present); see the last item below for the gap that's still open.

- [x] **Step 1 — Structural hygiene.** Zero-variance and fully-null
  checks run clean against real data — no `nuclear_mw`/`geothermal_mw`
  to begin with (Australia's fuel mix never populated those columns,
  so there was nothing to prune there), and `ingest_run_id`-style
  metadata was already excluded upstream in PreProcessing rather than
  something this step has to catch itself.
- [x] **Step 2 — Mutual Information ranking against `demand_mw`.** Done
  via `sklearn.feature_selection.mutual_info_regression`, dropping the
  bottom 17.5% (midpoint of the spec's 15–20%) — on the real data
  that's `wind_speed_kmh`, `cloud_cover_pct`, `rain_since_9am_mm`,
  `is_public_holiday`, `wind_gust_kmh`.
- [x] **Step 3 — PACF-driven lag selection.** Done via
  `statsmodels.tsa.stattools.pacf` on NSW1's demand series — confirmed
  all 4 of the spec's proposed lags (1, 2, 48, 336) are genuinely
  statistically significant, out of 131 significant lags found up to
  lag 340.
- [x] **Step 4 — TreeSHAP + LightGBM multicollinearity pruning.** Fit a
  LightGBM model, then for any feature pair correlated above 0.9, drop
  whichever has the lower LightGBM importance. On real data this is
  exactly what caught `total_generation_mw` (r=0.98 with
  `coal_black_mw` — the "redundant macro aggregate" the spec calls out
  by name), plus `apparent_temp_c` and `wind_gust_kmh`. Using
  LightGBM's own gain importance in place of true TreeSHAP: the `shap`
  package won't build on this machine (Python 3.12, no compatible
  wheel/sdist) — swap it in if that gets resolved later.
- [ ] **Step 5 — TFT variable-selection gating.** Blocked, not done —
  there's no TFT anywhere in this repo yet to read VSN weights from
  (see "Predictive model" below, "Stand up the TFT"). The notebook
  cell documents this explicitly rather than silently skipping it.
- [ ] **Extract Steps 1–4 out of the notebook into a reusable,
  re-runnable module.** Right now they're still exactly the "one-off
  notebook exercise" this section's own intro warns against — the
  logic is proven correct against real data, it just isn't callable
  from anywhere but that notebook yet.


# Feature Engineering

> Prototyped in `services/data-pipeline/notebooks/data-pipeline.ipynb`
> against the real `selected_feature_table_30min` (103,614 rows) from
> the Feature selection section above. Same open gap as that section:
> proven correct, not yet extracted into a reusable module.

- [x] **Generate demand lag features at 1, 2, 48, and 336 steps** (30
  min, 1 hour, 1 day, and 1 week back, at the 30-min grain). Grouped by
  `region` before shifting — verified explicitly (not just assumed)
  that no region's first row picks up a lag value leaked from the
  previous region in sort order.
- [x] **Generate rolling-window stats: mean, median, max, min, std.**
  Trailing 336-slot (7-day) window, computed on the lag-1-shifted
  series so the current slot never leaks into its own rolling feature
  — same convention the production `ml_features_demand_v1` dbt mart
  already uses (`rows between 336 preceding and 1 preceding`). Spot-
  checked one region/row's rolling mean against a manual `.mean()` over
  the exact same window, not just "did it run without error."
- [x] **Drop the raw, un-engineered columns once their derived
  lag/rolling features exist** — don't feed the model both forms.
  Concretely: `demand_mw` itself is excluded from the feature matrix
  (`X_engineered`) and kept only as the separate target (`y_engineered`)
  — keeping it in `X` alongside its own lags would be leakage, not
  redundancy.
- [ ] **Stale doc note found while reviewing `ml_features_demand_v1.sql`
  for comparison (not fixed here, flagging it):** its `total_generation_mw`
  comment still says "~53% null, AEMO NEM doesn't emit it" — that was
  true before this session's PreProcessing fix (`int_energy_unified_30min`
  now broadcasts AEMO NEM's own network-level fuel mix, including
  `total_generation_mw`, onto all 5 sub-regions), so the comment is now
  wrong about current behavior. Worth a real pass over that mart once
  the `raw.*` syncer (see PreProcessing) lands and it can actually be
  re-run against live data to confirm the new null rate.


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
