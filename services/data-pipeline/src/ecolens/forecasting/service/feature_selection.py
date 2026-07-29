"""The 5-step statistical gauntlet from root TODO.md's "Feature selection"
section — extracted from the notebook prototype
(`notebooks/data-pipeline.ipynb`, cells 11-16) into a reusable,
re-runnable module, closing that section's own "still a one-off notebook
exercise" gap. Steps 1-4 mirror the notebook's logic and thresholds
exactly (same 17.5% MI drop fraction, same 0.9 correlation threshold, same
LightGBM-gain-in-place-of-TreeSHAP substitution — `shap` still doesn't
build on this machine) — proven correct there against real
`ml_features_demand_v1` data, just not callable from anywhere but that
notebook until now.

Step 5 (TFT variable-selection gating) was blocked in the notebook ("no
TFT anywhere in this repo yet to read VSN weights from") — now
implementable via `DemandTFT.variable_selection_weights()`.

Every step is a pure function taking/returning plain pandas/numpy
structures — no dependency on `WindowedDataset`/`FeatureScaler`, so this
runs directly against a raw `ml_features_demand_v1` snapshot the same way
the notebook did, independent of the forecasting pipeline's own
train/val/calibration/test splitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
import torch


@dataclass(frozen=True)
class StructuralHygieneResult:
    """Step 1 — zero-variance and fully-null columns, the general-purpose
    version of "Australia has no nuclear/geothermal generation, so those
    columns never existed to begin with."
    """

    zero_variance_cols: list[str]
    fully_null_cols: list[str]

    @property
    def drop_cols(self) -> list[str]:
        return self.zero_variance_cols + self.fully_null_cols


def step1_structural_hygiene(
    df: pd.DataFrame, candidate_cols: list[str]
) -> StructuralHygieneResult:
    numeric_candidates = (
        df[candidate_cols].select_dtypes(include=[np.number, bool]).columns.tolist()
    )
    variances = df[numeric_candidates].var(numeric_only=True)
    zero_variance_cols = variances[variances.fillna(0) == 0].index.tolist()

    # Fully-null columns: a whole feature with zero real observations
    # anywhere -- distinct from the per-row nulls WEM/NEM's structural
    # split naturally produces (real "this fuel type doesn't exist in
    # this grid" signal, not missing data -- see the PreProcessing
    # section's own zero-fill guardrail for that distinction).
    null_pct = df[candidate_cols].isna().mean()
    fully_null_cols = null_pct[null_pct == 1.0].index.tolist()

    return StructuralHygieneResult(
        zero_variance_cols=zero_variance_cols, fully_null_cols=fully_null_cols
    )


@dataclass(frozen=True)
class MutualInformationResult:
    """Step 2 — non-linear relationships plain correlation would miss
    (e.g. price spikes driving demand response), ranked by
    `mutual_info_regression` against the target.
    """

    scores: pd.Series  # sorted descending, index = column name
    drop_fraction: float
    drop_cols: list[str]  # bottom drop_fraction of scores


def step2_mutual_information(
    df: pd.DataFrame,
    candidate_cols: list[str],
    target: str,
    *,
    drop_fraction: float = 0.175,  # midpoint of the spec's "bottom 15-20%"
    random_state: int = 42,
) -> MutualInformationResult:
    from sklearn.feature_selection import mutual_info_regression

    mi_df = df.dropna(subset=[target]).copy()

    # sklearn wants numeric input -- bool-dtype columns (e.g. is_holiday)
    # need the same int coercion the notebook applied to its one
    # bool-like column by name; generalized here to any bool column
    # rather than hardcoding a specific name, since the production
    # mart's column names don't exactly match the notebook's prototype.
    bool_cols = [c for c in candidate_cols if mi_df[c].dtype == bool]
    for col in bool_cols:
        mi_df[col] = mi_df[col].astype(int)

    x = mi_df[candidate_cols].apply(lambda s: s.fillna(s.median()))
    y = mi_df[target]

    scores = mutual_info_regression(x, y, random_state=random_state)
    mi_series = pd.Series(scores, index=candidate_cols).sort_values(ascending=False)

    n_drop = int(len(mi_series) * drop_fraction)
    low_mi_cols = mi_series.tail(n_drop).index.tolist() if n_drop > 0 else []

    return MutualInformationResult(
        scores=mi_series, drop_fraction=drop_fraction, drop_cols=low_mi_cols
    )


@dataclass(frozen=True)
class PACFResult:
    """Step 3 — validates proposed lag steps against demand's actual
    Partial Autocorrelation rather than trusting round numbers. Purely
    diagnostic: informs Feature Engineering's lag choice, doesn't drop
    any columns.
    """

    pacf_values: np.ndarray
    significant_lags: np.ndarray
    proposed_lags: tuple[int, ...]
    proposed_lag_significance: dict[int, bool]


def step3_pacf_lag_selection(
    df: pd.DataFrame,
    target: str,
    *,
    region_col: str = "region",
    region: str,
    ts_col: str = "ts_30",
    max_lag: int = 340,
    proposed_lags: tuple[int, ...] = (1, 2, 48, 336),
) -> PACFResult:
    from statsmodels.tsa.stattools import pacf

    series = df[df[region_col] == region].sort_values(ts_col)[target].ffill().bfill()

    pacf_vals, confint = pacf(series, nlags=max_lag, alpha=0.05, method="ywm")
    ci_half_width = confint[:, 1] - pacf_vals
    significant = np.where(np.abs(pacf_vals) > ci_half_width)[0]
    significant = significant[significant > 0]  # lag 0 is trivially 1.0

    return PACFResult(
        pacf_values=pacf_vals,
        significant_lags=significant,
        proposed_lags=proposed_lags,
        proposed_lag_significance={
            lag: bool(lag in significant) for lag in proposed_lags
        },
    )


@dataclass(frozen=True)
class MulticollinearityResult:
    """Step 4 — LightGBM gain importance (TreeSHAP substitute: `shap`
    doesn't build on this machine, see module docstring) fit once, used
    both as its own importance ranking and as the tiebreaker for dropping
    the weaker half of any highly-correlated feature pair.
    """

    importance: pd.Series  # sorted descending, index = column name
    correlation_threshold: float
    multicollinear_pairs: list[tuple[str, str, float]]  # (a, b, |r|)
    drop_cols: list[str]


def step4_multicollinearity_pruning(
    df: pd.DataFrame,
    candidate_cols: list[str],
    target: str,
    *,
    correlation_threshold: float = 0.9,
    n_estimators: int = 200,
    max_depth: int = 6,
    random_state: int = 42,
) -> MulticollinearityResult:
    import lightgbm as lgb

    fit_df = df.dropna(subset=[target]).copy()
    bool_cols = [c for c in candidate_cols if fit_df[c].dtype == bool]
    for col in bool_cols:
        fit_df[col] = fit_df[col].astype(int)

    x = fit_df[candidate_cols].apply(lambda s: s.fillna(s.median()))
    y = fit_df[target]

    model = lgb.LGBMRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=random_state,
        verbosity=-1,
        # importance_type="gain" (loss reduction attributed to each
        # feature), not the sklearn-API default "split" (raw split
        # count) -- root TODO.md documents this step as using "LightGBM's
        # own gain importance in place of true TreeSHAP," but the
        # notebook prototype's LGBMRegressor(...) call never actually
        # passed importance_type, so it silently used the "split"
        # default instead. Split count is a materially worse TreeSHAP
        # substitute (a pure-noise column can rack up splits without
        # ever reducing loss) -- fixed here to match the documented,
        # evidently-intended behavior.
        importance_type="gain",
        # n_jobs=1, not the default auto-detected core count: LightGBM's
        # own OpenMP thread pool colliding with an already-imported
        # torch's segfaults hard (SIGSEGV) in any process that imports
        # both -- reproduced directly (`import torch` before
        # `LGBMRegressor(...).fit(...)` crashes every time on this
        # machine; `n_jobs=1` is the one thing that reliably avoids it,
        # `KMP_DUPLICATE_LIB_OK=TRUE` does not). This module lives
        # alongside torch-importing siblings in forecasting/service/, so
        # this isn't a hypothetical -- any process that imports both
        # (e.g. this repo's own test suite) hits it by default.
        n_jobs=1,
    )
    model.fit(x, y)
    importance = pd.Series(
        model.feature_importances_, index=candidate_cols
    ).sort_values(ascending=False)

    corr_matrix = x.corr().abs()
    upper_triangle = corr_matrix.where(
        np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
    )

    pairs = [
        (col, other, float(upper_triangle.loc[other, col]))
        for col in upper_triangle.columns
        for other in upper_triangle.index[upper_triangle[col] > correlation_threshold]
    ]
    pairs.sort(key=lambda p: -p[2])

    drop_cols: set[str] = set()
    for a, b, _r in pairs:
        loser = a if importance[a] < importance[b] else b
        drop_cols.add(loser)

    return MulticollinearityResult(
        importance=importance,
        correlation_threshold=correlation_threshold,
        multicollinear_pairs=pairs,
        drop_cols=sorted(drop_cols),
    )


@dataclass(frozen=True)
class TFTGatingResult:
    """Step 5 — reads a trained `DemandTFT`'s temporal Variable Selection
    Network weights across a representative sample (its own test split —
    never used for training/early-stopping/calibration, so this reflects
    what the model actually leans on, not a training-set artifact) and
    flags any feature with near-zero average weight everywhere.
    """

    mean_weight_per_feature: pd.Series  # sorted ascending, index = feature name
    near_zero_threshold: float
    near_zero_cols: list[str]


class _VSNReadableModel(Protocol):
    """Structural type for `DemandTFT` (or anything shaped like it) --
    avoids a hard import-time dependency on `model/tft.py` for callers
    that only need the other four steps, and (unlike typing this as plain
    `nn.Module`) sidesteps `nn.Module.__getattr__`'s stub typing
    `variable_selection_weights` as `Tensor | Module` instead of a
    callable -- same reasoning as `mlops/registry.py`'s `ForecastingModel`
    protocol.
    """

    def eval(self) -> "_VSNReadableModel": ...
    def variable_selection_weights(
        self, x: torch.Tensor, region_idx: torch.Tensor
    ) -> torch.Tensor: ...


@torch.no_grad()
def step5_tft_vsn_gating(
    model: _VSNReadableModel,
    x: torch.Tensor,
    region_idx: torch.Tensor,
    *,
    feature_columns: tuple[str, ...],
    near_zero_threshold: float = 0.01,
) -> TFTGatingResult:
    """`model` must be a `DemandTFT`. `x`: `(n, lookback, n_features)`,
    `region_idx`: `(n,)` — typically a trained TFT's own
    `dataset.test.x`/region indices, so this reads real, held-out
    selection behavior.

    `near_zero_threshold` (fraction of uniform weight, i.e. `1/n_features`
    scaled) flags a feature the VSN essentially never uses -- a real
    candidate to drop, not a training-set artifact, since this only ever
    runs against held-out data the model never trained, early-stopped, or
    calibrated on.
    """
    model.eval()
    weights = model.variable_selection_weights(
        x, region_idx
    )  # (n, lookback, n_features)
    mean_weight = weights.mean(dim=(0, 1)).numpy()

    mean_weight_per_feature = pd.Series(
        mean_weight, index=list(feature_columns)
    ).sort_values()
    near_zero_cols = mean_weight_per_feature[
        mean_weight_per_feature < near_zero_threshold
    ].index.tolist()

    return TFTGatingResult(
        mean_weight_per_feature=mean_weight_per_feature,
        near_zero_threshold=near_zero_threshold,
        near_zero_cols=near_zero_cols,
    )


@dataclass(frozen=True)
class FeatureSelectionSummary:
    """Step 1+2+4's applied decision (Step 3 informs Feature Engineering's
    lag choice rather than dropping columns; Step 5 is reported alongside
    but not auto-applied -- see module docstring / CLI for why).
    """

    candidate_cols: list[str]
    kept_cols: list[str]
    structural: StructuralHygieneResult
    mutual_information: MutualInformationResult
    multicollinearity: MulticollinearityResult


def run_steps_1_2_4(
    df: pd.DataFrame,
    *,
    target: str = "demand_mw",
    identifier_cols: tuple[str, ...] = ("region", "ts_30"),
    metadata_cols: tuple[str, ...] = (),
    mi_drop_fraction: float = 0.175,
    correlation_threshold: float = 0.9,
) -> FeatureSelectionSummary:
    """The composed pipeline Steps 1, 2, and 4 actually apply (mirrors the
    notebook's own Step 16 "apply the decisions" cell) -- Step 3 (PACF)
    and Step 5 (TFT gating) are separate, independently-callable
    diagnostics above since neither drops columns as part of this
    pipeline (see their own docstrings).
    """
    exclude = set(identifier_cols) | set(metadata_cols) | {target}
    candidate_cols = [c for c in df.columns if c not in exclude]

    structural = step1_structural_hygiene(df, candidate_cols)
    remaining_after_1 = [c for c in candidate_cols if c not in structural.drop_cols]

    mi = step2_mutual_information(
        df, remaining_after_1, target, drop_fraction=mi_drop_fraction
    )
    remaining_after_2 = [c for c in remaining_after_1 if c not in mi.drop_cols]

    multicollinearity = step4_multicollinearity_pruning(
        df, remaining_after_2, target, correlation_threshold=correlation_threshold
    )
    kept_cols = [c for c in remaining_after_2 if c not in multicollinearity.drop_cols]

    return FeatureSelectionSummary(
        candidate_cols=candidate_cols,
        kept_cols=kept_cols,
        structural=structural,
        mutual_information=mi,
        multicollinearity=multicollinearity,
    )


__all__ = [
    "StructuralHygieneResult",
    "step1_structural_hygiene",
    "MutualInformationResult",
    "step2_mutual_information",
    "PACFResult",
    "step3_pacf_lag_selection",
    "MulticollinearityResult",
    "step4_multicollinearity_pruning",
    "TFTGatingResult",
    "step5_tft_vsn_gating",
    "FeatureSelectionSummary",
    "run_steps_1_2_4",
]
