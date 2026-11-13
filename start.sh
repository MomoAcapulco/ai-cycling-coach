#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$PROJECT_ROOT/scripts/load-env.sh"

for cmd in python3 mvn npm curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2; exit 1
  fi
done
# Avoid launching half a stack if a port is already in use.
for port in "$TRAINER_PORT" "$SERVER_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
    echo "Port $port is already in use. Stop the existing service or change .env" >&2
    exit 1
  fi
done
mkdir -p "$PROJECT_ROOT/.run"
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo; echo 'Stopping AI Cycling Coach...'
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -f "$PROJECT_ROOT/.run/pids"
}
trap cleanup INT TERM EXIT

(cd "$PROJECT_ROOT/trainer-adapter" && {
  if [[ -x .venv/bin/python ]]; then exec .venv/bin/python server.py; fi
  exec python3 server.py
}) &
PIDS+=("$!")
(cd "$PROJECT_ROOT/backend" && exec mvn spring-boot:run) &
PIDS+=("$!")
(cd "$PROJECT_ROOT/frontend" && {
  if [[ ! -d node_modules ]]; then npm install; fi
  exec npm run dev
}) &
PIDS+=("$!")
printf '%s\n' "${PIDS[@]}" > "$PROJECT_ROOT/.run/pids"
printf '\nFrontend: http://%s:%s\nJava API: %s/api/trainer/telemetry\nPython:   %s/telemetry\nPress Ctrl+C to stop.\n\n' "$FRONTEND_HOST" "$FRONTEND_PORT" "$BACKEND_URL" "$TRAINER_ADAPTER_URL"
# Monitor children; if a component exits, terminate the entire stack.
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "A component exited (PID $pid). Check errors above." >&2
      exit 1
    fi
  done
  sleep 2
done
