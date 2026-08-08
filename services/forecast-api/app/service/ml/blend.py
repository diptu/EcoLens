"""Multi-model blend (`todo-model-training.md` Phase 3) — combines P10/
P50/P90 forecasts from however many real experts are currently loaded,
via inverse-recent-error weighting.

**Decision recorded** (Phase 3's own explicit decision point): inverse-
recent-error weighting, not fixed learned stacking weights or best-of-
recent selection. Reasons, matching the plan's own framing: it's the
only one of the three options that actually adapts *which* expert
"wins" as conditions change (a fixed stacking weight is static until
manually retrained; best-of-recent throws away the benefit of properly
combining P10/P90 bands across models) — closest to the spec's
"continuously adapt... to handle sudden load shifts" language for the
blend layer itself.

**How "recent error" is computed, real not fabricated:** `BlendForecaster`
(below) needs each expert's *recent* accuracy to weight it, but nothing
external tracks that yet (Phase 8's `mlops/drift.py`/a live-serving error
feed doesn't exist). Rather than inventing a fake number, `predict`
re-forecasts each expert from `window` earlier points *within the
`history` it was already given* and compares against the real outcomes
`history` already contains for those (now-past) points -- genuinely
computed from real data, no new state, no harness changes (matches
`evaluate.py`'s own design promise that a new `Forecaster` needs zero
harness changes). This does mean each `BlendForecaster.predict` call
re-runs every sub-expert `window+1` times, not once -- real cost,
documented rather than hidden; keep `window` small for expensive experts
(e.g. `TimesFMForecaster`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.service.ml.evaluate import Forecaster
from app.service.ml.features import TARGET_COLUMN


def blend_forecasts(
    predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    recent_mapes: dict[str, float],
    epsilon: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    """Combine each expert's `(p10, p50, p90)` via inverse-recent-MAPE
    weighting: `weight_i = (1 / (mape_i + epsilon)) / sum_j(...)`. Both
    dicts must share the same keys (expert names). Returns `(p10, p50,
    p90, weights)` — `weights` is real and returned (not just used
    internally) so a caller (the dashboard, a `served_by`-style field)
    can report which experts are actually contributing right now, not
    just the combined number.

    Gracefully degrades to one expert (weight 1.0) -- the blend layer
    stays useful even if only one architecture is currently loaded,
    matching this phase's "doesn't have to all land before the blend
    layer is useful" framing. Raises on an empty `predictions` -- a
    blend over zero experts is a caller bug (the caller should simply
    not invoke the blend layer in that case), not a valid "no blend"
    state to silently paper over.
    """
    if not predictions:
        raise ValueError("blend_forecasts requires at least one expert's predictions")
    if set(predictions) != set(recent_mapes):
        raise ValueError(
            f"predictions and recent_mapes must share the same expert names -- "
            f"got {sorted(predictions)} vs {sorted(recent_mapes)}"
        )

    names = list(predictions)
    if len(names) == 1:
        name = names[0]
        p10, p50, p90 = predictions[name]
        return p10, p50, p90, {name: 1.0}

    inv_errors = np.array([1.0 / (recent_mapes[n] + epsilon) for n in names])
    weights = inv_errors / inv_errors.sum()

    p10 = np.sum(
        [w * predictions[n][0] for w, n in zip(weights, names, strict=True)], axis=0
    )
    p50 = np.sum(
        [w * predictions[n][1] for w, n in zip(weights, names, strict=True)], axis=0
    )
    p90 = np.sum(
        [w * predictions[n][2] for w, n in zip(weights, names, strict=True)], axis=0
    )

    return p10, p50, p90, dict(zip(names, (float(w) for w in weights), strict=True))


def _recent_mape(
    expert: Forecaster,
    history: pd.DataFrame,
    horizon: int,
    window: int,
    target_col: str = TARGET_COLUMN,
) -> float:
    """Real recent MAPE for `expert`, computed by re-forecasting from up
    to `window` earlier points within `history` and comparing against
    the real outcomes `history` already contains for them. `float("inf")`
    -- not 0, not a crash -- if no real recent origin could be scored
    (e.g. `history` too short): an infinite recent error makes
    `blend_forecasts`' inverse weighting push this expert's weight
    toward zero rather than accidentally toward "most trusted" (which a
    0.0 default would do), the safer failure direction for an expert
    with genuinely unknown recent performance.
    """
    errors: list[float] = []
    n = len(history)
    for k in range(1, window + 1):
        origin = n - horizon - k
        if origin < 0:
            continue
        sub_history = history.iloc[: origin + 1]
        actual = history[target_col].iloc[origin + 1 : origin + 1 + horizon].to_numpy()
        if len(actual) < horizon or np.isnan(actual).any():
            continue
        _, p50, _ = expert.predict(sub_history, horizon)
        if np.isnan(p50).any():
            continue
        mask = actual != 0
        if mask.any():
            errors.append(
                float(np.mean(np.abs((actual[mask] - p50[mask]) / actual[mask])) * 100)
            )
    return float(np.mean(errors)) if errors else float("inf")


@dataclass
class BlendForecaster:
    """Combines `experts`' forecasts via `blend_forecasts`, weighted by
    each expert's real recent accuracy (`_recent_mape`, computed fresh
    on every `predict` call -- see module docstring for the real cost
    this implies). Implements `evaluate.py`'s `Forecaster` protocol, so
    it plugs into the same `evaluate_walk_forward` harness every other
    model does -- this phase's own explicit requirement to evaluate the
    blend the same way as each individual expert.
    """

    experts: Sequence[Forecaster]
    window: int = 3
    name: str = "blend"
    last_weights: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        recent_mapes: dict[str, float] = {}
        for expert in self.experts:
            p10, p50, p90 = expert.predict(history, horizon)
            if np.isnan(p50).any():
                continue
            predictions[expert.name] = (p10, p50, p90)
            recent_mapes[expert.name] = _recent_mape(
                expert, history, horizon, self.window
            )

        if not predictions:
            self.last_weights = {}
            return (np.full(horizon, np.nan),) * 3

        p10, p50, p90, weights = blend_forecasts(predictions, recent_mapes)
        self.last_weights = weights
        return p10, p50, p90
