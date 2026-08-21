"""`ecolens-forecast` console-script entrypoint.

Click group for the training/tuning/evaluation/pruning commands ported
from `data-pipeline`'s identical `app/cli.py` as part of the training-
code migration -- this service trains now, not just serves (see
`README.md`'s updated service-boundary note). Deliberately narrower than
data-pipeline's CLI: no `ingest`/`dbt` groups (those stay with
`services/ingestion`/`services/waerehouse`, whose jobs those actually
are) -- just the ML surface this service now owns.

`serve` isn't a command here -- this service is still started the same
way it always was (`uvicorn app.main:app`, `infra/docker/
forecast-api.Dockerfile`), this CLI is additive for the new training
commands, not a replacement entrypoint for the API itself.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import click

from app import __version__
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing

log = get_logger(__name__)


@click.group()
@click.version_option(__version__, prog_name="ecolens-forecast")
def main() -> None:
    """ecoLens forecast-api CLI (training/tuning/evaluation/pruning)."""
    configure_logging()
    configure_tracing()


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
@click.option(
    "--source",
    "data_source",
    type=click.Choice(["fct_energy_demand", "r2_master", "ml_features_v1"]),
    default="fct_energy_demand",
    show_default=True,
    help="fct_energy_demand: live Postgres marts (~60-day retention). "
    "r2_master: master.duckdb's real ~1-year bootstrap history (2025-07-31 "
    "on), never touches Postgres. ml_features_v1: orphaned ml.* table, see "
    "ml/data.py's load_ml_features_v1_training_data.",
)
@click.option("--lr", type=float, default=None, help="Override Settings.model_train_lr.")
@click.option(
    "--patience",
    "early_stopping_patience",
    type=int,
    default=None,
    help="Override Settings.model_early_stopping_patience.",
)
@click.option(
    "--quantile-weight",
    type=float,
    default=None,
    help="Override Settings.model_quantile_weight.",
)
@click.option(
    "--hidden-size",
    type=int,
    default=None,
    help="Override Settings.model_hidden_size (LSTM hidden units per layer).",
)
@click.option(
    "--num-layers",
    type=int,
    default=None,
    help="Override Settings.model_num_layers (stacked LSTM layers).",
)
@click.option(
    "--dropout", type=float, default=None, help="Override Settings.model_dropout."
)
@click.option(
    "--train-frac",
    type=float,
    default=None,
    help="Override TrainConfig.train_frac (fraction-based split -- see split_by_time's "
    "own docstring for why this is chronological, not a random shuffle).",
)
@click.option(
    "--val-frac",
    type=float,
    default=None,
    help="Override TrainConfig.val_frac. Test is implicitly 1 - train_frac - val_frac.",
)
@click.option(
    "--shuffle/--no-shuffle",
    default=True,
    show_default=True,
    help="Reshuffle train_loader each epoch.",
)
@click.option(
    "--train-start", default=None, help="ISO date -- start of an explicit train window."
)
@click.option(
    "--train-end", default=None, help="ISO date -- end of an explicit train window."
)
@click.option(
    "--val-start", default=None, help="ISO date -- start of an explicit val window."
)
@click.option("--val-end", default=None, help="ISO date -- end of an explicit val window.")
@click.option(
    "--test-start", default=None, help="ISO date -- start of an explicit test window."
)
@click.option(
    "--test-end", default=None, help="ISO date -- end of an explicit test window."
)
def train(
    regions: tuple[str, ...],
    model_name: str | None,
    epochs: int | None,
    since: str | None,
    no_register: bool,
    data_source: str,
    lr: float | None,
    early_stopping_patience: int | None,
    quantile_weight: float | None,
    hidden_size: int | None,
    num_layers: int | None,
    dropout: float | None,
    train_frac: float | None,
    val_frac: float | None,
    shuffle: bool,
    train_start: str | None,
    train_end: str | None,
    val_start: str | None,
    val_end: str | None,
    test_start: str | None,
    test_end: str | None,
) -> None:
    """Train the demand-forecast LSTM and log (+ register) it in MLflow.
    Never promotes to Production."""
    from dataclasses import replace

    import pandas as pd

    from app.service.ml.train import TrainConfig, train_and_register

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name
    config = TrainConfig.from_settings(settings)

    overrides: dict[str, Any] = {"shuffle": shuffle}
    if epochs is not None:
        overrides["epochs"] = epochs
    if lr is not None:
        overrides["lr"] = lr
    if early_stopping_patience is not None:
        overrides["early_stopping_patience"] = early_stopping_patience
    if quantile_weight is not None:
        overrides["quantile_weight"] = quantile_weight
    if hidden_size is not None:
        overrides["hidden_size"] = hidden_size
    if num_layers is not None:
        overrides["num_layers"] = num_layers
    if dropout is not None:
        overrides["dropout"] = dropout
    if train_frac is not None:
        overrides["train_frac"] = train_frac
    if val_frac is not None:
        overrides["val_frac"] = val_frac

    date_fields = {
        "train_start": train_start,
        "train_end": train_end,
        "val_start": val_start,
        "val_end": val_end,
        "test_start": test_start,
        "test_end": test_end,
    }
    if any(date_fields.values()):
        missing = [name for name, value in date_fields.items() if value is None]
        if missing:
            click.echo(
                f"train: failed — explicit date split needs all six --*-start/--*-end "
                f"options, missing: {', '.join(missing)}",
                err=True,
            )
            sys.exit(1)
        for name, value in date_fields.items():
            overrides[name] = pd.Timestamp(value, tz="UTC")

    config = replace(config, **overrides)
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
                data_source=data_source,
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
    "vN LSTM aren't comparable versions of the same registered model.",
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
@click.option(
    "--source",
    "data_source",
    type=click.Choice(["fct_energy_demand", "r2_master"]),
    default="fct_energy_demand",
    show_default=True,
    help="fct_energy_demand: live Postgres marts (~60-day retention). "
    "r2_master: master.duckdb's real ~1-year bootstrap history (2025-07-31 "
    "on), never touches Postgres.",
)
@click.option("--lr", type=float, default=None, help="Override Settings.model_train_lr.")
@click.option(
    "--patience",
    "early_stopping_patience",
    type=int,
    default=None,
    help="Override Settings.model_early_stopping_patience.",
)
@click.option(
    "--quantile-weight",
    type=float,
    default=None,
    help="Override Settings.model_quantile_weight.",
)
@click.option(
    "--shuffle/--no-shuffle",
    default=True,
    show_default=True,
    help="Reshuffle train_loader each epoch.",
)
@click.option(
    "--train-start", default=None, help="ISO date -- start of an explicit train window."
)
@click.option(
    "--train-end", default=None, help="ISO date -- end of an explicit train window."
)
@click.option(
    "--val-start", default=None, help="ISO date -- start of an explicit val window."
)
@click.option("--val-end", default=None, help="ISO date -- end of an explicit val window.")
@click.option(
    "--test-start", default=None, help="ISO date -- start of an explicit test window."
)
@click.option(
    "--test-end", default=None, help="ISO date -- end of an explicit test window."
)
def train_tft(
    regions: tuple[str, ...],
    model_name: str,
    epochs: int | None,
    since: str | None,
    no_register: bool,
    data_source: str,
    lr: float | None,
    early_stopping_patience: int | None,
    quantile_weight: float | None,
    shuffle: bool,
    train_start: str | None,
    train_end: str | None,
    val_start: str | None,
    val_end: str | None,
    test_start: str | None,
    test_end: str | None,
) -> None:
    """Train the demand-forecast TFT and log (+ register) it in MLflow,
    under its own `lstm_demand_tft` registry entry, never `lstm_demand`.
    Never promotes to Production."""
    from dataclasses import replace

    import pandas as pd

    from app.service.ml.train_tft import TFTTrainConfig, train_and_register_tft

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    config = TFTTrainConfig.from_settings(settings)

    overrides: dict[str, Any] = {"shuffle": shuffle}
    if epochs is not None:
        overrides["epochs"] = epochs
    if lr is not None:
        overrides["lr"] = lr
    if early_stopping_patience is not None:
        overrides["early_stopping_patience"] = early_stopping_patience
    if quantile_weight is not None:
        overrides["quantile_weight"] = quantile_weight

    date_fields = {
        "train_start": train_start,
        "train_end": train_end,
        "val_start": val_start,
        "val_end": val_end,
        "test_start": test_start,
        "test_end": test_end,
    }
    if any(date_fields.values()):
        missing = [name for name, value in date_fields.items() if value is None]
        if missing:
            click.echo(
                f"train-tft: failed — explicit date split needs all six --*-start/--*-end "
                f"options, missing: {', '.join(missing)}",
                err=True,
            )
            sys.exit(1)
        for name, value in date_fields.items():
            overrides[name] = pd.Timestamp(value, tz="UTC")

    config = replace(config, **overrides)
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
                data_source=data_source,
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


@main.command("train-energy-forecast")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--model-name",
    default="energy_forecast_multi_task",
    show_default=True,
    help="MLflow registered model name -- its own entry, same naming-"
    "discipline reasoning as train-tft's --model-name.",
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
@click.option(
    "--source",
    type=click.Choice(["postgres", "r2_master"]),
    default="postgres",
    show_default=True,
    help="'postgres' reads raw_marts.fct_energy_demand (needs a real dbt "
    "build). 'r2_master' bootstraps from the R2-hosted master.duckdb "
    "instead (see energy_data_offline.py's docstring) -- for training "
    "before the Postgres marts are populated.",
)
def train_energy_forecast(
    regions: tuple[str, ...],
    model_name: str,
    epochs: int | None,
    since: str | None,
    no_register: bool,
    source: str,
) -> None:
    """Train the multi-task demand + generation-mix forecast LSTM
    (`app/models/energy_forecast_lstm.py`) and log (+ register) it in
    MLflow, under its own `energy_forecast_multi_task` registry entry.
    No conformal calibration this pass. Never promotes to Production."""
    from dataclasses import replace

    import pandas as pd

    from app.service.ml.train_energy_forecast import (
        EnergyTrainConfig,
        train_and_register_energy_forecast,
    )

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    config = EnergyTrainConfig.from_settings(settings)
    if epochs is not None:
        config = replace(config, epochs=epochs)
    resolved_since = pd.Timestamp(since, tz="UTC") if since else None

    try:
        result = asyncio.run(
            train_and_register_energy_forecast(
                resolved_regions,
                model_name=model_name,
                settings=settings,
                config=config,
                register=not no_register,
                since=resolved_since,
                source=source,
            )
        )
    except Exception as exc:
        click.echo(f"train-energy-forecast: failed — {exc}", err=True)
        sys.exit(1)

    registration = (
        f"registered as {model_name} v{result.model_version}"
        if result.model_version
        else "not registered (--no-register)"
    )
    click.echo(f"train-energy-forecast: run {result.run_id} logged, {registration}")
    if result.test_metrics:
        click.echo(
            "  demand_test_mape={:.2f} generation_test_mape={:.2f}".format(
                result.test_metrics.get("demand_test_mape", float("nan")),
                result.test_metrics.get("generation_test_mape", float("nan")),
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
    """Small grid search over hidden_size/lr, each trial logged to
    MLflow (a plain grid, not Optuna -- see `tune-optuna` for the real
    Optuna search)."""
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
    help="fct_energy_demand: dbt-tracked. ml_features_v1: the orphaned "
    "ml.ml_features_demand_v1 table -- see ml/data.py's "
    "load_ml_features_v1_training_data.",
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
    registers it."""
    from dataclasses import replace

    from app.service.ml.train import train_and_register
    from app.service.ml.tune import tune_optuna as run_tune_optuna

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name

    # Both awaited inside one `asyncio.run()` call, deliberately -- see
    # data-pipeline's identical comment (the DB engine's pooled
    # connections are bound to whichever event loop was running when
    # they were opened; two separate `asyncio.run()` calls would crash
    # the second one reusing connections from a torn-down loop).
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
    the seasonal-naive baseline, logged to MLflow tagged `evaluation`."""
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
    help="MLflow registered model name (default: Settings.mlflow_registry_model_name). LSTM only.",
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
    default=1.0,
    help="Max acceptable relative walk-forward MAPE regression vs. the unpruned version, in percent.",
)
@click.option(
    "--recovery-epochs",
    type=int,
    default=None,
    help=(
        "Recovery-fine-tune epochs (default: Settings.prune_recovery_epochs, 20). "
        "A more aggressive --keep-fraction may need more than the default to "
        "converge within --max-regression-pct -- see Settings.prune_recovery_epochs' "
        "own docstring for the measured 3-vs-20-epoch numbers this default replaced."
    ),
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
    recovery_epochs: int | None,
    no_register: bool,
) -> None:
    """Real structured pruning + fine-tune recovery for a registered LSTM
    version: structurally compacts the model, benchmarks real param
    count/on-disk size/CPU latency before vs. after, recovery-fine-tunes
    the compacted model, and gates registration on both a real accuracy-
    tolerance check and a real measured size/latency win."""
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
                recovery_epochs=recovery_epochs,
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
    the seasonal-naive baseline, logged to MLflow tagged `evaluation`."""
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
    registered version) against the seasonal-naive baseline, logged to
    MLflow tagged `evaluation`. Downloads/compiles a real ~200M-param
    checkpoint the first time -- expect real wall-clock time."""
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


@main.command("train-timesfm-correction")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option(
    "--model-name",
    default="timesfm_demand_correction",
    show_default=True,
    help="MLflow registered model name -- deliberately NOT lstm_demand/lstm_demand_tft: "
    "this is a Ridge regression's weights, not a comparable version of either.",
)
@click.option(
    "--horizon",
    type=int,
    default=6,
    show_default=True,
    help="Forecast horizon in steps -- same reasoning as evaluate-timesfm's --horizon.",
)
@click.option(
    "--n-origins-per-region",
    type=int,
    default=60,
    show_default=True,
    help="Walk-forward origins per region used to build the correction training set. "
    "Real cost warning: each origin costs 1 + max(--lag-window) real TimesFM "
    "inference calls.",
)
@click.option(
    "--lag-window",
    "lag_windows",
    type=int,
    multiple=True,
    default=None,
    help="Recent-error lookback window(s), in steps (repeatable). Defaults to (1, 3).",
)
@click.option(
    "--ridge-alpha",
    type=float,
    default=None,
    help="Ridge L2 strength. Default: cross-validated per horizon-step target "
    "(RidgeCV over app.service.ml.timesfm_correction.DEFAULT_RIDGE_ALPHAS) "
    "instead of one guessed value.",
)
@click.option(
    "--conformal-alpha",
    type=float,
    default=0.2,
    show_default=True,
    help="Miscoverage target for the corrected P10-P90 interval.",
)
@click.option(
    "--since",
    default=None,
    help="ISO date (YYYY-MM-DD) -- scope training data to ts >= this date.",
)
@click.option(
    "--no-register",
    is_flag=True,
    default=False,
    help="Log to MLflow but skip registering a model version.",
)
@click.option(
    "--source",
    "data_source",
    type=click.Choice(["fct_energy_demand", "r2_master"]),
    default="fct_energy_demand",
    show_default=True,
    help="fct_energy_demand: live Postgres marts (~60-day retention). "
    "r2_master: master.duckdb's real ~1-year bootstrap history, never touches Postgres.",
)
def train_timesfm_correction(
    regions: tuple[str, ...],
    model_name: str,
    horizon: int,
    n_origins_per_region: int,
    lag_windows: tuple[int, ...],
    ridge_alpha: float | None,
    conformal_alpha: float,
    since: str | None,
    no_register: bool,
    data_source: str,
) -> None:
    """Train a lightweight Ridge correction model on top of frozen
    TimesFM's own historical point-forecast errors, and log (+ register)
    it in MLflow under its own timesfm_demand_correction registry entry.
    TimesFM's real ~200M-param checkpoint itself never trains (it can't
    be fine-tuned) -- only the correction layer does."""
    import pandas as pd

    from app.service.ml.timesfm_correction import (
        CorrectionConfig,
        DEFAULT_LAG_WINDOWS,
        train_and_register_correction,
    )

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_since = pd.Timestamp(since, tz="UTC") if since else None
    config = CorrectionConfig(
        horizon=horizon,
        n_origins_per_region=n_origins_per_region,
        lag_windows=tuple(lag_windows) or DEFAULT_LAG_WINDOWS,
        ridge_alpha=ridge_alpha,
        conformal_alpha=conformal_alpha,
    )

    try:
        result = asyncio.run(
            train_and_register_correction(
                model_name,
                resolved_regions,
                settings=settings,
                config=config,
                register=not no_register,
                since=resolved_since,
                data_source=data_source,
            )
        )
    except Exception as exc:
        click.echo(f"train-timesfm-correction: failed — {exc}", err=True)
        sys.exit(1)

    registration = (
        f"registered as {model_name} v{result.model_version}"
        if result.model_version
        else "not registered (--no-register)"
    )
    click.echo(f"train-timesfm-correction: run {result.run_id} logged, {registration}")
    if result.metrics:
        click.echo(
            "  raw_test_mape={:.2f} corrected_test_mape={:.2f} mape_lift_pct={:.1f} "
            "corrected_test_coverage_calibrated={:.2f}".format(
                result.metrics.get("raw_test_mape", float("nan")),
                result.metrics.get("corrected_test_mape", float("nan")),
                result.metrics.get("mape_lift_pct", float("nan")),
                result.metrics.get("corrected_test_coverage_calibrated", float("nan")),
            )
        )


@main.command("evaluate-timesfm-correction")
@click.option("--model-name", default="timesfm_demand_correction", show_default=True)
@click.option("--version", required=True, help="Registered timesfm_demand_correction version.")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to evaluate on (repeatable). Defaults to Settings.model_default_regions.",
)
@click.option("--horizon", type=int, default=None, help="Defaults to the version's own trained horizon.")
@click.option(
    "--n-origins",
    type=int,
    default=10,
    show_default=True,
    help="Number of rolling-origin forecasts to walk forward over, per region.",
)
def evaluate_timesfm_correction(
    model_name: str,
    version: str,
    regions: tuple[str, ...],
    horizon: int | None,
    n_origins: int,
) -> None:
    """Real walk-forward backtest of a registered TimesFM correction
    version against the raw (uncorrected) TimesFM model and the
    seasonal-naive baseline, over the same rolling origins -- did the
    correction layer actually help, logged to MLflow tagged
    `evaluation`."""
    from app.service.ml.timesfm_correction import evaluate_timesfm_correction_and_log

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions

    try:
        result = asyncio.run(
            evaluate_timesfm_correction_and_log(
                model_name,
                version,
                resolved_regions,
                settings=settings,
                horizon=horizon,
                n_origins=n_origins,
            )
        )
    except Exception as exc:
        click.echo(f"evaluate-timesfm-correction: failed — {exc}", err=True)
        sys.exit(1)

    click.echo(f"evaluate-timesfm-correction: run {result.run_id} logged")
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


@main.command("train-worker")
def train_worker() -> None:
    """Run the training-trigger consumer (RabbitMQ -> warm-started
    incremental fine-tune -> MLflow). Long-running -- same process the
    `train-worker` docker-compose service runs; see
    `app.service.training_worker.run`. Ported from data-pipeline's
    identical command as part of the training-code migration -- events
    arrive from `services/waerehouse`'s automatic post-dbt-build publish
    and this service's own manual `POST /v1/model/train`, same queue
    either way."""
    from app.service.training_worker import run as run_train_worker

    asyncio.run(run_train_worker())


if __name__ == "__main__":
    main()
