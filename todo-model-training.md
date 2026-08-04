# Predictive Modeling & Carbon Insights — implementation plan

Companion to root `TODO.md`'s "Model Operations" section (that one is
about wiring the dashboard to whatever model(s) exist) and
`services/data-pipeline/TODO.md`'s ML Pipeline table (`ECO-M14`
through `ECO-M18`, the one-line versions of the 5 gaps this file plans
out in full). This is the "how do we actually build the thing the spec
describes" document.

## Ground truth before planning anything (verified against this codebase, not assumed)

| Spec claim | Reality today |
| :--- | :--- |
| LSTM + TFT + TimesFM blend | One LSTM (`app/models/ml.py`'s `DemandLSTM`) — explicitly descoped from a 3-model blend for "v0" (that file's own docstring). No TFT, no TimesFM anywhere. |
| Continuous online learning | A periodic *incremental* fine-tune (`ml/incremental.py`), triggered once per dbt build or manually (`POST /v1/model/train`, built this session) — batch, not continuous/streaming. |
| P10/P50/P90 | **Real.** `DemandLSTM`'s 3-head design (point + two non-negative spread heads) structurally guarantees `p10≤p50≤p90`. |
| Conformal calibration | **Real.** `service/ml/conformal.py`, applied post-hoc, verified live this session (`test_coverage_calibrated` in a real trained run). |
| Auto-fallback to a baseline model on anomaly | **Does not exist.** No baseline model exists at all (the old dashboard mock's "Naive baseline" row was fictional), and nothing monitors live forecast error to trigger a swap. |
| Structured pruning + fine-tune recovery | **Does not exist.** Zero pruning anywhere in the codebase. |
| MLflow lifecycle management | **Real and substantial**, more so after this session: `service/mlops/{tracking,registry}.py` (data-pipeline), `service/ml/registry.py` (forecast-api, model loading + `list_versions` + gated `promote_version`), and — as of today — one real trained-and-promoted model (`lstm_demand` v1, real `test_mape`/coverage metrics, real MLflow server). Gap: MLflow itself is a manually-started dev process, not a docker-compose service yet (flagged in root `TODO.md`). |
| Carbon intensity: external-provider-first, derived fallback | **Real but inverted.** The live path (`GET /v1/emissions*`) only ever serves the self-derived `live_mix_weighted` method. The external provider's own figure (`live_provider`, from OpenElectricity, computed at `stg_openelectricity_mix.intensity_kg_per_mwh`) exists but is never served — so today it's "derived-only", not "external-first-with-derived-fallback". |

## Design constraints this plan must respect (already established, real, non-negotiable)

- **"forecast-api never trains"** (`README.md`'s service-boundary rule, already enforced: `training_worker.py` lives in data-pipeline). Every new model (TFT, TimesFM fine-tuning if any) trains in data-pipeline; forecast-api only ever loads/serves.
- **Never run training synchronously inside a request/response cycle** (`training_worker.py`'s own docstring, the reason `POST /v1/model/train` publishes an event instead of training inline). Any new trigger path (pruning runs, TFT training, online-learning steps) follows the same publish-event-consume-separately pattern already built.
- **Real vs mock honesty.** Every checklist item below must produce something a live endpoint/log/metric can prove is real — no new fictional dashboard rows. If a technique's real accuracy on this data is bad, that's a real, reportable result, not something to hide behind a fabricated metric.
- **MLflow is the system of record** for every model version, regardless of architecture (LSTM/TFT/TimesFM) — one registry, one `lstm_demand`... actually see Phase 1's naming note below on why a shared name doesn't work once there's more than one architecture.

---

## Phase 0 — Foundations (blocks everything else)

Nothing later in this plan can be evaluated fairly without a working
comparison harness, a real backup model to compare against, and MLflow
actually surviving a restart.

-[] Add a real `mlflow` service to `docker-compose.yml` (image
   `ghcr.io/mlflow/mlflow`, `mlflow server --backend-store-uri
   postgresql://... --default-artifact-root s3://... ` or a Postgres
   schema + the existing MinIO service already in compose for
   artifacts) with a persistent volume — replaces the ad-hoc
   `mlflow server ... sqlite:///.mlflow/mlflow.db` process started
   manually this session (root `TODO.md`'s note). Update both
   services' `.env.example` (not `.env` — that's gitignored) with the
   real `MLFLOW_TRACKING_URI`.
-[] Add `dbt-core`/`dbt-postgres` to `services/data-pipeline`'s actual
   dependencies (`pyproject.toml`) — confirmed this session it isn't
   installed anywhere in this repo; had to fetch it ad hoc via `uvx`
   to rebuild a mart. `make dbt-build`/the CLI's `dbt` subcommand
   should work out of the box for the next person.
-[] `app/models/baseline.py` — a real, dependency-free seasonal-naive
   forecaster (`demand[t+h] = demand[t+h-7d]`, or a same-hour-last-week
   average with a small trailing-week rolling adjustment). Deliberately
   *not* a neural net: this is the "always available, never fails,
   nothing to load" floor every later phase (blend, fallback) needs to
   exist. No training step — it's a pure function over
   `ml/data.py`-shaped history.
-[] `service/ml/evaluate.py` — real walk-forward backtesting harness
   (data-pipeline's own `TODO.md` `ECO-M10`, currently `[ ]`): given a
   model (any of baseline/LSTM/TFT/TimesFM, same `DemandForecast`
   P10/P50/P90 contract) and a historical window, produces MAPE/RMSE/
   pinball-loss/empirical-coverage over multiple rolling origins, not
   one single train/test split. This is what every later phase's "did
   this actually help" claim gets checked against — build it once,
   reuse for TFT, TimesFM, blend, pruning, and online-learning
   evaluation alike.
-[] Wire `evaluate.py` into a CLI command (`ecolens-pipeline evaluate
   --model-name ... --version ...`) and log its output as an MLflow
   run tagged `evaluation` — so evaluation results live in the same
   system of record as training runs, queryable via the same
   `GET /v1/model/versions`-style API later.

**Acceptance:** `docker-compose up mlflow` survives a restart with
data intact; `ecolens-pipeline evaluate --model-name lstm_demand
--version 1` produces a real walk-forward report against the model
trained this session.

---

## Phase 1 — TimesFM (Google's foundation model) as a second real expert

Deliberately sequenced *before* TFT: TimesFM is zero-shot (no training
loop to build), so it's the fastest real path to "more than one model"
being true, and — see Phase 6 — it's also the natural candidate for
the *smart* fallback model, not just an ensemble member.

-[] Add `timesfm` (Google's PyPI package) as a data-pipeline dependency
   and download a real checkpoint (`google/timesfm-2.0-500m-pytorch`
   from HuggingFace, or the current recommended checkpoint at
   implementation time — pin the exact revision).
-[] `app/models/timesfm_adapter.py` — wraps the raw TimesFM model
   behind the *same* `DemandForecast(p10, p50, p90)` interface
   `DemandLSTM.forward` already returns, so every downstream consumer
   (blend, evaluate, serving route) is architecture-agnostic. TimesFM
   2.x natively supports quantile output; if the installed checkpoint
   doesn't, derive P10/P90 the same way `service/ml/conformal.py`
   already does for the LSTM (post-hoc conformal calibration around
   TimesFM's point forecast) — reuse that module, don't reimplement it.
-[] Real frequency/cadence mapping: TimesFM expects an explicit
   frequency indicator, not an inferred one — map NEM's 5-min and
   WEM's 30-min cadences to TimesFM's frequency buckets explicitly
   (document the mapping in the adapter's docstring; wrong bucket
   silently degrades accuracy without erroring).
-[] No training step, but *do* run it through Phase 0's
   `evaluate.py` against the same historical windows the LSTM was
   evaluated on — a zero-shot foundation model's real accuracy on
   this specific market's data is genuinely unknown until measured,
   not assumed good because it's a big pretrained model.
-[] Log the evaluation run to MLflow under a *separate* registered
   model name — `lstm_demand_timesfm` or similar, not shoehorned into
   the existing `lstm_demand` registry entry. Model-registry stages
   (Production/Staging/Archived) are per-registered-model, and a v1
   TimesFM checkpoint and a v7 LSTM checkpoint aren't comparable
   versions of "the same model" — naming them as if they were would
   break `promote_version`'s gating (root `TODO.md`'s Phase 3,
   `ECO-M12`) the moment two different architectures both have
   "Production" versions under one name.

**Acceptance:** a real `GET`-able forecast from TimesFM alone, evaluated
against the same backtest windows as the LSTM, with an honest
side-by-side MAPE comparison logged to MLflow — not assumed, measured.

---

## Phase 2 — Temporal Fusion Transformer (second *trained* expert)

-[] **Decision point, make it explicit before writing code:** hand-roll
   a minimal TFT (matching `DemandLSTM`'s existing from-scratch style
   in `app/models/ml.py` — variable-selection network + gated
   residual network + interpretable multi-head attention) vs. adopt
   `pytorch-forecasting`'s maintained `TemporalFusionTransformer` and
   build a `ml/data.py` → `TimeSeriesDataSet` adapter. Given the scope
   of this whole plan, adopting the library is the lower-risk default
   unless there's a specific reason (dependency weight, control over
   internals) to hand-roll — record the actual decision here once made.
-[] Classify `FEATURE_COLUMNS` (`ml/features.py`, 31 columns today)
   into TFT's three real input types — this is real design work, not
   mechanical:
   - *known future* (available at forecast time for the whole
     horizon): the calendar block — `is_weekend`, `is_holiday`,
     `hour_sin/cos`, `day_of_week_sin/cos`, `month_sin/cos`.
   - *observed past only*: everything else — `demand_mw_lag_*`,
     `demand_mw_rolling_*`, weather (`temp_c` etc.), generation-mix
     (`total_generation_mw` etc.), `price_mwh`, cross-region context.
     None of these are known ahead of time at this dataset's real
     granularity (no live weather *forecast* feed exists yet — that's
     its own future gap, not silently pretended away here).
   - *static* (per-series, doesn't change over the window): `region`,
     if training one multi-region model instead of one-model-per-region
     the way `DemandLSTM` currently is trained. Decide which — training
     N per-region TFTs mirrors the current LSTM setup exactly (lower
     risk, more MLflow runs to manage); one multi-region TFT with
     `region` as a static covariate is closer to what TFT is actually
     designed for (shares statistical strength across regions) but is
     a bigger architectural change from today's per-region convention.
-[] `app/service/ml/train_tft.py` (or extend `train.py` with an
   `architecture` param) — same `TrainConfig`-style dataclass, same
   MLflow logging (`log_and_register_run` already takes `config`/
   `result` generically; confirm it doesn't assume LSTM-specific
   fields before reusing it directly).
-[] Same registered-model-name discipline as Phase 1
   (`lstm_demand_tft`, not overloading `lstm_demand`).
-[] Run through Phase 0's `evaluate.py` against the identical backtest
   windows as the LSTM and TimesFM runs — three real, comparable
   numbers, not three different methodologies.

**Acceptance:** a real trained TFT, registered, with a real walk-forward
evaluation comparable (same windows, same metric definitions) to the
LSTM and TimesFM runs from Phases 0-1.

---

## Phase 3 — Multi-model blend (this is what actually makes the spec's headline claim true)

-[] Decide the real blending strategy — options, pick one and record
   why:
   - **Inverse-recent-error weighting**: weight each expert's P50 by
     `1 / recent_MAPE` (from a rolling window of Phase 0's evaluation
     harness re-run continuously against live outcomes, not a
     one-time backtest) — adapts which model "wins" as conditions
     change, closest to the spec's "continuously adapt... to handle
     sudden load shifts" language for the *blend* layer even before
     Phase 4's online learning touches individual models.
   - **Fixed learned stacking weights** (a small linear/logistic
     meta-model trained once on held-out predictions from all
     experts) — simpler, cheaper, but static until manually retrained.
   - **Best-of-recent selection** (serve whichever expert had the
     best recent error, no blending) — simplest, but throws away the
     "smart uncertainty ranges" benefit of properly combining P10/P90
     bands across models.
-[] `app/service/ml/blend.py` — combines P10/P50/P90 from however many
   experts are currently loaded (gracefully degrades to 1 model if
   only the LSTM is registered — this plan's phases don't have to all
   land before the blend layer is useful).
-[] Replace forecast-api's single-bundle `ModelRegistry` with a
   multi-bundle registry — `GET /v1/forecast`'s route
   (`api/v1/forecast/routes.py`) currently loads exactly one
   `ModelBundle`; needs to hold N bundles (one per registered model
   name from Phase 1/2) and call `blend.py` instead of a single
   `model.forward()`. This is the biggest single code change in this
   plan — budget real review time for it, it touches the hot serving
   path.
-[] `GET /v1/model` (root `TODO.md`'s work) needs a response-shape
   decision: does it now report *one* blended "model" concept, or does
   `GET /v1/model/versions` grow a `blend_weights`/`architecture` field
   so the dashboard can show which experts are actually contributing
   right now? Decide before touching the dashboard again.
-[] Evaluate the *blend* itself through Phase 0's harness — the
   headline number this whole plan should ultimately be judged on:
   does the blend actually beat the single best expert, or does it
   just add latency for no accuracy gain? Real risk, measure it.

**Acceptance:** `GET /v1/forecast` genuinely combines ≥2 real models'
outputs, the blend's backtested accuracy is measured against each
individual expert (not assumed better), and the dashboard can show
which experts are live.

---

## Phase 4 — True online / continuous incremental learning

Today's "incremental" path (`ml/incremental.py`,
`training_worker.py`) is real but batch: one warm-started fine-tune
per dbt build or manual trigger, not per-sample/continuous. Closing
this gap for real, safely:

-[] Increase trigger frequency from "once per dbt build" toward
   genuinely frequent — e.g. every N minutes as new 5-min AEMO data
   lands, via a scheduled Prefect deployment (root `TODO.md`'s Phase 4
   already wrote a real `prefect.yaml` for the daily flow; this is the
   same mechanism, much higher frequency, likely a *separate*
   deployment rather than repurposing `daily-demand`).
-[] Real safeguards a naive "just fine-tune more often" doesn't have —
   this is the actual hard part, not the scheduling:
   - **Catastrophic-forgetting guard**: cap the incremental
     learning-rate delta from the last full retrain's weights (already
     partially true — `Settings.incremental_train_lr` is deliberately
     much lower than the full-retrain default), and track a rolling
     divergence metric (e.g., weight-norm drift from the last full
     retrain) that trips a real alert if it exceeds a threshold.
   - **Periodic reset**: schedule a real full retrain (not
     incremental) on a coarser cadence (weekly?) as a "known-good"
     anchor, so incremental drift never compounds indefinitely between
     resets — matches `flows.py`'s existing `training_due()` staleness
     check, which already exists for exactly this purpose but isn't
     wired to a real schedule yet (root `TODO.md`'s Phase 4 gap).
   - **Live evaluation gate**: before a new incremental version is
     even a promotion *candidate*, run Phase 0's evaluate harness
     against the most recent real data (not just the training-time
     `test_mape`) — a model that overfit to a short recent window
     needs to be caught before `promote_version`'s gate (which only
     compares logged `test_mape`, not a fresh out-of-sample check).
-[] Apply the same higher-frequency treatment to TFT (Phase 2) once it
   exists — TimesFM (Phase 1) is zero-shot and has no weights to
   incrementally update, so it's naturally exempt from this phase
   (worth stating explicitly rather than leaving as an unexplained gap).

**Acceptance:** incremental fine-tunes happen on a real sub-daily
schedule with a real, measured divergence-guard metric visible
somewhere (MLflow tag, log line, or a dashboard card) — not just "runs
more often and we hope it's fine."

---

## Phase 5 — Structured pruning + fine-tune recovery

Applies to the LSTM and TFT (both have real weight tensors worth
shrinking); does not apply to TimesFM as integrated in Phase 1 (used
frozen/zero-shot — pruning a foundation-model checkpoint is a
materially different, much bigger undertaking than pruning a small
custom-trained net, explicitly out of scope for this phase).

-[] `service/ml/prune.py` — real structured pruning via
   `torch.nn.utils.prune`'s structured variants (e.g., `ln_structured`
   on LSTM hidden units / TFT attention heads), not unstructured
   weight-magnitude pruning — "structured" is the spec's own word and
   matters for the "lightweight resource footprint" claim: unstructured
   pruning doesn't actually reduce a dense tensor's real inference
   latency without specialized sparse kernels this stack doesn't have.
-[] Real before/after benchmark as part of the same run: parameter
   count, on-disk artifact size, and measured inference latency
   (CPU — matches this stack's real serving environment, not a GPU
   number that doesn't transfer) — logged to MLflow alongside the
   existing metrics, not just accuracy.
-[] Recovery fine-tune: reuse the *existing* incremental fine-tune
   machinery (`ml/incremental.py`) initialized from the pruned
   weights, not a new training path — a pruned model is just a
   different warm-start point.
-[] Gate: only register/promote a pruned+recovered version if its
   accuracy (Phase 0's evaluate harness, not just training-time
   metrics) is within a defined tolerance (e.g., ≤2% relative MAPE
   regression) of the unpruned version *and* it actually achieves a
   measured latency/size win — a pruned model that isn't meaningfully
   smaller/faster isn't worth the accuracy risk, don't ship it anyway
   just because pruning "sounds" like the right feature.

**Acceptance:** a real pruned+recovered model version in MLflow with
honest before/after latency, size, and accuracy numbers — including
the possibility that the honest result is "pruning wasn't worth it at
this model size," which is a legitimate real outcome to report, not a
failure to hide.

---

## Phase 6 — Forecast-anomaly detection + automatic fallback to a baseline model

The literal spec claim ("seamlessly falls back to a reliable backup
baseline model if any anomaly occurs") — confirmed this session to not
exist in any form. Real design, mirroring a pattern this codebase
already trusts: data-pipeline's Redis-backed `CircuitBreaker`
(`pipeline/circuit_breaker.py`) for external-API failures. This phase
is the same state machine, applied to *forecast quality* instead of
*upstream API availability*.

-[] `service/ml/forecast_breaker.py` (forecast-api) — a Redis-backed
   circuit breaker for the *serving* path, same closed→open→half_open
   state machine as data-pipeline's, backed by forecast-api's own
   already-existing Redis client (`app/db/redis.py`) — don't import
   across services; forecast-api needs its own copy/adaptation, same
   design.
-[] Real trip condition — needs actual realized-vs-forecast error, not
   a training-time metric: once real demand for a past forecasted
   timestamp lands in the warehouse, compute realized error for the
   live-serving model's recent predictions (a new small job/query
   comparing `raw_marts.fct_energy_demand.demand_mw` against whatever
   was served at that horizon) and feed it into the breaker the same
   way `CircuitBreaker.call()` records success/failure today.
-[] On trip (`open`): `GET /v1/forecast` serves Phase 0's seasonal-naive
   baseline (always available, zero load time) — Phase 1's TimesFM is
   the better "smart" fallback candidate if it's already loaded and
   itself healthy, naive is the guaranteed-last-resort if TimesFM
   isn't available either. Response should honestly report which
   model actually served the forecast (a `served_by` field), not
   silently swap without telling the client.
-[] Half-open trial + real recovery: same reset-timeout-then-trial
   pattern as the existing breaker, trialing the primary model's
   *next* real forecast against realized demand before fully closing
   again — don't just time out and blindly trust the primary model is
   healthy again.
-[] Dashboard wiring (once the backend piece is real): a status
   indicator showing which model is currently serving `/v1/forecast`
   — ties back into root `TODO.md`'s Model Operations work, don't
   duplicate that page's conventions, extend them.

**Acceptance:** a deliberately-degraded live model (or a test harness
that fakes bad realized-error data) actually triggers a real fallback
to the baseline within the breaker's configured window, and recovers
automatically once error normalizes — demonstrated live, not just
unit-tested.

---

## Phase 7 — Carbon Insights: external-provider-first with derived fallback

Independent of Phases 1-6 (touches emissions/carbon-intensity serving,
not demand forecasting) — can run in parallel with any of them.

-[] Confirm `stg_openelectricity_mix.intensity_kg_per_mwh` (the
   `live_provider` method, already computed at staging layer per this
   session's investigation) is fresh/reliable enough to serve live —
   check real staleness/gaps the same way this session found gaps in
   weather/generation joins before trusting it as primary.
-[] Add a `live_provider`-sourced column to `fct_carbon_intensity`
   (currently only materializes `live_mix_weighted`) — real dbt work,
   same mart, additional column(s), not a new mart (keeps `README.md`'s
   documented "keeps all three methods" intent intact rather than
   fragmenting it further).
-[] `service/ml/data.py`'s `load_latest_intensity`/`load_current_intensity`/
   `load_ytd_intensity` (forecast-api) — add a real
   `COALESCE(live_provider, live_mix_weighted)`-style fallback,
   preferring the external figure when it's fresh (define "fresh" —
   e.g., within one reporting interval) and falling back to the
   derived one otherwise. Report which method actually served each
   response (an honest `method` field on `EmissionsResponse`, not a
   silent swap) — same "tell the client what actually happened"
   principle as Phase 6's `served_by`.
-[] Update `GET /v1/emissions*`'s response schemas +
   `docs`/`README.md`'s Emissions model section to describe the real
   fallback behavior once it exists, so the next reader doesn't have
   to re-discover "derived-only today" by reading the SQL like this
   session did.

**Acceptance:** `GET /v1/emissions` genuinely prefers the external
provider's real figure when available and honestly reports falling
back to the derived one when it isn't — verified against a real
staleness scenario, not assumed from the SQL alone.

---

## Phase 8 (ongoing/cross-cutting) — Model Lifecycle Management polish

Not a "do this last" phase — pick up pieces of this alongside whichever
phase above is active, whenever a natural checkpoint appears.

-[] `mlops/drift.py` (data-pipeline `TODO.md`'s `ECO-M13`, currently
   `[ ]`) — PSI/KS drift detection between training-time feature
   distributions and live serving-time distributions, real input for
   Phase 4's "should we force a full retrain now" decision and Phase
   6's anomaly signal (feature drift often precedes forecast-error
   drift, a real, useful leading indicator).
-[] Gated promotion evaluation reports: extend `promote_version`
   (already gated on `test_mape` alone, built this session) to run
   Phase 0's full walk-forward evaluate harness as part of the gate,
   not just compare one logged scalar — a version can have a
   misleadingly good `test_mape` from a lucky split.
-[] MLflow experiment-comparison view on the dashboard's Model
   Registry page (`/dashboard/models`) — once ≥2 architectures exist
   (Phase 1+), the Registry tab (already real, built this session)
   should let a user actually compare LSTM vs. TFT vs. TimesFM
   versions side by side, not just list one flat version history.
-[] `docs/` updates throughout — every phase above changes something
   `README.md`'s "ML pipeline" section currently describes as a single
   LSTM; keep that doc honest as each phase actually ships, the same
   discipline this whole plan is trying to instill everywhere else.

---

## Explicit non-goals (for now — don't silently scope-creep into these)

- Resampling forecasts to an arbitrary requested `horizon`/`interval`
  (`forecast/routes.py`'s own documented limitation) — orthogonal to
  multi-model/online-learning/pruning, not touched by this plan.
- A true NEM+WEM whole-of-market forecast aggregate (needs the same
  resampling gap closed first).
- Live weather *forecast* ingestion (as opposed to historical
  observations) — would upgrade weather from "observed past only" to
  "known future" for Phase 2's TFT input classification, a real
  accuracy improvement, but a whole separate ingestion source to build
  and out of scope here.
- Multi-region *joint* modeling beyond Phase 2's static-covariate
  decision point — if that decision lands on "keep per-region models,"
  actually building a joint model is future work, not silently implied
  by this plan.
