"""Trains/retrains every `(source, metric)` IsolationForest anomaly model
from recent DuckDB history -- root TODO.md's "Anomaly Detection" section,
v2. Unsupervised, no anomaly labels anywhere in this pipeline; each model
is persisted as a plain joblib artifact under
`ingestion/service/anomaly/isolation_forest.py`'s `default_model_dir()`
(next to `historical_duckdb_path`), **not** registered through MLflow --
see that module's own docstring for why an ingestion-time anomaly scorer
doesn't need the demand models' registry/alias/promote-if-better
lifecycle.

Meant to run daily (far lighter and far more frequent than the
demand-forecasting models' own monthly retrain, `cron_model_train.sh`) --
see `scripts/cron_train_anomaly_models.sh` for the actual schedule.

Usage:
    uv run --active ./scripts/train_anomaly_isolation_forest.py

    # Or via Makefile from the repo root:
    make train-anomaly-models
"""

from __future__ import annotations

import argparse

from ecolens.ingestion.service.anomaly.isolation_forest import train_all
from ecolens.shared.observability.logging import get_logger

log = get_logger("train_anomaly_isolation_forest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    results = train_all()
    trained = [key for key, ok in results.items() if ok]
    skipped = [key for key, ok in results.items() if not ok]

    print(
        f"Trained {len(trained)}/{len(results)} model(s): {', '.join(trained) or '(none)'}"
    )
    if skipped:
        print(
            f"Skipped {len(skipped)} (insufficient recent history -- "
            f"a normal cold-start, not an error): {', '.join(skipped)}"
        )
    log.info(
        "train_anomaly_isolation_forest.complete",
        trained=len(trained),
        skipped=len(skipped),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
