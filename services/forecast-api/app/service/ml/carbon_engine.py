"""Deterministic carbon accounting over a reconciled generation-mix
forecast — serving-time-only, same as `reconciliation.
reconcile_generation` (see that module's docstring).

Ported from `services/forecast-api/notebooks/lstm.ipynb`'s `CarbonEngine`.
This module only holds the arithmetic; real, sourced emission factors
(replacing the notebook's illustrative example values) are loaded by
`service/ml/emission_factors.load_generation_bucket_factors` from
`dim_energy_mix.intensity_kgco2e_per_mwh` — see that module, not this
one, for where the numbers actually come from.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass
class CarbonEngine:
    """`emission_factors`: one entry per generation-mix bucket (same
    `sources` order/names as `EnergyForecast.generation`'s trailing
    source dim), in gCO2e/kWh. `interval_hours`: forecast step length
    (0.5 for this platform's native 30-minute cadence)."""

    emission_factors: dict[str, float]
    interval_hours: float = 0.5

    def __post_init__(self) -> None:
        self.source_names: tuple[str, ...] = tuple(self.emission_factors.keys())

    def calculate(self, generation_mw: Tensor, demand_mw: Tensor) -> dict[str, Tensor]:
        """`generation_mw`: `(B, H, S, Q)`, ideally already reconciled
        (`reconciliation.reconcile_generation`) so it sums to `demand_mw`
        across sources -- this function doesn't check that itself, it
        just weights whatever generation mix it's given. `demand_mw`:
        `(B, H, Q)`.

        Returns `emissions_kg: (B, H, Q)`, `carbon_intensity: (B, H, Q)`
        (gCO2e/kWh).
        """
        factors = torch.tensor(
            [self.emission_factors[source] for source in self.source_names],
            dtype=generation_mw.dtype,
            device=generation_mw.device,
        ).view(1, 1, -1, 1)  # [S] -> [1, 1, S, 1]

        # MW * hours * 1000 = kWh
        energy_kwh = generation_mw * self.interval_hours * 1000.0

        # kWh * gCO2e/kWh = gCO2e, summed across sources
        emissions_grams = (energy_kwh * factors).sum(dim=2)
        emissions_kg = emissions_grams / 1000.0

        demand_kwh = demand_mw * self.interval_hours * 1000.0
        carbon_intensity = emissions_grams / torch.clamp(demand_kwh, min=1.0)

        return {"emissions_kg": emissions_kg, "carbon_intensity": carbon_intensity}
