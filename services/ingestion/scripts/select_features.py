#!/usr/bin/env python3
"""Run real automated feature selection against `data/training/master.duckdb`
and persist the result as a committed artifact (`selected_features.json`),
not just a notebook cell output.

Ported from `services/ingestion/notebooks/feature-selection.ipynb` (which
had never been executed — no selected-feature list existed anywhere in the
repo before this). The selection library itself (`FeatureSelectorConfig`
through `AutomaticEnergyFeatureSelector`) is carried over verbatim, already
bug-fixed in the notebook (see inline "BUG FIX" comments preserved below —
the raw-historical-variable leakage-registration fix and the exception-
swallowing fix in `AutomaticEnergyFeatureSelector.fit`).

Differs from the notebook's own "RUN" cell in exactly one way: this reads
`data/training/master.duckdb` directly via `build_master_table.master_path()`
instead of downloading it from R2 first. The notebook treats the local file
as a disposable cache and always re-pulls from R2 (needs `services/ingestion/
.env` + real R2 credentials); this script assumes `scripts/build_master_table.py`
has already been run (or the file otherwise already exists locally) and
fails with a clear error if it hasn't, rather than silently requiring cloud
credentials just to run a local feature-selection pass.

Run from `services/ingestion/`:

    uv run python scripts/select_features.py
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import click
import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_selection import mutual_info_regression
from sklearn.inspection import permutation_importance

from app.core.logging import configure_logging, get_logger
from scripts.build_master_table import master_path

log = get_logger(__name__)

_REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1", "WEM"]

# `aemo_*` per-fuel columns are excluded here — checked directly against
# `master.duckdb`: that breakdown only started landing ~2 days before this
# was written, 99.9% NULL, nowhere near enough history for a 7-day rolling
# feature. `oe_demand_mw` is excluded too (100% NULL, a genuine
# OpenElectricity API gap). Target is `aemo_demand_mw` (0.3% missing);
# generation-mix features come from OpenElectricity's per-fuel mix
# (~97%+ coverage since Aug 2025).
_HISTORICAL_VARIABLES = (
    "aemo_demand_mw",
    "oe_total_generation_mw",
    "oe_total_renewable_mw",
    "oe_coal_mw",
    "oe_gas_mw",
    "oe_wind_mw",
    "oe_solar_utility_mw",
    "oe_solar_rooftop_mw",
    "oe_hydro_mw",
)


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass
class FeatureSelectorConfig:
    """Configuration for automatic feature selection."""

    frequency_minutes: int = 30
    max_features: int = 30
    correlation_threshold: float = 0.85
    min_variance: float = 1e-8
    max_missing_fraction: float = 0.05
    n_splits_stability: int = 5
    minimum_rows_per_split: int = 100
    mutual_information_weight: float = 0.25
    model_importance_weight: float = 0.35
    permutation_weight: float = 0.20
    stability_weight: float = 0.20
    n_estimators: int = 150
    max_depth: Optional[int] = 12
    min_samples_leaf: int = 10
    permutation_repeats: int = 3
    random_state: int = 42
    lag_steps: Tuple[int, ...] = (1, 2, 6, 12, 24, 48, 96, 336)
    rolling_hours: Tuple[int, ...] = (3, 6, 12, 24, 168)
    historical_variables: Tuple[str, ...] = (
        "demand_mw",
        "coal_mw",
        "gas_mw",
        "wind_mw",
        "solar_mw",
        "hydro_mw",
    )
    max_selection_rows: int = 100_000


# ============================================================================
# NORMALIZATION
# ============================================================================


def normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
    """Min-max normalize feature scores to [0, 1]. If all features have
    identical scores, all receive 1.0."""
    if not scores:
        return {}

    values = np.asarray(list(scores.values()), dtype=float)

    minimum = np.nanmin(values)
    maximum = np.nanmax(values)

    if not np.isfinite(minimum) or not np.isfinite(maximum):
        return {key: 0.0 for key in scores}

    if maximum - minimum < 1e-12:
        return {key: 1.0 for key in scores}

    return {
        key: float((value - minimum) / (maximum - minimum))
        for key, value in scores.items()
    }


# ============================================================================
# FEATURE REGISTRY
# ============================================================================


class FeatureRegistry:
    """Stores metadata describing how a feature is allowed to be used."""

    def __init__(self) -> None:
        self.registry: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        family: str,
        requires_lag: bool = False,
        availability: str = "historical",
    ) -> None:
        self.registry[name] = {
            "family": family,
            "requires_lag": requires_lag,
            "availability": availability,
        }

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        return self.registry.get(name)

    def export(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.registry)


# ============================================================================
# FEATURE ENGINEERING
# ============================================================================


class FeatureEngineer:
    """Creates deterministic forecasting features."""

    def __init__(self, registry: FeatureRegistry, config: FeatureSelectorConfig) -> None:
        self.registry = registry
        self.config = config

    def transform(
        self,
        df: pd.DataFrame,
        dt_col: str = "timestamp",
        target_cols: Sequence[str] = (),
    ) -> pd.DataFrame:
        if dt_col not in df.columns:
            raise ValueError(f"Missing datetime column: {dt_col}")

        df = df.copy()
        df[dt_col] = pd.to_datetime(df[dt_col])
        df = df.sort_values(dt_col).reset_index(drop=True)

        self._add_calendar_features(df, dt_col)
        self._add_weather_features(df)
        self._add_lag_features(df)
        self._add_rolling_features(df)

        return df

    def _add_calendar_features(self, df: pd.DataFrame, dt_col: str) -> None:
        dt = pd.to_datetime(df[dt_col])

        df["hour"] = dt.dt.hour
        df["minute"] = dt.dt.minute
        df["day_of_week"] = dt.dt.dayofweek
        df["day_of_year"] = dt.dt.dayofyear
        df["month"] = dt.dt.month
        df["is_weekend"] = (dt.dt.dayofweek >= 5).astype(int)

        minutes_since_midnight = dt.dt.hour * 60 + dt.dt.minute
        slot_minutes = self.config.frequency_minutes
        df["time_slot"] = minutes_since_midnight // slot_minutes

        fractional_hour = dt.dt.hour + dt.dt.minute / 60.0

        df["hour_sin"] = np.sin(2 * np.pi * fractional_hour / 24.0)
        df["hour_cos"] = np.cos(2 * np.pi * fractional_hour / 24.0)
        df["day_of_week_sin"] = np.sin(2 * np.pi * dt.dt.dayofweek / 7.0)
        df["day_of_week_cos"] = np.cos(2 * np.pi * dt.dt.dayofweek / 7.0)
        df["day_of_year_sin"] = np.sin(2 * np.pi * dt.dt.dayofyear / 365.25)
        df["day_of_year_cos"] = np.cos(2 * np.pi * dt.dt.dayofyear / 365.25)

        for feature in [
            "hour",
            "minute",
            "day_of_week",
            "day_of_year",
            "month",
            "is_weekend",
            "time_slot",
            "hour_sin",
            "hour_cos",
            "day_of_week_sin",
            "day_of_week_cos",
            "day_of_year_sin",
            "day_of_year_cos",
        ]:
            self.registry.register(feature, family="calendar", requires_lag=False, availability="known_future")

        if "is_holiday" in df.columns:
            self.registry.register("is_holiday", family="calendar", requires_lag=False, availability="known_future")

    def _add_weather_features(self, df: pd.DataFrame) -> None:
        if "air_temp_c" in df.columns:
            df["hdd_18c"] = (18.0 - df["air_temp_c"]).clip(lower=0)
            self.registry.register("hdd_18c", family="weather_derived", availability="forecast")

            df["cdd_24c"] = (df["air_temp_c"] - 24.0).clip(lower=0)
            self.registry.register("cdd_24c", family="weather_derived", availability="forecast")

        if {"air_temp_c", "relative_humidity_pct"}.issubset(df.columns):
            df["heat_index_proxy"] = df["air_temp_c"] + 0.05 * df["relative_humidity_pct"]
            self.registry.register("heat_index_proxy", family="weather_derived", availability="forecast")

        if {"air_temp_c", "wind_speed_kmh"}.issubset(df.columns):
            df["wind_chill_proxy"] = df["air_temp_c"] - 0.1 * df["wind_speed_kmh"]
            self.registry.register("wind_chill_proxy", family="weather_derived", availability="forecast")

        if "solar_radiation_wm2" in df.columns:
            self.registry.register("solar_radiation_wm2", family="weather", availability="forecast")

    def _add_lag_features(self, df: pd.DataFrame) -> None:
        new_columns: Dict[str, pd.Series] = {}

        for column in self.config.historical_variables:
            if column not in df.columns:
                continue

            # The raw, un-lagged value of a historical variable is
            # contemporaneous with the row's own target -- not knowable at
            # real forecast time. Registering it here (requires_lag=True,
            # its own name has neither "_lag_" nor "_rolling_") makes
            # `LeakageFilter` correctly drop the raw column and keep only
            # its lag/rolling derivatives below.
            self.registry.register(column, family="historical_raw", requires_lag=True, availability="historical")

            for lag in self.config.lag_steps:
                feature_name = f"{column}_lag_{lag}"
                new_columns[feature_name] = df[column].shift(lag)
                self.registry.register(feature_name, family="lag", requires_lag=True, availability="historical")

        # Batched into one assignment instead of one `df[name] = ...` per
        # lag -- avoids pandas' "DataFrame is highly fragmented" warning.
        if new_columns:
            df[list(new_columns.keys())] = pd.DataFrame(new_columns, index=df.index)

    def _add_rolling_features(self, df: pd.DataFrame) -> None:
        steps_per_hour = max(1, int(round(60 / self.config.frequency_minutes)))

        new_columns: Dict[str, pd.Series] = {}

        for column in self.config.historical_variables:
            if column not in df.columns:
                continue

            shifted = df[column].shift(1)

            for hours in self.config.rolling_hours:
                window_steps = hours * steps_per_hour
                mean_name = f"{column}_rolling_mean_{hours}h"
                std_name = f"{column}_rolling_std_{hours}h"

                new_columns[mean_name] = shifted.rolling(window=window_steps, min_periods=window_steps).mean()
                new_columns[std_name] = shifted.rolling(window=window_steps, min_periods=window_steps).std()

                self.registry.register(mean_name, family="rolling", requires_lag=True, availability="historical")
                self.registry.register(std_name, family="rolling", requires_lag=True, availability="historical")

        if new_columns:
            df[list(new_columns.keys())] = pd.DataFrame(new_columns, index=df.index)


# ============================================================================
# LEAKAGE FILTER
# ============================================================================


class LeakageFilter:
    """Removes features that violate forecast-time availability."""

    def __init__(self, registry: FeatureRegistry) -> None:
        self.registry = registry

    def filter(self, df: pd.DataFrame, target_columns: Sequence[str]) -> List[str]:
        target_set = set(target_columns)
        candidates = []

        for column in df.columns:
            if column in {"timestamp", "region_id"}:
                continue

            if column in target_set:
                continue

            metadata = self.registry.get_metadata(column)

            if metadata:
                if metadata["requires_lag"] and "_lag_" not in column and "_rolling_" not in column:
                    continue

                candidates.append(column)
                continue

            candidates.append(column)

        return candidates


# ============================================================================
# QUALITY FILTER
# ============================================================================


class QualityFilter:
    """Removes excessively missing or near-zero variance features."""

    def __init__(self, config: FeatureSelectorConfig) -> None:
        self.config = config
        self.metadata: Dict[str, Dict[str, float]] = {}

    def filter(self, df: pd.DataFrame, candidates: Sequence[str]) -> List[str]:
        valid = []
        n_rows = max(1, len(df))

        for column in candidates:
            if column not in df.columns:
                continue

            numeric = pd.to_numeric(df[column], errors="coerce")

            missing_fraction = numeric.isna().sum() / n_rows
            variance = numeric.var()

            self.metadata[column] = {
                "missing_fraction": float(missing_fraction),
                "variance": float(0.0 if pd.isna(variance) else variance),
            }

            if missing_fraction > self.config.max_missing_fraction:
                continue

            if pd.isna(variance) or variance < self.config.min_variance:
                continue

            valid.append(column)

        return valid


# ============================================================================
# FEATURE IMPORTANCE
# ============================================================================


class FeatureImportanceCalculator:
    """Calculates Mutual Information, Random Forest impurity, and
    Permutation importance."""

    def __init__(self, config: FeatureSelectorConfig) -> None:
        self.config = config

    def calculate(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Dict[str, float]]:
        X_clean = X.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        X_clean = X_clean.fillna(X_clean.median()).fillna(0.0)

        y_clean = pd.to_numeric(y, errors="coerce")
        valid = y_clean.notna()

        X_clean = X_clean.loc[valid]
        y_clean = y_clean.loc[valid]

        if len(y_clean) < 50:
            raise ValueError("Insufficient rows for feature selection.")

        mi = mutual_info_regression(X_clean, y_clean, random_state=self.config.random_state)
        mi_raw = dict(zip(X_clean.columns, mi))

        rf = RandomForestRegressor(
            n_estimators=self.config.n_estimators,
            max_depth=self.config.max_depth,
            min_samples_leaf=self.config.min_samples_leaf,
            random_state=self.config.random_state,
            n_jobs=-1,
        )
        rf.fit(X_clean, y_clean)
        model_raw = dict(zip(X_clean.columns, rf.feature_importances_))

        permutation = permutation_importance(
            rf,
            X_clean,
            y_clean,
            n_repeats=self.config.permutation_repeats,
            random_state=self.config.random_state,
            n_jobs=-1,
        )
        permutation_raw = dict(zip(X_clean.columns, np.maximum(permutation.importances_mean, 0.0)))

        mi_norm = normalize_scores(mi_raw)
        model_norm = normalize_scores(model_raw)
        permutation_norm = normalize_scores(permutation_raw)

        result = {}
        for feature in X_clean.columns:
            result[feature] = {
                "mutual_information": mi_norm.get(feature, 0.0),
                "model_importance": model_norm.get(feature, 0.0),
                "permutation_importance": permutation_norm.get(feature, 0.0),
            }

        return result


# ============================================================================
# TEMPORAL STABILITY
# ============================================================================


class TemporalStabilityAnalyzer:
    """Measures feature importance stability across sequential time blocks."""

    def __init__(self, config: FeatureSelectorConfig) -> None:
        self.config = config

    def calculate(self, df: pd.DataFrame, candidates: Sequence[str], target_col: str) -> Dict[str, float]:
        if not candidates:
            return {}

        X = df[list(candidates)].apply(pd.to_numeric, errors="coerce")
        X = X.fillna(X.median()).fillna(0.0)

        y = pd.to_numeric(df[target_col], errors="coerce")
        valid = y.notna()

        X = X.loc[valid]
        y = y.loc[valid]

        if len(X) < (self.config.minimum_rows_per_split * self.config.n_splits_stability):
            return {feature: 0.0 for feature in candidates}

        indices = np.arange(len(X))
        splits = np.array_split(indices, self.config.n_splits_stability)

        importance_history = {feature: [] for feature in candidates}

        for split in splits:
            if len(split) < self.config.minimum_rows_per_split:
                continue

            X_split = X.iloc[split]
            y_split = y.iloc[split]

            rf = RandomForestRegressor(
                n_estimators=75,
                max_depth=10,
                min_samples_leaf=10,
                random_state=self.config.random_state,
                n_jobs=-1,
            )

            try:
                rf.fit(X_split, y_split)
            except Exception:
                continue

            for feature, importance in zip(candidates, rf.feature_importances_):
                importance_history[feature].append(float(importance))

        stability_scores = {}
        for feature, importances in importance_history.items():
            if not importances:
                stability_scores[feature] = 0.0
                continue

            mean_imp = np.mean(importances)
            std_imp = np.std(importances)

            cv = std_imp / (mean_imp + 1e-8)
            stability_score = 1.0 / (1.0 + cv)
            stability_scores[feature] = float(stability_score)

        return stability_scores


# ============================================================================
# CORRELATION PRUNER
# ============================================================================


class CorrelationPruner:
    """Removes redundant multicollinear features based on correlation
    matrix.

    Known limitation, not fixed here: this is a greedy, single-pass prune
    over pairwise correlations, processed in column order. For a cluster
    of 3+ mutually-correlated features it can occasionally drop more than
    the strictly-necessary minimum, or keep a locally-but-not-globally
    best representative, depending on processing order.
    """

    def __init__(self, config: FeatureSelectorConfig) -> None:
        self.config = config

    def prune(self, df: pd.DataFrame, candidates: Sequence[str], relevance_scores: Dict[str, float]) -> List[str]:
        if not candidates:
            return []

        X = df[list(candidates)].apply(pd.to_numeric, errors="coerce")
        corr_matrix = X.corr().abs()

        upper_tri = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))

        to_drop = set()
        for column in upper_tri.columns:
            correlated = upper_tri.index[upper_tri[column] > self.config.correlation_threshold].tolist()

            if correlated:
                competing = correlated + [column]
                best_feature = max(competing, key=lambda f: relevance_scores.get(f, 0.0))
                for feature in competing:
                    if feature != best_feature:
                        to_drop.add(feature)

        return [c for c in candidates if c not in to_drop]


# ============================================================================
# AUTOMATED FEATURE SELECTOR ORCHESTRATOR
# ============================================================================


class AutomaticEnergyFeatureSelector:
    """Main orchestrator for the multi-output automated energy feature
    selection pipeline."""

    def __init__(self, config: Optional[FeatureSelectorConfig] = None) -> None:
        self.config = config or FeatureSelectorConfig()
        self.registry = FeatureRegistry()
        self.engineer = FeatureEngineer(self.registry, self.config)
        self.leakage_filter = LeakageFilter(self.registry)
        self.quality_filter = QualityFilter(self.config)
        self.importance_calc = FeatureImportanceCalculator(self.config)
        self.stability_analyzer = TemporalStabilityAnalyzer(self.config)
        self.correlation_pruner = CorrelationPruner(self.config)

        self.selected_features: List[str] = []
        self.feature_scores: Dict[str, float] = {}

    def fit(self, df: pd.DataFrame, target_columns: Sequence[str], dt_col: str = "timestamp") -> Dict[str, Any]:
        df_engineered = self.engineer.transform(df, dt_col=dt_col)

        if len(df_engineered) > self.config.max_selection_rows:
            df_selection = df_engineered.tail(self.config.max_selection_rows).copy()
        else:
            df_selection = df_engineered

        candidates = self.leakage_filter.filter(df_selection, target_columns)
        quality_candidates = self.quality_filter.filter(df_selection, candidates)

        if not quality_candidates:
            raise ValueError("No candidate features survived quality filtering.")

        X = df_selection[quality_candidates]

        aggregated_scores = {
            feat: {"mutual_information": 0.0, "model_importance": 0.0, "permutation_importance": 0.0}
            for feat in quality_candidates
        }
        aggregated_stability = {feat: 0.0 for feat in quality_candidates}

        valid_targets = [t for t in target_columns if t in df_selection.columns]
        if not valid_targets:
            raise ValueError("None of the specified target columns exist in the DataFrame.")

        weight_factor = 1.0 / len(valid_targets)

        for target in valid_targets:
            y = df_selection[target]

            try:
                imp_res = self.importance_calc.calculate(X, y)
                stab_res = self.stability_analyzer.calculate(df_selection, quality_candidates, target)
            except Exception as exc:
                warnings.warn(
                    f"feature importance/stability calculation failed for target {target!r}, skipping it: {exc!r}",
                    stacklevel=2,
                )
                continue

            for feat in quality_candidates:
                if feat in imp_res:
                    aggregated_scores[feat]["mutual_information"] += imp_res[feat]["mutual_information"] * weight_factor
                    aggregated_scores[feat]["model_importance"] += imp_res[feat]["model_importance"] * weight_factor
                    aggregated_scores[feat]["permutation_importance"] += imp_res[feat]["permutation_importance"] * weight_factor
                if feat in stab_res:
                    aggregated_stability[feat] += stab_res[feat] * weight_factor

        relevance_proxy = {
            feat: (
                self.config.model_importance_weight * scores["model_importance"]
                + self.config.mutual_information_weight * scores["mutual_information"]
            )
            for feat, scores in aggregated_scores.items()
        }

        pruned_features = self.correlation_pruner.prune(df_selection, quality_candidates, relevance_proxy)

        mi_dict = {f: aggregated_scores[f]["mutual_information"] for f in pruned_features}
        model_dict = {f: aggregated_scores[f]["model_importance"] for f in pruned_features}
        perm_dict = {f: aggregated_scores[f]["permutation_importance"] for f in pruned_features}
        stab_dict = {f: aggregated_stability[f] for f in pruned_features}

        mi_norm = normalize_scores(mi_dict)
        model_norm = normalize_scores(model_dict)
        perm_norm = normalize_scores(perm_dict)
        stab_norm = normalize_scores(stab_dict)

        final_scores = {}
        for feat in pruned_features:
            score = (
                self.config.mutual_information_weight * mi_norm.get(feat, 0.0)
                + self.config.model_importance_weight * model_norm.get(feat, 0.0)
                + self.config.permutation_weight * perm_norm.get(feat, 0.0)
                + self.config.stability_weight * stab_norm.get(feat, 0.0)
            )
            final_scores[feat] = score

        sorted_features = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        selected = [f for f, _ in sorted_features[: self.config.max_features]]

        self.selected_features = selected
        self.feature_scores = final_scores

        return {"selected_features": selected, "feature_scores": final_scores}

    def transform(self, df: pd.DataFrame, dt_col: str = "timestamp") -> pd.DataFrame:
        df_engineered = self.engineer.transform(df, dt_col=dt_col)
        available_cols = [c for c in self.selected_features if c in df_engineered.columns]
        return df_engineered[available_cols]

    def save(self, path: Union[str, Path]) -> None:
        payload = {
            "config": asdict(self.config),
            "selected_features": self.selected_features,
            "feature_scores": self.feature_scores,
            "registry": self.registry.export(),
        }
        with open(path, "w", encoding="utf-8") as f:
            import json

            json.dump(payload, f, indent=4)


# ============================================================================
# RUN: select features against the local master table, across all 6 regions
# ============================================================================


def selected_features_path() -> Path:
    return master_path().parent / "selected_features.json"


def run_selection() -> Dict[str, Any]:
    path = master_path()
    if not path.exists():
        raise click.ClickException(
            f"master.duckdb not found at {path} -- run `uv run python "
            "scripts/build_master_table.py` first (or place a copy there)."
        )

    per_region_scores: dict[str, dict[str, float]] = {}
    per_region_row_counts: dict[str, int] = {}

    with duckdb.connect(str(path), read_only=True) as conn:
        for region in _REGIONS:
            df_region = conn.execute(
                "SELECT * FROM master WHERE region = ? ORDER BY bucket_ts", [region]
            ).df()

            # Rename to match AutomaticEnergyFeatureSelector's expected
            # column names.
            df_region = df_region.rename(
                columns={
                    "bucket_ts": "timestamp",
                    "region": "region_id",
                    "temp_c": "air_temp_c",
                    "humidity_pct": "relative_humidity_pct",
                }
            )

            region_config = FeatureSelectorConfig(
                frequency_minutes=30,
                historical_variables=_HISTORICAL_VARIABLES,
            )
            selector = AutomaticEnergyFeatureSelector(region_config)
            selector.fit(df_region, target_columns=["aemo_demand_mw"], dt_col="timestamp")

            per_region_scores[region] = selector.feature_scores
            per_region_row_counts[region] = len(df_region)
            log.info(
                "select_features.region_done",
                region=region,
                rows=len(df_region),
                candidates=len(selector.feature_scores),
            )

    # A feature only counts if it survived quality filtering in *every*
    # region -- otherwise a feature that only exists because one sparse
    # region happened to pass the 5%-missing threshold would unfairly
    # make the cut.
    common_features = set.intersection(*(set(scores) for scores in per_region_scores.values()))

    aggregated_scores = {
        feature: float(np.mean([per_region_scores[r][feature] for r in _REGIONS]))
        for feature in common_features
    }

    max_features = 30
    selected_features = sorted(aggregated_scores, key=aggregated_scores.get, reverse=True)[:max_features]

    return {
        "selected_features": selected_features,
        "feature_scores": aggregated_scores,
        "per_region_row_counts": per_region_row_counts,
        "per_region_candidate_counts": {r: len(s) for r, s in per_region_scores.items()},
        "n_common_features": len(common_features),
        "historical_variables": list(_HISTORICAL_VARIABLES),
        "target": "aemo_demand_mw",
        "regions": _REGIONS,
    }


@click.command()
def main() -> None:
    """Run automated feature selection against `data/training/master.duckdb`
    and write `data/training/selected_features.json`."""
    configure_logging()

    result = run_selection()
    selected = result["selected_features"]
    scores = result["feature_scores"]

    out_path = selected_features_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    click.echo(
        f"\n{result['n_common_features']} features common to all 6 regions; "
        f"top {len(selected)} selected (written to {out_path}):\n"
    )
    for feat in selected:
        click.echo(f"  * {feat:40s} {scores[feat]:.4f}")

    log.info(
        "select_features.done",
        n_selected=len(selected),
        n_common=result["n_common_features"],
        out_path=str(out_path),
    )


if __name__ == "__main__":
    main()
