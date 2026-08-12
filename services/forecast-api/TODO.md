# TODO — Close the actual-vs-P50 forecast gap

Companion doc: `todo-model-training.md` (repo root) — the phase-numbered
history this service's training/serving pipeline was originally built
against. This file is new (2026-08-12), scoped specifically to the
real, measured problem below, not a restatement of that document.

## Status (2026-08-12): Phases 1-4 implemented and real-evaluated

All four phases below are coded, tested (`tests/test_losses.py`, full
suite green except one pre-existing unrelated hardware-detection
failure), and validated against real walk-forward evaluation
(`ecolens-forecast evaluate`/`evaluate-tft`, `n_origins=5`) on real,
now-clean warehouse data. **Nothing promoted to Production** — `lstm_demand`
v19/v20 and `lstm_demand_tft` v12 sit at stage `None`, same discipline
this whole project already follows. Real per-region results:

| Region | Phase 0 (control) bias / cov | Phase 1 (v19) bias / cov | Phase 3 (v20) bias / cov |
|---|---|---|---|
| NSW1 | -98.9 / 0.833 | +10.6 / 0.667 | **-6.0** / 0.766 |
| QLD1 | -343.1 / 0.771 | -389.7 / 0.745 | -454.8 / 0.693 |
| VIC1 | +57.3 / 0.776 | +38.2 / 0.677 | -229.6 / 0.604 |
| SA1 | -27.5 / 0.891 | -84.8 / 0.828 | -126.7 / 0.818 |
| TAS1 | +88.4 / 0.984 | +29.0 / 0.984 | **-2.9** / 0.979 |
| WEM | +20.9 / 0.865 | -19.4 / 0.792 | -107.4 / 0.823 |

(bias = `mean(p50 - actual)`, MW; Phase 2/TFT has no prior baseline to
diff against, see its own section below.)

**Honest read**: Phase 1 (pinball(0.5)) alone is a real but modest,
mixed improvement — better in some regions, and it cost coverage
almost everywhere (predicted risk in Phase 1's own writeup below,
confirmed real). **Phase 3 (per-region bias correction) is the
important real finding**: it worked dramatically for NSW1/TAS1 (bias
within ~6 MW of zero) but made QLD1/VIC1/SA1/WEM *worse*, in some cases
much worse (VIC1: +38 → -230 MW). Root cause, confirmed by comparing
the training-time cal-split bias against the later real walk-forward
bias: for those four regions, the two didn't even agree in *sign* —
the ~25-27-row real calibration split isn't a stable estimate of a
region's "true" bias, likely real non-stationarity (bias drifts across
the ~2-month window faster than a single small snapshot can track) more
than a code bug. **Recommendation: don't adopt Phase 3 as-implemented
for QLD1/VIC1/SA1/WEM as-is** — either average the bias estimate over
multiple real windows (not one snapshot) before trusting it, or make
Phase 3 opt-in per region until that's validated. The mechanism itself
(artifact, registry loading, serving-time application) is real and
correct — verified live end-to-end (`demand_bias_correction.json`
round-trips through MLflow, `GET /v1/forecast` applies it) — this is a
finding about the estimation method, not the plumbing.

## Context

Real per-region walk-forward evidence (`evaluate_walk_forward`'s
`mean_error = mean(pred50 - actual)`, MW; `empirical_coverage`,
n_origins=5, current best real candidate v16/v17 on clean data):

| Region | Coverage (target 80%) | Bias (P50 - actual, MW) | MAPE |
|---|---|---|---|
| NSW1 | 0.833 | -98.9 | 6.36% |
| QLD1 | **0.771** (under) | **-343.1** (largest) | 7.87% |
| VIC1 | **0.776** (under) | +57.3 | 8.12% |
| SA1 | 0.891 | -27.5 | 12.56% |
| TAS1 | 0.984 (over-covered) | +88.4 | 10.36% |
| WEM | 0.865 | +20.9 | 9.68% |

Bias varies in **both sign and magnitude** by region — a global fix
can't null this out; whatever closes it has to be region-aware.

### Root cause, confirmed against the code (not assumed)

