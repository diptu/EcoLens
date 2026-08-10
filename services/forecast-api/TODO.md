

## Cross-cutting: gaps the product description implies but no tab shows

- [ ] **TimesFM never actually serves or blends into a forecast — plan
      to close this, in plain English (2026-08-10).**

      Where things stand today: `timesfm_adapter.py` wraps a real
      Google TimesFM model, but the only thing that ever calls it is an
      offline benchmark command (`cli.py evaluate-timesfm`). It never
      contributes to a forecast a real user actually sees. The product
      description's promise of a "blend" of LSTM, TFT, and TimesFM
      isn't true yet — right now, exactly one model (the LSTM) serves
      every live forecast, and TFT and TimesFM both sit on the sidelines
      as offline comparisons. The good news is that the pieces to fix
      this mostly already exist; they've just never been connected to
      each other.

      **Step 1 — let TFT actually go live.** Right now, promoting a TFT
      version to Production doesn't change what gets served — a real
      gap already tracked above ("Promoting a TFT version to Production
      has no effect on what's served"). TFT needs the same kind of
      live, auto-reloading setup the LSTM already has before it can be
      part of any real blend.

      **Step 2 — turn on the blend layer that already exists.** There's
      a real, fully-built component (`ml/blend.py`) whose entire job is
      combining several models' forecasts, automatically leaning more
      on whichever one has been most accurate recently. It's just never
      been switched on — nothing in the app calls it yet. Once LSTM and
      TFT are both live, this is the natural place to plug TimesFM in
      too, so all three genuinely contribute to what gets served instead
      of just one model winning by default. One thing to watch closely:
      combining three models per request, including a large model like
      TimesFM, will be slower than serving one — this needs to be
      measured for real before it goes live, not assumed to be fine.

      **Step 3 — make "transfer learning" for TimesFM actually true, the
      honest way.** We checked directly, and the TimesFM software
      Google publishes doesn't let us retrain or fine-tune the model
      itself — it's built to be used as-is, not adjusted. So instead of
      claiming we're changing TimesFM's own knowledge (which wouldn't
      be accurate), the honest version of "transfer learning" here is:
      build a small model of our own that sits on top of TimesFM,
      learns from TimesFM's forecasts, and corrects them using our real
      regional demand data. That's a genuine, well-established way to
      reuse a big pretrained model's knowledge without needing to
      modify it directly — and this small correction model *can* keep
      learning from new data automatically, the same way the LSTM and
      TFT already do, so the "continuously adapts" part of the product
      description would become true for TimesFM's contribution too.

      **Step 4 — prove it actually helps before trusting it.** Before
      this blend becomes what real users see, run it through the same
      kind of honest, region-by-region accuracy check already used to
      validate the LSTM and TimesFM on their own this session. A blend
      should only replace what's live today if the real numbers show
      it's genuinely better, not because combining models sounds like
      it should help.

      **Step 5 — check the speed, then update what people see.** Make
      sure the blended forecast is still fast enough for how forecasts
      are cached and served today; if it isn't, it may need to run on a
      schedule instead of live per request. Once it's actually running,
      show which model is driving each forecast on the dashboard (the
      blend layer already calculates this, it's just not displayed
      anywhere yet), and update the architecture write-up so it
      describes what's really happening.
- [ ] **The carbon-insights route has no calibration or fallback — plan
      to close this, in plain English (2026-08-10).**

      Where things stand today: `/v1/forecast/intelligence` (the route
      behind carbon/generation-mix predictions, `EnergyForecastLSTM`) is
      the only forecast this platform serves with none of the safety
      net the plain demand forecast already has. The demand route
      (`/v1/forecast`) genuinely does everything the product description
      promises under "Auto-Correcting Accuracy": it calibrates its own
      uncertainty ranges, adjusts itself automatically if it's been
      running wide or narrow lately, and falls back to a safe baseline
      if something's clearly gone wrong. The carbon-insights route does
      none of that — it just returns the raw model output, uncalibrated,
      with nothing watching whether it's actually trustworthy. This was
      a known, disclosed shortcut when the carbon model was first built
      (its own code comments already say so), not a surprise.

      The genuinely good news: every piece of safety-net machinery the
      demand route uses was already built in a reusable way — keyed by
      model name and region, not hardcoded to the demand model
      specifically. This isn't "build it all again from scratch," it's
      "point the existing machinery at a second model too."

      **Step 1 — teach the carbon-insights model its own real error
      bars.** Right now its training step skips calibration entirely.
      Add the same held-back "calibration" slice of real data the
      demand model already uses, for both of the things this model
      predicts (demand and generation mix), so it learns honest
      uncertainty ranges instead of just a raw point guess.

      **Step 2 — actually apply those error bars when serving a real
      request.** Once they're calculated, wire them into what
      `/v1/forecast/intelligence` returns, so the ranges a user sees are
      calibrated, not the model's raw, overconfident output.

      **Step 3 — let it self-correct over time, the same way the
      demand model already does.** There's already a real background
      process that watches how the demand forecast's accuracy holds up
      against what actually happens, and nudges its confidence ranges
      wider or narrower accordingly. Point that same process at the
      carbon-insights model too, instead of building a second one.

      **Step 4 — give it a real safety net.** The demand route already
      has an automatic circuit breaker: if its recent accuracy looks
      genuinely bad, it stops serving its own forecasts and falls back
      to a safe, simple baseline until it's trustworthy again. Reuse
      that same breaker for the carbon-insights route too, so a bad
      carbon/generation-mix forecast can't reach a user silently.

      **Step 5 — prove it actually works before trusting it.** Confirm
      the calibrated ranges genuinely cover reality as often as they
      claim to (the same honest coverage check already used for the
      demand model), and deliberately test that the fallback actually
      kicks in when it should, before calling this closed.
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
