"""Tests for repository initialization helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codex_cli_sync.config import Config
from codex_cli_sync import init
from codex_cli_sync.errors import ConfigError
from codex_cli_sync.git_ops import git


def test_github_https_remote_uses_https_url() -> None:
    """Verify GitHub repo names become HTTPS remote URLs."""
    assert (
        init.github_https_remote("vanboardman7/codex-config")
        == "https://github.com/vanboardman7/codex-config.git"
    )


def test_github_https_remote_requires_owner_and_name() -> None:
    """Verify GitHub repo names must include owner and name."""
    with pytest.raises(ConfigError, match="owner/name"):
        init.github_https_remote("codex-config")


def test_create_github_repo_creates_private_repo(monkeypatch) -> None:
    """Verify GitHub repo creation uses a private repository."""
    commands = []

    monkeypatch.setattr(
        init.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None
    )

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(init.subprocess, "run", fake_run)

    remote = init.create_github_repo("vanboardman7/codex-config")

    assert remote == "https://github.com/vanboardman7/codex-config.git"
    assert commands[0][0] == [
        "gh",
        "repo",
        "create",
        "vanboardman7/codex-config",
        "--private",
    ]


def test_create_pushes_head_to_configured_branch(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify first push honors the configured branch as the destination."""
    commands = []

    def fake_git(cwd, *args, **kwargs):
        commands.append((cwd, args, kwargs))
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(init, "git", fake_git)
    monkeypatch.setattr(init, "is_repo", lambda _path: True)
    monkeypatch.setattr(init, "set_remote", lambda _path, _remote: None)
    monkeypatch.setattr(init, "staged_changes", lambda _path: True)
    monkeypatch.setattr(init, "has_commits", lambda _path: True)

    init.create(
        tmp_path,
        remote="https://github.com/vanboardman7/codex-config.git",
        config=Config(branch="trunk", hooks_source="", hooks_ref=""),
    )

    assert any(args == ("push", "-u", "origin", "HEAD:trunk") for _, args, _ in commands)


def test_clone_checks_out_main_when_remote_head_is_unset(tmp_path: Path) -> None:
    """Verify clone handles bare remotes whose HEAD still points at master."""
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    target = tmp_path / "target"

    git(tmp_path, "init", "--bare", str(bare))
    git(tmp_path, "init", "-b", "main", str(seed))
    git(seed, "config", "user.email", "test@example.com")
    git(seed, "config", "user.name", "Test User")
    git(seed, "remote", "add", "origin", str(bare))
    (seed / ".sync.toml").write_text(
        Config(hooks_source="", hooks_ref="").to_toml()
    )
    (seed / "AGENTS.md").write_text("rules\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "initial")
    git(seed, "push", "-u", "origin", "main")

    init.clone(target, remote=str(bare))

    assert (target / "AGENTS.md").read_text() == "rules\n"
    assert git(target, "branch", "--show-current").stdout.strip() == "main"
