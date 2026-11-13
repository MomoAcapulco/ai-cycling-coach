#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$PROJECT_ROOT/scripts/load-env.sh"
echo 'Checking Python adapter:'
curl --fail --silent --show-error "${TRAINER_ADAPTER_URL}/telemetry"; echo
echo 'Checking Java backend:'
curl --fail --silent --show-error "${BACKEND_URL}/api/trainer/telemetry"; echo
