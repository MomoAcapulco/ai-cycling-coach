#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$PROJECT_ROOT/scripts/load-env.sh"

# ./start.sh        normal use: the interface and the Java API are built once (again only when their sources
#                   change) and served optimised, so every page opens fast the first time too.
# ./start.sh --dev  development: Vite compiles each page when it is first opened (slow the first time, but
#                   changes appear without restarting) and Maven runs the Java API from its sources.
DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    -h|--help) sed -n '6,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (use --dev or nothing)" >&2; exit 1 ;;
  esac
done

# True when the build output $1 is missing or older than any of the sources (the remaining arguments).
needs_build() {
  local output="$1"; shift
  [[ ! -e "$output" ]] && return 0
  [[ -n "$(find "$@" -newer "$output" -type f -print -quit 2>/dev/null)" ]]
}

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
if (( DEV )); then
  (cd "$PROJECT_ROOT/backend" && exec mvn spring-boot:run) &
  PIDS+=("$!")
  (cd "$PROJECT_ROOT/frontend" && {
    if [[ ! -d node_modules ]]; then npm install; fi
    exec npm run dev
  }) &
  PIDS+=("$!")
else
  # Built in the foreground, before anything starts: a failed build stops here with its errors on screen.
  JAR="$PROJECT_ROOT/backend/target/coach-backend.jar"
  if needs_build "$JAR" "$PROJECT_ROOT/backend/src/main" "$PROJECT_ROOT/backend/pom.xml"; then
    echo 'Building the Java API (only when it changed)...'
    (cd "$PROJECT_ROOT/backend" && mvn -q -DskipTests package)
    cp "$(ls -t "$PROJECT_ROOT"/backend/target/coach-backend-*.jar | grep -v '\.original$' | head -1)" "$JAR"
  fi
  (cd "$PROJECT_ROOT/frontend" && {
    if [[ ! -d node_modules ]]; then npm install; fi
    if needs_build dist/index.html src index.html package.json vite.config.ts ../VERSION; then
      echo 'Building the interface (only when it changed)...'
      npm run build
    fi
  })
  (cd "$PROJECT_ROOT/backend" && exec java -jar "$JAR") &
  PIDS+=("$!")
  (cd "$PROJECT_ROOT/frontend" && exec npx vite preview --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort) &
  PIDS+=("$!")
fi
printf '%s\n' "${PIDS[@]}" > "$PROJECT_ROOT/.run/pids"
printf '\nMode: %s\nFrontend: http://%s:%s\nJava API: %s/api/trainer/telemetry\nPython:   %s/telemetry\nPress Ctrl+C to stop.\n\n' "$( (( DEV )) && echo 'development (--dev)' || echo normal)" "$FRONTEND_HOST" "$FRONTEND_PORT" "$BACKEND_URL" "$TRAINER_ADAPTER_URL"
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
