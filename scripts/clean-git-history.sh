#!/usr/bin/env bash
# Before publishing the repository (only once, and only if it has NOT been pushed yet): rebuild the history as
# two clean commits, with your GitHub noreply address as the commit e-mail.
#
#   bash scripts/clean-git-history.sh --email 12345678+user@users.noreply.github.com [--name "Your Name"]
#
#   v4.2.2  the imported v4.2.2, with scripts/mask_personal_data.py applied (device identifiers)
#   v4.3.0  exactly the files of your current last commit (already masked, tests passing)
#
# Why not rewrite every commit: the earlier v4.3.0 commits hold personal data inside tests whose expected
# results depend on it; masking them would leave commits whose tests fail. v4.3.0 was never released, so its
# final state is what gets published. Original dates and messages are kept. Old objects are deleted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EMAIL=""
NAME=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ "$EMAIL" != *@users.noreply.github.com ]]; then
  echo "Use your GitHub noreply address: --email 12345678+user@users.noreply.github.com" >&2
  echo "(github.com → Settings → Emails → 'Keep my email addresses private' shows it)" >&2
  exit 2
fi
NAME="${NAME:-$(git config user.name || true)}"
if [[ -z "$NAME" ]]; then
  echo "No git name: add --name \"Your Name\"" >&2
  exit 2
fi
for tag in v4.2.2 v4.3.0; do
  git rev-parse -q --verify "refs/tags/$tag" >/dev/null || { echo "Tag $tag not found." >&2; exit 1; }
done
for remote in $(git remote); do
  if [[ -n "$(git ls-remote --heads "$remote" 2>/dev/null || true)" ]]; then
    echo "Remote '$remote' already has branches: this history is published, it is not rewritten here." >&2
    exit 1
  fi
done
if [[ -n "$(git status --porcelain)" ]]; then
  echo "There are uncommitted changes: commit them first (git add -A && git commit -m \"...\")." >&2
  git status --short >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp scripts/mask_personal_data.py "$TMP/mask.py"
mkdir "$TMP/head"
git archive HEAD | tar -x -C "$TMP/head"
if ! python3 "$TMP/mask.py" --root "$TMP/head" --check; then
  echo "Your last commit still has personal data (listed above): run python3 scripts/mask_personal_data.py," >&2
  echo "commit, and run this again." >&2
  exit 1
fi

export GIT_AUTHOR_NAME="$NAME" GIT_COMMITTER_NAME="$NAME" GIT_AUTHOR_EMAIL="$EMAIL" GIT_COMMITTER_EMAIL="$EMAIL"
BRANCH="$(git symbolic-ref --short HEAD)"

# 1. v4.2.2, masked
mkdir "$TMP/v422"
git archive v4.2.2 | tar -x -C "$TMP/v422"
python3 "$TMP/mask.py" --root "$TMP/v422" >/dev/null
GIT_INDEX_FILE="$TMP/index" git --work-tree="$TMP/v422" add -A
TREE1="$(GIT_INDEX_FILE="$TMP/index" git write-tree)"
C1="$(GIT_AUTHOR_DATE="$(git log -1 --format=%aI v4.2.2)" GIT_COMMITTER_DATE="$(git log -1 --format=%cI v4.2.2)" \
      git commit-tree "$TREE1" -m "$(git log -1 --format=%B v4.2.2)")"

# 2. v4.3.0 = the files of the current last commit
C2="$(git commit-tree "HEAD^{tree}" -p "$C1" -m "$(git log -1 --format=%B v4.3.0)")"

git tag -f v4.2.2 "$C1" >/dev/null
git tag -f v4.3.0 "$C2" >/dev/null
git update-ref "refs/heads/$BRANCH" "$C2"
git reset -q                       # the files on disk are already these: only the index is refreshed
git config user.email "$EMAIL"
git config user.name "$NAME"

# Nothing of the old history may remain.
git reflog expire --expire=now --all
git gc -q --prune=now

echo "Checking every commit..."
FAILED=0
for rev in $(git rev-list --all); do
  rm -rf "$TMP/check" && mkdir "$TMP/check"
  git archive "$rev" | tar -x -C "$TMP/check"
  if ! python3 "$TMP/mask.py" --root "$TMP/check" --check >/dev/null; then
    echo "  personal data still in $(git log -1 --format='%h %s' "$rev")" >&2
    FAILED=1
  fi
done
EMAILS="$(git log --all --format='%ae%n%ce' | sort -u)"
if [[ "$EMAILS" != "$EMAIL" ]]; then
  echo "  other e-mails still in the history: $EMAILS" >&2
  FAILED=1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "  the files on disk differ from the new v4.3.0:" >&2
  git status --short >&2
  FAILED=1
fi
if [[ "$FAILED" != 0 ]]; then
  echo "NOT clean: do not publish yet." >&2
  exit 1
fi
echo "Clean: two commits, no personal data, every commit as $NAME <$EMAIL>. Future commits use it too."
git log --oneline --decorate --all
