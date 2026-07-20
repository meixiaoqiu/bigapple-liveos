#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DOCKER_HOST="${DOCKER_HOST:-unix://${XDG_RUNTIME_DIR}/docker.sock}"

COMPOSE_FILE="docker-compose.remote-dev.yml"

if [ ! -f ".env.dev" ]; then
  echo "ERROR: .env.dev not found."
  echo "Create .env.dev first. Do not commit it."
  exit 1
fi

echo "===== rootless docker ====="
docker info --format 'Rootless={{.SecurityOptions}} Driver={{.Driver}}'

echo "===== start big-apple-live-os dev ====="
docker compose -f "$COMPOSE_FILE" up -d --build

echo "===== ps ====="
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Local URL:"
echo "  admin: http://127.0.0.1:20100/admin/"
echo "  real:  http://127.0.0.1:20101/"
if [ -n "${REMOTE_DEV_PUBLIC_URL:-}" ]; then
  echo
  echo "Remote URL:"
  echo "  ${REMOTE_DEV_PUBLIC_URL}"
fi
