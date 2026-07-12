#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DOCKER_HOST="${DOCKER_HOST:-unix://${XDG_RUNTIME_DIR}/docker.sock}"

docker compose -f docker-compose.remote-dev.yml down
