"""ECO-F07: CPU inference optimization.

One of the three options `strategy.md` §5 lists (dynamic quantization,
ONNX Runtime, JIT trace) -- dynamic quantization picked because it's
the one with zero new dependencies (built into `torch` already, unlike
ONNX Runtime) and the one `strategy.md` itself gives a worked example
of for exactly this `{nn.LSTM, nn.Linear}` combination. Applied once,
right after a model is loaded (not per-request) -- quantization is a
one-time transform on the model's weights, not something to redo on
every forecast.

`Settings.inference_optimization` defaults to `"none"`: only turn this
on after the `ECO-P03` benchmark (`scripts/benchmark_inference.py`)
shows it's actually worth the accuracy/latency tradeoff for this
model's size -- a small LSTM may not be slow enough on CPU for the
tradeoff to pay off.
"""

from __future__ import annotations

import torch
from torch import nn

from ..logging import get_logger
from ..settings import ForecastApiSettings
from .model import DemandLSTM

log = get_logger(__name__)


def _select_quantized_engine() -> str:
    """`fbgemm` is the faster choice on the x86 servers this is meant to
    deploy to; `qnnpack` (ARM/mobile-oriented) is the fallback -- e.g.
    every dev machine on Apple Silicon, where `fbgemm` isn't built into
    this project's pinned `torch` wheel at all. Picked at call time,
    not hardcoded, so the same code is correct on both.
    """
    available = torch.backends.quantized.supported_engines
    if "fbgemm" in available:
        return "fbgemm"
    if "qnnpack" in available:
        return "qnnpack"
    raise RuntimeError(f"no usable quantization engine in {available}")


def apply_inference_optimization(
    model: DemandLSTM, settings: ForecastApiSettings
) -> DemandLSTM:
    if settings.inference_optimization == "none":
        return model
    if settings.inference_optimization == "dynamic_quantization":
        torch.backends.quantized.engine = _select_quantized_engine()
        quantized: DemandLSTM = torch.quantization.quantize_dynamic(
            model, {nn.LSTM, nn.Linear}, dtype=torch.qint8
        )
        log.info(
            "optimize.dynamic_quantization_applied",
            engine=torch.backends.quantized.engine,
        )
        return quantized
    raise ValueError(
        f"unknown inference_optimization: {settings.inference_optimization!r}"
    )


__all__ = ["apply_inference_optimization"]
