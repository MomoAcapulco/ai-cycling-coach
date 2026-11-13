#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
info() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for file in frontend/package.json backend/pom.xml trainer-adapter/requirements.txt start.sh; do
  [[ -f "$file" ]] || fail "Falta $file. Copia init.sh a la raiz del proyecto completo v4.2."
done
for cmd in python3 node npm java mvn; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Falta instalar $cmd"
done
[[ $# -eq 0 || ( $# -eq 1 && $1 == --start ) ]] || fail 'Uso: bash init.sh [--start]'
info 'Versiones'
python3 --version; node --version; npm --version; java -version 2>&1 | head -n 1; mvn -version | head -n 1
if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || fail 'Faltan .env y .env.example'
  cp .env.example .env
  info 'Configuracion .env creada; revisala antes de usar WAHOO'
else
  info 'Conservando .env'
fi
mkdir -p trainer-adapter/recordings
info 'Conservando todas las grabaciones existentes'
chmod u+x start.sh
if [[ -d scripts ]]; then find scripts -maxdepth 1 -type f -name '*.sh' -exec chmod u+x {} +; fi
info 'Preparando Python'
if [[ ! -x trainer-adapter/.venv/bin/python ]]; then python3 -m venv trainer-adapter/.venv; fi
trainer-adapter/.venv/bin/python -m pip install -r trainer-adapter/requirements.txt
info 'Instalando dependencias React'
cd "$ROOT/frontend"
if [[ -f package-lock.json ]]; then npm ci; else npm install; fi
info 'Compilando React'
npm run build
info 'Compilando backend Java'
cd "$ROOT/backend"
mvn -q -DskipTests package
info 'Inicializacion terminada'
printf 'Proyecto: %s\nGrabaciones: %s/trainer-adapter/recordings\n' "$ROOT" "$ROOT"
if [[ ${1:-} == --start ]]; then
  info 'Arrancando AI Cycling Coach'
  cd "$ROOT"
  exec ./start.sh
fi
printf 'Para arrancar: cd "%s" && ./start.sh\n' "$ROOT"
