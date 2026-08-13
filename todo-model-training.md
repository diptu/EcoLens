# TODO's — Model Training (LSTM / TFT / TimesFM / Blend)

Companion docs:
- `TODO.md` — platform-wide TODOs (Storage, Performance, Model Operations
  fine-tune-UI wiring, the backfill/dbt-staleness work)
- `todo-operational-tasks.md` — whole Operational Tasks page

This file is cited throughout `services/data-pipeline` and
`services/forecast-api` as `todo-model-training.md Phase N` — dozens of
real, working modules already reference specific phase numbers in their own
docstrings. This document itself was empty until now; reconstructed
(2026-08-04) from that scattered-but-consistent numbering plus a direct
read of every module it names, not written speculatively. Everything under
"Ground truth" already exists and runs today. Only the two sections after
it ("Training all three models" and "Frontend reflection") are new
planning, done at the user's request. Re-verified against current code
and the live database 2026-08-05 (Performance-page loss curve shipped,
`make train`/`make train-tft` updated, the OE region blocker re-checked
and confirmed unchanged) — see the "Done"/"Bug found + fixed" notes
inline for what changed that day.

---

## Ground truth — Phases 0-8 (verified against current code, 2026-08-04)

### Phase 0 — Walk-forward evaluation harness + baseline
Real: `service/ml/evaluate.py`'s `evaluate_walk_forward` (rolling-origin
backtest → real MAPE/RMSE/pinball-loss/coverage), `models/baseline.py`'s
seasonal-naive `Forecaster` (the floor every real model must beat), and
the `Forecaster` protocol itself — every model below (LSTM/TFT/TimesFM)
implements it, so the harness needs zero per-model changes. `cli.py
evaluate`.

### Phase 1 — TimesFM adapter (zero-shot foundation model)
Real: `models/timesfm_adapter.py` wraps `google/timesfm-2.5-200m-pytorch`
behind the same `Forecaster` protocol (the plan originally named the 2.0
checkpoint; 2.0's architecture isn't importable through the actually-
installed `timesfm==2.0.2` package — documented as a deliberate,
allowed substitution, not silently swapped). Zero-shot: no training
loop, no MLflow-registered weights — the checkpoint's own pinned
HuggingFace revision (`TIMESFM_REVISION`) is the version identity
instead. `cli.py evaluate-timesfm`.

### Phase 2 — TFT (Temporal Fusion Transformer)
Real: `models/tft.py` (Lim et al. 2019), `service/ml/train_tft.py`
(`train_and_register_tft`, registers under `lstm_demand_tft` — a
deliberately distinct MLflow model name from `lstm_demand`, naming-
discipline decision recorded directly in `cli.py`), and `features.py`'s
`KNOWN_FUTURE_COLUMNS`/`OBSERVED_PAST_COLUMNS` split for TFT's
encoder/decoder input contract. `cli.py train-tft`, `evaluate-tft`.

### Phase 3 — Multi-model blend
Real: `service/ml/blend.py`'s `BlendForecaster` — inverse-recent-error
weighting across however many real experts are currently loaded (a
recorded decision: not fixed learned stacking weights, not
best-of-recent selection — the only option of the three that adapts
*which* expert wins as conditions change). "Recent error" is computed
genuinely, by re-forecasting from `window` earlier points already
inside the `history` it was given and comparing to real outcomes — not
fabricated, no new state. Implements `Forecaster` like everything else,
so no harness/registry changes were needed to add it.

### Phase 4 — Online/incremental training infrastructure
Real: `service/ml/incremental.py`/`incremental_tft.py` (warm-started
fine-tune from Production/Staging), `service/ml/divergence.py` (weight-
norm drift guard vs. the last full retrain — `drift_relative_l2`,
`drift_exceeded_threshold`, `drift_compared_against_run_id`, logged as
real MLflow run params on every incremental run), `training_worker.py`'s
live-evaluation gate (`run_live_evaluation_gate`, sets real
`eval_gate_passed`/`eval_gate_mape` MLflow **version tags** — not
currently surfaced in `ModelVersionOut`/the dashboard), and
`pipeline.flows.incremental_retrain_trigger` (the higher-frequency
Prefect deployment — real code, undeployed; see `TODO.md`'s raw→marts
staleness entry for the same missing-Prefect-server gap).

### Phase 5 — Structured pruning + recovery fine-tune
Real: `service/ml/prune.py` — a real before/after benchmark, a real
acceptance check, and a real recovery fine-tune pass after pruning.
`cli.py prune`.

### Phase 6 — Forecast-serving resilience
Real: `forecast-api/service/ml/forecast_breaker.py` — a circuit breaker
around live forecast serving (closed → open → half_open), the same
pattern `data-pipeline`'s ingestion circuit breakers already use.

