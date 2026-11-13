#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OLD="${1:-$HOME/dev/ai-cycling-coachV2}"
SOURCE="$OLD/trainer-adapter/recordings"
DEST="${RECORD_DIR:-${AI_COACH_HOME:-$(cd "$HERE/.." && pwd)/ai-cycling-coach-data}/recordings}"
if [[ ! -d "$SOURCE" ]]; then
  echo "No se encontró: $SOURCE" >&2
  exit 1
fi
mkdir -p "$DEST"
# Never overwrite files from the destination; keep original v2 unchanged.
rsync -av --ignore-existing "$SOURCE/" "$DEST/"
echo "Grabaciones importadas sin sobrescritura. Original intacto: $SOURCE"
