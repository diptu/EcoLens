"""Manual ONNX model-bundle import -- the ONNX counterpart to `ml/
model_import.py`'s `.pt` state_dict bundle import, built from the same
staged-validation-before-any-MLflow-call discipline and reusing that
module's `BundleValidationError`/`ImportResult`/scaler-JSON helpers
directly rather than re-deriving them.

**Why a separate module, not a branch in `model_import.py`**: a `.pt`
bundle's weights load into a *known* Python class (`DemandLSTM`/
`DemandTFT`) this codebase already owns -- the uploaded architecture must
match exactly (hidden size, layer count, ...). An ONNX bundle is the
opposite: a self-contained, framework-agnostic graph that doesn't need to
match any class here at all, which is the entire point of accepting ONNX
(`services/forecast-api/docs/onnx-model-import.md`'s full design). That
difference runs through every validation stage below (opset/domain
allowlisting, I/O introspection against a *declared* manifest instead of
a known `forward()` signature), so sharing one function with branches
throughout would obscure more than it'd save. The genuinely shared parts
(bundle exception type, response shape, plain-JSON scaler helpers) are
imported from `model_import.py`, not duplicated.

Bundle format (`docs/onnx-model-import.md`'s manifest schema, as actually
implemented here):

    manifest.json           -- see `OnnxBundleManifest`.
    model.onnx               -- the exported graph, raw bytes.
    feature_scalers.json     -- same plain-JSON shape `model_import.py`
                                already uses (never joblib/pickle on
                                uploader-controlled bytes).
    target_scaler.json       -- same shape.
    conformal_calibration.json / demand_bias_correction.json -- optional,
                                same as the `.pt` path.

**Scope note** (see the design doc): `feature_columns` must be an ordered
subset of this service's own `FEATURE_COLUMNS` -- an uploaded model reuses
this system's feature engineering/scaling, it doesn't bring its own. No
auto-fitted conformal calibration for a `output_type="point"` upload that
ships none -- see `ml/evaluate.py`'s `ONNXForecaster` docstring.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import joblib
import mlflow
import mlflow.onnx
import numpy as np
import onnx
import onnxruntime
from mlflow.entities.model_registry import ModelVersion

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.service.ml.evaluate import (
    Forecaster,
    LiveEvaluationGateResult,
    load_registered_onnx_model,
    run_live_evaluation_gate,
)
from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS
from app.service.ml.model_import import (
    BundleValidationError,
    ImportResult,
    _open_bundle,
    _read_member,
    _scalers_from_json,
)
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha

log = get_logger(__name__)


def _require(condition: bool, message: str) -> None:
    """Shadows (not imports) `model_import._require` -- every check *this
    module* performs directly raises the ONNX-specific `OnnxBundle
    ValidationError` subclass, not the shared base class. Reused helpers
    from `model_import.py` (`_scalers_from_json` etc.) still raise the
    base `BundleValidationError` internally, unaffected by this -- they
    bind to their own module's `_require`, not this one. Both are caught
    identically at the route layer (`OnnxBundleValidationError` IS-A
    `BundleValidationError`); this only sharpens which specific pipeline
    a given failure came from for logs/tests."""
    if not condition:
        raise OnnxBundleValidationError(message)

#: Real, current export tooling (PyTorch's `torch.onnx.export`, the
#: legacy TorchScript-based path `forcast_pipelineV2.ipynb`'s Step 14
#: uses) targets opset 17 as of this writing; the range is generous
#: around that rather than pinned to one exact value -- a real ONNX
#: model's own reasonable opset choice shouldn't get rejected over a
#: version bump this codebase hasn't been re-checked against yet, but an
#: implausibly old or brand-new/experimental opset is real signal
#: something's off, not a value worth trusting blindly.
_MIN_OPSET = 13
_MAX_OPSET = 19

_ARCHITECTURE = "onnx_custom"

_MODEL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


class OnnxBundleValidationError(BundleValidationError):
    """Same 422-mapped exception `model_import.py`'s own
    `BundleValidationError` already is (subclassing, not aliasing, so
    `except BundleValidationError` at the route layer catches both
    import paths with one clause) -- a distinct name only so error
    messages/log events are unambiguous about which pipeline raised."""


@dataclass
class OnnxBundleManifest:
    manifest_version: int
    model_name: str
    lookback: int
    horizon: int
    feature_columns: list[str]
    input_name: str
    output_type: str  # "point" | "quantile3"
    output_names: dict[str, str]
    regions: list[str]
    architecture_note: str | None = None
    source_note: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "OnnxBundleManifest":
        try:
            manifest_version = int(data["manifest_version"])
        except KeyError as exc:
            raise OnnxBundleValidationError(
                f"manifest.json missing required field: {exc}"
            ) from exc
        _require(
            manifest_version == 1,
            f"unsupported manifest_version {manifest_version!r} -- only 1 is known",
        )

        try:
            model_name = str(data["model_name"])
            lookback = int(data["lookback"])
            horizon = int(data["horizon"])
            feature_columns = list(data["feature_columns"])
            input_name = str(data["input_name"])
            output_type = str(data["output_type"])
            regions = list(data["regions"])
        except KeyError as exc:
            raise OnnxBundleValidationError(
                f"manifest.json missing required field: {exc}"
            ) from exc

        _require(
            bool(_MODEL_NAME_PATTERN.match(model_name)),
            f"model_name {model_name!r} must match {_MODEL_NAME_PATTERN.pattern} "
            "(letters/digits/underscore/hyphen, 1-100 chars)",
        )
        _require(
            output_type in ("point", "quantile3"),
            f"output_type must be 'point' or 'quantile3', got {output_type!r}",
        )
        _require(len(feature_columns) > 0, "manifest.json 'feature_columns' must be non-empty")
        _require(len(regions) > 0, "manifest.json 'regions' must be non-empty")

        try:
            output_names_raw = dict(data["output_names"])
        except KeyError as exc:
            raise OnnxBundleValidationError(
                f"manifest.json missing required field: {exc}"
            ) from exc
        required_keys = ("p10", "p50", "p90") if output_type == "quantile3" else ("point",)
        for key in required_keys:
            _require(
                key in output_names_raw,
                f"manifest.json 'output_names' missing required key {key!r} "
                f"for output_type={output_type!r}",
            )
        output_names = {k: str(v) for k, v in output_names_raw.items() if k in required_keys}

        return cls(
            manifest_version=manifest_version,
            model_name=model_name,
            lookback=lookback,
            horizon=horizon,
            feature_columns=feature_columns,
            input_name=input_name,
            output_type=output_type,
            output_names=output_names,
            regions=regions,
            architecture_note=data.get("architecture_note"),
            source_note=data.get("source_note"),
        )


def _validate_feature_columns(manifest: OnnxBundleManifest) -> None:
    """Every declared column must be a real column from this service's
    own `FEATURE_COLUMNS` -- an uploaded ONNX model reuses this system's
    feature engineering/scaling (`docs/onnx-model-import.md`'s scope
    decision), it can't declare an arbitrary column name and expect this
    service to have any idea what to feed it. Order is preserved as
    declared (not sorted/deduped) -- it has to match the graph's own
    real input-tensor column order, which this function doesn't itself
    know; the I/O-shape cross-check later in `_validate_onnx_bundle`
    only confirms the *count* matches, not that the order is correct --
    a real, accepted limitation the design doc doesn't solve either
    (there's no way to introspect "which column is which" from an ONNX
    graph's shape alone)."""
    known = set(FEATURE_COLUMNS)
    unknown = [c for c in manifest.feature_columns if c not in known]
    _require(
        not unknown,
        f"feature_columns contains unknown column(s) not in this service's own "
        f"FEATURE_COLUMNS: {unknown}",
    )
    _require(
        len(manifest.feature_columns) == len(set(manifest.feature_columns)),
        "feature_columns must not contain duplicates",
    )


def _validate_onnx_model(onnx_model: onnx.ModelProto, manifest: OnnxBundleManifest) -> None:
    """Structural validity, opset/domain allowlisting, then I/O-shape
    cross-check against the manifest -- reject on any mismatch rather
    than trusting the declared shapes (`docs/onnx-model-import.md`'s
    validation pipeline, stages 2-3)."""
    try:
        onnx.checker.check_model(onnx_model)
    except Exception as exc:
        raise OnnxBundleValidationError(f"model.onnx failed structural validation: {exc}") from exc

    for opset in onnx_model.opset_import:
        _require(
            not opset.domain,
            f"model.onnx uses a custom operator domain ({opset.domain!r}) -- "
            "only the default ONNX domain is accepted",
        )
        _require(
            _MIN_OPSET <= opset.version <= _MAX_OPSET,
            f"model.onnx opset {opset.version} is outside the accepted range "
            f"[{_MIN_OPSET}, {_MAX_OPSET}]",
        )

    try:
        session = onnxruntime.InferenceSession(
            onnx_model.SerializeToString(), providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        raise OnnxBundleValidationError(f"onnxruntime failed to load model.onnx: {exc}") from exc

    inputs = {i.name: i for i in session.get_inputs()}
    _require(
        manifest.input_name in inputs,
        f"manifest declares input_name={manifest.input_name!r}, but the graph's "
        f"real inputs are {list(inputs)}",
    )
    input_shape = inputs[manifest.input_name].shape
    _require(
        len(input_shape) == 3,
        f"input {manifest.input_name!r} has {len(input_shape)} dims, expected 3 "
        "(batch, lookback, n_features)",
    )
    # Dim 0 (batch) is expected to be dynamic (a string axis name, e.g.
    # "batch") -- only dims 1/2 (lookback/n_features) are checked against
    # the manifest's declared, fixed values.
    _require(
        input_shape[1] in (manifest.lookback, "lookback", None),
        f"input {manifest.input_name!r} dim 1 is {input_shape[1]!r}, expected "
        f"lookback={manifest.lookback}",
    )
    _require(
        input_shape[2] in (len(manifest.feature_columns), None),
        f"input {manifest.input_name!r} dim 2 is {input_shape[2]!r}, expected "
        f"len(feature_columns)={len(manifest.feature_columns)}",
    )

    output_names = {o.name for o in session.get_outputs()}
    for declared_name in manifest.output_names.values():
        _require(
            declared_name in output_names,
            f"manifest declares output {declared_name!r}, but the graph's real "
            f"outputs are {sorted(output_names)}",
        )


def _sanity_check_onnx_inference(
    onnx_bytes: bytes, manifest: OnnxBundleManifest
) -> None:
    """Zero-valued dummy input through the real graph, same finite/
    monotonic checks `model_import.py`'s `_sanity_check_inference`
    already runs for the `.pt` path."""
    session = onnxruntime.InferenceSession(onnx_bytes, providers=["CPUExecutionProvider"])
    x = np.zeros((1, manifest.lookback, len(manifest.feature_columns)), dtype=np.float32)
    try:
        outputs = session.run(None, {manifest.input_name: x})
    except Exception as exc:
        raise OnnxBundleValidationError(
            f"model.onnx failed a dummy-input sanity check: {exc}"
        ) from exc
    by_name = dict(zip((o.name for o in session.get_outputs()), outputs, strict=True))

    values: tuple[np.ndarray, ...]
    if manifest.output_type == "quantile3":
        p10 = by_name[manifest.output_names["p10"]]
        p50 = by_name[manifest.output_names["p50"]]
        p90 = by_name[manifest.output_names["p90"]]
        values = (p10, p50, p90)
    else:
        p50 = by_name[manifest.output_names["point"]]
        values = (p50,)

    _require(
        all(bool(np.all(np.isfinite(v))) for v in values),
        "model.onnx produced non-finite output on a dummy-input sanity check",
    )
    if manifest.output_type == "quantile3":
        _require(
            bool(np.all(p10 <= p50 + 1e-6) and np.all(p50 <= p90 + 1e-6)),
            "model.onnx output violates p10<=p50<=p90 on a dummy-input sanity check",
        )


def _validate_onnx_bundle(
    bundle_bytes: bytes,
) -> tuple[OnnxBundleManifest, bytes, dict[str, object], dict[str, object], dict | None, dict | None]:
    zf = _open_bundle(bundle_bytes)

    manifest_raw = _read_member(zf, "manifest.json")
    assert manifest_raw is not None  # nosec B101 -- required=True default
    try:
        manifest_dict = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise OnnxBundleValidationError(f"manifest.json is not valid JSON: {exc}") from exc
    manifest = OnnxBundleManifest.from_dict(manifest_dict)
    _validate_feature_columns(manifest)

    onnx_bytes = _read_member(zf, "model.onnx")
    assert onnx_bytes is not None  # nosec B101 -- required=True default
    try:
        onnx_model = onnx.load_from_string(onnx_bytes)
    except Exception as exc:
        raise OnnxBundleValidationError(f"model.onnx failed to parse: {exc}") from exc
    _validate_onnx_model(onnx_model, manifest)
    _sanity_check_onnx_inference(onnx_bytes, manifest)

    feature_scalers_raw = _read_member(zf, "feature_scalers.json")
    target_scaler_raw = _read_member(zf, "target_scaler.json")
    assert feature_scalers_raw is not None  # nosec B101 -- required=True default
    assert target_scaler_raw is not None  # nosec B101 -- required=True default
    feature_scalers = _scalers_from_json(
        feature_scalers_raw,
        expected_len=len(NUMERIC_COLUMNS),
        regions=manifest.regions,
        label="feature_scalers.json",
    )
    target_scaler = _scalers_from_json(
        target_scaler_raw, expected_len=1, regions=manifest.regions, label="target_scaler.json"
    )

    calibration: dict | None = None
    calibration_raw = _read_member(zf, "conformal_calibration.json", required=False)
    if calibration_raw is not None:
        try:
            calibration = json.loads(calibration_raw)
        except json.JSONDecodeError as exc:
            raise OnnxBundleValidationError(
                f"conformal_calibration.json is not valid JSON: {exc}"
            ) from exc

    bias: dict | None = None
    bias_raw = _read_member(zf, "demand_bias_correction.json", required=False)
    if bias_raw is not None:
        try:
            bias = json.loads(bias_raw)
        except json.JSONDecodeError as exc:
            raise OnnxBundleValidationError(
                f"demand_bias_correction.json is not valid JSON: {exc}"
            ) from exc

    return manifest, onnx_bytes, feature_scalers, target_scaler, calibration, bias


def _register_onnx(
    manifest: OnnxBundleManifest,
    onnx_bytes: bytes,
    feature_scalers: dict[str, object],
    target_scaler: dict[str, object],
    calibration: dict | None,
    bias: dict | None,
    *,
    uploaded_filename: str,
    uploaded_by: str | None,
) -> tuple[str, ModelVersion]:
    """Writes the `serving/` artifact layout `ml/evaluate.py`'s
    `load_registered_onnx_model` expects, then registers under the
    uploader's own chosen (validated, slugified-pattern) model name --
    not a fixed constant like `model_import.MODEL_NAMES`, since ONNX
    models are open-ended by design."""
    with mlflow.start_run() as run:
        params: dict[str, object] = {
            "lookback": manifest.lookback,
            "horizon": manifest.horizon,
            "feature_columns": ",".join(manifest.feature_columns),
            "input_name": manifest.input_name,
            "output_type": manifest.output_type,
            "regions": ",".join(manifest.regions),
        }
        # Flat MLflow params, not a nested dict -- mirrors `output_names`
        # back out as `output_name_{key}` so `load_registered_onnx_model`
        # can reconstruct the same dict on read.
        for key, value in manifest.output_names.items():
            params[f"output_name_{key}"] = value
        mlflow.log_params(params)

        tags = {
            "git_sha": git_sha() or "unknown",
            "architecture": _ARCHITECTURE,
            "source": "manual_upload",
            "uploaded_filename": uploaded_filename,
        }
        if uploaded_by:
            tags["uploaded_by"] = uploaded_by
        if manifest.source_note:
            tags["source_note"] = manifest.source_note[:250]
        if manifest.architecture_note:
            tags["architecture_note"] = manifest.architecture_note[:250]
        mlflow.set_tags(tags)

        if calibration is not None:
            mlflow.log_dict(calibration, "conformal_calibration.json")
        if bias is not None:
            mlflow.log_dict(bias, "demand_bias_correction.json")

        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = Path(tmpdir) / "model.onnx"
            onnx_path.write_bytes(onnx_bytes)
            # MLflow-native flavor for registry/UI purposes (schema
            # display, parity with `model_import.py`'s `mlflow.pytorch.
            # log_model`) -- the real serving/eval-gate load path reads
            # the `serving/model.onnx` artifact directly via
            # `onnxruntime`, same "portable state, not the native
            # pickle" convention `ml/registry.py`'s own docstring already
            # documents for the `.pt` path.
            mlflow.onnx.log_model(onnx.load(str(onnx_path)), name="model")

            serving_dir = Path(tmpdir) / "serving"
            serving_dir.mkdir(exist_ok=True)
            (serving_dir / "model.onnx").write_bytes(onnx_bytes)
            joblib.dump(feature_scalers, serving_dir / "feature_scalers.joblib")
            joblib.dump(target_scaler, serving_dir / "target_scaler.joblib")
            mlflow.log_artifacts(str(serving_dir), artifact_path="serving")

        run_id = run.info.run_id

    version = register_model(run_id, manifest.model_name)
    return run_id, version


async def _run_onnx_eval_gate(
    model_name: str, version: str, regions: list[str], horizon: int
) -> LiveEvaluationGateResult | None:
    """`model_import.py`'s `_run_eval_gate`, for the ONNX path -- same
    non-fatal-on-failure convention: the version is already registered
    correctly regardless of whether this succeeds."""
    try:
        forecaster: Forecaster = load_registered_onnx_model(model_name, version)
        return await run_live_evaluation_gate(forecaster, model_name, version, regions, horizon)
    except Exception as exc:
        log.error(
            "onnx_import.eval_gate_failed",
            model_name=model_name,
            version=version,
            error=str(exc),
        )
        return None


async def import_onnx_bundle(
    bundle_bytes: bytes,
    *,
    uploaded_filename: str,
    uploaded_by: str | None = None,
    settings: Settings | None = None,
) -> ImportResult:
    """`model_import.py`'s `import_model_bundle`, for ONNX bundles --
    validates entirely before any MLflow call, registers only if every
    stage passes, then runs the live evaluation gate against fresh
    warehouse data."""
    settings = settings or get_settings()

    def _validate_and_register() -> tuple[OnnxBundleManifest, str, ModelVersion]:
        configure_mlflow(settings)
        manifest, onnx_bytes, feature_scalers, target_scaler, calibration, bias = (
            _validate_onnx_bundle(bundle_bytes)
        )
        run_id, version = _register_onnx(
            manifest,
            onnx_bytes,
            feature_scalers,
            target_scaler,
            calibration,
            bias,
            uploaded_filename=uploaded_filename,
            uploaded_by=uploaded_by,
        )
        return manifest, run_id, version

    manifest, run_id, version = await asyncio.to_thread(_validate_and_register)

    eval_gate = await _run_onnx_eval_gate(
        manifest.model_name, version.version, manifest.regions, manifest.horizon
    )

    return ImportResult(
        run_id=run_id,
        model_version=version.version,
        model_name=manifest.model_name,
        architecture=_ARCHITECTURE,
        eval_gate=eval_gate,
    )
