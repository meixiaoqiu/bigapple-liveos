#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DOCKER_HOST="${DOCKER_HOST:-unix://${XDG_RUNTIME_DIR}/docker.sock}"

COMPOSE_FILE="docker-compose.remote-dev.yml"
MYSQL_CHECK_HOST="${REMOTE_DEV_MYSQL_HOST:-mysql}"
MYSQL_CHECK_PORT="${REMOTE_DEV_MYSQL_PORT:-3306}"

echo "===== containers ====="
docker compose -f "$COMPOSE_FILE" ps

echo
echo "===== django check ====="
docker compose -f "$COMPOSE_FILE" exec web python manage.py check

echo
echo "===== mysql port from container ====="
docker compose -f "$COMPOSE_FILE" exec \
  -e MYSQL_CHECK_HOST="$MYSQL_CHECK_HOST" \
  -e MYSQL_CHECK_PORT="$MYSQL_CHECK_PORT" \
  web bash -lc 'timeout 5 bash -c "</dev/tcp/${MYSQL_CHECK_HOST}/${MYSQL_CHECK_PORT}" && echo "mysql ${MYSQL_CHECK_HOST}:${MYSQL_CHECK_PORT} OK" || echo "mysql ${MYSQL_CHECK_HOST}:${MYSQL_CHECK_PORT} FAIL"'

echo
echo "===== unapplied migrations ====="
for db in default realworld simulation0001; do
  echo "--- $db ---"
  docker compose -f "$COMPOSE_FILE" exec web python manage.py showmigrations --database="$db" | grep '\[ \]' || echo "no unapplied migrations"
done

echo
echo "===== local page check ====="
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" --max-time 10 http://127.0.0.1:20101/observer/ || true
