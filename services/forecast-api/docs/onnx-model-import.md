# Design: user-uploaded ONNX models for forecasting

**Status**: proposed, not implemented. Written 2026-08-22 against the codebase
state at that date — cite line numbers loosely, re-check before implementing.

## Goal

Let a user upload a model's weights in **ONNX format** from the dashboard UI
and have the system use it for live forecasting and every other task the
built-in architectures (LSTM, TFT, TimesFM) already participate in:
walk-forward backtesting, the live evaluation gate, MLflow registration,
`None → Staging → Production` promotion, and the Model Comparison dashboard.

## Why this isn't a copy of the existing bundle-import feature

`app/service/ml/model_import.py` (uncommitted at time of writing) already
implements an end-to-end "upload a trained checkpoint" pipeline for
`lstm`/`tft`: a zip containing `manifest.json` + `model_state_dict.pt` +
plain-JSON scalers, validated (feature-fingerprint check, strict
`load_state_dict`, a dummy-input sanity forward pass) and registered in
MLflow before ever running. `POST /v1/model/versions/import` and a dashboard
"Import" tab already exist for it.

That pipeline works *because* a `state_dict` is just a name→tensor mapping
loaded into an already-instantiated, known Python class (`DemandLSTM`/
`DemandTFT`, from `app/models/`). The uploaded weights must match that
class's exact architecture (hidden size, layer count, etc.) — the system
supplies the `forward()` logic, the upload only supplies parameters.

**ONNX inverts this.** The entire point of accepting ONNX is that the
uploader does *not* need to match this codebase's Python model classes at
all — a self-contained, framework-agnostic graph, exported from PyTorch,
TensorFlow, scikit-learn, or anything else, is the artifact. That's what
makes "any architecture" real, but it also means the system loses the free
architectural knowledge it currently gets from "load into a known
`nn.Module`" — the shape/order/meaning of inputs and outputs has to come
from an explicit, validated contract instead. That contract is the actual
design problem here; everything else is plumbing this codebase already has
working precedent for.

## Prerequisite gap found while researching this (not ONNX-specific)

`GET /v1/forecast` — the *live* serving route — is hardcoded to
`LSTMForecaster` today. TFT and TimesFM-correction can be trained and
evaluated (`POST /v1/model/versions/{version}/evaluate` dispatches on
`body.architecture`) but are **not reachable from live serving at all**.

So "use an uploaded model for forecasting... like LSTM, TFT, TimesFM" already
doesn't fully hold for TFT/TimesFM today. ONNX needs the same dispatch
layer TFT/TimesFM are missing. Building it once, generically, benefits both
— see Phase 0 below.

## The `Forecaster` contract (already generic — reuse as-is)

`app/service/ml/evaluate.py` defines `Forecaster` as a structural `Protocol`:

```python
class Forecaster(Protocol):
    name: str
    def predict(self, history: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns (p10, p50, p90), each shape (horizon,), real MW units."""
```

`evaluate_walk_forward` and `run_live_evaluation_gate` never import a
concrete architecture — only this shape. `LSTMForecaster`/`TFTForecaster`/
`BaselineForecaster` each implement it independently, no shared base class.
An `ONNXForecaster` implementing this same protocol gets backtesting, the
live eval gate, and promotion gating **for free** — confirmed
`promote_version` (`app/service/ml/registry.py`) gates purely on MLflow
tags/metrics keyed by `model_name` string, never on an architecture field.

## The manifest — the actual design problem

An ONNX graph has fixed input/output tensor shapes and no semantic labels
attached. `ONNXForecaster` needs an explicit, versioned `manifest.json`
(uploaded in a zip alongside the `.onnx` file, same convention as the
existing bundle) that declares:

```jsonc
{
  "manifest_version": 1,
  "model_name": "my-custom-demand-net",   // user-chosen, slugified -> MLflow registered-model name
  "framework_note": "exported from PyTorch 2.3, opset 17",
  "lookback": 24,
  "horizon": 48,
  "feature_columns": [                    // ORDERED, must be a subset of
    "temp_c", "humidity_pct", "hour_sin", // app/service/ml/features.py's
    "hour_cos", "region_NSW1", "..."      // FEATURE_COLUMNS -- not arbitrary
  ],                                       // raw columns (see Non-goals).
  "decoder_columns": null,                // optional, TFT-shaped 2-input models only
  "input_names": {"encoder": "input_0"},  // ONNX graph input tensor name(s)
  "output_type": "point",                 // "point" | "quantile3"
  "output_name": "output_0",
  "regions": ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"],
  "uploaded_by": null,                    // optional, free text
  "source_note": null                     // optional, free text
}
```

