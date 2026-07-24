"""Stage 2: invoke dbt as a subprocess.

We use subprocess rather than importing dbt-core as a library because:
  - dbt-core has its own process model + adapter plugins
  - subprocess isolates adapter crashes from our service
  - the cron entry expects a CLI process exit code
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - invoked with a fixed argv list, no shell=True, see run()
from datetime import datetime, timezone

from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)


class DbtRunner:
    """Invokes dbt as a subprocess and captures results."""

    def __init__(self, settings: WarehouseRunnerSettings) -> None:
        self.settings = settings
        if not settings.dbt_path.exists():
            log.warning("dbt.path_missing", path=str(settings.dbt_path))
        if not shutil.which(settings.dbt_binary):
            log.warning("dbt.binary_missing", binary=settings.dbt_binary)

    def run(
        self,
        *,
        command: str,  # "build" / "test" / "seed" / "run"
        select: list[str] | None = None,
        exclude: list[str] | None = None,
        full_refresh: bool = False,
        dbt_vars: dict[str, object] | None = None,
    ) -> StageResult:
        started = datetime.now(timezone.utc)
        if not shutil.which(self.settings.dbt_binary):
            return StageResult(
                name=f"dbt_{command}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"dbt binary not found: {self.settings.dbt_binary}",
            )
        args = [
            self.settings.dbt_binary,
            command,
            "--profiles-dir",
            str(self.settings.dbt_profiles_dir),
            "--target",
            self.settings.dbt_target,
            "--threads",
            str(self.settings.dbt_threads),
        ]
        if select:
            args.extend(["--select", " ".join(select)])
        if exclude:
            args.extend(["--exclude", " ".join(exclude)])
        if full_refresh:
            args.append("--full-refresh")
        if dbt_vars:
            args.extend(["--vars", json.dumps(dbt_vars)])

        log.info("dbt.invoke", cmd=" ".join(args))
        try:
            proc = subprocess.run(  # nosec B603 - argv list, no shell=True; args built above from config, not raw input
                args,
                cwd=self.settings.dbt_path,
                capture_output=True,
                text=True,
                timeout=self.settings.dbt_timeout_seconds,
            )
            success = proc.returncode == 0
            # Tail of stdout/stderr for log file
            tail = (proc.stdout or "")[-2000:]
            if not success:
                tail += "\n--- stderr ---\n" + (proc.stderr or "")[-2000:]
            finished = datetime.now(timezone.utc)
            rows_affected = self._parse_row_count(proc.stdout or "")
            log.info(
                "dbt.complete",
                cmd=command,
                success=success,
                duration_s=round((finished - started).total_seconds(), 1),
                rows=rows_affected,
            )
            return StageResult(
                name=f"dbt_{command}",
                started_at=started,
                finished_at=finished,
                success=success,
                rows_affected=rows_affected,
                error=None if success else f"dbt exited {proc.returncode}",
                metrics={"stdout_tail": tail, "returncode": proc.returncode},
            )
        except subprocess.TimeoutExpired as exc:
            return StageResult(
                name=f"dbt_{command}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"dbt timed out after {exc.timeout}s",
            )
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name=f"dbt_{command}",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _parse_row_count(stdout: str) -> int:
        """Extract row count from dbt's 'Done. XXX rows ...' summary line."""
        for line in stdout.splitlines():
            if "Done. " in line and "rows" in line:
                parts = line.replace(",", "").split()
                for i, tok in enumerate(parts):
                    if tok.isdigit() and i + 1 < len(parts) and "rows" in parts[i + 1]:
                        return int(tok)
        return 0


__all__ = ["DbtRunner"]
