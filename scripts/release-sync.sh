#!/usr/bin/env bash
set -euo pipefail

DEV_DIR=${DEV_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
RELEASE_DIR=${1:-"$(cd "$DEV_DIR/.." && pwd)/codex-cli-sync"}
BRANCH=${2:-main}

if ! git -C "$RELEASE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: release dir is not a git repository: $RELEASE_DIR" >&2
  exit 1
fi

rsync -av --delete \
  --exclude='.git/' \
  --exclude='.codex/' \
  --exclude='.serena/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='dist/' \
  --exclude='build/' \
  --exclude='planning/' \
  --exclude='docs/planning/' \
  --exclude='*.pyc' \
  "$DEV_DIR/" "$RELEASE_DIR/"

git -C "$RELEASE_DIR" add -A
if git -C "$RELEASE_DIR" diff --cached --quiet; then
  echo "No release changes to commit."
  exit 0
fi

git -C "$RELEASE_DIR" commit -m "Release $(date +%Y-%m-%d)"
git -C "$RELEASE_DIR" push origin "$BRANCH"