Key decisions baked into this schema:

- **`feature_columns` must be an ordered subset of this codebase's own
  `FEATURE_COLUMNS`**, not arbitrary raw warehouse columns. This lets
  `ONNXForecaster.predict` reuse `build_features`/`fit_scalers`/
  `apply_scalers` exactly as `LSTMForecaster` does — same normalization,
  same calendar/weather/lag feature engineering, no new preprocessing code
  path, no way for an upload to smuggle in a custom feature-computation
  step (a real safety boundary, not just convenience). See Non-goals for
  why this is deliberately not "bring your own arbitrary preprocessing."
- **`output_type: "point"` is a first-class, expected case, not a
  degraded one.** Most external ONNX exports won't natively produce
  `(p10, p50, p90)` — that's a fairly bespoke pinball-loss training setup
  specific to this project. If `output_type` is `"point"`, the import
  pipeline fits **conformal calibration** on it automatically
  (`app/service/ml/conformal.py`'s `fit_conformal`, already
  model-agnostic — it only needs a point-prediction stream vs. real
  actuals on a held-out split, which the import pipeline computes as part
  of validation). The uploader gets real, calibrated p10/p90 bands without
  having trained a quantile model at all.
- **`lookback`/`horizon`/tensor names are cross-checked against the
  graph's actual I/O** (`onnxruntime.InferenceSession.get_inputs()/
  get_outputs()`) during validation, never trusted from the manifest
  alone — same "verify, don't just believe declared metadata" discipline
  `model_import.py`'s feature-fingerprint check already applies.

## Validation pipeline

Mirrors `model_import.py`'s staged-rejection pattern (fail fast, before any
MLflow call), extended for ONNX-specific risk:

1. **Structural**: zip size cap, `onnx.checker.check_model()`.
2. **Opset/domain allowlist**: reject custom ops/domains. ONNX Runtime is a
   full C++ execution engine — meaningfully larger attack surface than
   "load a state_dict into a known `nn.Module`." No custom op libraries,
   pin to a small allowed opset range.
3. **I/O introspection**: `session.get_inputs()/get_outputs()` shapes/
   dtypes/names cross-checked against the manifest. Any mismatch → reject
   with a specific error, not a downstream crash.
4. **Sanity forward pass**: run real recent history through
   `session.run()`. Check: finite output, correct shape,
   `p10 ≤ p50 ≤ p90` if `output_type: "quantile3"`.
5. **Calibration** (only if `output_type: "point"`): fit conformal
   calibration on a held-out real split, same split convention
   `train_model`'s `_split_val_for_calibration` already uses.
6. **Register**: only after every prior stage passes — MLflow, `None`
   stage (never auto-promoted), tags `architecture=onnx_custom`,
   `uploaded_by`, `source_note`, `manifest_version`.

## Runtime safety

Directly applying this session's own TimesFM-OOM incident
(`app/models/timesfm_adapter.py`'s `@lru_cache` fix, `train-worker` killed
by the OOM reaper loading a second 200M-param checkpoint): arbitrary
uploaded inference code is a real resource-exhaustion vector, not a
hypothetical one, on this exact service.

- `CPUExecutionProvider` only.
- Wall-clock timeout around every `session.run()` call — both at
  validation time and at serve time.
- Ideally, run `session.run()` in a resource-capped subprocess (memory
  ulimit + timeout) rather than inline in `api`'s or `train-worker`'s
  shared process — a bad graph shouldn't be able to take down live
  serving or the training consumer the way the TimesFM incident did.
- File size cap enforced before parsing anything.

## API surface

**New endpoint**, not a branch in the existing one:
`POST /v1/model/versions/import-onnx` — deliberately separate from
`POST /v1/model/versions/import` because the validation pipelines
(onnxruntime vs. torch) are different enough that sharing one function
would mean branching internals throughout, not just at the entrypoint.
Factor the shared tail (MLflow registration + live eval gate) into a
helper both `model_import.py` and the new `onnx_import.py` call — the
fork's research confirmed that part is already architecture-agnostic.

```
POST /v1/model/versions/import-onnx
  multipart/form-data:
    file: <zip containing model.onnx + manifest.json>
    uploaded_by: str | None   (form field, optional)

  201 -> ModelImportResponse (run_id, model_version, model_name,
                               architecture="onnx_custom",
                               eval_gate_passed, eval_gate_mape, regions)
  422 -> ApiError (BundleValidationError, one of the staged reasons above)
