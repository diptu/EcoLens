"""`ecolens-pipeline` console-script entrypoint (ECO-D47/D48).

Click group: `ingest {oe,aemo-nem,aemo-wem,bom,holidays}`, `dbt
{build,run,test}`, `worker`, `train-worker`, `serve`, `health`. This is
what cron, GitHub Actions, and `docker exec` all call — the same code
path as the matching API endpoint (`app/api/v1/dbt/routes.py`,
`ingest.py`), via `app.service.pipeline.tasks.registry.run_source` /
`app.service.dbt_runner.run_dbt`. `worker`/`train-worker` have no
API-endpoint counterpart — they're long-running RabbitMQ consumers
(`app.service.worker.run`, `app.service.training_worker.run`), not one-shot
triggers.
"""

from __future__ import annotations

import asyncio
import sys

import click

from app import __version__
from app.core.config import get_settings
from app.service.dbt_runner import run_dbt
from app.db.session import get_session
from app.core.logging import configure_logging, get_logger
from app.service.pipeline.tasks.registry import run_source
from app.service.pipelines import is_pipeline_paused

log = get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="ecolens-pipeline")
def main() -> None:
    """ecoLens data-pipeline CLI."""
    configure_logging()


# ── ingest ───────────────────────────────────────────────────────────────


@main.group()
def ingest() -> None:
    """Trigger an ingestion source (same path `run_source()` uses for the API)."""


async def _run_ingest_async(
    key: str, triggered_by: str, call_kwargs: dict[str, object]
) -> int | None:
    """Returns `None` (not 0) if the run was skipped because its pipeline
    is paused — distinct from "ran and staged 0 rows" for `_run_ingest`'s
    exit-message branching."""
    if triggered_by == "schedule":
        async with get_session() as db:
            if await is_pipeline_paused(db, key):
                return None
    return await run_source(key, triggered_by=triggered_by, **call_kwargs)  # type: ignore[arg-type]


def _run_ingest(key: str, *, triggered_by: str = "manual", **kwargs: object) -> None:
    call_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    try:
        # call_kwargs only ever holds lookback_minutes/year -- see the
        # matching comment on api/routers/ingest.py's trigger_ingest.
        rows = asyncio.run(_run_ingest_async(key, triggered_by, call_kwargs))
    except Exception as exc:
        click.echo(f"{key}: failed — {exc}", err=True)
        sys.exit(1)
    if rows is None:
        # A paused pipeline isn't a failure -- GitHub Actions' cron step
        # should exit 0 so the run shows as skipped, not red.
        click.echo(
            f"{key}: skipped — pipeline is paused (see GET /v1/ingestion/pipelines)"
        )
        return
    click.echo(f"{key}: {rows} rows staged (warehouse sync runs asynchronously)")


_TRIGGERED_BY_OPTION = click.option(
    "--triggered-by",
    type=click.Choice(["manual", "schedule", "backfill"]),
    default="manual",
    help="Recorded on meta._ingest_log; 'schedule' is also the only value "
    "that respects a paused pipeline (GitHub Actions workflows pass this).",
)


