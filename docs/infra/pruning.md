# Making the Model Smaller Without Making It Wrong: Pruning and Conformal Calibration in EcoLens

A trained forecasting model raises two uncomfortable questions once it works. The first: does it need to be this big? The second: how much should anyone actually trust the uncertainty band around its predictions? EcoLens answers both with real, tested mechanisms rather than hand-waving — structured pruning for the first question, conformalized quantile regression (plus an adaptive layer on top of it) for the second.

They sound unrelated, but they share a philosophy that shows up everywhere in this codebase: don't claim a win you haven't measured, and don't quietly promote something to production because it *should* work in theory. Both mechanisms here compute a real number, compare it against a real threshold, and let the honest answer be "no, this wasn't worth it" as often as "yes."

This document walks through both — why each exists, how it's actually implemented, what it costs, and where the real, recorded rough edges still are.

---

## Part 1: Structured Pruning — Shrinking the LSTM Without Guessing

### Why prune at all

`DemandLSTM`, the model actually serving `GET /v1/forecast`, has 128 hidden units per layer. That number was chosen once, empirically, and never revisited under the question "does it actually need to be this large?" A smaller model is cheaper to store, cheaper to load, and — in principle — cheaper to run inference on. But "smaller" is only a win if accuracy doesn't quietly pay for it, and EcoLens treats that as something to prove, not assume.

Pruning in EcoLens is scoped deliberately narrowly: **LSTM only**. The TFT's interlinked variable-selection/gated-residual/attention structure would make a correct structural compaction meaningfully harder to get right — a subtly wrong compaction there is a silent-bad-predictions bug, not just a missing feature, so it's left as real future work rather than silently implied as already covered. TimesFM is out of scope for the same reason it's out of scope everywhere else in this codebase: it's used frozen, zero-shot, and pruning a foundation-model checkpoint is a materially different, much bigger undertaking.

### Why it isn't just `torch.nn.utils.prune.ln_structured`

The obvious move would be to reach for PyTorch's built-in structured pruning utility. It doesn't actually work here, and the reason is specific to how `nn.LSTM` stores its weights.

`weight_hh_l{layer}` is shaped `(4 * hidden_size, hidden_size)` — the four gates (input, forget, cell, output) are stacked as four separate row-blocks. One logical "hidden unit" is really four *non-contiguous* rows, at offsets `j`, `hidden+j`, `2*hidden+j`, and `3*hidden+j`. `ln_structured` prunes along one flat tensor dimension, treating each slice independently — it has no way to say "prune these four scattered rows together, as one unit." Used naively, it would prune individual gate-rows independently, which doesn't correspond to removing a real hidden unit at all.

So `services/forecast-api/app/service/ml/prune.py` implements the same underlying idea by hand — rank by L2 norm, drop the lowest — but grouped correctly across all four gate blocks, and it goes one step further than masking:

- **Zero-masking** (what a lot of "pruning" tutorials actually do) leaves the tensor the same physical size, just full of zeros. It doesn't shrink the artifact on disk and doesn't speed up dense matmul on hardware without specialized sparse kernels — which this stack doesn't have.
- **Physical compaction** — what this module actually does — rebuilds a genuinely smaller model and copies over only the surviving rows and columns. That's the only way to get a real parameter-count and on-disk-size reduction.

### How a "unit" gets ranked and removed

`_unit_importance` computes an L2-norm importance score per hidden unit, and it's careful about what "a unit's footprint" means:

```python
gates = weight_hh_l0.reshape(4, hidden_size, hidden_size)  # (gate, out_unit, in_unit)
row_norm = torch.norm(gates, p=2, dim=(0, 2))   # how the unit is computed
col_norm = torch.norm(gates, p=2, dim=(0, 1))   # what the unit feeds into
importance = row_norm + col_norm
```

Both directions matter: a unit that's an important *input* to other units, even if its own row weights look small, shouldn't be ranked as prunable just because one side of its footprint is small.

Removing a unit correctly means two things have to hold simultaneously:

1. Nothing downstream ever reads that unit's hidden state again — satisfied by dropping its row (and its three gate-siblings) from every downstream weight tensor and head.
2. The unit's own hidden state no longer influences anything else — satisfied by also dropping its *column* from `weight_hh_l{layer}`, since a hidden unit feeds every gate's input at the next timestep through that column space.

