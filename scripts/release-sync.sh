#!/usr/bin/env bash
set -euo pipefail

DEV_DIR=${DEV_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
RELEASE_DIR=${1:-"$(cd "$DEV_DIR/.." && pwd)/codex-cli-sync"}
BRANCH=${2:-main}

if ! git -C "$RELEASE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: release dir is not a git repository: $RELEASE_DIR" >&2
  exit 1
fi

uv run python - "$DEV_DIR" "$RELEASE_DIR" <<'PY'
from __future__ import annotations

import filecmp
import os
import shutil
import sys
from pathlib import Path

DEV_DIR = Path(sys.argv[1]).resolve()
RELEASE_DIR = Path(sys.argv[2]).resolve()
EXCLUDED_NAMES = {
    ".git",
    ".codex",
    ".serena",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "planning",
}
EXCLUDED_PATHS = {"docs/planning"}


def excluded(path: Path) -> bool:
    rel = path.as_posix()
    return (
        any(part in EXCLUDED_NAMES for part in path.parts)
        or rel in EXCLUDED_PATHS
        or any(rel.startswith(f"{prefix}/") for prefix in EXCLUDED_PATHS)
        or path.name.endswith(".pyc")
    )


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def copy_file(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        same_type = source.is_symlink() == target.is_symlink()
        if source.is_symlink() and same_type and os.readlink(source) == os.readlink(target):
            return
        if source.is_file() and target.is_file() and filecmp.cmp(source, target, shallow=False):
            return
        remove(target)
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, target)


def sync_dir(source: Path, target: Path, rel: Path = Path()) -> None:
    target.mkdir(parents=True, exist_ok=True)
    source_entries = {entry.name for entry in source.iterdir()}
    for entry in list(target.iterdir()):
        child_rel = rel / entry.name
        if child_rel.parts[:1] == (".git",):
            continue
        if excluded(child_rel) or entry.name not in source_entries:
            remove(entry)
    for entry in source.iterdir():
        child_rel = rel / entry.name
        if excluded(child_rel):
            continue
        target_entry = target / entry.name
        if entry.is_dir() and not entry.is_symlink():
            if target_entry.exists() and not target_entry.is_dir():
                remove(target_entry)
            sync_dir(entry, target_entry, child_rel)
        else:
            copy_file(entry, target_entry)


sync_dir(DEV_DIR, RELEASE_DIR)
print(f"Synced release files into {RELEASE_DIR}")
PY

git -C "$RELEASE_DIR" add -A
if git -C "$RELEASE_DIR" diff --cached --quiet; then
  echo "No release changes to commit."
  exit 0
fi

git -C "$RELEASE_DIR" commit -m "Release $(date +%Y-%m-%d)"
git -C "$RELEASE_DIR" push origin "$BRANCH"