@ingest.command("oe")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_oe(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest("oe", triggered_by=triggered_by, lookback_minutes=lookback_minutes)


@ingest.command("aemo-nem")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_aemo_nem_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest(
        "aemo-nem", triggered_by=triggered_by, lookback_minutes=lookback_minutes
    )


@ingest.command("aemo-wem")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_aemo_wem_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest(
        "aemo-wem", triggered_by=triggered_by, lookback_minutes=lookback_minutes
    )


@ingest.command("bom")
@click.option("--lookback-minutes", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_bom_cmd(lookback_minutes: int | None, triggered_by: str) -> None:
    _run_ingest("bom", triggered_by=triggered_by, lookback_minutes=lookback_minutes)


@ingest.command("holidays")
@click.option("--year", type=int, default=None)
@_TRIGGERED_BY_OPTION
def ingest_holidays_cmd(year: int | None, triggered_by: str) -> None:
    _run_ingest("holidays", triggered_by=triggered_by, year=year)


# ── dbt ──────────────────────────────────────────────────────────────────


@main.group()
def dbt() -> None:
    """Run a dbt subcommand (same path `POST /v1/dbt/{subcommand}` uses)."""


def _run_dbt(subcommand: str, target: str | None, extra_args: tuple[str, ...]) -> None:
    settings = get_settings()
    resolved_target = target or settings.dbt_target
    exit_code = run_dbt(
        subcommand, settings.dbt_project_dir, resolved_target, list(extra_args)
    )
    if exit_code != 0:
        click.echo(f"dbt {subcommand}: failed — exit code {exit_code}", err=True)
        sys.exit(exit_code)
    click.echo(f"dbt {subcommand}: succeeded")


@dbt.command("build")
@click.option("--target", default=None)
@click.argument("extra_args", nargs=-1)
def dbt_build(target: str | None, extra_args: tuple[str, ...]) -> None:
    _run_dbt("build", target, extra_args)


@dbt.command("run")
@click.option("--target", default=None)
@click.argument("extra_args", nargs=-1)
def dbt_run(target: str | None, extra_args: tuple[str, ...]) -> None:
    _run_dbt("run", target, extra_args)


@dbt.command("test")
@click.option("--target", default=None)
@click.argument("extra_args", nargs=-1)
def dbt_test(target: str | None, extra_args: tuple[str, ...]) -> None:
    _run_dbt("test", target, extra_args)


# ── train / tune ─────────────────────────────────────────────────────────


@main.command()
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--model-name",
    default=None,
    help="MLflow registered model name (default: Settings.mlflow_registry_model_name).",
)
@click.option(
    "--epochs", type=int, default=None, help="Override Settings.model_train_epochs."
)
@click.option(
    "--since",
    default=None,
    help="ISO date (YYYY-MM-DD) -- scope training data to ts >= this date. "
    "Needed when the real history for some feature (e.g. total_generation_mw) "
    "only covers a recent window: the 70/15/15 split is chronological over "
    "*all* history in the query, so without --since, real data confined to "
    "a recent window mostly lands in the test split and starves "
    "train/val/calibration (see train_and_register's own docstring).",
)
@click.option(
    "--no-register",
    is_flag=True,
    default=False,
    help="Log to MLflow but skip registering a model version.",
)
def train(
    regions: tuple[str, ...],
    model_name: str | None,
    epochs: int | None,
    since: str | None,
    no_register: bool,
) -> None:
    """Train the demand-forecast LSTM and log (+ register) it in MLflow
    (`README.md` § ML pipeline, ECO-D50). Never promotes to Production —
    see `scripts/promote_model.sh`."""
    from dataclasses import replace

    import pandas as pd

    from app.service.ml.train import TrainConfig, train_and_register

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name
    config = TrainConfig.from_settings(settings)
    if epochs is not None:
        config = replace(config, epochs=epochs)
    resolved_since = pd.Timestamp(since, tz="UTC") if since else None

    try:
        result = asyncio.run(
            train_and_register(
                resolved_model_name,
                resolved_regions,
                settings=settings,
                config=config,
                register=not no_register,
                since=resolved_since,
            )
        )
    except Exception as exc:
        click.echo(f"train: failed — {exc}", err=True)
        sys.exit(1)

    registration = (
        f"registered as {resolved_model_name} v{result.model_version}"
        if result.model_version
        else "not registered (--no-register)"
    )
    click.echo(f"train: run {result.run_id} logged, {registration}")
    if result.test_metrics:
        click.echo(
            "  test_mape={:.2f} test_coverage_calibrated={:.2f}".format(
                result.test_metrics.get("test_mape", float("nan")),
                result.test_metrics.get("test_coverage_calibrated", float("nan")),
            )
        )


@main.command("train-tft")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--model-name",
    default="lstm_demand_tft",
    show_default=True,
    help="MLflow registered model name -- deliberately NOT "
    "Settings.mlflow_registry_model_name (lstm_demand): a v1 TFT and a "
    "vN LSTM aren't comparable versions of the same registered model "
    "(todo-model-training.md Phase 2's own naming-discipline note).",
)
@click.option(
    "--epochs", type=int, default=None, help="Override Settings.model_train_epochs."
)
@click.option(
    "--since",
    default=None,
    help="ISO date (YYYY-MM-DD) -- scope training data to ts >= this date. "
    "Same reasoning as `train`'s own --since (see its help text).",
)
@click.option(
    "--no-register",
    is_flag=True,
    default=False,
    help="Log to MLflow but skip registering a model version.",
)
def train_tft(
    regions: tuple[str, ...],
    model_name: str,
    epochs: int | None,
    since: str | None,
    no_register: bool,
) -> None:
    """Train the demand-forecast TFT (hand-rolled -- see `app/models/
    tft.py`'s module docstring for why, `todo-model-training.md` Phase 2)
    and log (+ register) it in MLflow, under its own `lstm_demand_tft`
    registry entry, never `lstm_demand`. Never promotes to Production."""
    from dataclasses import replace

    import pandas as pd

    from app.service.ml.train_tft import TFTTrainConfig, train_and_register_tft

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    config = TFTTrainConfig.from_settings(settings)
    if epochs is not None:
        config = replace(config, epochs=epochs)
    resolved_since = pd.Timestamp(since, tz="UTC") if since else None

    try:
        result = asyncio.run(
            train_and_register_tft(
                model_name,
                resolved_regions,
                settings=settings,
                config=config,
                register=not no_register,
                since=resolved_since,
            )
        )
    except Exception as exc:
        click.echo(f"train-tft: failed — {exc}", err=True)
        sys.exit(1)

    registration = (
        f"registered as {model_name} v{result.model_version}"
        if result.model_version
        else "not registered (--no-register)"
    )
    click.echo(f"train-tft: run {result.run_id} logged, {registration}")
    if result.test_metrics:
        click.echo(
            "  test_mape={:.2f} test_coverage_calibrated={:.2f}".format(
                result.test_metrics.get("test_mape", float("nan")),
                result.test_metrics.get("test_coverage_calibrated", float("nan")),
            )
        )


