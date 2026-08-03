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
    "--no-register",
    is_flag=True,
    default=False,
    help="Log to MLflow but skip registering a model version.",
)
def train(
    regions: tuple[str, ...],
    model_name: str | None,
    epochs: int | None,
    no_register: bool,
) -> None:
    """Train the demand-forecast LSTM and log (+ register) it in MLflow
    (`README.md` § ML pipeline, ECO-D50). Never promotes to Production —
    see `scripts/promote_model.sh`."""
    from dataclasses import replace

    from app.service.ml.train import TrainConfig, train_and_register

    settings = get_settings()
    resolved_regions = list(regions) or settings.model_default_regions
    resolved_model_name = model_name or settings.mlflow_registry_model_name
    config = TrainConfig.from_settings(settings)
    if epochs is not None:
        config = replace(config, epochs=epochs)

    try:
        result = asyncio.run(
            train_and_register(
                resolved_model_name,
                resolved_regions,
                settings=settings,
                config=config,
                register=not no_register,
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


@main.command()
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Region(s) to train on (repeatable). Defaults to Settings.model_default_regions.",
)
def tune(regions: tuple[str, ...]) -> None:
    """Small grid search over hidden_size/lr, each trial logged to MLflow
    (`TODO.md`'s Forecasting section item 6 — not Optuna, see
    `ml/tune.py`'s module docstring)."""
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
