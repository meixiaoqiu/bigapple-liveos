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
docker compose -f "$COMPOSE_FILE" exec -T admin python manage.py check
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py check

echo
echo "===== mysql port from container ====="
if [ -z "${REMOTE_DEV_MYSQL_HOST:-}" ]; then
  MYSQL_CHECK_HOST="$(docker compose -f "$COMPOSE_FILE" exec -T web python -c 'from django.conf import settings; print(settings.DATABASES["default"].get("HOST") or "localhost")')"
fi
if [ -z "${REMOTE_DEV_MYSQL_PORT:-}" ]; then
  MYSQL_CHECK_PORT="$(docker compose -f "$COMPOSE_FILE" exec -T web python -c 'from django.conf import settings; print(settings.DATABASES["default"].get("PORT") or "3306")')"
fi
docker compose -f "$COMPOSE_FILE" exec \
  -T \
  -e MYSQL_CHECK_HOST="$MYSQL_CHECK_HOST" \
  -e MYSQL_CHECK_PORT="$MYSQL_CHECK_PORT" \
  web bash -lc 'timeout 5 bash -c "</dev/tcp/${MYSQL_CHECK_HOST}/${MYSQL_CHECK_PORT}" && echo "mysql ${MYSQL_CHECK_HOST}:${MYSQL_CHECK_PORT} OK" || echo "mysql ${MYSQL_CHECK_HOST}:${MYSQL_CHECK_PORT} FAIL"'

echo
echo "===== unapplied migrations ====="
for check in "control:default:worlds" "realworld:realworld:core" "simulation0001:simulation0001:core"; do
  IFS=":" read -r label db app <<< "$check"
  echo "--- $label / $db / $app ---"
  docker compose -f "$COMPOSE_FILE" exec -T admin python manage.py showmigrations "$app" --database="$db" | grep '\[ \]' || echo "no unapplied migrations"
done

echo
echo "===== local page check ====="
curl -fsS -o /dev/null -w "admin HTTP %{http_code}\n" --max-time 10 http://127.0.0.1:20100/admin/ || true
curl -fsS -o /dev/null -w "real HTTP %{http_code}\n" --max-time 10 http://127.0.0.1:20101/ || true
