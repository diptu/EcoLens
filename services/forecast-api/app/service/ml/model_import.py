"""Manual model-bundle import -- lets an operator hand this service an
already-trained LSTM/TFT checkpoint (trained anywhere: a notebook, a
different machine, a one-off experiment) and have it enter the exact
same MLflow registry / serving path `ml/train.py`'s
`log_and_register_run` already produces, so `load_registered_model`/
`load_registered_tft_model` and everything downstream of them
(evaluation, promotion, `/v1/forecast`) need zero changes to serve an
uploaded version indistinguishably from a trained one.

Deliberately open, no auth (matches `api/v1/model/routes.py`'s own
"deliberately open, no auth required... triggering work isn't a
privileged action in this platform's current scope" convention for
every other mutating route in that router). Registration always lands
in the `None` stage, same as every other path -- nothing here
auto-promotes -- and the live evaluation gate still runs against fresh
warehouse data immediately after registration, exactly as it does for a
freshly-trained incremental version (`training_worker._run_live_
evaluation_gate`), so a bad upload is flagged the same way a bad
training run would be.

Bundle format
-------------
A zip file containing:

    manifest.json          -- architecture + hyperparams + feature
                               fingerprint, see `BundleManifest`.
    model_state_dict.pt     -- `torch.save(model.state_dict())`, read
                               back with `weights_only=True` (never
                               `False`) -- the same restricted unpickler
                               every existing loader in this codebase
                               already trusts for this exact file
                               (`ml/evaluate.py`'s `_load_registered_run_
                               artifacts`), so accepting an uploaded one
                               doesn't lower the bar this service
                               already accepts internally. PyTorch's
                               weights-only unpickler only reconstructs
                               tensors/basic types, not arbitrary
                               objects -- the classic pickle
                               remote-code-execution vector doesn't
                               apply to this specific file.
    feature_scalers.json    -- per-region `{region: {mean, scale, var,
                               n_samples_seen}}`, plain JSON, NOT
                               `joblib`/pickle. This is the one place a
                               naive "just accept whatever the uploader
                               sends" design would be a real RCE hole:
                               `joblib.load` (what every existing loader
                               uses for its OWN, self-produced
                               artifacts) is full pickle underneath with
                               no restricted-unpickling option, unlike
                               `torch.load(weights_only=True)` above.
                               Scalers are reconstructed here by setting
                               `StandardScaler` attributes directly from
                               plain numbers -- `pickle.loads` never runs
                               on uploader-controlled bytes anywhere in
                               this module.
    target_scaler.json      -- same shape as `feature_scalers.json`
                               (each region's `mean`/`scale`/`var` are
                               length-1 arrays -- one target column).
    conformal_calibration.json / demand_bias_correction.json -- optional,
                               already-plain-JSON (the same format
                               `ml/train.py`'s `log_and_register_run`
                               already writes via `mlflow.log_dict`) --
                               passed through as-is if present.

`import_model_bundle` validates the bundle end-to-end (feature-set
fingerprint, per-region scaler shape, a strict `load_state_dict`, a
dummy-input inference sanity check) BEFORE any MLflow call -- a bad
upload fails loudly with a real reason (`BundleValidationError`), never
a half-registered version.
"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import joblib
import mlflow
import mlflow.pytorch
import numpy as np
import torch
from mlflow.entities.model_registry import ModelVersion
from sklearn.preprocessing import StandardScaler

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.ml import DemandLSTM
from app.models.tft import DemandTFT
from app.service.ml.evaluate import (
    Forecaster,
    LiveEvaluationGateResult,
    load_registered_model,
    load_registered_tft_model,
    run_live_evaluation_gate,
)
from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS
from app.service.mlops.registry import register_model
from app.service.mlops.tracking import configure_mlflow, git_sha

log = get_logger(__name__)

#: Identifies which `FEATURE_COLUMNS` shape a bundle was built against --
#: this service's own feature engineering is a hand-tuned, evolving
#: pipeline (`ml/features.py`'s own docstring: "kept in sync by hand"),
#: so a bundle trained against a stale/foreign feature set must be
#: rejected loudly. A same-count-different-meaning mismatch (a reordered
#: or substituted column) would otherwise pass `load_state_dict` (shapes
#: still line up) and silently produce nonsense predictions -- this
#: fingerprint is what actually catches that.
FEATURE_FINGERPRINT = ",".join(FEATURE_COLUMNS)

_ARCHITECTURES = ("lstm", "tft")

MODEL_NAMES: dict[str, str] = {
    "lstm": "lstm_demand",
    "tft": "lstm_demand_tft",
}


class BundleValidationError(ValueError):
    """A bundle failed validation before anything was registered -- the
    HTTP route maps this straight to a 422: a malformed/incompatible
    upload, not a server fault."""


@dataclass
class ImportResult:
    run_id: str
    model_version: str
    model_name: str
    architecture: str
    #: `None` when the gate itself failed to run (logged, non-fatal --
    #: see `_run_eval_gate`), not when it ran and failed (`passed=False`
    #: on the result itself covers that case).
    eval_gate: LiveEvaluationGateResult | None


@dataclass
class BundleManifest:
    architecture: str
    horizon: int
    lookback: int
    hidden_size: int
    num_layers: int
    dropout: float
    regions: list[str]
    feature_fingerprint: str
    n_heads: int | None = None
    n_encoder_features: int | None = None
    n_decoder_features: int | None = None
    source_note: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "BundleManifest":
        _require("architecture" in data, "manifest.json missing 'architecture'")
        architecture = data["architecture"]
        _require(
            architecture in _ARCHITECTURES,
            f"unsupported architecture {architecture!r} -- must be one of {_ARCHITECTURES}",
        )
        try:
            fields: dict[str, object] = dict(
                architecture=architecture,
                horizon=int(data["horizon"]),
                lookback=int(data["lookback"]),
                hidden_size=int(data["hidden_size"]),
                num_layers=int(data.get("num_layers", 2)),
                dropout=float(data.get("dropout", 0.2)),
                regions=list(data["regions"]),
                feature_fingerprint=str(data["feature_fingerprint"]),
                source_note=data.get("source_note"),
            )
        except KeyError as exc:
            raise BundleValidationError(
                f"manifest.json missing required field: {exc}"
            ) from exc

        if architecture == "tft":
            try:
                fields["n_heads"] = int(data.get("n_heads", 4))
                fields["n_encoder_features"] = int(data["n_encoder_features"])
                fields["n_decoder_features"] = int(data["n_decoder_features"])
            except KeyError as exc:
                raise BundleValidationError(
                    f"manifest.json missing required TFT field: {exc}"
                ) from exc

        return cls(**fields)  # type: ignore[arg-type]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleValidationError(message)


def _open_bundle(bundle_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(bundle_bytes))
    except zipfile.BadZipFile as exc:
        raise BundleValidationError("not a valid zip file") from exc


def _read_member(zf: zipfile.ZipFile, name: str, *, required: bool = True) -> bytes | None:
    if name not in zf.namelist():
        _require(not required, f"bundle missing required file: {name}")
        return None
    return zf.read(name)


def _scaler_from_json(data: dict, *, expected_len: int, label: str) -> StandardScaler:
    """Reconstructs a fitted `StandardScaler` from plain JSON numbers --
    never `pickle`/`joblib.load` on uploader-controlled bytes (see this
    module's own docstring for why that distinction matters here).
    Setting these attributes directly is exactly what `StandardScaler.
    fit` itself computes and stores -- nothing else about a fitted
    instance affects `.transform()`/`.inverse_transform()`."""
    try:
        mean = np.array(data["mean"], dtype=np.float64)
        scale = np.array(data["scale"], dtype=np.float64)
        var = np.array(data["var"], dtype=np.float64)
        n_samples_seen = int(data["n_samples_seen"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BundleValidationError(f"{label}: malformed scaler entry ({exc})") from exc

    _require(
        mean.shape == scale.shape == var.shape == (expected_len,),
        f"{label}: expected {expected_len} value(s) per field, got "
        f"mean={mean.shape}, scale={scale.shape}, var={var.shape}",
    )

    scaler = StandardScaler()
    scaler.mean_ = mean
    scaler.scale_ = scale
    scaler.var_ = var
    scaler.n_samples_seen_ = n_samples_seen
    scaler.n_features_in_ = expected_len
    return scaler


def _scalers_from_json(
    raw: bytes, *, expected_len: int, regions: list[str], label: str
) -> dict[str, StandardScaler]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BundleValidationError(f"{label} is not valid JSON: {exc}") from exc
    _require(
        bool(isinstance(data, dict) and data),
        f"{label} must be a non-empty object keyed by region",
    )
    for region in regions:
        _require(region in data, f"{label} missing region {region!r}")
    return {
        region: _scaler_from_json(entry, expected_len=expected_len, label=f"{label}[{region!r}]")
        for region, entry in data.items()
    }


def _build_model(manifest: BundleManifest) -> torch.nn.Module:
    if manifest.architecture == "lstm":
        return DemandLSTM(
            n_features=len(FEATURE_COLUMNS),
            horizon=manifest.horizon,
            hidden_size=manifest.hidden_size,
            num_layers=manifest.num_layers,
            dropout=manifest.dropout,
        )
    assert manifest.architecture == "tft"  # nosec B101 -- from_dict already restricted to _ARCHITECTURES
    assert manifest.n_encoder_features is not None  # nosec B101 -- set by from_dict's tft branch
    assert manifest.n_decoder_features is not None  # nosec B101 -- set by from_dict's tft branch
    assert manifest.n_heads is not None  # nosec B101 -- set by from_dict's tft branch
    return DemandTFT(
        n_encoder_features=manifest.n_encoder_features,
        n_decoder_features=manifest.n_decoder_features,
        horizon=manifest.horizon,
        hidden_size=manifest.hidden_size,
        n_heads=manifest.n_heads,
        dropout=manifest.dropout,
    )


def _sanity_check_inference(model: torch.nn.Module, manifest: BundleManifest) -> None:
    """Real forward pass on zero-valued dummy input, matching each
    architecture's exact training-time input shape -- catches a bundle
    whose weights load (shapes match) but whose forward pass itself is
    broken or produces a nonsensical (non-finite, or non-monotonic
    P10/P50/P90) output, before it's ever registered."""
    model.eval()
    with torch.no_grad():
        if manifest.architecture == "lstm":
            x = torch.zeros(1, manifest.lookback, len(FEATURE_COLUMNS))
            out = model(x)
        else:
            assert manifest.n_encoder_features is not None  # nosec B101 -- see _build_model
            assert manifest.n_decoder_features is not None  # nosec B101 -- see _build_model
            x_enc = torch.zeros(1, manifest.lookback, manifest.n_encoder_features)
            x_dec = torch.zeros(1, manifest.horizon, manifest.n_decoder_features)
            out = model(x_enc, x_dec)

    _require(
        tuple(out.p50.shape) == (1, manifest.horizon),
        f"model produced output shape {tuple(out.p50.shape)}, expected (1, {manifest.horizon})",
    )
    p10, p50, p90 = out.p10.numpy(), out.p50.numpy(), out.p90.numpy()
    _require(
        bool(np.all(np.isfinite(p10)) and np.all(np.isfinite(p50)) and np.all(np.isfinite(p90))),
        "model produced non-finite output on a dummy-input sanity check",
    )
    _require(
        bool(np.all(p10 <= p50 + 1e-6) and np.all(p50 <= p90 + 1e-6)),
        "model output violates p10<=p50<=p90 on a dummy-input sanity check",
    )


def _validate_bundle(
    bundle_bytes: bytes,
) -> tuple[
    BundleManifest,
    torch.nn.Module,
    dict[str, StandardScaler],
    dict[str, StandardScaler],
    dict | None,
    dict | None,
]:
    zf = _open_bundle(bundle_bytes)

    manifest_raw = _read_member(zf, "manifest.json")
    assert manifest_raw is not None  # nosec B101 -- required=True default above
    try:
        manifest_dict = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise BundleValidationError(f"manifest.json is not valid JSON: {exc}") from exc
    manifest = BundleManifest.from_dict(manifest_dict)

    _require(len(manifest.regions) > 0, "manifest.json 'regions' must be non-empty")
    _require(
        manifest.feature_fingerprint == FEATURE_FINGERPRINT,
        "feature_fingerprint does not match this service's current FEATURE_COLUMNS -- "
        "this bundle was trained against a different/stale feature set",
    )

    state_dict_bytes = _read_member(zf, "model_state_dict.pt")
    assert state_dict_bytes is not None  # nosec B101 -- required=True default above
    try:
        # weights_only=True: PyTorch's restricted unpickler only ever
        # reconstructs tensors/basic types from this file -- see this
        # module's own docstring for why that makes an *uploaded*
        # state_dict no less safe than the ones this codebase already
        # loads this same way from its own MLflow-logged runs.
        state_dict = torch.load(
            io.BytesIO(state_dict_bytes),
            map_location=torch.device("cpu"),
            weights_only=True,
        )
    except Exception as exc:
        raise BundleValidationError(f"model_state_dict.pt failed to load: {exc}") from exc

    model = _build_model(manifest)
    try:
        model.load_state_dict(state_dict, strict=True)
    except Exception as exc:
        raise BundleValidationError(
            "model_state_dict.pt is incompatible with the declared architecture/"
            f"hyperparams: {exc}"
        ) from exc
    model.eval()

    _sanity_check_inference(model, manifest)

    feature_scalers_raw = _read_member(zf, "feature_scalers.json")
    target_scaler_raw = _read_member(zf, "target_scaler.json")
    assert feature_scalers_raw is not None  # nosec B101 -- required=True default above
    assert target_scaler_raw is not None  # nosec B101 -- required=True default above
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
            raise BundleValidationError(
                f"conformal_calibration.json is not valid JSON: {exc}"
            ) from exc

    bias: dict | None = None
    bias_raw = _read_member(zf, "demand_bias_correction.json", required=False)
    if bias_raw is not None:
        try:
            bias = json.loads(bias_raw)
        except json.JSONDecodeError as exc:
            raise BundleValidationError(
                f"demand_bias_correction.json is not valid JSON: {exc}"
            ) from exc

    return manifest, model, feature_scalers, target_scaler, calibration, bias


def _register(
    manifest: BundleManifest,
    model: torch.nn.Module,
    feature_scalers: dict[str, StandardScaler],
    target_scaler: dict[str, StandardScaler],
    calibration: dict | None,
    bias: dict | None,
    *,
    uploaded_filename: str,
    uploaded_by: str | None,
) -> tuple[str, ModelVersion]:
    """Writes the exact `serving/` artifact layout `ml/evaluate.py`'s
    `_load_registered_run_artifacts` already expects (same filenames,
    same `mlflow.log_dict` calendar-JSON convention for calibration/bias
    -- see `ml/train.py`'s `log_and_register_run`, this is its
    upload-path counterpart), then registers the run in the `None`
    stage -- promoting is always a separate, deliberately-gated step,
    same as every other path in this codebase."""
    model_name = MODEL_NAMES[manifest.architecture]

    with mlflow.start_run() as run:
        params: dict[str, object] = {
            "horizon": manifest.horizon,
            "lookback": manifest.lookback,
            "hidden_size": manifest.hidden_size,
            "num_layers": manifest.num_layers,
            "dropout": manifest.dropout,
            "n_features": len(FEATURE_COLUMNS),
            "regions": ",".join(manifest.regions),
        }
        if manifest.architecture == "tft":
            params["n_heads"] = manifest.n_heads
            params["n_encoder_features"] = manifest.n_encoder_features
            params["n_decoder_features"] = manifest.n_decoder_features
        mlflow.log_params(params)

        tags = {
            "git_sha": git_sha() or "unknown",
            "architecture": manifest.architecture,
            # Real provenance signal (this feature's own reason for
            # existing) -- lets a human reviewing the registry tell an
            # uploaded version apart from one this service's own
            # training loop produced, same governance pattern
            # `services/waerehouse`'s dbt `trigger`/`triggered_by` tags
            # already establish for build provenance.
            "source": "manual_upload",
            "uploaded_filename": uploaded_filename,
        }
        if uploaded_by:
            tags["uploaded_by"] = uploaded_by
        if manifest.source_note:
            tags["source_note"] = manifest.source_note[:250]
        mlflow.set_tags(tags)

        if calibration is not None:
            mlflow.log_dict(calibration, "conformal_calibration.json")
        if bias is not None:
            mlflow.log_dict(bias, "demand_bias_correction.json")

        # Same "logged twice" convention `log_and_register_run` documents:
        # the MLflow-native pickle (registry/pyfunc support) plus a plain
        # state_dict under `serving/` that `forecast-api`'s own loaders
        # actually read at inference time.
        mlflow.pytorch.log_model(model, artifact_path="model", serialization_format="pickle")

        with tempfile.TemporaryDirectory() as tmpdir:
            joblib.dump(feature_scalers, Path(tmpdir) / "feature_scalers.joblib")
            joblib.dump(target_scaler, Path(tmpdir) / "target_scaler.joblib")
            torch.save(model.state_dict(), Path(tmpdir) / "model_state_dict.pt")
            mlflow.log_artifacts(tmpdir, artifact_path="serving")

        run_id = run.info.run_id

    version = register_model(run_id, model_name)
    return run_id, version


async def _run_eval_gate(
    architecture: str, model_name: str, version: str, regions: list[str]
) -> LiveEvaluationGateResult | None:
    """Runs the live walk-forward gate against fresh warehouse data
    immediately after registration -- same non-fatal-on-failure
    convention `training_worker._run_live_evaluation_gate` already
    established for freshly-trained incremental versions: the version
    is already registered correctly in the `None` stage regardless, it
    just won't have an `eval_gate_passed` tag for `promote_version` to
    consult if this fails. Loads the version back through the exact
    same `load_registered_model`/`load_registered_tft_model` path any
    other consumer would use, rather than reusing the in-memory model --
    a stronger end-to-end check that the artifacts this run just wrote
    are genuinely readable, not just that the in-memory objects were
    valid before they were serialized."""
    try:
        forecaster: Forecaster
        if architecture == "tft":
            tft_forecaster = load_registered_tft_model(model_name, version)
            forecaster, horizon = tft_forecaster, tft_forecaster.model.horizon
        else:
            lstm_forecaster = load_registered_model(model_name, version)
            forecaster, horizon = lstm_forecaster, lstm_forecaster.model.horizon
        return await run_live_evaluation_gate(forecaster, model_name, version, regions, horizon)
    except Exception as exc:
        log.error(
            "model_import.eval_gate_failed",
            model_name=model_name,
            version=version,
            error=str(exc),
        )
        return None


async def import_model_bundle(
    bundle_bytes: bytes,
    *,
    uploaded_filename: str,
    uploaded_by: str | None = None,
    settings: Settings | None = None,
) -> ImportResult:
    """Validates `bundle_bytes` end-to-end, then -- only if every check
    passes -- registers it and immediately runs the live evaluation
    gate. Raises `BundleValidationError` for anything wrong with the
    bundle itself; never partially registers (validation happens
    entirely before the first MLflow call, all inside the same
    `asyncio.to_thread` offload `ml/train.py`'s `train_and_register`
    already uses for its own CPU-bound MLflow logging)."""
    settings = settings or get_settings()

    def _validate_and_register() -> tuple[BundleManifest, str, ModelVersion]:
        configure_mlflow(settings)
        manifest, model, feature_scalers, target_scaler, calibration, bias = _validate_bundle(
            bundle_bytes
        )
        run_id, version = _register(
            manifest,
            model,
            feature_scalers,
            target_scaler,
            calibration,
            bias,
            uploaded_filename=uploaded_filename,
            uploaded_by=uploaded_by,
        )
        return manifest, run_id, version

    manifest, run_id, version = await asyncio.to_thread(_validate_and_register)
    model_name = MODEL_NAMES[manifest.architecture]

    eval_gate = await _run_eval_gate(
        manifest.architecture, model_name, version.version, manifest.regions
    )

    return ImportResult(
        run_id=run_id,
        model_version=version.version,
        model_name=model_name,
        architecture=manifest.architecture,
        eval_gate=eval_gate,
    )
