"""Real CUDA/MPS/CPU device selection for the training loops in
`ml/train.py`, `ml/train_tft.py`, and `ml/train_energy_forecast.py`
(`TODO.md` Forecasting Phase 1's "ML & Deep Learning Environment" --
until this module, no training/inference code anywhere in this service
ever called `.to(device)`, so every run was CPU-only regardless of
whether a GPU was actually available on the training host).

Deliberately not wired into the *serving* path
(`ml/registry.py`/`ml/energy_registry.py`/`ml/evaluate.py`/
`ml/divergence.py`/`ml/incremental*.py`'s warm-start loaders): those all
load weights with `map_location=torch.device("cpu")` by design
(`docs/training-strategy.md`'s "Model Portability Strategy") and run
inference for a single request at a time -- a GPU round-trip isn't worth
it at that scale, and would reintroduce the exact device-placement
bugs this module exists to avoid, on every request instead of once per
training run.
"""

from __future__ import annotations

import torch


def get_device() -> torch.device:
    """CUDA if available, else Apple Silicon's MPS backend, else CPU.
    Checked in this order since a machine that has both an Nvidia GPU
    and is running on Apple Silicon is not a real combination -- the
    order only matters for `torch.backends.mps.is_available()` itself
    being safe to call on a non-macOS build (it is: always `False`
    there)."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
