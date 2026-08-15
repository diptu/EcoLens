"""MLflow model loading + hot-reload (`README.md`: "loads LSTM from
MLflow on boot"; "forecast-api hot-reloads it on the next request — no
service-to-service call, just a watch on the MLflow registry"; `TODO.md`'s
"Non-Blocking Training Architecture" checklist item on thread-safe
model hot-swapping).

`load_bundle` reconstructs `DemandLSTM` from its own copy of the class
(`models/ml.py`) plus the `state_dict`/scalers/calibration
`data-pipeline`'s `service/ml/train.py` persisted under the `serving` artifact
path — see `models/ml.py`'s docstring for why this is a `state_dict` load,
not `mlflow.pytorch.load_model`.

`ModelRegistry` holds the currently-served bundle behind a plain instance
attribute. A background task (`watch`, started in `main.py`'s
lifespan) polls MLflow on an interval and, when it finds a newer
`Production` version, builds the new bundle *first* and only then
reassigns `self._bundle` — a single attribute write, atomic under the
GIL, so an in-flight request reading `self._bundle` never observes a
half-constructed bundle. This is the "atomic pointer swap" pattern
`TODO.md`'s hot-swapping checklist item describes; it hasn't yet been
load-tested under real concurrent traffic (that verification is still
open, tracked there) but the swap mechanism itself is real, not a stub.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.artifacts
import torch
from mlflow.tracking import MlflowClient
from sklearn.preprocessing import StandardScaler

from app.core.config import get_settings
from app.service.ml.bias_correction import DemandBiasCorrection
from app.service.ml.conformal import ConformalCalibration
from app.service.ml.features import ALL_MODEL_REGIONS
from app.models.ml import DemandLSTM
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ModelBundle:
    model: DemandLSTM
    feature_scalers: dict[str, StandardScaler]
    # `dict[str, StandardScaler]` for any version trained after
    # `ml/train.py`'s per-region target-scaling fix (2026-08-15); a bare
    # `StandardScaler` for versions registered before it (backward
    # compatibility, not a live code path going forward as those age out
    # of Production).
    target_scaler: StandardScaler | dict[str, StandardScaler]
    calibration: ConformalCalibration
    bias_correction: DemandBiasCorrection
    run_id: str
    version: str
    stage: str
    loaded_at: datetime
    horizon: int
    lookback: int
    metrics: dict[str, float]
    git_sha: str | None


async def load_bundle(model_name: str, stage: str = "Production") -> ModelBundle | None:
    """`None` if `model_name` has no version in `stage` yet — a real,
    expected state before the first model is ever trained+promoted, not
    an error. Runs MLflow's (blocking) client calls in a worker thread
    (`asyncio.to_thread`) so this never blocks the event loop other
    requests are being served on, even though it's only ever called from
    the background watch loop / app startup, not from a request handler
    directly."""

    def _load() -> ModelBundle | None:
        tracking_uri = get_settings().mlflow_tracking_uri
        # `mlflow.artifacts.download_artifacts`/`load_dict` below resolve
        # `runs:/...` URIs against the *global* active tracking URI, not
        # a per-call parameter -- set it explicitly rather than relying
        # on whatever MLflow's own default happens to be (its built-in
        # fallback silently creates a local `mlflow.db`/`mlruns/` in the
        # process's cwd, not `Settings.mlflow_tracking_uri`).
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        versions = client.get_latest_versions(model_name, stages=[stage])
        if not versions:
            return None
        version = versions[0]
        run = client.get_run(version.run_id)
        params = run.data.params
        metrics = run.data.metrics

        model = DemandLSTM(
            n_features=int(params["n_features"]),
            horizon=int(params["horizon"]),
            hidden_size=int(params["hidden_size"]),
            num_layers=int(params["num_layers"]),
            dropout=float(params["dropout"]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_dir = mlflow.artifacts.download_artifacts(
                run_id=version.run_id, artifact_path="serving", dst_path=tmpdir
            )
            # weights_only=True: this file is always a plain state_dict
            # data-pipeline wrote via mlflow.artifacts (never an
            # externally-sourced file), but there's no reason to allow
            # arbitrary-object unpickling when only tensors are ever
            # stored here.
            state_dict = torch.load(
                Path(local_dir) / "model_state_dict.pt",
                map_location=torch.device("cpu"),
                weights_only=True,
            )
            feature_scalers = joblib.load(Path(local_dir) / "feature_scalers.joblib")
            target_scaler = joblib.load(Path(local_dir) / "target_scaler.joblib")

        model.load_state_dict(state_dict)
        model.eval()

        calibration_dict = mlflow.artifacts.load_dict(
            f"runs:/{version.run_id}/conformal_calibration.json"
        )

        # `demand_bias_correction.json` only exists on runs from
        # `TODO.md` Phase 3 on (2026-08-12) -- a version registered
        # before that real, expected state, not an error; falls back to
        # an empty `DemandBiasCorrection` (every `.apply()` call becomes
        # a no-op, same as if this field didn't exist at all).
        try:
            bias_correction_dict = mlflow.artifacts.load_dict(
                f"runs:/{version.run_id}/demand_bias_correction.json"
            )
            bias_correction = DemandBiasCorrection.from_dict(bias_correction_dict)
        except Exception:
            log.info(
                "registry.no_bias_correction_artifact",
                run_id=version.run_id,
                model_name=model_name,
            )
            bias_correction = DemandBiasCorrection()

        return ModelBundle(
            model=model,
            feature_scalers=feature_scalers,
            target_scaler=target_scaler,
            calibration=ConformalCalibration.from_dict(calibration_dict),
            bias_correction=bias_correction,
            run_id=version.run_id,
            version=version.version,
            stage=stage,
            loaded_at=datetime.now(UTC),
            horizon=int(params["horizon"]),
            lookback=int(params["lookback"]),
            metrics=dict(metrics),
            git_sha=run.data.tags.get("git_sha"),
        )

    return await asyncio.to_thread(_load)


@dataclass
class ModelVersionSummary:
    version: str
    stage: str
    run_id: str
    created_at: datetime
    metrics: dict[str, float]
    git_sha: str | None


async def list_versions(model_name: str) -> list[ModelVersionSummary]:
    """Every registered version of `model_name`, any stage -- unlike
    `load_bundle` (which only ever loads whichever version is currently
    `Production`), this is a pure registry read: no state_dict/scaler
    download, no model reconstruction. Newest first. `[]` if the model
    has no registered versions yet (same "real, expected before the
    first train+register" reasoning as `load_bundle` returning `None`).
    """

    def _list() -> list[ModelVersionSummary]:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        versions = client.search_model_versions(f"name='{model_name}'")
        summaries = []
        for v in versions:
            # A registered MLflow model version always has a real
            # run_id/stage -- mlflow's own stubs type both `Optional[str]`
            # more conservatively than what's actually possible here.
            assert v.run_id is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check
            assert v.current_stage is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check
            run = client.get_run(v.run_id)
            summaries.append(
                ModelVersionSummary(
                    version=v.version,
                    stage=v.current_stage,
                    run_id=v.run_id,
                    created_at=datetime.fromtimestamp(
                        v.creation_timestamp / 1000, tz=UTC
                    ),
                    metrics=dict(run.data.metrics),
                    git_sha=run.data.tags.get("git_sha"),
                )
            )
        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries

    return await asyncio.to_thread(_list)


@dataclass
class LossCurvePoint:
    epoch: int
    train_loss: float | None
    val_loss: float | None
    val_mape: float | None
    val_rmse: float | None
    val_mae: float | None


@dataclass
class LossCurve:
    run_id: str
    points: list[LossCurvePoint]


async def get_loss_curve(model_name: str, version: str) -> LossCurve:
    """Real per-epoch `train_loss`/`val_loss`/`val_mape`/`val_rmse`/
    `val_mae` history for one registered version -- `data-pipeline`'s
    `ml/train.py`'s `log_and_register_run` logs all five as real MLflow
    step-metrics (`mlflow.log_metrics(..., step=epoch)`), shared
    verbatim by the LSTM and TFT training paths (`train_tft.py` reuses
    the same function, see its own docstring).

    `val_loss` (added 2026-08-05, for the Performance page's "training
    vs validation loss" chart) is the real `demand_loss` on the
    validation split -- the same units as `train_loss`, unlike
    `val_mape`/`val_rmse`/`val_mae` (inverse-scaled-MW error metrics, not
    losses). `val_rmse`/`val_mae` (added the same day, for the
    "validation RMSE & MAE" chart) are real MW-unit error metrics
    computed from the same inverse-scaled P50-vs-actual pair `val_mape`
    already uses. A version registered before any of these fields
    existed simply has no history for it to return -- real absence, not
    backfilled with a fabricated value.

    `MlflowClient.get_metric_history` -- not `client.get_run(...).data.
    metrics` (`list_versions`/`load_bundle`'s calls above), which only
    ever surfaces the *last* logged value per key -- is the only way to
    read the full curve back out. All five metrics are merged by epoch
    (`step`) into one point each; a version missing any of them at some
    epoch still contributes a point with the other fields `None`, rather
    than being dropped -- same "don't silently discard a real data
    point" reasoning as `ModelVersionOut.metrics` leaving an absent key
    out rather than fabricating a `0.0`.
    """

    def _fetch() -> LossCurve:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        version_info = client.get_model_version(model_name, version)
        assert version_info.run_id is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check; a registered version always has a run_id
        run_id = version_info.run_id

        metric_keys = ("train_loss", "val_loss", "val_mape", "val_rmse", "val_mae")
        by_step = {
            key: {m.step: m.value for m in client.get_metric_history(run_id, key)}
            for key in metric_keys
        }
        steps = sorted(set().union(*(s.keys() for s in by_step.values())))
        points = [
            LossCurvePoint(
                epoch=step,
                train_loss=by_step["train_loss"].get(step),
                val_loss=by_step["val_loss"].get(step),
                val_mape=by_step["val_mape"].get(step),
                val_rmse=by_step["val_rmse"].get(step),
                val_mae=by_step["val_mae"].get(step),
            )
            for step in steps
        ]
        return LossCurve(run_id=run_id, points=points)

    return await asyncio.to_thread(_fetch)


@dataclass
class RegionEvaluation:
    region: str
    # e.g. "lstm_demand_v6" (calibrated), "lstm_demand_v6_raw"
    # (uncalibrated quantiles), "seasonal_naive" (baseline) -- whatever
    # `Forecaster.name` the candidate that produced this report used
    # (`ml/evaluate.py`'s `LSTMForecaster`/`BaselineForecaster`).
    candidate: str
    mape: float
    rmse: float
    coverage: float
    interval_width: float
    n_origins: int
    # `None` for a real evaluation run logged before these two metrics
    # existed (`_EVAL_METRIC_SUFFIXES`/`ml/evaluate.py`'s own note) --
    # not fabricated as 0/NaN.
    mae: float | None = None
    mean_error: float | None = None


@dataclass
class EvaluationSummary:
    run_id: str
    evaluated_at: datetime
    n_origins: int
    regions: list[RegionEvaluation]


# The exact metric-name suffixes `EvaluationReport.as_mlflow_metrics()`
# (`ml/evaluate.py`) logs -- fixed, not user input.
_EVAL_METRIC_SUFFIXES = (
    "eval_mape",
    "eval_rmse",
    "eval_coverage",
    "eval_interval_width",
    "eval_n_origins",
    "eval_pinball_p10",
    "eval_pinball_p50",
    "eval_pinball_p90",
    "eval_mae",
    "eval_mean_error",
)


def _parse_evaluation_metrics(metrics: dict[str, float]) -> list[RegionEvaluation]:
    """Reconstructs per-`(region, candidate)` rows from `evaluate_and_log`'s
    flat `f"{region}_{candidate.name}_{metric}"` MLflow metric keys
    (`EvaluationReport.as_mlflow_metrics()`, `ml/evaluate.py`) -- MLflow
    only ever stores flat key/value pairs per run, so this is the one
    place that un-flattens them back into real per-region/candidate
    reports. Matches from the region side, not the metric-suffix side --
    `ALL_MODEL_REGIONS` codes never contain `_`, but candidate names
    sometimes do (`lstm_demand_v6_raw`), so a region-prefix match is
    unambiguous where a suffix-only match wouldn't be. Metric keys that
    don't parse (an unrelated param/metric on the same run, or a region
    outside `ALL_MODEL_REGIONS`) are silently skipped, not an error --
    this function's whole job is picking the real evaluation rows out of
    a flat namespace, not validating every key on the run.
    """
    grouped: dict[tuple[str, str], dict[str, float]] = {}
    for key, value in metrics.items():
        region = next((r for r in ALL_MODEL_REGIONS if key.startswith(f"{r}_")), None)
        if region is None:
            continue
        rest = key[len(region) + 1 :]
        suffix = next((s for s in _EVAL_METRIC_SUFFIXES if rest.endswith(f"_{s}")), None)
        if suffix is None:
            continue
        candidate = rest[: -(len(suffix) + 1)]
        if not candidate:
            continue
        grouped.setdefault((region, candidate), {})[suffix] = value

    out = []
    for (region, candidate), vals in grouped.items():
        if "eval_mape" not in vals or "eval_n_origins" not in vals:
            continue
        out.append(
            RegionEvaluation(
                region=region,
                candidate=candidate,
                mape=vals["eval_mape"],
                rmse=vals.get("eval_rmse", float("nan")),
                coverage=vals.get("eval_coverage", float("nan")),
                interval_width=vals.get("eval_interval_width", float("nan")),
                n_origins=int(vals["eval_n_origins"]),
                mae=vals.get("eval_mae"),
                mean_error=vals.get("eval_mean_error"),
            )
        )
    out.sort(key=lambda r: (r.region, r.candidate))
    return out


def _evaluation_runs_filter(model_name: str, version: str) -> str:
    """Shared MLflow filter-string builder for both `get_latest_evaluation`
    and `get_evaluation_history` -- `model_name`/`version` come from a
    caller-controlled path/query param, escaped before interpolation into
    MLflow's filter-string DSL so a stray `'` can't break out of the
    quoted literal (this only ever scopes a read against this service's
    own MLflow instance, not a SQL injection into the real warehouse, but
    there's no reason to build the filter string unescaped anyway)."""
    safe_model_name = model_name.replace("'", "\\'")
    safe_version = str(version).replace("'", "\\'")
    return (
        "tags.evaluation = 'true' and "
        f"tags.evaluated_model = '{safe_model_name}' and "
        f"tags.evaluated_version = '{safe_version}'"
    )


async def get_latest_evaluation(model_name: str, version: str) -> EvaluationSummary | None:
    """Real walk-forward backtest results (`ecolens-forecast evaluate`)
    for one registered version -- `None` (not an error) if no evaluation
    run has ever been logged for it, a real and common state (`evaluate`
    is a deliberate, occasional CLI run, not something every training
    run triggers automatically).

    Reads a SEPARATE MLflow run from the version's own training run --
    `evaluate_and_log` (`ml/evaluate.py`) always starts a fresh
    `mlflow.start_run()` tagged `evaluation=true`/`evaluated_model`/
    `evaluated_version`, deliberately not appended to the training run
    (a walk-forward backtest can be re-run repeatedly against the same
    version as fresher data lands, and each run should be its own real,
    timestamped record, not silently overwrite the last one). This is
    also why `GET /v1/model/versions`' own `ModelVersionOut.metrics`
    can never surface real walk-forward numbers under an `eval_mape`
    key -- that key only ever exists on THIS separate run. Callers that
    want the honest, harder walk-forward MAPE (against a real
    seasonal-naive baseline, over multiple rolling origins) rather than
    the easier training-time `test_mape` need this function specifically.
    """

    def _fetch() -> EvaluationSummary | None:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        experiments = client.search_experiments()
        if not experiments:
            return None
        exp_ids = [exp.experiment_id for exp in experiments]
        runs = client.search_runs(
            exp_ids,
            filter_string=_evaluation_runs_filter(model_name, version),
            order_by=["start_time DESC"],
            max_results=1,
        )
        if not runs:
            return None
        run = runs[0]
        regions = _parse_evaluation_metrics(dict(run.data.metrics))
        if not regions:
            return None
        return EvaluationSummary(
            run_id=run.info.run_id,
            evaluated_at=datetime.fromtimestamp(run.info.start_time / 1000, tz=UTC),
            n_origins=int(float(run.data.params.get("n_origins", 0))),
            regions=regions,
        )

    return await asyncio.to_thread(_fetch)


async def get_evaluation_history(
    model_name: str, version: str, limit: int = 50
) -> list[EvaluationSummary]:
    """Every real walk-forward evaluation run ever logged for `version`
    (`get_latest_evaluation`'s identical query, without the `max_results
    =1`/`DESC`-only restriction), oldest first -- the real data source
    for a genuine "has this version's accuracy drifted over time" signal
    (dashboard Model Comparison page's "Stability" metric): compare the
    earliest run's `eval_mape` against the most recent one's, computed by
    the caller from real, independently-timestamped backtests, not a
    fabricated single "drift score" stored here. `[]` (not `None`) when
    `evaluate` has never been run for this version, or has only been run
    once -- both real, honest states a drift comparison simply can't be
    made from yet, same "empty is expected, not an error" convention
    `get_latest_evaluation` already follows.
    """

    def _fetch() -> list[EvaluationSummary]:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)
        experiments = client.search_experiments()
        if not experiments:
            return []
        exp_ids = [exp.experiment_id for exp in experiments]
        runs = client.search_runs(
            exp_ids,
            filter_string=_evaluation_runs_filter(model_name, version),
            order_by=["start_time ASC"],
            max_results=limit,
        )
        summaries = []
        for run in runs:
            regions = _parse_evaluation_metrics(dict(run.data.metrics))
            if not regions:
                continue
            summaries.append(
                EvaluationSummary(
                    run_id=run.info.run_id,
                    evaluated_at=datetime.fromtimestamp(
                        run.info.start_time / 1000, tz=UTC
                    ),
                    n_origins=int(float(run.data.params.get("n_origins", 0))),
                    regions=regions,
                )
            )
        return summaries

    return await asyncio.to_thread(_fetch)


class PromotionRejected(Exception):
    """Raised by `promote_version` when promoting to Production would
    replace a better-performing version with a worse one -- the "gated
    promotion" `data-pipeline/TODO.md`'s `ECO-M12` flags as unbuilt.
    The route (`api/v1/model/routes.py`) turns this into a 409."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


_PROMOTION_GATE_METRIC = "test_mape"  # lower is better


async def promote_version(
    model_name: str, version: str, stage: str, force: bool = False
) -> ModelVersionSummary:
    """Transitions `version` to `stage` in the MLflow registry.

    Promoting to `Production` is gated on two independent, real checks
    (`todo-model-training.md` Phase 8's "extend `promote_version`... not
    just compare one logged scalar"):

    1. **Training-time `test_mape`** (the original gate): if both the
       candidate and the current Production version have one logged,
       reject when the candidate's is worse (higher). Skipped when
       `force=True` -- see that param's own docstring (`schemas.model.
       create.PromoteModelRequest`) for the real case this exists for: a
       multi-region model's blended `test_mape` can fail this gate even
       when a real per-region walk-forward evaluation shows most regions
       genuinely improved, something this one scalar can't see.
    2. **Live evaluation gate** (Phase 4's `evaluate.run_live_evaluation_
       gate`, data-pipeline-side): if the candidate version carries a
       real `eval_gate_passed` *tag* set to `"False"`, reject outright --
       that tag means a real walk-forward backtest against *fresh*
       out-of-sample data already found this specific version wanting,
       something `test_mape` alone (a single split, current only as of
       *training* time) can't catch on its own (a version that overfit
       to a short recent incremental window can still show a fine
       `test_mape`). Reading this tag is not a service-boundary
       violation -- forecast-api never *runs* the evaluate harness
       itself (still `README.md`'s "forecast-api never trains" rule),
       it only reads a tag data-pipeline's own training/incremental
       pipeline already computed and persisted. **Never skipped by
       `force`** -- this is a real correctness signal from fresh
       out-of-sample data, not a blended-metric artifact.

    Neither gate blocks if its respective signal is simply *absent*
    (no logged `test_mape`, no `eval_gate_passed` tag at all -- e.g. an
    older version registered before Phase 4, or a full retrain that
    never went through the incremental live-eval-gate path) -- ungated
    is the honest fallback when a comparison genuinely can't be made,
    not silently rejecting for a reason that was never actually checked.

    No gate on Staging/Archived transitions -- those don't replace
    what's actually serving traffic.

    Promoting to `Production` also archives whatever version was
    previously in that stage (`archive_existing_versions=True`) -- the
    same "only one Production at a time" invariant the old mock's
    client-side `promote()` enforced, now real.
    """

    def _promote() -> ModelVersionSummary:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)

        candidate = client.get_model_version(model_name, version)
        assert candidate.run_id is not None  # nosec B101 -- internal invariant for type-narrowing, not a security check; a registered version always has a run_id
        run_id = candidate.run_id
        candidate_metrics = dict(client.get_run(run_id).data.metrics)

        if stage == "Production":
            eval_gate_passed = candidate.tags.get("eval_gate_passed")
            if eval_gate_passed == "False":
                eval_gate_mape = candidate.tags.get("eval_gate_mape")
                raise PromotionRejected(
                    f"version {version} failed its live evaluation gate "
                    f"(fresh walk-forward MAPE: {eval_gate_mape or 'unknown'}) -- "
                    "see evaluate.run_live_evaluation_gate"
                )
            # Real coverage/bias, surfaced (`TODO.md` Phase 4) for a
            # human/dashboard to see on ANY promotion attempt -- not just
            # a rejected one, and never itself a rejection reason (no
            # `raise` here). Deliberately visibility-only for now: watch
            # real tag values across a few real training cycles before
            # ever turning either into a hard gate, same real lesson
            # `_resolve_max_acceptable_mape`'s own 2026-08-12 fix already
            # cost this codebase once (a hastily-added MAPE-only
            # threshold that silently mis-rejected a good candidate by
            # comparing two non-comparable metrics).
            eval_gate_coverage = candidate.tags.get("eval_gate_coverage")
            eval_gate_bias_mw = candidate.tags.get("eval_gate_bias_mw")
            if eval_gate_coverage is not None or eval_gate_bias_mw is not None:
                log.info(
                    "promote_version.eval_gate_coverage_bias",
                    model_name=model_name,
                    version=version,
                    eval_gate_coverage=eval_gate_coverage,
                    eval_gate_bias_mw=eval_gate_bias_mw,
                )

            current = client.get_latest_versions(model_name, stages=["Production"])
            if current and not force:
                current_metrics = dict(client.get_run(current[0].run_id).data.metrics)
                candidate_mape = candidate_metrics.get(_PROMOTION_GATE_METRIC)
                current_mape = current_metrics.get(_PROMOTION_GATE_METRIC)
                if (
                    candidate_mape is not None
                    and current_mape is not None
                    and candidate_mape > current_mape
                ):
                    raise PromotionRejected(
                        f"version {version}'s {_PROMOTION_GATE_METRIC} "
                        f"({candidate_mape:.4f}) is worse than the current "
                        f"Production version's ({current_mape:.4f})"
                    )

        client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage=stage,
            archive_existing_versions=(stage == "Production"),
        )
        run = client.get_run(run_id)
        return ModelVersionSummary(
            version=candidate.version,
            stage=stage,
            run_id=run_id,
            created_at=datetime.fromtimestamp(
                candidate.creation_timestamp / 1000, tz=UTC
            ),
            metrics=dict(run.data.metrics),
            git_sha=run.data.tags.get("git_sha"),
        )

    return await asyncio.to_thread(_promote)


class DeletionRejected(Exception):
    """Raised by `delete_model_version` when deleting `version` would
    remove the currently-serving Production version out from under
    `forecast-api`'s live model. The route (`api/v1/model/routes.py`)
    turns this into a 409."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def delete_model_version(model_name: str, version: str) -> None:
    """Permanently removes `version` from the MLflow *registry* --
    the real training run underneath it (params/metrics/artifacts,
    including the `serving/model_state_dict.pt` weights) is untouched;
    `MlflowClient.delete_model_version` only ever deletes the registry
    entry pointing at it, a real MLflow behavior, not a limitation
    introduced here. Once deleted, the version stops appearing in
    `GET /v1/model/versions` and can no longer be promoted or served.

    Gated the same way `promote_version` already gates *Production*
    transitions, for the same reason: `ModelRegistry.watch` holds
    whichever version is currently `Production` in memory and serves
    live traffic from it. Deleting that registry entry wouldn't crash
    the already-running process, but would leave nothing to identify or
    roll back to afterward -- refuse outright rather than let an
    operator do that by accident. Staging/Archived/`None`-stage versions
    delete freely; they aren't what's actually serving.
    """

    def _delete() -> None:
        tracking_uri = get_settings().mlflow_tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        client = MlflowClient(tracking_uri=tracking_uri)

        candidate = client.get_model_version(model_name, version)
        if candidate.current_stage == "Production":
            raise DeletionRejected(
                f"version {version} is the current Production version -- "
                "demote it (e.g. Archive) before deleting"
            )

        client.delete_model_version(name=model_name, version=version)

    return await asyncio.to_thread(_delete)


class ModelRegistry:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._bundle: ModelBundle | None = None

    @property
    def bundle(self) -> ModelBundle | None:
        return self._bundle

    async def refresh(self) -> bool:
        """Loads the current `Production` version and swaps it in if
        it's a different version than what's currently held. Returns
        whether a swap happened (used by `/v1/readyz` to report "model
        loaded" and by tests)."""
        new_bundle = await load_bundle(self.model_name)
        if new_bundle is None:
            return False
        if self._bundle is not None and self._bundle.version == new_bundle.version:
            return False
        self._bundle = new_bundle
        log.info(
            "registry.model_loaded",
            model_name=self.model_name,
            version=new_bundle.version,
            run_id=new_bundle.run_id,
        )
        return True

    async def watch(self, interval_seconds: float) -> None:
        """Long-running background loop — `main.py`'s lifespan starts
        this as an `asyncio.Task` and cancels it on shutdown. A failed
        refresh is logged and retried next interval, not raised — MLflow
        being briefly unreachable shouldn't crash request serving using
        the last-known-good bundle."""
        while True:
            try:
                await self.refresh()
            except Exception as exc:
                log.error(
                    "registry.refresh_failed",
                    model_name=self.model_name,
                    error=str(exc),
                )
            await asyncio.sleep(interval_seconds)
