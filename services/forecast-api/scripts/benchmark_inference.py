"""ECO-P03: benchmark the CPU inference optimization ECO-F07 picked
(dynamic quantization) against the plain fp32 model -- p50/p99 latency
and RSS memory -- before it ships as the default.

Standalone script, not a pytest test: benchmarks are about measured
numbers on real hardware, not pass/fail assertions that would be
meaningless (or flaky) run-to-run and machine-to-machine.

Usage:
    cd services/forecast-api
    uv run python scripts/benchmark_inference.py [--iterations 200] [--hidden-size 128]
"""

from __future__ import annotations

import argparse
import gc
import os
import statistics
import time

import torch

from ecolens_forecast_api.forecasting.model import DemandLSTM
from ecolens_forecast_api.forecasting.optimize import apply_inference_optimization
from ecolens_forecast_api.settings import ForecastApiSettings

LOOKBACK = 48
N_FEATURES = 24


def _rss_mb() -> float:
    """Current process resident memory, in MB. `/proc`-free (works on
    macOS dev machines, not just Linux containers) via `resource`.
    """
    import resource

    # ru_maxrss is KB on Linux, bytes on macOS -- normalize to MB either way.
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 1024 if os.uname().sysname == "Linux" else raw / (1024 * 1024)


def _bench(model: DemandLSTM, *, iterations: int) -> dict[str, float]:
    model.eval()
    x = torch.randn(1, LOOKBACK, N_FEATURES)

    with (
        torch.no_grad()
    ):  # warmup, not measured -- first call pays one-time lazy-init cost
        for _ in range(5):
            model(x)

    latencies_ms = []
    with torch.no_grad():
        for _ in range(iterations):
            start = time.perf_counter()
            model(x)
            latencies_ms.append((time.perf_counter() - start) * 1000)

    latencies_ms.sort()
    return {
        "p50_ms": statistics.median(latencies_ms),
        "p99_ms": latencies_ms[int(len(latencies_ms) * 0.99)],
        "mean_ms": statistics.mean(latencies_ms),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--num-layers", type=int, default=2)
    args = parser.parse_args()

    fp32_model = DemandLSTM(
        n_features=N_FEATURES,
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
        horizon=48,
    )

    gc.collect()
    rss_before_fp32 = _rss_mb()
    fp32_result = _bench(fp32_model, iterations=args.iterations)
    rss_after_fp32 = _rss_mb()

    quantized_settings = ForecastApiSettings(
        inference_optimization="dynamic_quantization"
    )  # type: ignore[call-arg]
    quantized_model = apply_inference_optimization(fp32_model, quantized_settings)

    gc.collect()
    rss_before_quant = _rss_mb()
    quant_result = _bench(quantized_model, iterations=args.iterations)
    rss_after_quant = _rss_mb()

    print(f"{'':20} {'fp32':>12} {'quantized':>12}")
    print(
        f"{'p50 latency (ms)':20} {fp32_result['p50_ms']:>12.3f} {quant_result['p50_ms']:>12.3f}"
    )
    print(
        f"{'p99 latency (ms)':20} {fp32_result['p99_ms']:>12.3f} {quant_result['p99_ms']:>12.3f}"
    )
    print(
        f"{'mean latency (ms)':20} {fp32_result['mean_ms']:>12.3f} {quant_result['mean_ms']:>12.3f}"
    )
    print(
        f"{'peak RSS delta (MB)':20} "
        f"{rss_after_fp32 - rss_before_fp32:>12.2f} "
        f"{rss_after_quant - rss_before_quant:>12.2f}"
    )
    speedup = (
        fp32_result["p50_ms"] / quant_result["p50_ms"]
        if quant_result["p50_ms"]
        else float("nan")
    )
    print(f"\np50 speedup: {speedup:.2f}x")
    print(
        "\nInterpretation: if speedup is meaningfully > 1 (and RSS didn't "
        "regress), set FORECAST_INFERENCE_OPTIMIZATION=dynamic_quantization. "
        "If it's close to 1x, this model is small enough that plain fp32 is "
        "simpler and just as fast -- leave the default ('none')."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
