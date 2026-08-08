# Remaining Forecast API Todo's for frontend

Root `TODO.md`'s "Forcasting todos" section already audits the backend
build-out for **Predictive Modeling & Carbon Insights** end-to-end
(adaptive multi-model architecture, incremental learning, quantile
heads + conformal calibration, self-correction/fallback, pruning,
carbon accounting, MLflow lifecycle) and marks nearly all of it `[x]`
real and wired, as of 2026-08-08. This file is the companion to
`services/ingestion/TODO.md`/`services/waerehouse/TODO.md`: what's
still missing to fully surface that backend in the dashboard's **ML
Platform** tabs (`/dashboard/models` — Model Registry, `/dashboard/
training` — Training & Experiments, `/dashboard/performance` —
Performance), plus a few backend gaps that sit underneath the product
description but aren't visible from any tab today.

## Model Registry & Performance — architecture coverage

- [x] **The carbon-insights model wasn't a selectable architecture
      anywhere in the dashboard — closed 2026-08-08.** `MODEL_ARCHITECTURES`
      (`dashboard/src/lib/emissions.ts`) now has a third entry,
      `{ modelName: "energy_forecast_multi_task", label: "Energy
      Forecast" }`, next to `lstm_demand`/`lstm_demand_tft` — confirmed
      live via `list_versions("energy_forecast_multi_task")` (the same
      function `GET /v1/model/versions` calls): a real registered `v1`
      with real metrics/`run_id`/`git_sha` now shows up in Model
      Registry/Performance, no backend change needed (`api/v1/model/
      routes.py` was already `model_name`-agnostic).

      That `v1` came from a first, real bootstrap training run — see
      "R2 bootstrap training path" below for how, since `raw_marts`
      doesn't exist in this environment's Postgres yet (empty `raw.*`
      too — no `dbt build` has run against it). Only 5 epochs
      (verification pass, not a real fit): `demand_test_mape≈14.4`,
      `generation_test_mape` is a known, pre-existing metric artifact
      (see below), not a new bug. Re-run for real once early-stopped —
      `MODEL_TRAIN_EPOCHS` in `.env` currently pinned to `5` for the
      verification pass, raise it (or unset it, default is `50`) before
      the real run.

- [ ] **R2 bootstrap training path is new, CLI-only, single-source-of-
      truth risk.** `app/service/ml/energy_data_offline.py`
      (`load_energy_training_data_from_master`) trains
      `EnergyForecastLSTM` from `master.duckdb` (R2-hosted, built by
      `services/ingestion/scripts/build_master_table.py`) instead of
      `raw_marts.fct_energy_demand`, via `train-energy-forecast
      --source r2_master`. This is a real, permanent second data path now
      (not scaffolding to delete) — but nothing currently reconciles it
      against the Postgres-marts path once that's populated (different
      grain per `energy_features.py`'s own docstring: `master.duckdb`
      is a uniform 30-min grid across regions, the live marts run at
      each region's native cadence). Decide: keep both paths
      indefinitely (bootstrap + ongoing live retrain), or treat
      `r2_master` as one-time-only once `raw_marts` has enough real
      history to retrain from scratch there.