`compact_lstm` does both, for every affected tensor — `lstm.weight_ih_l*`, `weight_hh_l*`, biases, the attention layer, and all three output heads (`point_head`, `lower_spread_head`, `upper_spread_head`) — and returns the new, smaller model plus `keep_idx`, the original indices that survived, so the decision is auditable rather than just trusted. The strongest correctness check is the simplest one: at `keep_fraction=1.0` (prune nothing), the compacted model's weights reproduce the original's exactly. That invariant is what the test suite actually verifies.

### The gate: a real win, not an assumed one

Compacting the model is only step one. `prune_and_recover` runs the full pipeline:

1. Load a registered LSTM version and structurally compact it.
2. **Benchmark** the before/after honestly — real parameter count, real on-disk artifact size (the same `torch.save`d state dict format training already produces), and real measured CPU inference latency (mean over 20 repeated forward passes, with an explicit warm-up pass excluded from the timing).
3. **Recovery fine-tune** the compacted model — pruning removes real capacity, so the model needs to re-adapt. This reuses the same warm-start machinery `ml/incremental.py` already uses for lighter incremental retrains, just seeded from pruned weights instead of an unpruned Production version.
4. **Re-evaluate** both the unpruned and recovered candidates through the same walk-forward harness (`evaluate_walk_forward`) everything else in this codebase is judged by — not just training-time loss.
5. **Gate on both axes at once**: `achieves_a_real_win()` requires the artifact to be at least 5% smaller *and* not more than 10% slower, while a separate accuracy check requires the recovered candidate's walk-forward MAPE regression to stay within a tolerance (default 1%) of the unpruned version.

Only if both pass is the result considered a real win — and even then, the recovered version is always registered to MLflow (tagged `prune_gate_passed`) but **never auto-promoted to Production**. A human, or `promote_version`, makes that call. If the gate fails, the honest outcome is "pruning wasn't worth it at this model size" — a legitimate result to record, not a failure to bury.

### The recovery-epochs bug — a real number, not a hypothetical

This is worth telling because it's a good example of the difference between "should work" and "measured to work." The recovery step originally defaulted its epoch count to `incremental_train_epochs` (3) whenever no explicit value was given — the right number for incremental's own "small nudge to an already-converged model" use case, but nowhere near enough to recover from an actual structural cut. The default `--keep-fraction 0.5` removes *half* the LSTM's hidden units — that's not a nudge, it's a real capacity cut the model has to relearn from.

Measured live against a real registered version, at `keep_fraction=0.5`:

- **3 epochs**: validation MAPE was still steeply descending (85% → 61% → 37%, nowhere near converged) and produced a **+131.2%** relative walk-forward MAPE regression — about 131x past the pipeline's own 1% accuracy-tolerance gate. Every default prune was guaranteed to fail.
- **15 epochs**: already recovered to **better than the unpruned version** (-21.1% relative).
- **20 epochs** (the fix, and the current default `prune_recovery_epochs`): keeps a real margin above that recovery point without meaningfully more compute — about 0.6 seconds per epoch on this dataset.

The number is still overridable per call (`--recovery-epochs`) for a more aggressive `keep_fraction` that might genuinely need more, but the default no longer sets every prune up to fail its own gate.

### How to actually run it

```bash
make prune VERSION=19 KEEP_FRACTION=0.5 REGION=NSW1
```

which drives `ecolens-forecast prune` (`app/cli.py`) — flags for `--model-name`, `--version` (required), `--region` (repeatable), `--keep-fraction` (default 0.5), `--max-regression-pct` (default 1.0), `--recovery-epochs`, and `--no-register` for a dry run that skips MLflow entirely.

### What this actually buys you

- A concrete, auditable answer to "could this model be smaller" instead of an assumption baked into a hyperparameter chosen once and never revisited.
- A structural reduction — real parameter count and real artifact size go down — not a sparse tensor that looks smaller on paper but runs the same.
- A safety net: accuracy regression and size/latency wins are both required before anything is even considered a candidate, and nothing reaches Production without a separate, deliberate promotion step regardless.
- An honest paper trail: every attempt is registered and tagged with whether it actually passed its own gate, so "we tried pruning and it didn't help" is as visible in MLflow as a genuine win would be.

---

