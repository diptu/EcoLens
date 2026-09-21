#!/bin/bash
# Builds infra/docker/warehouse.Dockerfile and pushes it to Docker Hub as
# diptu/ecolense:warehouse-<tag> (default V2.0.0 — override via $1 or TAG
# env). All 4 ecoLens service images share the single diptu/ecolense repo
# (https://hub.docker.com/repository/docker/diptu/ecolense/) and are told
# apart by tag prefix, not by repo name.
#
# Usage (from anywhere):
#   services/waerehouse/scripts/deploy.sh [tag]
#   TAG=V2.0.1 services/waerehouse/scripts/deploy.sh
#
# Requires `docker login -u diptu` to already be done — this script never
# handles credentials itself.
set -euo pipefail

TAG="${1:-${TAG:-V2.0.0}}"
IMAGE="diptu/ecolense:warehouse-${TAG}"

# infra/docker/warehouse.Dockerfile's build context is the repo root
# (it COPYs services/waerehouse/, not just its own directory) -- resolve
# that regardless of where this script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -f infra/docker/warehouse.Dockerfile ]; then
  echo "Error: infra/docker/warehouse.Dockerfile not found under ${REPO_ROOT} -- wrong repo root?" >&2
  exit 1
fi

echo "=== Building and pushing ${IMAGE} (linux/amd64) ==="
docker buildx build \
  --platform linux/amd64 \
  -f infra/docker/warehouse.Dockerfile \
  -t "${IMAGE}" \
  --push .

echo "=== Done: ${IMAGE} ==="
