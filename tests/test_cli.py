"""Tests for the codex-sync command-line interface."""

from __future__ import annotations

from pathlib import Path

from codex_cli_sync import cli
from codex_cli_sync.cli import main
from codex_cli_sync.sync import PushOutcome


def test_config_apply_command(tmp_path: Path, capsys) -> None:
    """Verify the config apply command writes generated files."""
    code = main(["--codex-dir", str(tmp_path), "config", "apply"])
    output = capsys.readouterr().out
    assert code == 0
    assert output == "applied\n"
    assert (tmp_path / ".gitignore").exists()


def test_hooks_status_fails_when_missing(tmp_path: Path, capsys) -> None:
    """Verify hooks status fails when managed hooks are missing."""
    code = main(["--codex-dir", str(tmp_path), "hooks", "status"])
    output = capsys.readouterr().out
    assert code == 1
    assert "SessionStart: False" in output


def test_push_command_fails_for_invalid_config(tmp_path: Path, monkeypatch, capsys) -> None:
    """Verify push command exits nonzero when validation blocks sync."""

    def fake_push(codex_dir):
        assert codex_dir == tmp_path
        return PushOutcome("invalid", "config.toml: invalid TOML")

    monkeypatch.setattr(cli, "push", fake_push)

    code = main(["--codex-dir", str(tmp_path), "push"])
    output = capsys.readouterr().out

    assert code == 1
    assert output == "invalid: config.toml: invalid TOML\n"


def test_init_create_accepts_github_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    """Verify init create accepts a GitHub repo target."""
    call = {}

    def fake_create(codex_dir, *, remote, github_repo, install, config):
        call.update(
            codex_dir=codex_dir,
            remote=remote,
            github_repo=github_repo,
            install=install,
            config=config,
        )

    monkeypatch.setattr(cli, "create_config", fake_create)

    code = main(
        [
            "--codex-dir",
            str(tmp_path),
            "init",
            "--create",
            "--github-repo",
            "vanboardman7/codex-config",
            "--install-hooks",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert output == "initialized\n"
    assert call["codex_dir"] == tmp_path
    assert call["remote"] is None
    assert call["github_repo"] == "vanboardman7/codex-config"
    assert call["install"] is True


def test_init_clone_rejects_github_repo(tmp_path: Path, capsys) -> None:
    """Verify init clone rejects GitHub repo creation options."""
    code = main(
        [
            "--codex-dir",
            str(tmp_path),
            "init",
            "--clone",
            "https://github.com/vanboardman7/codex-config.git",
            "--github-repo",
            "vanboardman7/codex-config",
        ]
    )
    output = capsys.readouterr().out

    assert code == 1
    assert "--github-repo can only be used with --create" in output
