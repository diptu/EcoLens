"""Run dbt as a subprocess (README Phase 4's "Transformation Engine
Integration") against the `dbt/ecolens` project ported into this
service (`services/waerehouse/dbt/ecolens` — was `data-pipeline/dbt/
ecolens`, models/sources/tests unchanged, now run from here instead).

`dbt` isn't a Python *import* dependency (`dbt-postgres` on the
`pyproject.toml` dependency list installs the `dbt` console script into
this venv, but this module always invokes it as an external CLI, never
imports its internals) — `run_dbt` is synchronous by design (it's just
`subprocess.run` under the hood); an async caller offloads it via
`asyncio.to_thread` rather than this module pretending to be async.

Ported from `data-pipeline`'s identical `app.service.dbt_runner` module
— same subprocess shape, same `dbt_postgres_env` fallback for a single-
DSN (`DATABASE_URL`) deployment (`Settings.dbt_postgres_env`'s own
docstring covers the real bug this avoids).
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
    project_dir: str | Path | None = None,
    target: str = "dev",
    extra_args: list[str] | None = None,
) -> tuple[int, str]:
    """Run `dbt <subcommand path> --project-dir <project_dir> --target <target> [extra_args]`.

    Returns `(exit_code, combined_stdout_and_stderr)`. Never raises — a
    non-zero dbt exit and a missing `dbt` binary are both just a
    non-zero return code for the caller to handle, output included
    either way (an interactive CLI caller wants to actually see dbt's
    output, not just a bare exit code).

    `--profiles-dir <project_dir>` — `profiles.yml` lives next to
    `dbt_project.yml` rather than relying on `~/.dbt/` or the
    `DBT_PROFILES_DIR` env var being set correctly on whatever process/
    container ends up running this.

    **Multi-word dbt subcommands** (`source freshness`, `docs generate`,
    ...) — real bug found live (`TODO.md` Phase 4) while trying to
    actually run `ecolens-warehouse dbt source freshness`, the CLI's own
    documented example: dbt requires `--project-dir`/`--profiles-dir`/
    `--target` to come *after every word of the subcommand path*, not
    right after the first word (`dbt source --project-dir X freshness`
    fails with `Error: No such option '--project-dir'`; `dbt source
    freshness --project-dir X` is the only ordering that works —
    confirmed directly against the real `dbt` CLI, not assumed). `click`
    parses only the first word into `subcommand`, so a call like
    `dbt("source", extra_args=["freshness"])` (what the CLI layer's
    `@click.argument("subcommand")` + `nargs=-1 extra_args` naturally
    produce for `ecolens-warehouse dbt source freshness`) needs
    `"freshness"` treated as a continuation of the subcommand path, not
    a trailing flag. `subcommand.split()` handles a pre-joined string
    (`run_dbt("source freshness")`, e.g. from a test or a future
    non-CLI caller); consuming extra_args' *leading non-flag* tokens
    handles the click-split case — either path already stops at the
    first `-`/`--`-prefixed token, since a real dbt flag never
    continues a subcommand path.
    """
    settings = get_settings()
    resolved_project_dir = str(project_dir or settings.dbt_project_dir)

    path = subcommand.split()
    remaining_extra_args = list(extra_args or [])
    while remaining_extra_args and not remaining_extra_args[0].startswith("-"):
        path.append(remaining_extra_args.pop(0))
    # Metrics/log label: the full resolved path ("source freshness"), not
    # just the caller's original (possibly partial, pre-click-split)
    # `subcommand` string -- otherwise `dbt source freshness` and a bare
    # `dbt source` would be indistinguishable in Prometheus.
    full_subcommand = " ".join(path)

    args = [
        "dbt",
        *path,
        "--project-dir",
        resolved_project_dir,
        "--profiles-dir",
        resolved_project_dir,
        "--target",
        target,
        *remaining_extra_args,
    ]

    # `dbt/ecolens/profiles.yml` reads POSTGRES_HOST/PORT/USER/PASSWORD/DB
    # as raw OS env vars (Jinja `env_var()`) -- entirely separate from
    # this service's own `DATABASE_URL`-first `Settings.database_url`.
    # `setdefault` so an operator's explicit env var still wins.
    env = os.environ.copy()
    for key, value in settings.dbt_postgres_env.items():
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
        dbt_run_duration_seconds.labels(subcommand=full_subcommand).observe(
            time.monotonic() - started
        )

    outcome = "success" if exit_code == 0 else "failure"
    dbt_runs_total.labels(subcommand=full_subcommand, outcome=outcome).inc()
    if exit_code != 0:
        logger.warning(
            "dbt_run_failed",
            subcommand=full_subcommand,
            exit_code=exit_code,
            output=output[-2000:],
        )

    return exit_code, output