```

Reuses the existing `ModelImportResponse` schema
(`app/schemas/model/import_bundle.py`) — no new response shape needed.

## Dashboard

Extend the existing Import tab (`services/dashboard/.../models/page.tsx`)
with an ONNX option alongside LSTM/TFT bundle import, or auto-detect from
the uploaded zip's contents (presence of a `.onnx` file). The Model
Comparison / registry list views need to handle an **open-ended set of
model names** — today's dashboard effectively assumes ~3 fixed names
(`lstm_demand`, `lstm_demand_tft`, `timesfm_demand_correction`); ONNX
uploads are user-named, so search/filter-by-name and an
architecture-tag filter become necessary, not optional polish.

## Non-goals (explicit scope boundary)

- **No incremental retraining of uploaded ONNX models.** An exported
  graph has no optimizer state attached; "updating" one means the user
  re-exports and re-uploads a new version externally. This mirrors the
  precedent TimesFM already sets (frozen base model + a separately
  retrainable correction layer) — this codebase already has a working
  pattern for "the core model is immutable, only a small layer on top
  adapts," reused rather than reinvented.
- **Not arbitrary raw-column feature engineering in v1.** Features are
  constrained to `FEATURE_COLUMNS`, computed via the existing
  `build_features` pipeline. Fully custom preprocessing (a user-uploaded
  transform spec operating on raw warehouse columns) is a much larger,
  much less safe surface — no code execution, so it would need a
  sandboxed declarative transform DSL. Worth revisiting once the
  constrained version is live and its limits are actually felt, not
  before.
- **No dynamic-shape ONNX models in v1.** `lookback`/`horizon` are
  fixed per upload (matching how LSTM/TFT already work — a version is
  trained for one horizon). Dynamic axes add real validation complexity
  (shape-cross-checking becomes "is this shape compatible," not "does
  this shape match") for a use case nothing here currently needs.

## Suggested phasing

0. **Prerequisite** (not ONNX-specific): generalize `/v1/forecast` to
   dispatch by `model_name`/architecture. Closes the existing TFT/TimesFM
   live-serving gap as a side effect, and builds the dispatch layer ONNX
   needs to slot into.
1. `ONNXForecaster` + manifest schema + validation pipeline as pure
   library code (`app/service/ml/onnx_import.py`,
   `app/models/onnx_adapter.py`) — testable without any endpoint.
2. `POST /v1/model/versions/import-onnx` + MLflow registration, reusing
   the shared register-and-eval-gate tail from `model_import.py`.
3. Dashboard: extend the Import tab; registry/comparison views handle
   open-ended model names.
4. Hardening: subprocess-sandboxed inference, opset allowlist
   enforcement, per-upload rate limits.

## Open questions to resolve before implementation

- Where does `onnxruntime` get pinned in `pyproject.toml`, and does the
  Dockerfile need a new system dependency for it (it's usually pure
  wheel, but confirm for the `forecast-api` image's base).
- Does MLflow's own artifact store (R2, via `mlops/tracking.py`) need any
  change to store `.onnx` files, or does `mlflow.log_artifacts` already
  handle arbitrary file types with no special-casing needed (very likely
  yes — it's not `mlflow.pytorch.log_model`, just a directory upload).
- Exact opset allowlist range — needs a decision informed by what real
  export tooling (PyTorch, sklearn-onnx, etc.) actually emits by default
  today, not guessed.
- Whether `import-onnx` needs any form of auth/rate-limiting beyond what
  the rest of this router has (today: "deliberately open, no auth" is
  the existing convention for every mutating route in this service —
  worth explicitly re-deciding for this one, given it accepts executable
  inference graphs from anyone who can reach the endpoint).
