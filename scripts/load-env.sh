#!/usr/bin/env bash
# Source this file. It loads project .env and derives dependent URLs.
set -a
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  # .env is a trusted local configuration file; no untrusted content.
  source "$PROJECT_ROOT/.env"
fi
: "${SERVER_HOST:=127.0.0.1}"
: "${SERVER_PORT:=8081}"
: "${TRAINER_HOST:=127.0.0.1}"
: "${TRAINER_PORT:=8766}"
: "${FRONTEND_HOST:=127.0.0.1}"
: "${FRONTEND_PORT:=5173}"
: "${TRAINER_ADAPTER_URL:=http://${TRAINER_HOST}:${TRAINER_PORT}}"
: "${BACKEND_URL:=http://${SERVER_HOST}:${SERVER_PORT}}"
set +a
for label in SERVER_PORT TRAINER_PORT FRONTEND_PORT; do
  value="${!label}"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( 10#$value < 1 || 10#$value > 65535 )); then
    echo "Invalid $label: $value (expected 1-65535)" >&2
    return 1
  fi
done
if [[ "$SERVER_PORT" == "$TRAINER_PORT" || "$SERVER_PORT" == "$FRONTEND_PORT" || "$TRAINER_PORT" == "$FRONTEND_PORT" ]]; then
  echo 'SERVER_PORT, TRAINER_PORT and FRONTEND_PORT must be different' >&2
  return 1
fi