@main.command()
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
def tune(regions: tuple[str, ...]) -> None:
    """Small grid search over hidden_size/lr, each trial logged to MLflow
    (`TODO.md`'s Forecasting section item 6 — a plain grid, not Optuna;
    see `tune-optuna` for the real Optuna search)."""
    from app.service.ml.tune import tune as run_tune

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions

    try:
        result = asyncio.run(run_tune(resolved_regions, settings=settings))
    except Exception as exc:
        click.echo(f"tune: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(
        "tune: {} trials, best val_mape={:.2f} (hidden_size={}, lr={}, run={})".format(
            len(result.trials),
            result.best_val_mape,
            result.best_config.hidden_size,
            result.best_config.lr,
            result.best_run_id,
        )
    )


@main.command("tune-optuna")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--model-name",
    default=None,
    help="MLflow registered model name (default: Settings.mlflow_registry_model_name).",
)
@click.option(
    "--n-trials", type=int, default=20, show_default=True, help="Optuna trial count."
)
@click.option(
    "--tune-epochs",
    type=int,
    default=15,
    show_default=True,
    help="Reduced per-trial epoch budget used during the search.",
)
@click.option(
    "--data-source",
    type=click.Choice(["fct_energy_demand", "ml_features_v1"]),
    default="fct_energy_demand",
    show_default=True,
    help="fct_energy_demand: dbt-tracked, ~55K rows. ml_features_v1: the "
    "orphaned ml.ml_features_demand_v1 table, ~104K rows, 66% imputed -- "
    "see ml/data.py's load_ml_features_v1_training_data.",
)
@click.option(
    "--train-frac", type=float, default=None, help="Override TrainConfig.train_frac."
)
@click.option(
    "--val-frac", type=float, default=None, help="Override TrainConfig.val_frac."
)
@click.option(
    "--epochs",
    type=int,
    default=None,
    help="Full epoch budget for the final retrain of the winning config "
    "(default: Settings.model_train_epochs) -- NOT --tune-epochs, which "
    "only applies to search trials.",
)
@click.option(
    "--no-register",
    is_flag=True,
    default=False,
    help="Search + final retrain, but skip registering the result.",
)
def tune_optuna_cmd(
    regions: tuple[str, ...],
    model_name: str | None,
    n_trials: int,
    tune_epochs: int,
    data_source: str,
    train_frac: float | None,
    val_frac: float | None,
    epochs: int | None,
    no_register: bool,
) -> None:
    """Real Optuna TPE search over hidden_size/num_layers/dropout/lr/
    batch_size (`ml/tune.py`'s `tune_optuna`), then retrains the winning
    config at full epoch budget on the real train/val/test split and
    registers it — a real end-to-end tune-then-train run, not just a
    search report. Each search trial AND the final run are logged to
    MLflow individually."""
    from dataclasses import replace

    from app.service.ml.train import train_and_register
    from app.service.ml.tune import tune_optuna as run_tune_optuna

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name

    # Both awaited inside one `asyncio.run()` call, deliberately -- the DB
    # engine (`app.db.session.get_engine`) is a process-wide `@lru_cache`d
    # singleton whose pooled connections are bound to whichever event loop
    # was running when they were opened. Two separate `asyncio.run()`
    # calls in a row (search, then a second one for the final retrain)
    # leaves the search's connections bound to a loop `asyncio.run()`
    # already tore down -- the final retrain then crashes reusing them
    # ("attached to a different loop" / "Event loop is closed"), confirmed
    # by hitting this for real against the live warehouse. One shared loop
    # for both steps avoids it entirely.
    async def _search_then_retrain():
        search = await run_tune_optuna(
            resolved_regions,
            settings=settings,
            n_trials=n_trials,
            tune_epochs=tune_epochs,
            data_source=data_source,  # type: ignore[arg-type]
            train_frac=train_frac,
            val_frac=val_frac,
        )
        final_config = replace(
            search.best_config,
            epochs=epochs if epochs is not None else settings.model_train_epochs,
            early_stopping_patience=settings.model_early_stopping_patience,
        )
        final_result = await train_and_register(
            resolved_model_name,
            resolved_regions,
            settings=settings,
            config=final_config,
            register=not no_register,
            data_source=data_source,
            extra_tags={
                "tuning_method": "optuna",
                "optuna_search_run_id": search.best_run_id,
            },
        )
        return search, final_result

    try:
        search, final_result = asyncio.run(_search_then_retrain())
    except Exception as exc:
        click.echo(f"tune-optuna: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(
        "tune-optuna: {} trials ({} pruned), best val_mape={:.2f} "
        "(hidden_size={}, num_layers={}, dropout={:.3f}, lr={:.5f}, "
        "batch_size={}, search_run={})".format(
            len(search.trials),
            search.n_pruned_trials,
            search.best_val_mape,
            search.best_config.hidden_size,
            search.best_config.num_layers,
            search.best_config.dropout,
            search.best_config.lr,
            search.best_config.batch_size,
            search.best_run_id,
        )
    )
    if search.imputed_fraction is not None:
        click.echo(
            f"  data_source={data_source} imputed_fraction={search.imputed_fraction:.3f}"
        )

    registration = (
        f"registered as {resolved_model_name} v{final_result.model_version}"
        if final_result.model_version
        else "not registered (--no-register)"
    )
    click.echo(f"tune-optuna: final run {final_result.run_id} logged, {registration}")
    if final_result.test_metrics:
        click.echo(
            "  test_mape={:.2f} test_coverage_calibrated={:.2f}".format(
                final_result.test_metrics.get("test_mape", float("nan")),
                final_result.test_metrics.get("test_coverage_calibrated", float("nan")),
            )
        )