## Part 2: Conformal Calibration — Making the Uncertainty Band Trustworthy

### Why the raw quantile heads aren't enough

`DemandLSTM` predicts P10/P50/P90 directly, trained with pinball loss on the P10/P90 heads. That sounds like it should already give a calibrated 80% interval — in practice, a quantile-regression head's raw output has no coverage guarantee at all. It's only as good as the training loss happened to get it, and pinball loss alone tends to *under-cover*: the true value falls outside the predicted interval more often than the target rate would suggest. A model can look good on paper (low pinball loss) and still produce an 80%-labeled interval that's really only right 65–75% of the time.

EcoLens fixes this with **conformalized quantile regression (CQR)**, from Romano, Patterson & Candès (2019) — a post-hoc correction layer computed once on a held-out calibration split the model never trained on, that turns "the model's own quantile heads, for whatever they're worth" into an interval with a real, finite-sample coverage guarantee.

### How CQR actually works here

The implementation lives in `services/forecast-api/app/service/ml/conformal.py`, and it's short — the core idea fits in about twenty lines. For each held-out calibration sample, it computes a **nonconformity score**:

```python
scores = np.maximum(lo_cal - y_cal, y_cal - hi_cal)
```

This is positive when the true value fell *outside* the raw interval (by however much), and negative — "room to spare" — when it fell inside. Then it takes a specific quantile of those scores:

```python
level = min(1.0, np.ceil((1 - alpha) * (n + 1)) / n)
q = np.quantile(scores, level, axis=0, method="higher")
```

That `ceil((1-alpha)*(n+1))/n` correction, rather than the plain `(1-alpha)` quantile, is what makes the guarantee *exact* for finite sample sizes rather than merely asymptotic — using the naive quantile would systematically under-cover by a sample-size-dependent amount.

The resulting `q` — one value per horizon step — gets applied symmetrically at inference time:

```python
def apply(self, lo, hi):
    return lo - self.q, hi + self.q
```

Widen the low side, widen the high side, by exactly as much as the calibration data says the raw interval was wrong. `alpha` defaults to 0.2, targeting an 80% (P10–P90) interval. The calibration result is persisted as an MLflow artifact (`conformal_calibration.json`) alongside the model, so serving doesn't need to recompute it — it's loaded back at forecast time and applied automatically, tolerating older model versions that predate it (calibration is simply `None` there).

### Where it sits in the pipeline

Order matters here, and it's deliberate. Per-region bias correction is applied to the raw P10/P90 *before* conformal calibration sees them — bias first, then conformal on the debiased residual. The reasoning: conformal calibration only widens or tightens a band symmetrically around whatever center the model already produced; it can't fix a band that's mis-centered in the first place. Fixing the center first, then measuring how wrong the (now better-centered) width still is, gets more out of each step than doing it the other way around.

`empirical_coverage` — the fraction of true values that actually land inside `[lo, hi]` — is computed and logged to MLflow on every training run, both raw and calibrated, so a calibration's real coverage against its 1-alpha target is something you can actually look up, not just assume worked.

### The honest caveat, stated in the code itself

CQR's coverage guarantee formally requires the calibration and test data to be *exchangeable* — independent and identically distributed, or at least not adversarially ordered. Chronological time-series data violates this in general: if demand undergoes a regime shift between the calibration window and actual deployment, the guarantee doesn't hold anymore. This isn't a bug specific to this implementation — it's the same simplifying assumption most applied conformal-prediction-for-forecasting work makes — but it's written directly into the module's docstring rather than glossed over, because it's exactly the kind of assumption that's easy to forget is there once the numbers look fine in a dashboard.

It also can't fix everything. Conformal calibration — and the adaptive layer described next — only ever rescales width around P50. Neither one can correct a systematically mis-centered forecast; that's a job for bias correction (or a better-trained model), not for the calibration layer.

### The adaptive layer on top: reacting to real drift

Static conformal calibration is fit once, on one calibration split, at training time. But conditions drift — demand volatility a month after training isn't guaranteed to match the calibration window. `services/forecast-api/app/service/ml/adaptive_calibration.py` implements a simplified version of **Adaptive Conformal Inference** (Gibbs & Candès, 2021): instead of a fixed `q`, each `(model_name, region)` pair gets one scalar multiplier, persisted in Redis, that adjusts over time based on real, reconciled outcomes.

