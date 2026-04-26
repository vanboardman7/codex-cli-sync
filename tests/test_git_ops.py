"""Tests for git command helper behavior."""

from __future__ import annotations

from pathlib import Path

from codex_cli_sync.git_ops import (
    git,
    has_commits,
    has_remote,
    init_repo,
    is_repo,
    set_remote,
    staged_changes,
)


def test_git_helpers_initialize_and_update_remote(tmp_path: Path) -> None:
    """Verify git helpers cover the repository setup path."""
    init_repo(tmp_path, branch="main")

    assert is_repo(tmp_path)
    assert not has_commits(tmp_path)
    assert not has_remote(tmp_path)

    set_remote(tmp_path, "https://github.com/example/config.git")
    assert has_remote(tmp_path)

    set_remote(tmp_path, "https://github.com/example/updated.git")
    result = git(tmp_path, "remote", "get-url", "origin")
    assert result.stdout.strip() == "https://github.com/example/updated.git"


def test_staged_changes_detects_index_changes(tmp_path: Path) -> None:
    """Verify staged change detection only reports index changes."""
    init_repo(tmp_path, branch="main")
    (tmp_path / "AGENTS.md").write_text("rules\n")

    assert not staged_changes(tmp_path)

    git(tmp_path, "add", "AGENTS.md")
    assert staged_changes(tmp_path)
