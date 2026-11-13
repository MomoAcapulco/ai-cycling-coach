#!/usr/bin/env bash
# Creates the git repository of AI Cycling Coach in THIS folder (only once).
#
#   scripts/init-git-repo.sh                 one commit with the current version
#   scripts/init-git-repo.sh --with-history  first v4.2.2 (from ../ai-cycling-coach-v4.2.2, read only), then this
#                                            version on top, so "git diff v4.2.2 v4.3.0" shows what changed
#   --email you@example.com [--name "Your Name"]
#                                            identity for THIS repository only (e.g. a personal address when the
#                                            global one is the work one); stored in .git/config
#
# It never pushes anything and never touches the other version folders. Run it with YOUR git identity
# (git config --global user.name / user.email) on your Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(tr -d '[:space:]' < VERSION)"
OLD="$ROOT/../ai-cycling-coach-v4.2.2"
TRAILER=$'\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'

WITH_HISTORY=false
EMAIL=""
NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-history) WITH_HISTORY=true; shift ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ -n "$EMAIL" && "$EMAIL" != *@* ]]; then
  echo "--email needs an address, e.g. --email you@example.com" >&2
  exit 2
fi

CREATED=false
if [[ -e .git ]]; then
  if git rev-parse -q --verify HEAD >/dev/null 2>&1; then
    echo "There is already a git repository with commits here ($ROOT/.git). Nothing done." >&2
    exit 1
  fi
  echo "Empty git repository found (e.g. from a manual 'git init'): using it, its settings are kept."
else
  git init -q
  CREATED=true
fi
git symbolic-ref HEAD refs/heads/main   # no commits yet: the first branch is called main
[[ -n "$EMAIL" ]] && git config user.email "$EMAIL"
[[ -n "$NAME" ]] && git config user.name "$NAME"
if [[ -z "$(git config user.email || true)" || -z "$(git config user.name || true)" ]]; then
  echo "No git identity: run again with --email you@example.com --name \"Your Name\"" >&2
  [[ "$CREATED" == true ]] && rm -rf .git
  exit 1
fi
echo "Commits of this repository as: $(git config user.name) <$(git config user.email)>"
# The same private rules for any work tree we read (the old version has an older .gitignore).
mkdir -p .git/info && cp .gitignore .git/info/exclude

if [[ "$WITH_HISTORY" == true ]]; then
  if [[ ! -d "$OLD" ]]; then
    echo "Not found: $OLD (run without --with-history)" >&2
    rm -rf .git
    exit 1
  fi
  # Stage the OLD folder's files into this repository without changing that folder.
  git --work-tree="$OLD" add -A
  git commit -q -m "AI Cycling Coach v4.2.2 (imported from the version folder)${TRAILER}"
  git tag v4.2.2
  echo "Committed v4.2.2: $(git ls-files | wc -l | tr -d ' ') files"
fi

git add -A
git commit -q -m "AI Cycling Coach v${VERSION}

Single event loop for Bluetooth, device autodiscovery, admin page, native virtual shifting,
training sessions, grade control (pending trainer test), virtual road with physics speed and
elevation. See CHANGELOG.md.${TRAILER}"
git tag "v${VERSION}"

echo "Committed v${VERSION}: $(git ls-files | wc -l | tr -d ' ') files"
echo
echo "Check that nothing private went in (should print nothing):"
git ls-files | grep -E '(^|/)(\.env$|diagnostics/|recordings/|node_modules/|target/|\.venv/)' || echo "  OK: nothing private"
echo
git log --oneline --decorate