- [x] **Postgres `raw_marts` schema doesn't exist in this environment
      at all — closed 2026-08-08, confirmed the predicted cause.**
      `services/forecast-api/.env`'s `DATABASE_URL` was pointed at
      `ep-noisy-water` (ap-southeast-1), a different, near-empty Neon
      project with no `raw_marts`/`staging` schema at all — exactly the
      stale-DSN-pointing-at-the-wrong-Neon-branch failure mode
      `services/waerehouse/.env`'s own comment documents already
      hitting and fixing on 2026-08-07 for that service, but
      `forecast-api` never got the same fix. Repointed to
      `ep-bold-feather` (us-east-2), the real DB `services/ingestion`
      and `services/waerehouse` both write to — confirmed live: that
      DSN has a real `raw_marts` schema (`dim_energy_mix`,
      `fct_energy_demand`, etc., dbt-built) and `staging`. `GET /v1/
      model/drift?model_name=lstm_demand` (previously a hard 500) now
      returns `200 {"data": []}` cleanly.

      **Not fully resolved — a real, smaller gap remains**: `raw_marts`
      exists now, but real accumulated volume there is thin
      (`fct_energy_demand`: 1 row, `raw.aemo_nem_dispatch`: 0 rows) --
      nowhere near `live_drift.py`'s 200-rows-per-side minimum, so
      `lstm_demand`/`lstm_demand_tft` drift and `--source postgres`
      training still honestly come back empty until enough real
      ingestion + `dbt build` runs have accumulated history (the
      `energy_forecast_multi_task` architecture sidesteps this via the
      separate `r2_master` bootstrap path, per that section above).
- [ ] **`generation_test_mape` is a known, unfixed metric artifact, not
      just an energy-forecast-specific footnote anymore — confirmed
      live.** The 5-epoch run above logged `generation_test_mape≈
      310210` (not a typo) — verified this comes from `solar_mw` being
      near-zero (<1 MW) for ~44% of real rows and `other_mw` for ~16%
      (day/night solar cycle + region mix), which blows up unmasked
      MAPE on real, legitimate near-zero-but-nonzero targets.
      `train_energy_forecast.py`'s own code comment already flagged
      this as accepted-not-fixed; a MAE-as-fraction-of-
      `total_generation_mw` metric (also flagged there) would be
      honest. Still not built.

- [ ] **Promoting a TFT version to Production has no effect on what's
      served.** `lstm_demand_tft` is a real, selectable architecture in
      Model Registry/Performance, and training/promotion/deletion all
      work against it (`training_worker.py`'s `architecture=="tft"`
      branch, `incremental_tft.py`). But no API route ever loads a
      `DemandTFT` bundle for live inference — `/v1/forecast` only ever
      serves `DemandLSTM`, `/v1/forecast/intelligence` only ever serves
      `EnergyForecastLSTM`. TFT is reachable only via `cli.py
      evaluate-tft`. The dashboard doesn't disclose this anywhere:
      clicking "Promote to Production" on a TFT version reads as a real
      deployment action but is currently a no-op for serving. Either
      wire a TFT serving path or add an explicit note next to the TFT
      toggle until one exists.

## Training & Experiments (`training/page.tsx`) — tabs still illustrative

Per that page's own module docstring, "Training Jobs", "Model
Registry", and now "Experiments" are done. Still `IllustrativeBadge`,
no backing endpoint:

- [x] **MLflow Experiments tab / Recent MLflow Runs table — closed
      2026-08-08.** New `app/service/mlops/experiments.py`
      (`list_experiments`/`list_mlflow_runs`, real `MlflowClient.
      search_experiments`/`search_runs`) backing two new endpoints,
      `GET /v1/model/experiments`/`GET /v1/model/mlflow-runs`. Every
      architecture this service trains logs to one shared experiment
      (`mlops.tracking.EXPERIMENT_NAME = "lstm_demand"`, despite the
      name) — confirmed live: `GET /v1/model/experiments` returns one
      real `lstm_demand` experiment (`run_count` growing with each real
      training run) plus MLflow's own empty `Default`. `GET /v1/model/
      mlflow-runs` returns real runs tagged with their `architecture`
      (`energy_forecast_lstm` for the recent bootstrap runs). Dashboard
      (`lib/emissions.ts`'s `fetchMlflowExperiments`/`fetchMlflowRuns`,
      `training/page.tsx`) updated to match — `dashboards.
      getMlflowExperiments()`/`getMlflowRuns()`'s fabricated sample
      experiments (`lstm_demand_v8_hptune`, `rf_baseline`, etc.) are no
      longer used anywhere.

      Side effect, found and fixed while verifying this live:
      `train_and_register_energy_forecast` (CLI-triggered training)
      never wrote to `meta._training_log` at all — that logging was
      private to `training_worker.py`'s RabbitMQ-triggered path only.
      Moved `log_training_start`/`log_training_finish` to `service/
      model/actions.py` (shared) and wired them into the energy-forecast
      CLI path too, so `GET /v1/model/training-runs` (Training Jobs tab)
      now shows CLI-triggered runs as well, not just trigger-event ones.

      **Also found and fixed, more broadly load-bearing than this one
      tab**: `db/session.py`'s `get_session()` context manager never
      called `session.commit()` — only `session.close()`. Every writer
      using it (not just the two functions above) was silently a no-op:
      `execute()` raised no error, but nothing persisted, because
      SQLAlchemy's async session opens an implicit transaction on first
      `execute()` and rolls it back on close without an explicit commit.
      Confirmed live (`GET /v1/model/training-runs` stayed empty after
      a real successful training run, before the fix). Fixed narrowly —
      added `await session.commit()` inside `log_training_start`/
      `log_training_finish` themselves, not in `get_session()` itself
      (that function's own docstring calls this service read-only by
      design; changing its shared behavior could affect other callers
      in ways out of scope here). **Worth an audit**: any other write
      path using bare `get_session()`/`get_db()` elsewhere in this
      service should be checked for the same silent-no-op bug.
- [ ] **Hyperparameter Tuning tab.** `POST /v1/model/train` only
      accepts `regions`/`window_hours` — no hyperparameter payload.
      `ml/tune.py` (grid search + Optuna, real, 363 lines) is CLI-only
      (`cli.py tune`/`tune-optuna`) — nothing calls it from a route.
      Needs a `POST /v1/model/tune` trigger (same publish-to-RabbitMQ
      pattern `service/model/actions.py::trigger_training` already
      uses, picked up by `training_worker.py`) before this tab can be
      real, or it stays honestly disabled.
- [ ] **Hparam Search History table** — 4 hardcoded sample rows.
      `ml/tune.py` doesn't persist per-trial results anywhere queryable
      yet; needs a store before this can read real data.
- [ ] **Feature Store tab** — no feature-store *listing* endpoint.
      Feature engineering itself is real (`ml/features.py`,
      `ml/energy_features.py`) but there's no registered "feature
      group" concept anywhere in this service to list.
- [ ] **Deployments tab** — no deployment-status endpoint; this
      platform has no replica/canary-traffic concept to report
      (single-process CPU serving — root `TODO.md`'s Forecasting
      Phase 7).

## Performance (`performance/page.tsx`) — sections still illustrative

- [ ] **"Batches processed" (Online learning card)** — not tracked
      anywhere; `meta._training_log` records whole runs, not per-batch
      counts.
- [ ] **Cumulative drift / diminishing-returns tracking** — no
      computation exists combining `ml/divergence.py`'s drift metric
      with training history to answer "are online updates still
      improving accuracy."
- [x] **Concept drift tracking card — closed 2026-08-08.** New
      `app/service/mlops/live_drift.py` (`compute_drift`) is the first
      real caller of `mlops/drift.py`'s PSI/KS detector, backing a new
      `GET /v1/model/drift` route. Not a training-vs-live-serving
      comparison (no live serving feature snapshot is logged anywhere
      yet) — a chronological split of the same real training data
      instead, real and honest but with a disclosed limitation
      (`live_drift.py`'s own docstring): a calendar/seasonal feature
      can read as high-PSI purely because the reference/comparison
      windows don't each span a full year. `[]` when there isn't
      enough real data on both sides yet (this environment's empty
      Postgres marts for `lstm_demand`/`lstm_demand_tft`), same
      "empty is a real, expected state" convention `GET /v1/model/
      versions` uses. `dashboard/src/lib/emissions.ts`'s `fetchDrift`
      and `performance/page.tsx`'s Concept drift tracking card wired
      to it, `IllustrativeBadge`/hardcoded sample PSI rows removed.
- [ ] **Model health score** — no scoring formula exists in this
      codebase; the card's own subtitle already says so. Needs a
      product-approved formula (not an invented one) before this is
      real.
- [ ] **Retraining decision guide** — sample thresholds only, no
      policy wired to real alerts.
- [ ] **Alert conditions card** — no alert policy or paging
      integration in `forecast-api` itself. (Prometheus alert *rules*
      exist at the infra level per `services/observility/TODO.md`, but
      nothing model-specific like "MAPE increase > 15%" is evaluated
      in-service.)
- [ ] **"Recalibrate conformal model" button** — disabled, no
      endpoint. Note: recalibration already happens automatically and
      continuously for the demand-LSTM route (`adaptive_calibration.py`,
      driven by `forecast_reconciliation.py`'s reconciliation sweep) —
      this button implies a *manual* override, which isn't built.
      Lower priority given the automatic path already covers the real
      need.
- [ ] **"Notify team" button** — disabled, no endpoint; same gap as
      Alert conditions above.

## Cross-cutting: gaps the product description implies but no tab shows

- [ ] **TimesFM never actually serves or blends into a forecast.**
      `timesfm_adapter.py` wraps a real `google/timesfm-2.5-200m-pytorch`
      model, but its only caller anywhere is `ml/evaluate.py`'s
      zero-shot benchmark harness (`cli.py evaluate-timesfm`). The
      product description's "blend of... LSTM and TFT alongside...
      TimesFM" implies TimesFM participates in live serving; today
      it's an offline comparison baseline only. `ml/blend.py`'s
      `BlendForecaster` (real inverse-recent-MAPE ensemble weighting)
      is the natural place to wire this in — it's currently orphaned
      too (zero callers anywhere).
- [ ] **The carbon-insights route has no calibration or fallback.**
      `/v1/forecast/intelligence` (`EnergyForecastLSTM`) is the only
      serving route with no conformal calibration, no adaptive-scale
      correction, and no circuit-breaker/baseline fallback — all three
      are real and wired for `/v1/forecast` (plain demand) but stop
      there. The product description's "auto-correcting accuracy...
      falls back to a reliable backup baseline model" doesn't hold for
      carbon-insight forecasts today.
- [ ] **The carbon-insights model has no incremental/online-learning
      path.** Only a full-batch CLI trainer exists
      (`cli.py train-energy-forecast`); `ml/incremental.py`/
      `incremental_tft.py` cover the LSTM/TFT architectures, nothing
      covers the multi-task model, and it isn't wired to the RabbitMQ
      training-trigger consumer at all — so even after the Model
      Registry gap above is fixed, this architecture's Fine-tune tab
      would still have nothing to call.
- [ ] **Structured pruning is demand-LSTM-only, by design.**
      `prune.py` explicitly excludes TFT/TimesFM/EnergyForecastLSTM —
      the physical-compaction approach relies on `DemandLSTM`'s fixed
      4-gate structure. Not a bug, just worth flagging since the
      product description frames pruning as platform-wide ("deep
      architectures," plural).

---

**Notebooks note** (resolves the original ask that prompted this file):
`notebooks/feature_selection.ipynb` and `notebooks/lstm.ipynb` were
reviewed for anything not yet reflected in `app/models/
energy_forecast_lstm.py`. Both are single-cell, no-markdown prototype
scripts with no roadmap or architecture notes beyond what's already
been ported into `energy_forecast_lstm.py`/`ml/energy_features.py`/
`ml/carbon_engine.py` — safe to treat as historical source material,
not a pending-features spec. No model-architecture changes are needed;
the real gaps are the wiring ones listed above (registry visibility,
calibration/fallback, incremental training), not the model itself.
