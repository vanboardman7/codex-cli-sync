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


def test_push_omits_local_runtime_files_but_syncs_sessions(sync_repos) -> None:
    """Verify push de-indexes runtime state while syncing session history."""
    config = Config(hooks_source="", hooks_ref="")
    (sync_repos.first / "logs_2.sqlite").write_text("cached state\n")
    git(sync_repos.first, "add", "logs_2.sqlite")
    git(sync_repos.first, "commit", "-m", "track local runtime file")
    git(sync_repos.first, "push", "origin", "main")
    git(sync_repos.second, "pull", "--ff-only", "origin", "main")

    session_file = (
        sync_repos.first
        / "sessions"
        / "2026"
        / "04"
        / "27"
        / "rollout.jsonl"
    )
    session_file.parent.mkdir(parents=True)
    session_file.write_text('{"type":"message"}\n')
    (sync_repos.first / "history.jsonl").write_text('{"session":"latest"}\n')
    (sync_repos.first / "logs_2.sqlite").write_text("new local cache\n")
    git(sync_repos.first, "add", "logs_2.sqlite")
    (sync_repos.first / "logs_2.sqlite").write_text("newer local cache\n")
    (sync_repos.first / "logs_2.sqlite-wal").write_text("wal\n")
    content_dir = sync_repos.first / "context-mode" / "content"
    content_dir.mkdir(parents=True)
    (content_dir / "cache.db").write_text("cache\n")

    outcome = push(sync_repos.first, config=config)

    assert outcome.status == "pushed"
    assert (sync_repos.first / "logs_2.sqlite").exists()
    assert (sync_repos.first / "logs_2.sqlite-wal").exists()
    tracked_runtime = git(
        sync_repos.first,
        "ls-files",
        "logs_2.sqlite",
        "logs_2.sqlite-wal",
        "context-mode/content/cache.db",
    )
    assert tracked_runtime.stdout == ""

    pulled = pull(sync_repos.second, config=config)
    assert pulled.status in {"pulled", "clean"}
    assert (sync_repos.second / "history.jsonl").read_text() == '{"session":"latest"}\n'
    assert (sync_repos.second / session_file.relative_to(sync_repos.first)).read_text() == (
        '{"type":"message"}\n'
    )
    assert not (sync_repos.second / "logs_2.sqlite").exists()



def test_push_refuses_config_toml_with_conflict_markers(sync_repos) -> None:
    """Verify push refuses to sync unresolved config.toml conflicts."""
    config = Config(hooks_source="", hooks_ref="")
    (sync_repos.first / "config.toml").write_text(
        "[projects.foo]\n<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n"
    )

    outcome = push(sync_repos.first, config=config)

    assert outcome.status == "invalid"
    assert "config.toml" in outcome.detail
    assert "conflict marker" in outcome.detail
    ahead = git(sync_repos.first, "rev-list", "--count", "origin/main..HEAD")
    assert ahead.stdout.strip() == "0"
    assert _remote_config(sync_repos.second) == "[features]\n"


def test_push_refuses_invalid_config_toml(sync_repos) -> None:
    """Verify push refuses to sync unparsable config.toml."""
    config = Config(hooks_source="", hooks_ref="")
    (sync_repos.first / "config.toml").write_text("[projects\n")

    outcome = push(sync_repos.first, config=config)

    assert outcome.status == "invalid"
    assert "config.toml" in outcome.detail
    assert "invalid TOML" in outcome.detail
    ahead = git(sync_repos.first, "rev-list", "--count", "origin/main..HEAD")
    assert ahead.stdout.strip() == "0"
    assert _remote_config(sync_repos.second) == "[features]\n"


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


def _remote_config(repo) -> str:
    """Return config.toml from the current remote main branch."""
    git(repo, "fetch", "origin", "main")
    return git(repo, "show", "origin/main:config.toml").stdout
