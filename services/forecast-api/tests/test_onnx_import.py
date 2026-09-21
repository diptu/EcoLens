from __future__ import annotations

import io
import json
import zipfile

import pytest
import torch
from torch import nn

from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS
from app.service.ml.model_import import BundleValidationError
from app.service.ml.onnx_import import (
    OnnxBundleManifest,
    OnnxBundleValidationError,
    _validate_onnx_bundle,
)

_LOOKBACK = 4
_HORIZON = 3
_FEATURE_COLUMNS = list(FEATURE_COLUMNS[:5])  # a real, proper subset -- exercises that path


class _QuantileNet(nn.Module):
    """The smallest real net that satisfies the (batch, lookback,
    n_features) -> 3x (batch, horizon) quantile3 contract -- not
    `DemandLSTM`, deliberately: proves the import pipeline doesn't
    assume any particular architecture, only the declared I/O shape."""

    def __init__(self, n_features: int, horizon: int) -> None:
        super().__init__()
        self.point = nn.Linear(n_features, horizon)
        self.spread = nn.Linear(n_features, horizon)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        pooled = x.mean(dim=1)
        p50 = self.point(pooled)
        spread = torch.nn.functional.softplus(self.spread(pooled))
        return p50 - spread, p50, p50 + spread


def _export_onnx_bytes(
    n_features: int = len(_FEATURE_COLUMNS),
    horizon: int = _HORIZON,
    lookback: int = _LOOKBACK,
    opset: int = 17,
) -> bytes:
    model = _QuantileNet(n_features, horizon)
    model.eval()
    x = torch.randn(1, lookback, n_features)
    buf = io.BytesIO()
    torch.onnx.export(
        model,
        (x,),
        buf,
        input_names=["x"],
        output_names=["p10", "p50", "p90"],
        dynamic_axes={"x": {0: "batch"}, "p10": {0: "batch"}, "p50": {0: "batch"}, "p90": {0: "batch"}},
        opset_version=opset,
        dynamo=False,
    )
    return buf.getvalue()


def _scaler_json(length: int) -> dict:
    return {"mean": [0.0] * length, "scale": [1.0] * length, "var": [1.0] * length, "n_samples_seen": 100}


def _manifest_dict(**overrides) -> dict:
    base = {
        "manifest_version": 1,
        "model_name": "test-model",
        "lookback": _LOOKBACK,
        "horizon": _HORIZON,
        "feature_columns": _FEATURE_COLUMNS,
        "input_name": "x",
        "output_type": "quantile3",
        "output_names": {"p10": "p10", "p50": "p50", "p90": "p90"},
        "regions": ["NSW1"],
    }
    base.update(overrides)
    return base


def _build_bundle(
    *,
    manifest: dict | None = None,
    onnx_bytes: bytes | None = None,
    regions: list[str] | None = None,
    include_scalers: bool = True,
) -> bytes:
    manifest = manifest if manifest is not None else _manifest_dict()
    regions = regions if regions is not None else manifest["regions"]
    onnx_bytes = onnx_bytes if onnx_bytes is not None else _export_onnx_bytes()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("model.onnx", onnx_bytes)
        if include_scalers:
            feature_scalers = {r: _scaler_json(len(NUMERIC_COLUMNS)) for r in regions}
            target_scaler = {r: _scaler_json(1) for r in regions}
            zf.writestr("feature_scalers.json", json.dumps(feature_scalers))
            zf.writestr("target_scaler.json", json.dumps(target_scaler))
    return buf.getvalue()


class TestManifestParsing:
    def test_missing_required_field_rejected(self):
        bad = _manifest_dict()
        del bad["lookback"]
        with pytest.raises(OnnxBundleValidationError, match="missing required field"):
            OnnxBundleManifest.from_dict(bad)

    def test_bad_model_name_rejected(self):
        with pytest.raises(OnnxBundleValidationError, match="model_name"):
            OnnxBundleManifest.from_dict(_manifest_dict(model_name="../etc/passwd"))

    def test_bad_output_type_rejected(self):
        with pytest.raises(OnnxBundleValidationError, match="output_type"):
            OnnxBundleManifest.from_dict(_manifest_dict(output_type="mean_only"))

    def test_quantile3_missing_output_name_rejected(self):
        with pytest.raises(OnnxBundleValidationError, match="output_names"):
            OnnxBundleManifest.from_dict(
                _manifest_dict(output_names={"p10": "p10", "p50": "p50"})
            )

    def test_point_output_only_needs_point_name(self):
        manifest = OnnxBundleManifest.from_dict(
            _manifest_dict(output_type="point", output_names={"point": "out"})
        )
        assert manifest.output_names == {"point": "out"}

    def test_valid_manifest_parses(self):
        manifest = OnnxBundleManifest.from_dict(_manifest_dict())
        assert manifest.feature_columns == _FEATURE_COLUMNS
        assert manifest.lookback == _LOOKBACK