1. **P50 is trained with Huber loss, not pinball(0.5)**
   (`app/service/ml/losses.py::demand_loss`):
   ```python
   point = huber_loss(forecast.p50, target, delta=huber_delta)  # NOT pinball(0.5)
   lower = pinball_loss(forecast.p10, target, 0.1)
   upper = pinball_loss(forecast.p90, target, 0.9)
   return point + quantile_weight * (lower + upper)
   ```
   `quantile_weight` only scales the P10/P90 terms — it has **zero
   effect on P50's bias**. In the same file, `energy_forecast_loss` (a
   different model, `EnergyForecastLSTM`) already trains its point
   estimate with true pinball(0.5) via `_stacked_quantile_pinball_loss`
   — this pattern already exists and works in this codebase, just isn't
   applied to `DemandLSTM`/`DemandTFT`.

2. **The target scaler is global, not per-region**
   (`app/service/ml/train.py::_fit_target_scaler`): one `StandardScaler`
   fit on `demand_mw` pooled across all 6 regions. `HUBER_DELTA=1.0` is
   applied in that pooled-scaled space — a small region's (e.g. TAS1)
   residuals mostly sit inside `delta=1.0` there, so Huber degenerates
   toward plain MSE (pulls toward the conditional *mean*) for that
   region specifically, while a bigger region sees more of Huber's
   linear (more median-like) region. A second, independent,
   region-varying mechanism pointing at the same symptom.

3. **Region is already an input feature**
   (`app/service/ml/features.py::add_region_dummies`, one-hot
   `region_{code}` × 6, always present — added after an earlier real
   test: a region-blind model scored 76.79% test_mape vs. 3.73%
   single-region). Despite that, real per-region bias persists — a
   shared point_head evidently can't fully null out region-specific
   offsets from the one-hot alone.

4. **Conformal calibration never touches P50**
   (`app/service/ml/conformal.py::ConformalCalibration.apply`): `lo - q,
   hi + q` — symmetric widening only. Neither it nor the live Adaptive
   Conformal Inference loop (`app/service/ml/adaptive_calibration.py`,
   rescales width around P50 using a Redis-persisted per-`(model,
   region)` scale factor from `app/service/model/forecast_
   reconciliation.py`) can fix a mis-centered band — they can only
   resize it around whatever P50 the model already produced.

5. **No promotion gate checks coverage or bias today**
   (`app/service/mlops/registry.py::promote_version`) — only
   `test_mape` (force-skippable) and `eval_gate_passed` (MAPE-threshold
   only, see `training_worker._resolve_max_acceptable_mape`, fixed
   2026-08-12 for its own unrelated apples-to-oranges bug). A candidate
   with great MAPE and terrible coverage/bias would sail through today.

### Why NOT a learned residual-correction model (e.g. Ridge, like `timesfm_correction.py`)

`timesfm_correction.py` already does exactly this pattern (Ridge on
real residuals, shift P10/P50/P90, then conformal) for a *different*
model — and its own history is the argument against reusing it here
directly: it overfit badly (test MAPE 4.45%→6.96%) at 204 real training
rows until `RidgeCV` per-target alpha search fixed it. NEM regions have
~300 real rows total, of which the cal split is ~25-27 rows per region
(49/49 `train_frac`/`val_frac`, `cal_frac=0.5` — already rebalanced once,
2026-08-09, purely to make `cal` non-empty for NEM regions at all). A
regression fit on that few real per-region rows is a worse-conditioned
version of a problem that already failed once in this exact codebase.
**A per-region scalar (constant) bias offset, not a learned model, is
the right first lever** — see Phase 3.

There is also no room for a fourth disjoint data split. The real,
honest tradeoff: reuse the same cal split for both bias-fitting and
conformal (bias correction first, conformal on the debiased residual
second) — stated here explicitly, not silently accepted.

## Plan

### Phase 0 — control (done, no new work)
v16/v17's real per-region walk-forward numbers above are the fixed
baseline every phase below is compared against. Don't re-run to get a
"fresh" control — reusing the same real numbers is what makes the
comparison honest.

### Phase 1 — P50 loss: Huber → true pinball(0.5), `DemandLSTM` only (done, `lstm_demand` v19)
- `app/service/ml/losses.py::demand_loss`: change `point =
  huber_loss(forecast.p50, target, delta=huber_delta)` to `point =
  pinball_loss(forecast.p50, target, 0.5)`. Matches `energy_forecast_
  loss`'s already-proven pattern in the same file. Drop the now-unused
  `huber_delta` param (confirmed nothing overrides it — no `Settings`
  field, no CLI flag); keep `huber_loss` itself defined/available, just
  unused by `demand_loss`.
