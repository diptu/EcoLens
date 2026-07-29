"""ECO-113: the Optuna search space, externalized to YAML.

`training/tune.py` used to hardcode which hyperparameters get searched
(hidden size/layers/dropout/lr) and their ranges directly in Python
(`_suggest_settings`/`_apply_best_params`). That meant trying a wider
`hidden_size` or a narrower `lr` range required a code change. This
module reads the same search space from
`Settings.hyperparameter_search_config_path` (default
`hyperparameter_search.yml`) instead, so it's editable without touching
`tune.py`.

`DEFAULT_SEARCH_SPACE` mirrors exactly what was previously hardcoded --
a missing/malformed config file falls back to it (logged, not raised),
so deleting the YAML file or running from a directory that doesn't ship
one (e.g. most tests, which `monkeypatch.chdir` to an empty `tmp_path`)
doesn't break `tune()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import optuna
import yaml

from ecolens.config import Settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

ParamKind = Literal["categorical", "int", "float"]


@dataclass(frozen=True)
class ParamSpec:
    """One searched hyperparameter: how Optuna should sample it, and
    which `Settings` field the sampled value overrides.
    """

    name: str
    kind: ParamKind
    setting: str
    choices: tuple[Any, ...] | None = None
    low: float | None = None
    high: float | None = None
    log: bool = False

    def suggest(self, trial: optuna.Trial) -> Any:
        if self.kind == "categorical":
            assert self.choices is not None  # noqa: S101 - validated in from_dict
            return trial.suggest_categorical(self.name, list(self.choices))
        if self.kind == "int":
            assert self.low is not None and self.high is not None  # noqa: S101
            return trial.suggest_int(self.name, int(self.low), int(self.high))
        if self.kind == "float":
            assert self.low is not None and self.high is not None  # noqa: S101
            return trial.suggest_float(self.name, self.low, self.high, log=self.log)
        raise ValueError(f"unknown param kind {self.kind!r} for {self.name!r}")

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> ParamSpec:
        kind = d.get("type")
        if kind not in ("categorical", "int", "float"):
            raise ValueError(
                f"search_space.{name}.type must be categorical/int/float, got {kind!r}"
            )
        if "setting" not in d:
            raise ValueError(f"search_space.{name} is missing required key 'setting'")
        return cls(
            name=name,
            kind=kind,
            setting=d["setting"],
            choices=tuple(d["choices"]) if "choices" in d else None,
            low=d.get("low"),
            high=d.get("high"),
            log=bool(d.get("log", False)),
        )


@dataclass(frozen=True)
class SearchSpace:
    """A set of `ParamSpec`s -- one full Optuna trial's worth of
    hyperparameters, all mapped onto `Settings` fields.
    """

    params: tuple[ParamSpec, ...]

    def suggest_settings(self, trial: optuna.Trial, base: Settings) -> Settings:
        """One trial's `Settings`: `base` with every searched field
        overridden by this trial's sampled values.
        """
        return base.model_copy(
            update={p.setting: p.suggest(trial) for p in self.params}
        )

    def apply_best_params(
        self, base: Settings, best_params: dict[str, Any]
    ) -> Settings:
        """`base` with the winning trial's params applied -- same
        mapping `suggest_settings` uses, but from a finished
        `optuna.Study.best_params` dict instead of a live `Trial`.
        """
        return base.model_copy(
            update={p.setting: best_params[p.name] for p in self.params}
        )


# Exactly what `_suggest_settings`/`_apply_best_params` hardcoded before
# this module existed -- the fallback when no (or a broken) YAML config
# is present, so behavior is unchanged by default.
DEFAULT_SEARCH_SPACE = SearchSpace(
    params=(
        ParamSpec(
            name="hidden_size",
            kind="categorical",
            setting="model_hidden_size",
            choices=(32, 64, 128, 256),
        ),
        ParamSpec(
            name="num_layers", kind="int", setting="model_num_layers", low=1, high=3
        ),
        ParamSpec(
            name="dropout",
            kind="float",
            setting="model_dropout",
            low=0.0,
            high=0.5,
        ),
        ParamSpec(
            name="lr",
            kind="float",
            setting="model_train_lr",
            low=1e-4,
            high=1e-2,
            log=True,
        ),
    )
)


def load_search_space(path: Path) -> SearchSpace:
    """Reads `path` (see `hyperparameter_search.yml` for the schema).
    Falls back to `DEFAULT_SEARCH_SPACE` -- logged, not raised -- if
    the file doesn't exist, so a missing config degrades to "same as
    before this module existed" rather than breaking `tune()`.
    """
    if not path.exists():
        log.warning("search_space.config_missing", path=str(path))
        return DEFAULT_SEARCH_SPACE
    try:
        data = yaml.safe_load(path.read_text()) or {}
        raw_params = data["search_space"]
        params = tuple(
            ParamSpec.from_dict(name, spec) for name, spec in raw_params.items()
        )
        if not params:
            raise ValueError("search_space is empty")
    except Exception as exc:  # noqa: BLE001 - a malformed config degrades to the default, doesn't crash the search
        log.warning("search_space.config_invalid", path=str(path), error=str(exc))
        return DEFAULT_SEARCH_SPACE
    return SearchSpace(params=params)


__all__ = [
    "ParamSpec",
    "SearchSpace",
    "DEFAULT_SEARCH_SPACE",
    "load_search_space",
]
