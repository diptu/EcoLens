#!/usr/bin/env python3
"""Mirror the local MLflow server's artifact directory (model weights,
`.mlflow/artifacts/**` -- the actually-running local server per
`.env`'s `MLFLOW_TRACKING_URI=http://localhost:5001` comment, not the
docker-compose `mlflow` service) to object storage — `TODO.md`'s Storage
item ("...including model weights on Cloudflare R2").

**This is a backup/mirror copy, not a live artifact-root switch.**
MLflow fixes each experiment's `artifact_location` at the moment that
experiment is first created, and reads/writes model artifacts through
that location for every run in it, not through whatever `--default-
artifact-root` the tracking server happens to be started with later.
The `lstm_demand` experiment already exists locally with its
`artifact_location` pointed at `./.mlflow/artifacts` -- rewriting that
means editing MLflow's own backend-store records (`mlflow.db`), a live
tracking store `mlops/registry.py`'s warm-start/promote path depends on.
Deliberately not attempted here; this script only keeps a growing
*copy* of what's already local on R2, safe to re-run any time (skips
keys already present), so today's/future model weights aren't only ever
on one machine's disk. A real "MLflow serves straight from R2" cutover
(new experiment with an explicit `artifact_location=s3://...`, or
migrating `mlflow.db`'s existing rows) is a separate, bigger decision --
not bundled into this script.

Run from `services/data-pipeline/`:

    uv run --package data-pipeline python scripts/sync_mlflow_artifacts_to_r2.py
    uv run --package data-pipeline python scripts/sync_mlflow_artifacts_to_r2.py --dry-run
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.service import object_storage

log = get_logger(__name__)

_DEFAULT_ARTIFACTS_DIR = (
    Path(__file__).resolve().parent.parent / ".mlflow" / "artifacts"
)
_R2_PREFIX = "mlflow/artifacts"


async def _sync_all(source_dir: Path, prefix: str, dry_run: bool) -> None:
    settings = get_settings()
    log.info(
        "sync_mlflow_artifacts.backend", summary=object_storage.active_backend_summary()
    )

    if not source_dir.exists():
        log.warning("sync_mlflow_artifacts.no_source_dir", source_dir=str(source_dir))
        return

    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    if not files:
        log.warning("sync_mlflow_artifacts.no_files_found", source_dir=str(source_dir))
        return

    uploaded = 0
    skipped = 0
    total_bytes = 0
    for path in files:
        key = f"{prefix}/{path.relative_to(source_dir).as_posix()}"
        if dry_run:
            click.echo(
                f"[dry-run] would upload {path} -> s3://{settings.object_storage_bucket}/{key}"
            )
            continue
        if await object_storage.object_exists(key):
            skipped += 1
            continue
        uri = await object_storage.upload_file(path, key)
        uploaded += 1
        total_bytes += path.stat().st_size
        click.echo(f"uploaded {path.relative_to(source_dir)} -> {uri}")

    if not dry_run:
        click.echo(
            f"\ndone: {uploaded} uploaded ({total_bytes / 1024 / 1024:.1f} MB), "
            f"{skipped} already present, {len(files)} total files under {source_dir}"
        )


@click.command()
@click.option(
    "--source-dir",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    default=_DEFAULT_ARTIFACTS_DIR,
    show_default=True,
    help="Local MLflow artifacts directory to mirror.",
)
@click.option(
    "--prefix",
    default=_R2_PREFIX,
    show_default=True,
    help="Object storage key prefix to upload under.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List what would be uploaded without touching object storage.",
)
def main(source_dir: Path, prefix: str, dry_run: bool) -> None:
    configure_logging()
    asyncio.run(_sync_all(source_dir, prefix, dry_run))


if __name__ == "__main__":
    main()