class TestBundleValidation:
    def test_not_a_zip_rejected(self):
        # Raised by `model_import._open_bundle` (reused, not ONNX-
        # specific) -- the base `BundleValidationError`, not the
        # ONNX-specific subclass. Both are caught identically at the
        # route layer.
        with pytest.raises(BundleValidationError, match="not a valid zip"):
            _validate_onnx_bundle(b"definitely not a zip")

    def test_unknown_feature_column_rejected(self):
        bundle = _build_bundle(
            manifest=_manifest_dict(feature_columns=["not_a_real_column"]),
        )
        with pytest.raises(OnnxBundleValidationError, match="unknown column"):
            _validate_onnx_bundle(bundle)

    def test_duplicate_feature_columns_rejected(self):
        cols = [_FEATURE_COLUMNS[0], _FEATURE_COLUMNS[0]]
        bundle = _build_bundle(manifest=_manifest_dict(feature_columns=cols))
        with pytest.raises(OnnxBundleValidationError, match="duplicates"):
            _validate_onnx_bundle(bundle)

    def test_opset_out_of_range_rejected(self):
        onnx_bytes = _export_onnx_bytes(opset=9)
        bundle = _build_bundle(onnx_bytes=onnx_bytes)
        with pytest.raises(OnnxBundleValidationError, match="opset"):
            _validate_onnx_bundle(bundle)

    def test_input_shape_mismatch_rejected(self):
        # Graph really has 3 features; manifest declares 5 -- must be caught.
        onnx_bytes = _export_onnx_bytes(n_features=3)
        bundle = _build_bundle(onnx_bytes=onnx_bytes)
        with pytest.raises(OnnxBundleValidationError, match="dim 2"):
            _validate_onnx_bundle(bundle)

    def test_declared_output_missing_from_graph_rejected(self):
        bundle = _build_bundle(
            manifest=_manifest_dict(
                output_names={"p10": "p10", "p50": "p50", "p90": "does_not_exist"}
            ),
        )
        with pytest.raises(OnnxBundleValidationError, match="does_not_exist"):
            _validate_onnx_bundle(bundle)

    def test_missing_scalers_rejected(self):
        # Raised by `model_import._read_member` (reused) -- base class,
        # same reasoning as `test_not_a_zip_rejected` above.
        bundle = _build_bundle(include_scalers=False)
        with pytest.raises(BundleValidationError, match="feature_scalers.json"):
            _validate_onnx_bundle(bundle)

    def test_scaler_missing_region_rejected(self):
        # Raised by `model_import._scalers_from_json` (reused) -- base class.
        bundle = _build_bundle(regions=["QLD1"])  # manifest still says NSW1
        with pytest.raises(BundleValidationError, match="NSW1"):
            _validate_onnx_bundle(bundle)

    def test_valid_bundle_passes(self):
        bundle = _build_bundle()
        manifest, onnx_bytes, feature_scalers, target_scaler, calibration, bias = (
            _validate_onnx_bundle(bundle)
        )
        assert manifest.model_name == "test-model"
        assert onnx_bytes
        assert set(feature_scalers) == {"NSW1"}
        assert set(target_scaler) == {"NSW1"}
        assert calibration is None
        assert bias is None

    def test_point_output_bundle_passes(self):
        model = nn.Sequential(nn.Linear(len(_FEATURE_COLUMNS), _HORIZON))
        model.eval()
        x = torch.randn(1, _LOOKBACK, len(_FEATURE_COLUMNS))

        class _PointWrapper(nn.Module):
            def __init__(self, m):
                super().__init__()
                self.m = m

            def forward(self, x):
                pooled = x.mean(dim=1)
                return self.m(pooled)

        wrapper = _PointWrapper(model)
        buf = io.BytesIO()
        torch.onnx.export(
            wrapper, (x,), buf, input_names=["x"], output_names=["out"],
            dynamic_axes={"x": {0: "batch"}, "out": {0: "batch"}},
            opset_version=17, dynamo=False,
        )
        bundle = _build_bundle(
            manifest=_manifest_dict(output_type="point", output_names={"point": "out"}),
            onnx_bytes=buf.getvalue(),
        )
        manifest, *_rest = _validate_onnx_bundle(bundle)
        assert manifest.output_type == "point"


class TestNaNOutputRejected:
    def test_non_finite_sanity_check_output_rejected(self):
        """A model whose bias makes a zero-valued dummy input produce
        NaN (via a 0/0-shaped division) -- the sanity check's job is to
        catch exactly this before anything registers."""

        class _NanNet(nn.Module):
            def forward(self, x: torch.Tensor):
                pooled = x.mean(dim=1)
                # sum(pooled, dim=1) is 0.0 for the all-zero dummy input
                # the sanity check feeds in -- 0.0 / 0.0 is a real NaN,
                # not a synthetic injection.
                bad = pooled.sum(dim=1, keepdim=True) / pooled.sum(dim=1, keepdim=True)
                p50 = bad.expand(-1, _HORIZON) * 0 + bad
                return p50, p50, p50

        model = _NanNet()
        model.eval()
        x = torch.randn(1, _LOOKBACK, len(_FEATURE_COLUMNS))
        buf = io.BytesIO()
        torch.onnx.export(
            model, (x,), buf, input_names=["x"], output_names=["p10", "p50", "p90"],
            dynamic_axes={"x": {0: "batch"}}, opset_version=17, dynamo=False,
        )
        bundle = _build_bundle(onnx_bytes=buf.getvalue())
        with pytest.raises(OnnxBundleValidationError, match="non-finite"):
            _validate_onnx_bundle(bundle)