@main.command()
@click.option(
    "--model-name",
    default=None,
    help="MLflow registered model name (default: Settings.mlflow_registry_model_name).",
)
@click.option(
    "--version", required=True, help="Registered model version to evaluate (e.g. 1)."
)
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to evaluate on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--horizon",
    type=int,
    default=None,
    help="Override the forecast horizon (default: the evaluated version's own trained horizon).",
)
@click.option(
    "--n-origins",
    type=int,
    default=10,
    help="Number of rolling-origin forecasts to walk forward over, per region.",
)
def evaluate(
    model_name: str | None,
    version: str,
    regions: tuple[str, ...],
    horizon: int | None,
    n_origins: int,
) -> None:
    """Real walk-forward backtest of a registered model version against
    the seasonal-naive baseline (`todo-model-training.md` Phase 0,
    `service/ml/evaluate.py`), logged to MLflow tagged `evaluation`."""
    from app.service.ml.evaluate import evaluate_and_log

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name

    try:
        result = asyncio.run(
            evaluate_and_log(
                resolved_model_name,
                version,
                resolved_regions,
                settings=settings,
                horizon=horizon,
                n_origins=n_origins,
            )
        )
    except Exception as exc:
        click.echo(f"evaluate: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(f"evaluate: run {result.run_id} logged")
    for report in result.reports:
        click.echo(
            "  {}/{}: mape={:.2f} rmse={:.1f} coverage={:.2f} (n_origins={})".format(
                report.region,
                report.model_name,
                report.mape,
                report.rmse,
                report.empirical_coverage,
                report.n_origins,
            )
        )


@main.command("prune")
@click.option(
    "--model-name",
    default=None,
    help="MLflow registered model name (default: Settings.mlflow_registry_model_name). LSTM only -- see prune.py's module docstring.",
)
@click.option(
    "--version", required=True, help="Registered LSTM version to prune (e.g. 1)."
)
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to recovery-fine-tune and evaluate on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--keep-fraction",
    type=float,
    default=0.5,
    help="Fraction of LSTM hidden units to keep (e.g. 0.5 = prune half).",
)
@click.option(
    "--max-regression-pct",
    type=float,
    default=2.0,
    help="Max acceptable relative walk-forward MAPE regression vs. the unpruned version, in percent.",
)
@click.option(
    "--no-register",
    is_flag=True,
    default=False,
    help="Benchmark + recovery-fine-tune but skip registering the result.",
)
def prune(
    model_name: str | None,
    version: str,
    regions: tuple[str, ...],
    keep_fraction: float,
    max_regression_pct: float,
    no_register: bool,
) -> None:
    """Real structured pruning + fine-tune recovery for a registered LSTM
    version (`todo-model-training.md` Phase 5, `service/ml/prune.py`):
    structurally compacts the model, benchmarks real param count/on-disk
    size/CPU latency before vs. after, recovery-fine-tunes the compacted
    model, and gates registration on both a real accuracy-tolerance check
    and a real measured size/latency win. Reports an honest outcome
    either way -- "pruning wasn't worth it at this model size" is a
    legitimate real result, not a failure."""
    from app.service.ml.prune import prune_and_recover

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name

    try:
        result = asyncio.run(
            prune_and_recover(
                resolved_model_name,
                version,
                resolved_regions,
                keep_fraction,
                settings=settings,
                max_relative_mape_regression_pct=max_regression_pct,
                register=not no_register,
            )
        )
    except Exception as exc:
        click.echo(f"prune: failed — {exc}", err=True)
        sys.exit(1)

    b = result.benchmark
    click.echo(f"prune: run {result.recovered_run_id} logged")
    click.echo(
        "  params: {} -> {} ({:.1f}% reduction)".format(
            b.original_param_count, b.pruned_param_count, b.param_reduction_pct
        )
    )
    click.echo(
        "  artifact size: {} -> {} bytes ({:.1f}% reduction)".format(
            b.original_artifact_bytes, b.pruned_artifact_bytes, b.size_reduction_pct
        )
    )
    click.echo(
        "  CPU latency: {:.2f}ms -> {:.2f}ms ({:+.1f}%)".format(
            b.original_latency_ms, b.pruned_latency_ms, b.latency_change_pct
        )
    )
    click.echo(
        "  eval MAPE: {:.2f} -> {:.2f} ({:+.1f}% relative)".format(
            result.unpruned_eval_mape,
            result.recovered_eval_mape,
            result.relative_mape_regression_pct,
        )
    )
    click.echo(
        "  size/latency win: {}  accuracy within tolerance: {}  GATE: {}".format(
            result.achieves_size_latency_win,
            result.passes_accuracy_tolerance,
            "PASSED" if result.gate_passed else "FAILED",
        )
    )
    if result.recovered_model_version:
        click.echo(
            f"  registered as {resolved_model_name} v{result.recovered_model_version}"
        )
    else:
        click.echo("  not registered (--no-register)")


