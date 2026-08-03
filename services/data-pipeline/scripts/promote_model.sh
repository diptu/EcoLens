#!/usr/bin/env bash
# Promotes a registered MLflow model version to a target stage (README's
# "Promotion is CI-gated", the `ml-pipeline` GitHub Action calling this
# after a training run). Gated on a metric threshold read straight off
# the run that produced the version being promoted -- not a bare stage
# flip -- so a regression can't reach Production just because someone (or
# some CI job) ran this script.
#
# Usage:
#   scripts/promote_model.sh <model-name> <version> [stage] [--max-test-mape N]
#
# Examples:
#   scripts/promote_model.sh lstm_demand 3                          # -> Production, no gate
#   scripts/promote_model.sh lstm_demand 3 Production --max-test-mape 15
#   scripts/promote_model.sh lstm_demand 3 Staging                  # Staging never auto-archives
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$SERVICE_DIR/../../.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

MODEL_NAME="${1:?Usage: $0 <model-name> <version> [stage] [--max-test-mape N]}"
shift
VERSION="${1:?Usage: $0 <model-name> <version> [stage] [--max-test-mape N]}"
shift

STAGE="Production"
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
  STAGE="$1"
  shift
fi

MAX_TEST_MAPE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --max-test-mape)
      MAX_TEST_MAPE="${2:?--max-test-mape needs a value}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

cd "$SERVICE_DIR"
uv run python - "$MODEL_NAME" "$VERSION" "$STAGE" "$MAX_TEST_MAPE" <<'PYEOF'
import sys

from mlflow.tracking import MlflowClient

from app.service.mlops.registry import transition_stage

model_name, version, stage, max_test_mape = sys.argv[1:5]

client = MlflowClient()
model_version = client.get_model_version(model_name, version)

if max_test_mape:
    run = client.get_run(model_version.run_id)
    test_mape = run.data.metrics.get("test_mape")
    if test_mape is None:
        print(
            f"error: run {model_version.run_id} (model {model_name} v{version}) has no "
            "'test_mape' metric logged -- cannot gate on it",
            file=sys.stderr,
        )
        sys.exit(1)
    threshold = float(max_test_mape)
    if test_mape > threshold:
        print(
            f"blocked: {model_name} v{version} test_mape={test_mape:.2f} "
            f"exceeds --max-test-mape {threshold}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"gate passed: test_mape={test_mape:.2f} <= {threshold}")

# Production is meant to have exactly one serving version at a time;
# Staging is meant to hold several candidates under evaluation at once.
archive_existing = stage == "Production"
transition_stage(model_name, version, stage, archive_existing=archive_existing)
print(f"promoted: {model_name} v{version} -> {stage}")
PYEOF