The mechanism is genuinely simple. Every time a served forecast is reconciled against the real demand value that eventually landed:

```python
miss = 0.0 if covered else 1.0
updated = current + step_size * (miss - target_alpha)
updated = min(max(updated, MIN_SCALE), MAX_SCALE)
```

A miss nudges the scale up (wider next time); a hit nudges it down toward 1.0. The subtlety worth calling out: at `target_alpha=0.2`, a real fifth of hits are *expected* to look like misses at the calibration's intended width — the scale doesn't chase a zero-miss streak, it relaxes toward 1.0 even when things are going well, because "every single forecast landed inside the band" would itself mean the band is wider than it needs to be.

The scale is clamped to `[0.5, 3.0]` — generous enough that real, sustained drift still visibly moves the number long before hitting either wall, but bounded so a long lucky streak can't collapse the interval toward zero width, and a long unlucky one can't blow it out to something useless. The step size (0.02) is deliberately small: it takes about 50 consecutively-missed reconciled forecasts to move the scale by a full 1.0 — territory that would already be tripping the separate forecast-quality circuit breaker (which swaps out the whole model for the seasonal-naive baseline on sustained, severe miscalibration) long before the adaptive scale alone got anywhere near its limits. The two mechanisms cover different severities of the same underlying problem: the breaker handles "this model shouldn't be serving right now," while the adaptive scale handles the far more common case of "this is still the right model, it's just not perfectly calibrated at the moment."

Persisted with no TTL, deliberately — unlike the transient served/pending bookkeeping the reconciliation job otherwise keeps, this scale *is* the adaptation. Letting it silently expire and reset to 1.0 mid-drift would undo exactly the correction it exists to provide.

### What the real numbers actually looked like

This isn't theoretical — walk-forward evaluation on real warehouse data surfaced genuinely uneven per-region coverage before any of this was tuned:

| Region | Coverage (target 80%) | Bias (P50 − actual, MW) |
|---|---|---|
| NSW1 | 0.833 | −98.9 |
| QLD1 | 0.771 (under) | −343.1 (largest) |
| VIC1 | 0.776 (under) | +57.3 |
| SA1 | 0.891 | −27.5 |
| TAS1 | 0.984 (over-covered) | +88.4 |
| WEM | 0.865 | +20.9 |

Bias varies in both sign and magnitude by region, which is exactly why a single global correction can't paper over it — whatever closes the gap has to be region-aware, which is the whole reason bias correction and conformal calibration are both applied per-region rather than once globally. And the follow-up experiment was just as honest about its own limits: per-region bias correction helped dramatically for some regions (NSW1 and TAS1 landed within about 6 MW of zero bias) and made others measurably worse — the ~25–27-row real calibration split per region turned out not to be a stable enough estimate of a region's "true" bias for every region, likely because bias drifts across the evaluation window faster than one small snapshot can track. That finding is recorded as a reason to be cautious about adopting it uniformly, not smoothed over.

### What this actually buys you

- A real, finite-sample coverage guarantee on top of quantile heads that otherwise have none — the difference between "an 80% interval because we called it that" and "an 80% interval because held-out data says so."
- A correction that adapts to drift after deployment, not just a number frozen at training time, without needing to retrain or recalibrate from scratch.
- Two independently tunable failure responses at two different severities — a gradual width adjustment for ordinary drift, and a full model swap for a real, sustained breakdown — instead of one blunt mechanism trying to do both jobs.
- Total honesty about what it can't do: it won't fix a mis-centered forecast, and its formal guarantee technically assumes something (exchangeability) that time-series data doesn't strictly provide. Both limitations are documented in the code itself rather than discovered the hard way later.

---

## The common thread

Neither of these mechanisms exists to make a number on a dashboard look better. Pruning exists to answer "is this model carrying weight it doesn't need" with a measured yes-or-no, gated so a bad answer can't sneak into production. Conformal calibration exists to answer "can you actually trust the width of this uncertainty band" with a real guarantee instead of a hopeful label — and its adaptive layer keeps that trust current as the world drifts, rather than letting it quietly go stale.

The pattern worth taking away isn't the math in either mechanism specifically. It's the discipline around both: compute a real before/after, gate on it, register the result whether it's a win or not, and never let "should work" stand in for "measured to work."
