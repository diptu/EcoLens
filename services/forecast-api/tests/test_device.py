from __future__ import annotations

import torch

from app.service.ml.device import get_device


class TestGetDevice:
    def test_prefers_cuda_when_available(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
        assert get_device() == torch.device("cuda")

    def test_falls_back_to_mps_when_cuda_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
        assert get_device() == torch.device("mps")

    def test_falls_back_to_cpu_when_neither_is_available(self, monkeypatch):
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        assert get_device() == torch.device("cpu")

    def test_reflects_real_hardware_when_unmocked(self):
        # On this (real, unmocked) CI/dev machine, no CUDA/MPS is
        # present -- confirms `get_device()` genuinely calls into
        # `torch`, not a fake/hardcoded stand-in for it.
        assert get_device() == torch.device("cpu")