- Update `app/models/ml.py`'s module docstring and `losses.py`'s own
  header comment (currently claims "Huber... for DemandLSTM" — this
  codebase already flags stale docstrings like this as a real, recurring
  problem, see `app/models/ml.py`'s own "2026-08-11 update" section).
- Add `tests/test_losses.py` (doesn't exist today despite `train.py`'s
  docstring implying coverage exists — that claim is itself stale): a
  synthetic asymmetric-target case proving `demand_loss`'s P50 term
  targets the conditional median, not the mean.
- Tag the MLflow run (`TrainConfig.as_mlflow_params`/`log_and_register_
  run`) with `p50_loss: "pinball"` so later comparisons are unambiguous.
- **Retrain**: `ecolens-forecast train` (all 6 regions). **Evaluate**:
  `ecolens-forecast evaluate --version <new> --n-origins 5`. Compare
  `eval_mean_error`/`eval_coverage`/`eval_mape` per region against Phase
  0 — check coverage too, not just bias/MAPE (changing P50's loss shape
  changes `quantile_weight`'s effective relative scale against the
  P10/P90 pinball terms, which could shift QLD1/VIC1's already-under
  coverage either direction).

### Phase 2 — same change, `DemandTFT` (done, `lstm_demand_tft` v12)
Both `train.py`/`train_tft.py` already call the same `demand_loss`, so
Phase 1's edit covers TFT too — but retrain (`train-tft`) and evaluate
(`evaluate-tft`) as a fully separate MLflow run/comparison. Don't
conflate LSTM and TFT attribution in one pass (matches this project's
existing per-architecture evaluation convention — `evaluate_tft_and_
log` is already a distinct function from `evaluate_and_log` for exactly
this reason).

**Real result**: no prior TFT walk-forward baseline exists in this repo
to diff against (TFT versions 2-11 never logged a comparable number), so
this is reported standalone, not as a before/after. v12's real bias is
large in most regions -- NSW1 +357, QLD1 -204, VIC1 +250, SA1 -108, TAS1
+67, WEM -41 -- clearly worse-calibrated than LSTM v19/v20 across the
board. TFT is not currently the better-calibrated candidate; LSTM
remains the stronger real option for this specific problem.

### Phase 3 — per-region bias offset, built into the existing per-region training loop (done, `lstm_demand` v20 — see "Status" above for the real, honest result)
`train_model` (`app/service/ml/train.py`) already loops per-region
before folding splits into one `ConcatDataset` (~line 486-520) — a
per-region cal set (`region_cal_ds`) exists in that loop *before*
`fit_conformal` consumes the concatenated version (~line 671-675,
which currently discards `p50_cal` entirely). This is what makes a
per-region bias table cheap: zero new data-plumbing, zero new split,
zero region-label plumbing through the loader.

- Inside that loop, after best-state load and before `fit_conformal`:
  run `_predict` on `region_cal_ds`, inverse-transform, compute
  `bias[region] = mean(y_region_cal - p50_region_cal, axis=0)` (shape
  `(horizon,)`). Shift that region's `p10_cal`/`p90_cal` by the same
  amount *before* `fit_conformal` sees them (bias-then-conformal, same
  cal split for both — the explicit tradeoff above).
- New small artifact (not a new MLflow-registered model, not a new CLI
  command — `timesfm_correction.py`'s separate-registry machinery
  exists specifically because TimesFM is a frozen, independently-
  versioned external checkpoint; `DemandLSTM`/`DemandTFT` are retrained
  from scratch/incrementally every run, so a bias table has no reason
  to live independently of one specific run's own weights): a
  `dict[region, np.ndarray]` + `.apply(region, p10, p50, p90)` helper
  that shifts all three by the same amount (trivially preserves `p10 <=
  p50 <= p90`), persisted as `demand_bias_correction.json`, a same-run
  MLflow artifact next to `conformal_calibration.json`.
- `app/service/ml/registry.py::ModelBundle`/`load_bundle`: add an
  optional `bias_correction` field, loaded the same guarded-missing-
  artifact way `calibration` already is — an older run without this
  artifact still loads fine.
- `app/api/v1/forecast/routes.py::_forecast_arrays_single_region`:
  apply `bundle.bias_correction.apply(...)` right after `_inverse_
  target`, before `bundle.calibration.apply(p10, p90)`.
- `app/service/ml/evaluate.py`'s forecasters: same optional field at
  the same point, so `evaluate_walk_forward` can score "Phase 1/2 +
  Phase 3" as its own named candidate against the Phase-1/2-only and
  Phase-0 numbers in one report (same 3-way attribution shape `evaluate_
  and_log` already uses for calibrated/raw).
- **Retrain + evaluate**, compared against Phase 1/2's own numbers (not
  Phase 0's) to isolate Phase 3's real marginal contribution.
- Only escalate beyond a flat per-region constant (e.g. to per-region-
  per-hour-bucket averages — still constants, never a regression) if
  the real walk-forward residuals show a visible hour-of-day pattern
  after Phase 3 — diagnosable directly from `GET /v1/forecast/recent-
  actual-vs-predicted`'s existing `step_hours` field, no new
  instrumentation needed.

### Phase 4 — visibility on the promotion gate, not a hard gate yet (done)
Extend `run_live_evaluation_gate` (`app/service/ml/evaluate.py`) to
also tag `eval_gate_coverage`/`eval_gate_bias_mw` per candidate
(reusing metrics `EvaluationReport` already computes — no new
computation), surfaced via a log line at `promote_version`'s own
promotion-attempt point (`app/service/ml/registry.py`) for a human/
dashboard to see, but **not enforced yet** (never raises
`PromotionRejected`). Given `training_worker.py`'s own real 2026-08-12
bug (an MAPE gate that compared two non-comparable metrics and silently
mis-rejected a good candidate) is the exact failure mode a hastily-added
coverage/bias gate risks repeating, watch real tag values across a few
Phase 1-3 training cycles before turning this into a hard gate with real
thresholds.

**Verified live**: `lstm_demand` v20 carries real tags
`eval_gate_coverage=0.7795`, `eval_gate_bias_mw=-147.18` after a
`run_live_evaluation_gate` call, confirmed via direct MLflow query.

## Sequencing

Strictly sequential (Phase 1 → 2 → 3 → 4), not joint — matches this
project's own established "change one variable at a time" discipline,
and Phase 3's entire purpose is to correct whatever Phase 1/2's
retrained model *doesn't* fix, which can't be measured without Phase
1/2's own real walk-forward numbers locked in first as the new control.

## Verification

- Every phase: `ecolens-forecast evaluate --version <v> --n-origins 5`
  (real walk-forward, not training-time `test_mape`/`test_coverage_*`
  alone — this project's own repeatedly-confirmed reason: single-split
  val_mape has been measured swinging 8.02%-14.26% across ~10 nominally-
  identical runs).
- Compare `eval_mean_error` (bias, MW) and `empirical_coverage` per
  region against the table above, plus `eval_mape` to confirm no
  regression on the metric already being tracked.
- Report real numbers honestly per region even where a phase doesn't
  fully close the gap (QLD1's -343 MW bias is the one to watch hardest).
- Never force-promote past the live-eval gate to make a number look
  better than it is.

## Next steps (not yet done)

- **Investigate Phase 3's real cal-split instability** before adopting
  it for QLD1/VIC1/SA1/WEM: is the ~25-27-row snapshot genuinely too
  small/temporally-narrow, or does it point at a deeper real
  non-stationarity issue these regions have that a static correction
  (of any kind) can't fix? Try averaging the bias estimate across
  multiple real cal-like windows before trusting a single snapshot.
- **QLD1 remains the region to watch hardest** — its bias got *worse*
  in every phase tried so far (Phase 0: -343 → Phase 1: -390 → Phase 3:
  -455). None of Phases 1-3 have found what's actually wrong there; it
  may need its own real investigation (a QLD1-specific feature gap? a
  real regime shift within the training window?) rather than another
  general-purpose lever.
- Decide whether to keep Phase 3's bias correction *unconditionally
  active* (current implementation) or make it opt-in per model/region
  once the instability above is understood — nothing is promoted yet,
  so this is safe to leave as real, working, un-promoted code while
  that's decided.
- TFT (Phase 2) needs its own real investigation independent of this
  file's scope — v12's bias is large across the board; unclear yet
  whether that's an inherent TFT-vs-LSTM difference on this real, small
  dataset or a separate bug.
