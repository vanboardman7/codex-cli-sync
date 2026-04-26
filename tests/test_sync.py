"""Tests for pull, push, and status sync operations."""

from __future__ import annotations

from codex_cli_sync.config import Config
from codex_cli_sync.git_ops import git
from codex_cli_sync.sync import pull, push, status


def test_push_commits_and_updates_remote(sync_repos) -> None:
    """Verify push commits local changes and pull receives them."""
    (sync_repos.first / "AGENTS.md").write_text("rules\n")
    outcome = push(sync_repos.first, config=Config(hooks_source="", hooks_ref=""))
    assert outcome.status == "pushed"
    pulled = pull(sync_repos.second, config=Config(hooks_source="", hooks_ref=""))
    assert pulled.status in {"pulled", "clean"}
    assert (sync_repos.second / "AGENTS.md").read_text() == "rules\n"


def test_push_reports_clean_when_nothing_changed(sync_repos) -> None:
    """Verify push reports a clean or already synchronized repo."""
    outcome = push(sync_repos.first, config=Config(hooks_source="", hooks_ref=""))
    assert outcome.status in {"clean", "pushed"}
    report = status(sync_repos.first, config=Config(hooks_source="", hooks_ref=""))
    assert report.repo is True
    assert report.remote is True


def test_push_conflict_does_not_create_auto_commit(sync_repos) -> None:
    """Verify remote conflicts do not leave a local auto-sync commit behind."""
    config = Config(hooks_source="", hooks_ref="")
    (sync_repos.second / "AGENTS.md").write_text("remote\n")
    assert push(sync_repos.second, config=config).status == "pushed"

    (sync_repos.first / "AGENTS.md").write_text("local\n")
    outcome = push(sync_repos.first, config=config)

    assert outcome.status == "conflict"
    ahead = git(
        sync_repos.first,
        "rev-list",
        "--count",
        "origin/main..HEAD",
        check=False,
    )
    assert ahead.stdout.strip() == "0"
