#!/usr/bin/env python3
"""Upload the dashboard's static assets (`services/dashboard/public/`) to
object storage — `TODO.md`'s Storage item ("store all assets & art-effects
on Cloudflare R2"). Goes through `app.service.object_storage`, which
resolves to real R2 once `Settings.object_storage_configured` is true
(`CLOUDFLARESTORAGE_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY` set), else falls
back to local MinIO — so this same script is how to verify the upload
path works (against MinIO, `make -C .. up` or `docker compose up -d minio
minio-setup`) before real R2 credentials exist at all.

This uploads a *mirror* under an `assets/` prefix; it does not change how
the Next.js app serves images (still local `public/`) — switching actual
serving to R2 URLs is a separate, bigger decision (CDN/custom domain,
`next.config.js` `remotePatterns`, rewriting every `<Image src=...>`) not
bundled into this script.

Run from `services/data-pipeline/`:

    uv run --package data-pipeline python scripts/upload_assets_to_r2.py
    uv run --package data-pipeline python scripts/upload_assets_to_r2.py --dry-run
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.service import object_storage

log = get_logger(__name__)

# `services/data-pipeline/scripts/` -> `services/dashboard/public` --
# both are siblings under `services/`, not relative to this repo's root,
# so the walk-up is fixed at exactly 2 parents regardless of invoking cwd
# (matches `config.py`'s own "anchor by real file location, not cwd"
# reasoning, `_PACKAGE_ROOT`'s docstring).
_DASHBOARD_PUBLIC_DIR = (
    Path(__file__).resolve().parent.parent.parent / "dashboard" / "public"
)
_R2_PREFIX = "assets/dashboard"


async def _upload_all(source_dir: Path, prefix: str, dry_run: bool) -> None:
    settings = get_settings()
    log.info("upload_assets.backend", summary=object_storage.active_backend_summary())

    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    if not files:
        log.warning("upload_assets.no_files_found", source_dir=str(source_dir))
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
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_DASHBOARD_PUBLIC_DIR,
    show_default=True,
    help="Local directory to mirror.",
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
    asyncio.run(_upload_all(source_dir, prefix, dry_run))


if __name__ == "__main__":
    main()
