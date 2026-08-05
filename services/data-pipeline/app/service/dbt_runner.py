"""Run dbt as a subprocess.

`dbt` isn't a Python dependency of this service — it's invoked as an
external CLI. `run_dbt` is synchronous by design (it's just
`subprocess.run` under the hood); the event-loop-facing caller
(`app/api/v1/dbt/routes.py`, ECO-D22) offloads it via
`asyncio.to_thread` rather than this module pretending to be async.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 -- shelling out to the dbt CLI is this module's entire purpose
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import dbt_run_duration_seconds, dbt_runs_total

logger = get_logger(__name__)

_COMMAND_NOT_FOUND = 127


def run_dbt(
    subcommand: str,
    project_dir: str | Path,
    target: str = "prod",
    extra_args: list[str] | None = None,
) -> int:
    """Run `dbt <subcommand> --project-dir <project_dir> --target <target> [extra_args]`.

    Returns the process's exit code. Never raises — a non-zero dbt exit
    and a missing `dbt` binary are both just a non-zero return code for
    the caller to handle.

    `--profiles-dir <project_dir>` — `profiles.yml` lives next to
    `dbt_project.yml` (`dbt/ecolens/profiles.yml`) rather than relying on
    `~/.dbt/` or the `DBT_PROFILES_DIR` env var being set correctly on
    whatever process/container ends up running this.
    """
    args = [
        "dbt",
        subcommand,
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(project_dir),
        "--target",
        target,
        *(extra_args or []),
    ]

    # `dbt/ecolens/profiles.yml` reads POSTGRES_HOST/PORT/USER/PASSWORD/DB
    # as raw OS env vars (Jinja `env_var()`) -- entirely separate from
    # this service's own `DATABASE_URL`-first `Settings.database_url`.
    # Fill them in from there when not already present in this process's
    # environment, so a NeonDB/single-DSN deployment (the normal case
    # everywhere else in this app) doesn't need them duplicated by hand
    # -- without this, dbt silently falls back to its own `localhost`
    # defaults instead of the real database (see `Settings.
    # dbt_postgres_env`'s own docstring). `setdefault` so an operator's
    # explicit env var still wins.
    env = os.environ.copy()
    for key, value in get_settings().dbt_postgres_env.items():
        env.setdefault(key, value)

    started = time.monotonic()
    try:
        result = subprocess.run(  # nosec B603 -- args is a static list, no shell=True involved
            args, capture_output=True, text=True, check=False, env=env
        )
        exit_code = result.returncode
        output = result.stdout + result.stderr
    except FileNotFoundError:
        exit_code = _COMMAND_NOT_FOUND
        output = "dbt executable not found on PATH"
    finally:
        dbt_run_duration_seconds.labels(subcommand=subcommand).observe(
            time.monotonic() - started
        )

    outcome = "success" if exit_code == 0 else "failure"
    dbt_runs_total.labels(subcommand=subcommand, outcome=outcome).inc()
    if exit_code != 0:
        logger.warning(
            "dbt_run_failed",
            subcommand=subcommand,
            exit_code=exit_code,
            output=output[-2000:],
        )

    return exit_code
