#!/usr/bin/env bash
set -euo pipefail

# Curated weekly sync helper for the internal Hermes fork.
# This does NOT auto-merge to main. It creates an update branch, merges upstream,
# and tells you what to test next.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not inside a git repo" >&2
  exit 1
fi

CURRENT_BRANCH="$(git branch --show-current)"
TODAY="$(date +%F)"
UPDATE_BRANCH="update/upstream-${TODAY}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is dirty. Commit or stash changes first." >&2
  git status --short
  exit 1
fi

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "Missing upstream remote. Expected upstream -> NousResearch/hermes-agent" >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Missing origin remote." >&2
  exit 1
fi

echo "==> Fetching remotes"
git fetch origin --prune
git fetch upstream --prune

echo "==> Switching to main"
git checkout main
git pull --ff-only origin main

if git rev-parse --verify "$UPDATE_BRANCH" >/dev/null 2>&1; then
  echo "Branch $UPDATE_BRANCH already exists. Reusing it."
  git checkout "$UPDATE_BRANCH"
else
  echo "==> Creating $UPDATE_BRANCH"
  git checkout -b "$UPDATE_BRANCH"
fi

echo "==> Merging upstream/main into $UPDATE_BRANCH"
git merge upstream/main || {
  echo
  echo "Merge conflict. Resolve conflicts, then run:"
  echo "  git add <resolved-files>"
  echo "  git commit"
  exit 1
}

echo
echo "Update branch ready: $UPDATE_BRANCH"
echo
echo "Next steps:"
echo "  1. source .venv/bin/activate || true"
echo "  2. uv venv .venv --python 3.11 && source .venv/bin/activate"
echo "  3. uv pip install -e ."
echo "  4. bash scripts/install-superbud-hook.sh --check"
echo "  5. hermes webapi --port 8652"
echo "  6. In another shell: HERMES_API_URL=http://127.0.0.1:8652 bash scripts/smoke-test-webapi.sh"
echo "  7. Manually verify Hermes Workspace loads and chat/sessions/memory/skills work"
echo
echo "If clean, promote with:"
echo "  git checkout main"
echo "  git merge $UPDATE_BRANCH"
echo "  git push origin main"
echo
echo "If not worth keeping, drop it with:"
echo "  git checkout main && git branch -D $UPDATE_BRANCH"

if [[ "$CURRENT_BRANCH" != "main" && "$CURRENT_BRANCH" != "$UPDATE_BRANCH" ]]; then
  echo
  echo "You started on: $CURRENT_BRANCH"
fi
