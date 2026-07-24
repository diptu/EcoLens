"""Tests for ecolens.forecasting.training.search_space (ECO-113).

`suggest_settings`/`apply_best_params` are exercised against a real
`optuna.Study` (one trial), not a hand-rolled fake `Trial` -- the
`trial.suggest_*` calls are the actual contract being tested, and a
fake would just test the fake.
"""

from __future__ import annotations

from pathlib import Path

import optuna
import pytest

from ecolens.config import Settings
from ecolens.forecasting.training.search_space import (
    DEFAULT_SEARCH_SPACE,
    ParamSpec,
    SearchSpace,
    load_search_space,
)


def _one_trial_settings(search_space: SearchSpace, base: Settings) -> Settings:
    captured: dict[str, Settings] = {}

    def objective(trial: optuna.Trial) -> float:
        captured["settings"] = search_space.suggest_settings(trial, base)
        return 0.0

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=1)
    return captured["settings"]


class TestLoadSearchSpace:
    def test_missing_file_falls_back_to_default(self, tmp_path: Path) -> None:
        result = load_search_space(tmp_path / "does_not_exist.yml")
        assert result is DEFAULT_SEARCH_SPACE

    def test_malformed_yaml_falls_back_to_default(self, tmp_path: Path) -> None:
        path = tmp_path / "hyperparameter_search.yml"
        path.write_text("search_space:\n  hidden_size:\n    type: bogus\n")
        result = load_search_space(path)
        assert result is DEFAULT_SEARCH_SPACE

    def test_missing_setting_key_falls_back_to_default(self, tmp_path: Path) -> None:
        path = tmp_path / "hyperparameter_search.yml"
        path.write_text(
            "search_space:\n  hidden_size:\n    type: categorical\n    choices: [8, 16]\n"
        )
        result = load_search_space(path)
        assert result is DEFAULT_SEARCH_SPACE

    def test_loads_a_real_config(self, tmp_path: Path) -> None:
        path = tmp_path / "hyperparameter_search.yml"
        path.write_text(
            "search_space:\n"
            "  hidden_size:\n"
            "    type: categorical\n"
            "    setting: model_hidden_size\n"
            "    choices: [8, 16]\n"
            "  lr:\n"
            "    type: float\n"
            "    setting: model_train_lr\n"
            "    low: 0.001\n"
            "    high: 0.1\n"
            "    log: true\n"
        )
        result = load_search_space(path)
        assert result is not DEFAULT_SEARCH_SPACE
        names = {p.name for p in result.params}
        assert names == {"hidden_size", "lr"}


class TestSuggestAndApply:
    def test_default_search_space_suggests_all_four_fields(self) -> None:
        base = Settings()  # type: ignore[call-arg]
        trial_settings = _one_trial_settings(DEFAULT_SEARCH_SPACE, base)
        assert trial_settings.model_hidden_size in (32, 64, 128, 256)
        assert 1 <= trial_settings.model_num_layers <= 3
        assert 0.0 <= trial_settings.model_dropout <= 0.5
        assert 1e-4 <= trial_settings.model_train_lr <= 1e-2

    def test_a_custom_search_space_only_overrides_its_own_fields(self) -> None:
        base = Settings(model_num_layers=2, model_dropout=0.2)  # type: ignore[call-arg]
        custom = SearchSpace(
            params=(
                ParamSpec(
                    name="hidden_size",
                    kind="categorical",
                    setting="model_hidden_size",
                    choices=(8, 16),
                ),
            )
        )
        trial_settings = _one_trial_settings(custom, base)
        assert trial_settings.model_hidden_size in (8, 16)
        # untouched fields carry over from base unchanged
        assert trial_settings.model_num_layers == 2
        assert trial_settings.model_dropout == 0.2

    def test_apply_best_params_maps_generic_names_to_settings_fields(self) -> None:
        base = Settings()  # type: ignore[call-arg]
        best = {
            "hidden_size": 256,
            "num_layers": 3,
            "dropout": 0.4,
            "lr": 0.005,
        }
        result = DEFAULT_SEARCH_SPACE.apply_best_params(base, best)
        assert result.model_hidden_size == 256
        assert result.model_num_layers == 3
        assert result.model_dropout == 0.4
        assert result.model_train_lr == 0.005


class TestParamSpecFromDict:
    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="categorical/int/float"):
            ParamSpec.from_dict("x", {"type": "bogus", "setting": "model_x"})

    def test_rejects_missing_setting(self) -> None:
        with pytest.raises(ValueError, match="setting"):
            ParamSpec.from_dict("x", {"type": "int", "low": 1, "high": 2})