@main.command("evaluate-tft")
@click.option(
    "--model-name",
    default="lstm_demand_tft",
    show_default=True,
    help="MLflow registered model name -- deliberately NOT "
    "Settings.mlflow_registry_model_name; see `train-tft --model-name`'s help.",
)
@click.option(
    "--version",
    required=True,
    help="Registered TFT model version to evaluate (e.g. 1).",
)
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to evaluate on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--horizon",
    type=int,
    default=None,
    help="Override the forecast horizon (default: the evaluated version's own trained horizon).",
)
@click.option(
    "--n-origins",
    type=int,
    default=10,
    help="Number of rolling-origin forecasts to walk forward over, per region.",
)
def evaluate_tft(
    model_name: str,
    version: str,
    regions: tuple[str, ...],
    horizon: int | None,
    n_origins: int,
) -> None:
    """Real walk-forward backtest of a registered TFT version against
    the seasonal-naive baseline (`todo-model-training.md` Phase 2,
    `service/ml/evaluate.py`), logged to MLflow tagged `evaluation`."""
    from app.service.ml.evaluate import evaluate_tft_and_log

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions

    try:
        result = asyncio.run(
            evaluate_tft_and_log(
                model_name,
                version,
                resolved_regions,
                settings=settings,
                horizon=horizon,
                n_origins=n_origins,
            )
        )
    except Exception as exc:
        click.echo(f"evaluate-tft: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(f"evaluate-tft: run {result.run_id} logged")
    for report in result.reports:
        click.echo(
            "  {}/{}: mape={:.2f} rmse={:.1f} coverage={:.2f} (n_origins={})".format(
                report.region,
                report.model_name,
                report.mape,
                report.rmse,
                report.empirical_coverage,
                report.n_origins,
            )
        )


@main.command("evaluate-timesfm")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to evaluate on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--horizon",
    type=int,
    default=6,
    help="Forecast horizon in steps -- TimesFM is zero-shot, so this has no trained default.",
)
@click.option(
    "--n-origins",
    type=int,
    default=10,
    help="Number of rolling-origin forecasts to walk forward over, per region.",
)
@click.option(
    "--max-context",
    type=int,
    default=None,
    help="Override TimesFM's max_context (default: app.models.timesfm_adapter.DEFAULT_MAX_CONTEXT).",
)
def evaluate_timesfm(
    regions: tuple[str, ...], horizon: int, n_origins: int, max_context: int | None
) -> None:
    """Real walk-forward backtest of TimesFM (zero-shot, no MLflow-
    registered version -- `todo-model-training.md` Phase 1,
    `service/ml/evaluate.py`) against the seasonal-naive baseline, logged
    to MLflow tagged `evaluation`. Downloads/compiles a real ~200M-param
    checkpoint the first time -- expect this to take real wall-clock time,
    not `evaluate`'s near-instant baseline/LSTM comparison."""
    from app.models.timesfm_adapter import DEFAULT_MAX_CONTEXT
    from app.service.ml.evaluate import evaluate_timesfm_and_log

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions

    try:
        result = asyncio.run(
            evaluate_timesfm_and_log(
                resolved_regions,
                settings=settings,
                horizon=horizon,
                n_origins=n_origins,
                max_context=max_context or DEFAULT_MAX_CONTEXT,
            )
        )
    except Exception as exc:
        click.echo(f"evaluate-timesfm: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(f"evaluate-timesfm: run {result.run_id} logged")
    for report in result.reports:
        click.echo(
            "  {}/{}: mape={:.2f} rmse={:.1f} coverage={:.2f} (n_origins={})".format(
                report.region,
                report.model_name,
                report.mape,
                report.rmse,
                report.empirical_coverage,
                report.n_origins,
            )
        )


# ── auth ─────────────────────────────────────────────────────────────────


@main.group()
def auth() -> None:
    """Manage `meta.api_users` (`POST /v1/auth/token`'s credential store)."""


@auth.command("create-user")
@click.option("--username", required=True)
@click.option(
    "--password",
    help="Prompted for (hidden) if not given — passing it here leaves it in your shell history.",
)
@click.option("--role", type=click.Choice(["admin", "analyst"]), required=True)
def auth_create_user(username: str, password: str | None, role: str) -> None:
    """Create a user that can authenticate via `POST /v1/auth/token`."""
    from app.service.auth import create_user

    if password is None:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)

    async def _create() -> str:
        async with get_session() as db:
            return await create_user(db, username, password, role)

    try:
        user_id = asyncio.run(_create())
    except Exception as exc:
        click.echo(f"auth create-user: failed — {exc}", err=True)
        sys.exit(1)
    click.echo(f"auth create-user: created {username!r} (role={role}, id={user_id})")


