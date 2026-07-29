"""Frozen wrapper around Google's TimesFM foundation model -- root
TODO.md's "Stand up TimesFM: Frozen transformer backbone, head-only
training."

TimesFM (`timesfm[torch]`, `google/timesfm-2.5-200m-pytorch`, ~2GB via
Hugging Face Hub) is pretrained, not trained by this repo. Its real
`nn.Module` has a genuine 20-layer transformer stack, but the only
*public, documented* way to run it is the no-grad `forecast()` call below
-- there's no supported gradient-fine-tuning API, and reconstructing its
undocumented internal patch/RevIN/decode-cache forward pass by hand would
risk a subtly wrong reimplementation of Google's model for no real
benefit. So this wrapper does exactly one thing: load the checkpoint once,
run the safe public API, hand back raw MW-scale point/quantile forecasts.
Everything trainable in this repo's TimesFM path lives one layer up, in
`model/timesfm_head.py`'s `TimesFMCalibrationHead` -- this module never
computes a gradient.

`TimesFMBackbone` is a `Protocol` (not a base class) so tests can swap in
a fake, instant implementation instead of downloading/running the real
2GB model -- see `training/train_timesfm.py`'s `backbone` parameter.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


class TimesFMBackbone(Protocol):
    def forecast_raw(
        self, contexts: np.ndarray, *, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`contexts`: `(n, context_len)`, raw MW-scale `demand_mw` history
        (TimesFM does its own internal normalization -- never pass
        pre-scaled input). Returns `(p10, p50, p90)`, each `(n, horizon)`,
        raw MW scale.
        """
        ...


class FrozenTimesFM:
    """Lazily loads the real pretrained checkpoint on first `forecast_raw`
    call, not at construction/import time -- importing this module (or
    building an unused instance) never triggers the ~2GB download.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # `Any` since `timesfm` ships no py.typed marker/stubs (see root
        # pyproject.toml's mypy override) -- mypy can't meaningfully check
        # its internals either way.
        self._model: Any = None
        self._compiled_horizon: int | None = None

    def _ensure_loaded(self, *, context_len: int, horizon: int) -> None:
        import timesfm

        if self._model is None:
            log.info("timesfm_backbone.loading", repo_id=self.settings.timesfm_repo_id)
            self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                self.settings.timesfm_repo_id
            )
            log.info("timesfm_backbone.loaded", repo_id=self.settings.timesfm_repo_id)

        # compile() fixes max_context/max_horizon for the compiled decode
        # path -- recompile if a caller ever asks for a bigger horizon than
        # what's currently compiled (not expected in normal use, since this
        # repo always calls with the same settings.model_horizon, but safe
        # rather than silently truncating).
        if self._compiled_horizon is None or horizon > self._compiled_horizon:
            self._model.compile(
                timesfm.ForecastConfig(
                    max_context=context_len,
                    max_horizon=horizon,
                    per_core_batch_size=self.settings.timesfm_per_core_batch_size,
                    normalize_inputs=True,
                    fix_quantile_crossing=True,
                )
            )
            self._compiled_horizon = horizon

    def forecast_raw(
        self, contexts: np.ndarray, *, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`contexts`: `(n, context_len)` raw MW-scale history. Returns
        `(p10, p50, p90)`, each `(n, horizon)`, raw MW scale -- built only
        on the public `forecast()` call, batched internally by the library
        itself (a single call handles the whole `contexts` array; TimesFM's
        own `per_core_batch_size` config controls its internal batching).
        """
        self._ensure_loaded(context_len=contexts.shape[1], horizon=horizon)

        inputs = [row for row in contexts]
        point, quantiles = self._model.forecast(horizon=horizon, inputs=inputs)
        # quantiles: (n, horizon, 9) for [0.1, 0.2, ..., 0.9] -- confirmed
        # against TimesFM_2p5_200M_Definition.quantiles; index 0 = P10,
        # index 8 = P90. `point` (already separated by the library) is P50.
        p10 = quantiles[..., 0]
        p90 = quantiles[..., -1]
        return p10, point, p90


__all__ = ["TimesFMBackbone", "FrozenTimesFM"]
