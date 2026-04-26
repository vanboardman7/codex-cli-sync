"""Shared fixtures for sync tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class SyncRepos:
    """Pair of test working repositories backed by one bare remote."""

    bare: Path
    first: Path
    second: Path


@pytest.fixture
def sync_repos(tmp_path: Path) -> SyncRepos:
    """Create two working clones that share a bare sync remote."""
    bare = tmp_path / "remote.git"
    first = tmp_path / "first"
    second = tmp_path / "second"
    _run(tmp_path, "git", "init", "--bare", str(bare))
    _run(tmp_path, "git", "init", "-b", "main", str(first))
    _run(first, "git", "config", "user.email", "test@example.com")
    _run(first, "git", "config", "user.name", "Test User")
    _run(first, "git", "remote", "add", "origin", str(bare))
    (first / "config.toml").write_text("[features]\n")
    _run(first, "git", "add", "-A")
    _run(first, "git", "commit", "-m", "initial")
    _run(first, "git", "push", "-u", "origin", "main")
    _run(tmp_path, "git", "clone", str(bare), str(second))
    _run(second, "git", "checkout", "-B", "main", "origin/main")
    _run(second, "git", "config", "user.email", "test@example.com")
    _run(second, "git", "config", "user.name", "Test User")
    return SyncRepos(bare=bare, first=first, second=second)


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