# ── serve / health ──────────────────────────────────────────────────────


@main.command()
def health() -> None:
    """Liveness check — mirrors `GET /v1/healthz`'s response shape."""
    from app.schemas.health import HealthResponse

    click.echo(HealthResponse().model_dump_json())


@main.command()
def worker() -> None:
    """Run the warehouse-sync consumer (RabbitMQ -> DuckDB read -> Postgres
    `raw.*` load). Long-running — same process the `warehouse-sync`
    docker-compose service runs; see `app.service.worker.run`."""
    from app.service.worker import run as run_worker

    asyncio.run(run_worker())


@main.command("train-worker")
def train_worker() -> None:
    """Run the training-trigger consumer (RabbitMQ -> warm-started
    incremental fine-tune -> MLflow). Long-running — same process the
    `train-worker` docker-compose service runs; see
    `app.service.training_worker.run`. `TODO.md`'s Event-Driven Pipeline
    Trigger section, item 3."""
    from app.service.training_worker import run as run_train_worker

    asyncio.run(run_train_worker())


@main.command()
@click.option("--host", default="0.0.0.0")  # nosec B104 -- must bind all interfaces to be reachable in a container (matches ECO-D49's Dockerfile CMD)
@click.option("--port", type=int, default=None)
@click.option("--reload", is_flag=True, default=False)
def serve(host: str, port: int | None, reload: bool) -> None:
    """Run the FastAPI app with uvicorn (equivalent to `uvicorn app.main:app`)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=host, port=port or settings.api_port, reload=reload
    )


if __name__ == "__main__":
    main()
