"""ECO-F04 (hot-reload) + ECO-F08 (rollback safety).

Polls the registry every `model_reload_interval_seconds` for a new
`model_alias` version and atomically swaps the in-memory model
reference so in-flight requests never see a half-loaded model
(`strategy.md` §4, "Synchronization"). Python attribute assignment is
atomic under the GIL, so `routes.py` reading `reloader.state.current`
mid-request can only ever see the old or the new `LoadedModel`, never
a half-constructed one -- no lock needed for the read side.

A freshly loaded candidate must pass a cheap sanity check (a dummy
forward pass producing finite, non-NaN output) before it's swapped in;
a candidate that fails the check is logged and discarded, and the
previous, already-validated model keeps serving (ECO-F08). What
"failed" means beyond NaN output -- a latency regression, say -- is
still an open question (`strategy.md` §7); NaN/Inf output is the one
unambiguous "this model is broken" signal available without a labelled
holdout set on hand at serve time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import torch

from ..logging import get_logger
from ..metrics import record_reload_result
from ..settings import ForecastApiSettings
from .loader import LoadedModel, ModelLoader

log = get_logger(__name__)

# Any positive sequence length works for a finite-output sanity check --
# nn.LSTM has no fixed-length requirement -- so this doesn't need to
# match the real serving lookback.
_SANITY_CHECK_SEQUENCE_LENGTH = 4


def _sanity_check(loaded: LoadedModel) -> bool:
    try:
        x = torch.zeros(1, _SANITY_CHECK_SEQUENCE_LENGTH, loaded.model.n_features)
        with torch.no_grad():
            outputs, _ = loaded.model(x)
        return all(torch.isfinite(v).all().item() for v in outputs.values())
    except Exception as exc:  # noqa: BLE001 - any failure here means "not safe to serve", not a crash
        log.error("reload.sanity_check_error", error=str(exc))
        return False


@dataclass
class ReloadState:
    current: LoadedModel | None = None
    last_reload_at: datetime | None = None
    last_reload_success: bool | None = None
    last_reload_error: str | None = None
    last_check_at: datetime | None = None


class ModelReloader:
    """Owns the currently-served model reference and the background poll
    loop task.
    """

    def __init__(
        self, settings: ForecastApiSettings, loader: ModelLoader | None = None
    ) -> None:
        self.settings = settings
        self.loader = loader or ModelLoader(settings)
        self.state = ReloadState()
        self._task: asyncio.Task[None] | None = None

    async def reload_once(self) -> bool:
        """One reload attempt. Returns True if the served model actually
        changed (new version, passed the sanity check, swapped in).
        """
        self.state.last_check_at = datetime.now(timezone.utc)
        try:
            # load_current() is blocking (MLflow artifact downloads, torch
            # deserialization) -- off the event loop so a reload can't
            # stall in-flight request handling for its duration.
            candidate = await asyncio.to_thread(self.loader.load_current)
        except Exception as exc:  # noqa: BLE001 - a down/unreachable MLflow server (ModelLoadError or a raw connection error) must degrade -- the baseline forecaster keeps serving -- not crash the poll loop or app startup
            self.state.last_reload_success = False
            self.state.last_reload_error = str(exc)
            log.error("reload.load_failed", error=str(exc))
            record_reload_result("failed")
            return False

        if candidate is None:
            record_reload_result("unchanged")
            return False  # nothing registered/aliased yet -- not an error

        if (
            self.state.current is not None
            and candidate.version == self.state.current.version
        ):
            record_reload_result("unchanged")
            return False  # already serving this exact version

        if not _sanity_check(candidate):
            self.state.last_reload_success = False
            self.state.last_reload_error = (
                f"version {candidate.version} failed the post-load sanity check "
                "(non-finite output) -- keeping previous version"
            )
            log.error(
                "reload.sanity_check_failed",
                candidate_version=candidate.version,
                kept_version=self.state.current.version if self.state.current else None,
            )
            record_reload_result("failed")
            return False

        previous_version = self.state.current.version if self.state.current else None
        self.state.current = candidate  # the atomic swap
        self.state.last_reload_at = datetime.now(timezone.utc)
        self.state.last_reload_success = True
        self.state.last_reload_error = None
        log.info(
            "reload.swapped",
            previous_version=previous_version,
            new_version=candidate.version,
        )
        record_reload_result("swapped")
        return True

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.model_reload_interval_seconds)
            try:
                await self.reload_once()
            except Exception as exc:  # noqa: BLE001 - the poll loop must never die from one bad reload attempt
                log.error("reload.poll_loop_error", error=str(exc))

    async def start(self) -> None:
        """Loads once synchronously (so a model is available the moment
        the app finishes starting, not up to `model_reload_interval_seconds`
        later) then starts the background poll loop.
        """
        await self.reload_once()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


__all__ = ["ModelReloader", "ReloadState"]