### Phase 7 — Real external-provider-first emissions intensity
Real: `forecast-api/service/ml/data.py`'s provider-vs-derived intensity
fallback (`resolve_intensity_method`), threaded through every
emissions/footprint response schema and route (`live_provider` vs.
`live_mix_weighted`, freshness-gated). The logic itself is real and
correct — but currently starved of fresh input, since OpenElectricity
ingestion has been broken in two separate, unrelated ways since
~2026-07-27 (see `TODO.md`'s `OE_API_KEY` finding, and this file's
region-mismatch finding below).

### Phase 8 — Multi-architecture dashboard support (partial)
Real, backend only: `forecast-api`'s `GET /v1/model`, `GET /v1/model/
versions`, `POST .../promote` already accept an arbitrary `model_name`
(`ModelRegistry.list_versions(model_name)` — genuinely not hardcoded to
`lstm_demand`, confirmed directly). `mlops/drift.py`'s PSI/KS feature-
drift detector is real, tested code with zero callers anywhere in the
pipeline (confirmed this session — a live "concept drift" feature built
on top of it today would be fabricated).

**Not real yet**: the dashboard only ever queries `lstm_demand`/
`lstm_demand_tft` (`lib/emissions.ts`'s `MODEL_ARCHITECTURES`). TimesFM
is *correctly* absent from that list — it has no registry versions to
list (zero-shot) — but there's also no *other* real data path exposing
its evaluation-run history to the frontend at all yet. See "Frontend
reflection" below.

**Done (2026-08-05)**: per-epoch `train_loss`/`val_mape` history — real
since `ml/train.py`'s `log_and_register_run` (shared by LSTM and TFT
alike) always logged it as real MLflow step-metrics
(`mlflow.log_metrics(..., step=epoch)`), but had no read path: `client.
get_run(...).data.metrics` only ever returns each key's *final* value,
not its history — only `MlflowClient.get_metric_history` reads the full
curve. Closed by a new `forecast-api` route `GET /v1/model/versions/
{version}/loss-curve` (`ml/registry.py`'s `get_loss_curve`, merges
`train_loss`/`val_mape` by epoch), `lib/emissions.ts`'s
`fetchLossCurve()`, and a real "Training loss curve" card on
`/dashboard/performance` (`LineChart` of `train_loss` for the Production
version, falling back to the newest version if none is Production yet).
Applies to LSTM and TFT alike (same shared logging function) — **not**
TimesFM, which has no per-epoch training loop to log from (zero-shot,
Phase 1).

**Bug found + fixed while verifying the page (2026-08-05)**: its
`RMSE_KEYS` fallback list included `"test_rmse"` — that key is never
actually logged anywhere in this codebase (`train.py`'s `test_metrics`
only ever logs `test_mape`/`test_coverage_raw`/`test_coverage_calibrated`;
RMSE is exclusively an `evaluate.py` walk-forward metric, `eval_rmse`).
Not a crash (the lookup just silently fell through to the real
`"—"` empty state), but a version that was only ever trained, never
live-evaluated, would misleadingly *look* like it was checked for an
RMSE fallback that could never exist. Fixed to `["eval_rmse"]` only.

## Training all three models on the real, current dataset (2026-08-04)

### Blocker — root cause fixed in code (2026-08-05); still not
end-to-end unblocked (2 follow-ups remain, see below)

**Original finding** (confirmed empirically): LSTM and TFT couldn't
train against real data at all, for *any* region, not just a
multi-region run. `raw.openelectricity_mix.region` only ever contained
the literal values `'NEM'`/`'WEM'` (network-level) — never the
per-region values (`NSW1`, `QLD1`, etc.) that `int_demand_with_weather.
sql`'s generation `LEFT JOIN LATERAL` needs to match against AEMO's
per-region demand rows. Confirmed directly against the live database:
`total_generation_mw` was `NULL` for **100% of NSW1 rows** in
`raw_marts.fct_energy_demand` (0 of 105,727 — re-queried 2026-08-05,
unchanged). `total_generation_mw`/`total_renewable_mw` are required
(unimputed) `FEATURE_COLUMNS`, and `DemandDataset` drops any sliding
window containing a NaN in *any* feature column — so a real end-to-end
`ecolens-pipeline train` run (any region) produced **zero usable
train/val/calibration windows**.

**Root cause, found investigating the "decide (a)/(b)/(c)" question
below (2026-08-05)**: it was neither purely bad seed data (b) nor a case
for weakening the join (a) — `ingest_openelectricity.py`'s *own current
code* had the real bug. Its loop called `fetch_network_data(net,
since=since)` — no region scoping at all — once per NEM region
(NSW1/QLD1/VIC1/SA1/TAS1), got back the exact same network-wide answer
each time (`emissions.py`'s SDK wrapper never passed a region filter to
`AsyncOEClient.get_network_data`, even though its own real, typed
signature has always accepted `network_region: str | None`, confirmed
by reading the installed SDK directly), and just relabeled that one
network-wide result 5 times with a different region code each time. Even
a real (non-empty) run of the *old* code would have written `NSW1`'s
`total_generation_mw` == `QLD1`'s == `VIC1`'s etc. — silently
masquerading as real per-region data, not just producing NULLs. The
`int_demand_with_weather.sql` join itself was never the problem — it
already joins on `region` correctly, exactly what's needed once the
upstream data is genuinely per-region.

- [x] **Fixed (region mislabeling)**: `emissions.py`'s
      `fetch_network_data`/`fetch_emissions` now accept and pass through
      `network_region` (NEM's 5 regions get their own scoped query; WEM
      passes `None`, having no sub-regions of its own).
      `ingest_openelectricity.py`'s loop now asks for each NEM region's
      real numbers instead of relabeling one shared network-wide fetch.

- [x] **Two more real bugs found + fixed the same day (2026-08-05), once
      a real `OE_API_KEY` finally let this get tested against the live
      API for the first time** — both were completely unreachable before
      that (client construction always raised first without a key), so
      neither could have been caught by code review alone:
      1. **OE rejects a tz-aware `date_start`** ("Date start must be
         timezone naive and in network time", confirmed live) — `since`
         has always been UTC-aware
         (`datetime.now(timezone.utc) - timedelta(...)`); every real call
         would have 400'd regardless of the region fix. Fixed:
         `_fetch_metric` now converts to naive local network time before
         querying (NEM = fixed AEST/UTC+10, WEM = fixed AWST/UTC+8, both
         confirmed against real API response `date_start`/`date_end`
         fields, not assumed) and converts the response's `ts` back to
         real UTC before returning it (the SDK's own `to_records()`
         hands back naive *local* time, confirmed by reading
         `TimeSeriesResponse._create_network_date` directly — reusing it
         unconverted would have misaligned every OE row against AEMO's
         UTC `ts` by the network's fixed offset once joined).
      2. **`_FUEL_COLUMN_MAP` never matched OE's real fuel-type
         taxonomy** — confirmed live the real API returns
         `coal_black`/`coal_brown`/`gas_ccgt`/`gas_ocgt`/`gas_steam`/
         `gas_recip`/`gas_wcmg`/`bioenergy_biomass`/`bioenergy_biogas`/
         `pumps` (`openelectricity.types.UnitFueltechType`'s own
         canonical enum), none of which the old map recognized (it only
         had `"coal"`/`"black_coal"`/`"ccgt"`/`"biomass"`/
         `"pumped_hydro"` — values the real API has apparently never
         actually sent). Every real coal/CCGT/OCGT row — the single
         largest share of real NEM generation — was being silently
         dropped from `total_generation_mw`, a far more severe bug than
         either of the other two: even after fixing region-scoping and
         the date format, `total_generation_mw` would have come back
         near-zero instead of the real ~5-7 GW per region. Fixed by
         rewriting the map against the SDK's real enum.
      Live-verified end to end after all three fixes: NSW1 6854 MW total
      (83% coal), QLD1 6649 MW (92% coal), VIC1 7150 MW (64% brown coal +
      24% wind) — all textbook-correct for these grids, and genuinely
      different per region (e.g. wind: NSW1 759 MW vs. QLD1 397 MW vs.
      VIC1 1731 MW at the same timestamp).

  13 new/updated tests across
  `test_emissions_openelectricity.py`/`test_ingest_openelectricity.py`/
  `test_registry.py` (all passing), covering: distinct `network_region`
  per NEM call, naive-local `date_start` conversion (both networks'
  offsets), UTC round-trip on the response `ts`, and the corrected
  fuel-type map against real fuel_type strings. Three other pre-existing
  tests that unmonkeypatched-ly relied on `OE_API_KEY` being absent from
  this environment (`test_missing_api_key_raises_a_catchable_error`,
  `test_run_degrades_to_zero_rows_without_a_live_oe_api_key`,
  `test_run_source_oe_is_not_double_wrapped`) broke the moment a real
  key was added and were fixed to monkeypatch `get_settings` explicitly
  instead of depending on ambient environment state. Ruff/mypy clean.

- [x] `OE_API_KEY` is now set (2026-08-05, real credential added to
      `services/data-pipeline/.env`) — no longer the blocker `TODO.md`
      originally flagged.

- [x] **Two more real bugs found trying to actually land the first
      real per-region batch (2026-08-05)** — both only surfaced once
      genuinely distinct, non-empty per-region data existed to insert,
      which nothing before today's fixes had ever produced:
      1. **`_pivot_long_to_wide`'s rename silently orphaned a collided
         column.** The real API sends `"battery"` *and*
         `"battery_discharging"` simultaneously, and both map to
         `battery_discharge_mw` — the old rename-based logic renamed
         only the first and left the second under its *original*
         fuel_type name. That's not just a few dropped MW: the
         orphaned column has no matching column in
         `raw.openelectricity_mix` at all, so the Postgres load failed
         outright (`column "battery_discharging" ... does not exist`).
         Fixed by grouping source columns by destination and *summing*
         each group, not renaming 1:1.
      2. **`raw.openelectricity_mix` itself was missing `region` from
         its own uniqueness constraint.** Migration 0011 defines
         `PRIMARY KEY (ts, network_code, region)`, but that `CREATE
         TABLE` only ever runs when the table is empty — this specific
         database instead went through migration 0020's legacy-adoption
         path (renaming an old `raw.openelectricity_responses` table
         onto `openelectricity_mix`), which just renamed whatever
         constraint the legacy table already had
         (`UNIQUE (network_code, ts)` — no `region`) instead of
         reconciling it against 0011's intended shape. Once genuinely
         per-region rows existed, `load_to_postgres`'s
         `ON CONFLICT DO NOTHING` used that too-narrow constraint and
         silently dropped every region after the first to land for a
         given `(network_code, ts)` — 6 regions staged, only 2 (NSW1,
         WEM) actually reached the table. Fixed with a new migration,
         `migrations/0024_fix_openelectricity_mix_region_key.sql`
         (idempotent: drops the old constraint if present, adds the
         correct `(ts, network_code, region)` primary key if missing) —
         applied live, confirmed zero pre-existing duplicate
         `(ts, network_code, region)` groups before adding the key, so
         no data was lost adding it.
      1 new regression test added
      (`test_pivot_long_to_wide_sums_colliding_fueltechs_into_one_column`)
      for the first bug; the second is a DB-schema fix with no
      code-level test surface, verified by the successful re-ingest
      below instead.

- [x] **Stale data purged and real data re-ingested (2026-08-05).** The
      original 17,277 stale rows (`2026-06-27`→`2026-07-27`, region only
      ever `'NEM'`/`'WEM'`) were deleted, then real data was landed
      through the actual production path (`run_source("oe",
      lookback_minutes=1440)`, a 1-day window — wide multi-day native
      5-minute-resolution queries turned out to be impractically slow
      for this SDK version, see the wall-clock note below, so this was a
      deliberate scope choice, not a limitation of the fix itself).
      Confirmed in the database: **1,716 rows, all 6 real regions
      (NSW1/QLD1/VIC1/SA1/TAS1/WEM), 286 rows each**, `meta._ingest_log`
      status `success`. Per-region averages are textbook-correct and
      genuinely differentiated: NSW1 9,820 MW (59% coal), QLD1 8,549 MW
      (61% coal), VIC1 8,508 MW (54% brown coal, largest wind share at
      2,083 MW), SA1 1,478 MW (**zero coal** — SA's grid is coal-free,
      correctly), TAS1 1,547 MW (**zero coal** — TAS is ~100% hydro,
      correctly), WEM 2,657 MW (25% coal).
      **Not done**: a real historical *backfill* spanning weeks/months
      (matching AEMO's demand data, which goes back to 2025-07-31) —
      "oe" still isn't in `backfill.py`'s `_DATE_RANGE_SOURCES`, and
      wide-range queries are currently too slow (a single 3-day,
      6-region query took **86 seconds** — `openelectricity`'s own
      `TimeSeriesResponse.to_records()` does an O(n²) linear
      re-scan of already-built records per data point, confirmed by
      reading its source directly, not this codebase's own inefficiency
      to fix). A real day-by-day chunked backfill (mirroring
      AEMO/BOM's `_fetch_historical_range` pattern) is a real, separate
      follow-up, not attempted here — 1 day of real data across all 6
      regions is enough to unblock and re-verify training, not enough to
      train a production-quality model on.

- [x] **`dbt build` run, `raw_marts.fct_energy_demand` rebuilt
      (626,898 rows) — the blocker itself is empirically fixed
      (2026-08-05).** `dbt build` reported 1 failing test
      (`assert_national_intensity_within_tolerance`), but that's a
      separate, pre-existing, known-unfixed gap, not a regression: its
      own file comment says its `expected_national_intensity_kgco2e_per_mwh
      = 650` default is "a PLACEHOLDER, not a verified figure" that
      "needs a human to fill in with a citation" — it silently always
      passed before today only because the query it checks filters to
      `WHERE system_intensity_kgco2e_per_mwh IS NOT NULL`, and
      `total_generation_mw` being unconditionally NULL (this exact
      blocker) meant that row never existed to check. The real computed
      value is 501.86 kgCO2e/MWh — a plausible real NEM average, not an
      obviously-wrong number — but I have no cited authoritative figure
      to replace the placeholder with, so I left it failing rather than
      invent one; a real follow-up, tracked here, not fixed blind.
      `fct_energy_demand` itself built successfully regardless (dbt
      builds models before running tests; the model that actually
      matters for training was created 2 tests before the one that
      failed).

- [x] **Empirical NaN check re-run for real, using the actual training
      code path (`ml/data.py`'s `load_training_data` +
      `ml/features.py`'s `build_features`), not inferred from SQL
      (2026-08-05):**
      ```
      raw_df shape: (626898, 10)
      feat_df shape: (626898, 37)
      rows with any NaN: 626,723 of 626,898
      usable (no-NaN) rows: 175
      ```
      **The blocker is empirically, conclusively fixed**: before today,
      `total_generation_mw`/`total_renewable_mw` were NaN for **100%**
      of rows (0 usable) — structurally impossible to train on, any
      region, confirmed by actually running it. Now they're NaN for
      "only" 626,723 of 626,898 (still the overwhelming majority — but
      real, non-zero, real per-region data). **This is the expected,
      already-documented consequence of the 1-day-only backfill scope
      decision above, not a new bug**: with only 1 day of real OE
      generation data landed (out of a full year of AEMO demand
      history), only rows inside that 1-day window can possibly have a
      non-NaN `total_generation_mw` — the other ~364 days are
      genuinely, correctly NaN because there's real no data there yet,
      the honest state, not a bug pretending to be fixed.
      **175 usable rows is not enough to actually train on** — nowhere
      near enough real windows for meaningful train/val/calibration/test
      splits at `lookback+horizon=96` steps/window. The real historical
      backfill (this file's own tracked follow-up, immediately above)
      is what turns "the blocker is fixed" into "there's enough data to
      actually run `make train`" — those are two different, now
      correctly distinguished claims. Don't conflate them.
- [x] Same root ingestion module (`ingest_openelectricity.py`) as
      `TODO.md`'s `OE_API_KEY` finding, but was a genuinely different bug
      — setting the key alone fixes *freshness*, and (as of 2026-08-05)
      the region-label mismatch is fixed in code separately. Both are
      now addressed at the code level; what's left is operational
      (set the key, purge + re-ingest — see the two follow-ups above),
      not another code fix.

### LSTM (`lstm_demand`)
Once unblocked:
- [x] **Makefile updated (2026-08-05)**: `make train` now defaults to
      `--region NSW1 --region QLD1 --region VIC1 --region SA1 --region
      TAS1 --region WEM` (all 6 real regions in one joint run) instead of
      the old default of `Settings.model_default_regions` (`["NSW1"]`
      alone) — matches this plan's intended usage, not a claim it works
      yet (still blocked above). `make train REGION=NSW1` still trains a
      single region if that's genuinely what's wanted.
- [ ] `ecolens-pipeline train --region NSW1 --region QLD1 --region VIC1
      --region SA1 --region TAS1 --region WEM` (i.e. `make train` as of
      the update above) — one joint model across all 6 real regions
      (confirmed: `train_and_register`'s `regions` trains a single model
      conditioned on every passed region in one run, not N separate
      models).
- [ ] Confirm real `test_mape`/`test_coverage_calibrated` land in MLflow
      (`ModelVersion.metrics`) and look genuine — a suspiciously
      "perfect" MAPE immediately after the join fix would suggest
      leakage introduced by that fix, not real skill, and deserves a
      second look before trusting it.
- [ ] `evaluate --version <new>` for a real walk-forward number, not
      just the training-time test split.
- [ ] Registers at MLflow stage `None` — promote to `Staging` (or
      `Production`, gated on beating the current Production version's
      `test_mape` via the existing `promote_version` check) from
      `/dashboard/models`.

### TFT (`lstm_demand_tft`)
Same blocker, same fix, then:
- [x] **Makefile updated (2026-08-05)**: `make train-tft` gets the same
      all-6-region default as `make train` above, same reasoning.
- [ ] `ecolens-pipeline train-tft --region NSW1 --region QLD1 --region
      VIC1 --region SA1 --region TAS1 --region WEM` (i.e. `make
      train-tft`) — heavier than LSTM
      (attention over `OBSERVED_PAST_COLUMNS`/`KNOWN_FUTURE_COLUMNS`);
      budget real wall-clock time and run it backgrounded, don't block
      on it synchronously.
- [ ] `evaluate-tft --version <new>` — same Phase 0 walk-forward
      harness, no special-casing needed since TFT already implements
      the shared `Forecaster` protocol.
- [ ] Compare LSTM vs. TFT's real `eval_mape`/`eval_coverage` before
      deciding which (if either) becomes the dashboard's default
      Production-facing model — a real product decision once both have
      honest numbers, not something to default silently.

### TimesFM (zero-shot — a genuinely different process, not "training")
**Not blocked by the OE bug at all** — TimesFM's `Forecaster.predict`
only consumes `demand_mw`'s own history, not `FEATURE_COLUMNS`, so this
can run today, independently of the fix above:
- [ ] `ecolens-pipeline evaluate-timesfm --region NSW1` (repeat per
      region, or all 6). First run downloads/compiles the real ~200M-
      param checkpoint — genuine wall-clock cost, budget for it and run
      backgrounded.
- [ ] This logs a real walk-forward MAPE/coverage vs. the seasonal-naive
      baseline to MLflow tagged `evaluation` — **not** a registered
      model version (zero-shot; nothing to promote or serve as a
      stage). Don't conflate this with LSTM/TFT's registry entries
      anywhere it gets reflected (see below).
- [ ] Record the real numbers here once run — "TimesFM is competitive"
      needs a logged, comparable MAPE against the same regions/windows
      LSTM and TFT were evaluated on, not a hand-wave.

---

## Frontend reflection: real three-way model comparison

Current state (`lib/emissions.ts`'s `MODEL_ARCHITECTURES`, used by
`/dashboard/models` and the `/dashboard/performance` page built this
session): LSTM + TFT only, both genuinely real — `GET /v1/model/
versions` already accepts either `model_name` (Phase 8's backend
flexibility is already there). TimesFM is *correctly* absent from that
array today — it has no registry versions, and showing it there would
mean either an always-empty row (honest but useless) or inventing fake
version rows (exactly what this app's conventions forbid).

The real gap: there's no data path *at all* yet for TimesFM's
evaluation-run history (Phase 1's `evaluate-timesfm` output) to reach
the frontend. Closing it needs backend work first, not just a frontend
change:

- [ ] **Backend**: a new read endpoint (e.g. `GET /v1/model/evaluations?
      model_name=timesfm`, backed by an MLflow `search_runs` against the
      right experiment, filtered to `tag.mlflow.runName`/a custom
      `evaluation` tag) surfacing real logged evaluation runs —
      `eval_mape`, `eval_coverage`, `eval_rmse`, region, `evaluated_at`,
      the checkpoint revision tag. Genuinely new work — unlike the
      already-logged-but-unexposed `eval_gate_passed`/`eval_gate_mape`
      version tags (a smaller, similar gap noted in `TODO.md`'s
      Performance-page section for LSTM/TFT), TimesFM's evaluation runs
      have no existing endpoint to extend at all.
- [ ] **Frontend types**: `lib/emissions.ts` gets a parallel
      `EvaluationRun`/`fetchModelEvaluations()` — deliberately *not*
      reusing `ModelVersion`'s shape (no `stage`, no promote actions;
      an evaluation run isn't a registry entry and shouldn't imply one
      can be promoted or archived).
- [ ] **Models page** (`/dashboard/models`): a third, read-only
      section — "Zero-shot evaluations" — listing TimesFM's real logged
      runs, explicitly labeled as not-a-registry-entry (no stage badge,
      no promote button — there's nothing to promote to).
- [ ] **Performance page** (`/dashboard/performance`, built this
      session; now also has a real "Training loss curve" card,
      2026-08-05 — see the "Done" note in Phase 8 above): extend the
      architecture selector from the current LSTM/TFT toggle to a
      three-way LSTM/TFT/TimesFM toggle. LSTM/TFT tabs are unchanged
      (already real registry data + loss curve). The TimesFM tab reads
      from the new evaluations endpoint instead of `fetchModelVersions()`
      /`fetchLossCurve()` (TimesFM has no per-epoch loss curve — zero-
      shot, nothing to log) — same card layout, different data source,
      still fully real (no `IllustrativeBadge` needed here once Phase
      1's `evaluate-timesfm` has actually run for real data to show).
- [ ] **Blend (Phase 3) reflection** — lower priority, after the three
      individual architectures are real on the frontend: `BlendForecaster`'s
      inverse-recent-error weights aren't logged or exposed anywhere
      today. Before building any UI for it, confirm `GET /v1/forecast`
      actually serves a blend in production — today it only ever serves
      one Production model, not a blend, so a "blend" dashboard section
      would currently have nothing real behind it at all.

**Acceptance**: an operator on `/dashboard/models` or
`/dashboard/performance` can see real, current numbers for all three
architectures side by side — LSTM/TFT from the registry, TimesFM from
its evaluation history — with no fabricated rows and no tab presented as
if data should be there when it isn't.

---

## New — combined forecast + generation-mix + carbon-intelligence endpoint

Requested shape (2026-08-05): one response per forecast point carrying
demand (P10/P50/P90), a per-fuel generation-mix breakdown, derived
carbon intelligence, and an explicit calibration flag. **Decision made:
serve at the model's native 5-min interval** (matching `/v1/forecast`'s
own real output cadence for a NEM region — `interval: "5m"`, 48 points
over the 4h horizon), not the originally-sketched 30-min. This removes
the interval-resampling question entirely — no aggregation-method
decision needed, no risk of a resampling choice silently changing what
"P90 at a given timestamp" means. None of this exists today as one
response even at native cadence — it's a real composition of three
different real subsystems plus one genuinely new approximation, not a
reshape of an existing endpoint. Breaking down what's actually behind
each piece before building it:

| Field | Status | Real source |
| :--- | :--- | :--- |
| `electricity_demand_mw.{p10,p50,p90}` | **Real, direct pass-through** | `/v1/forecast`'s existing per-region inference (`_run_single_region_forecast`) at its native 5-min cadence — no resampling |
| `carbon_intelligence.*` | **Real**, needs restructuring | Exactly `/v1/emissions/forecast`'s existing math (demand × *current* intensity — see that route's own documented "holding intensity constant across the horizon" caveat; this endpoint inherits the same limitation, doesn't remove it) |
| `metadata.conformal_calibration_applied` | **Real, trivial** | Calibration already runs unconditionally on every served forecast (`bundle.calibration.apply(p10, p90)`, `forecast/routes.py:203`) — this can honestly always be `true` today; the field's only real value is making an always-true fact checkable by a caller, not toggling behavior |
| `generation_mix_breakdown_mw.*` | **Does not exist — needs a new, honestly-scoped approximation** | `GET /v1/generation-mix` only reports *historical/current* mix (`raw_marts.fct_generation_mix`) — there is no per-fuel generation *forecast* anywhere. A real one (predicting coal/gas/wind/solar dispatch ahead of time) is a materially harder ML problem than demand forecasting — depends on weather forecasts, dispatch/market decisions, plant availability — genuinely out of scope for this endpoint |
| `renewable_proportion_derived` | **Derivable from the same approximation**, real classification | `dim_energy_mix.is_renewable`/`category` per fuel already exists and is real — the ratio itself is only as good as `generation_mix_breakdown_mw`'s approximation above |

### Decisions to record before building

- [x] **Interval — decided: native 5-min, no resampling.** `horizon`/
      `interval` in this new response report the same real native
      cadence `/v1/forecast` already reports (`"4h"`/`"5m"` for a NEM
      region) — avoids ever having to decide what "P90 at 10:00" means
      under aggregation (window-max vs. subsampled point), since there's
      no aggregation at all. A coarser, opt-in interval (e.g. `?interval=
      30m`) can be added later as real aggregation work if a caller
      actually needs it — not built speculatively now.
- [ ] **Generation-mix-at-horizon methodology** (the one genuinely new
      piece): hold each fuel's *current* real share of total generation
      constant (from the latest real `GET /v1/generation-mix`-equivalent
      query), then scale those shares by the *forecasted* total demand
      at each future point. Same honesty pattern already established by
      `/v1/emissions/forecast`'s "current intensity held constant" — an
      explicit, documented approximation, not a claim that dispatch is
      being forecast. The response (or its docs) must say so — e.g. a
      `generation_mix_method: "current_share_scaled_by_demand_forecast"`
      field alongside the numbers, not just numbers that *look* like a
      real per-fuel forecast.
- [ ] **New route, not a flag on `/v1/forecast`**: matches this
      codebase's existing pattern of one route per real concern
      (`/v1/forecast`, `/v1/emissions/forecast`, `/v1/generation-mix` are
      already separate) rather than an increasingly-optional-fields lean
      endpoint. Proposed: `GET /v1/forecast/intelligence?region=NSW1`.

### Implementation checklist (once the above is decided)

- [ ] Backend schema: new `ForecastIntelligencePoint`/
      `ForecastIntelligenceResponse` (forecast-api) — nested
      `electricity_demand_mw`/`generation_mix_breakdown_mw`/
      `carbon_intelligence`/`metadata` objects, matching the requested
      shape (`horizon`/`interval` at top level report the real native
      cadence, same as `/v1/forecast`). `unit`/`generation_mix_method`
      fields stay explicit, not implied.
- [ ] Service function composing, per native 5-min point: demand +
      latest real generation-mix shares + the existing emissions-
      forecast math — reusing `_forecast_arrays_single_region`/
      `_forecast_arrays_nem`, `load_generation_mix`, and
      `_resolve_row_intensity`'s existing real logic directly, not
      reimplementing any of them.
- [ ] `gCO2/kWh` vs. this codebase's existing `kgCO2e/MWh` unit: these
      are numerically identical (kg/MWh = g/kWh) — a direct pass-through,
      not a real conversion, but name it as a deliberate unit-alias in
      code so a future reader doesn't "fix" it into a wrong conversion.
- [ ] Cache with the same Redis TTL pattern every other forecast-api
      route already uses (`forecast_cache_ttl_seconds`), keyed on region
      + model version, same as `/v1/forecast` itself.
- [ ] Tests: the generation-mix scaling math in isolation, and a
      full-route test asserting the combined shape (48 points at 5-min
      cadence for a NEM region) with all four sub-objects present and
      internally consistent (`renewable_proportion_derived` actually
      matches the renewable share of that same point's
      `generation_mix_breakdown_mw`).
- [ ] Frontend: `lib/emissions.ts` gets the matching type +
      `fetchForecastIntelligence()`; surfaces on `/dashboard/forecast`
      (Forecast Explorer) as the natural home — not the Performance page
      built earlier this session, which is about model *health*, not
      per-point serving output.

**Acceptance**: `GET /v1/forecast/intelligence?region=NSW1` returns the
requested shape with real demand and real carbon numbers, an honestly-
labeled (not silently-presented-as-exact) generation-mix approximation,
and `conformal_calibration_applied` that's actually checked, not just
hardcoded `true` without the underlying `bundle.calibration.apply` call
being confirmed to have run.

---

## Out of scope here (tracked elsewhere)

- Deploying the Prefect `incremental-retrain-trigger-schedule` deployment
  → `TODO.md`'s raw→marts staleness entry (same missing-Prefect-server gap).
- `OE_API_KEY` (freshness) vs. the region-label mismatch (this file,
  above) — two different bugs in the same ingestion module, tracked
  separately on purpose; fixing one doesn't fix the other.
- Cloudflare R2 artifact storage, Gzip/response caching → `TODO.md`.


Instruction Guideline: Conformal Calibration for Probabilistic ForecastingThis guideline outlines the standard operating procedure for implementing and maintaining conformal calibration within the electricity demand forecasting and carbon intelligence platform.1. Overview & ObjectiveProbabilistic models generate raw uncertainty bounds ($P_{10}$, $P_{50}$, $P_{90}$). Over time, changing grid dynamics and weather patterns can cause these prediction intervals to become miscalibrated (e.g., capturing less than the target $80\%$ of actual outcomes). Conformal calibration wraps a post-processing adjustment layer over raw outputs to guarantee statistically rigorous coverage without requiring full model retraining.2. Prerequisites & Data RequirementsHoldout Calibration Set: Use a dedicated validation or calibration dataset separate from training data (recommended: sliding window of the last 14 to 30 days).Ground Truth Availability: Historical actual electricity demand ($y_{true}$) must be present in the data warehouse to calculate historical prediction errors.Target Alpha ($\alpha$): Set based on desired uncertainty bounds. For an 80% prediction interval ($P_{10}$ to $P_{90}$), $\alpha = 0.20$.3. Step-by-Step Implementation ProcedureStep 3.1: Compute Nonconformity ScoresFor each data point $i$ in the calibration dataset, evaluate how far the true observed demand fell outside the raw predicted bounds ($\hat{y}_{10, i}$ and $\hat{y}_{90, i}$):$$E_i = \max(\hat{y}_{10, i} - y_{true, i}, \ y_{true, i} - \hat{y}_{90, i})$$Negative or zero scores indicate the actual value fell safely inside the interval.Positive scores indicate a boundary violation (underestimation of $P_{90}$ or overestimation of $P_{10}$).Step 3.2: Determine the Quantile Threshold ($q'$)Calculate the adjusted empirical quantile of the collected nonconformity scores to find the correction factor:Let $n$ be the total number of samples in the calibration set.Determine the quantile level:$$q_{level} = \frac{\lceil(n + 1)(1 - \alpha)\rceil}{n}$$Extract the quantile value $q'$ from the distribution of scores. Ensure $q' \ge 0$ so bounds never artificially shrink when the model is already conservative.Step 3.3: Apply the Calibration Shift to Production InferencesWhen generating live predictions, apply the calculated adjustment symmetrically to the outer bounds:$P_{10\_calibrated} = P_{10\_raw} - q'$$P_{90\_calibrated} = P_{90\_raw} + q'$$P_{50}$ (median point forecast) remains unchanged.4. Operational Maintenance & MonitoringRecalibration Cadence: Execute automated calibration script updates on a rolling weekly schedule via the dbt/warehousing transformation pipeline to adapt to seasonal shifts.Health Tracking: Continuously monitor Actual Coverage (Rolling 7D) on the ModelOps dashboard. If coverage drops below the acceptable threshold (e.g., $< 75\%$), trigger an automated recalibration alert or soft warning flag.