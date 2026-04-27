"""Tests for dependency tracking during git sync."""

from __future__ import annotations

import json

from codex_cli_sync.config import Config
from codex_cli_sync.sync import pull, push


def test_pull_reports_dependency_changes_from_remote(sync_repos) -> None:
    """Verify startup pulls surface remote dependency changes."""
    config = Config(hooks_source="", hooks_ref="")
    (sync_repos.second / "config.toml").write_text(
        """
[mcp_servers.web]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
"""
    )
    assert push(sync_repos.second, config=config).status == "pushed"

    outcome = pull(sync_repos.first, config=config)

    assert outcome.status == "pulled"
    assert "external dependencies changed" in outcome.detail
    manifest = json.loads((sync_repos.first / ".sync-dependencies.json").read_text())
    assert manifest["dependencies"][0]["package"] == "@modelcontextprotocol/server-fetch"
    state = json.loads((sync_repos.first / ".sync-state.json").read_text())
    assert state["dependency_changes"]["added"] == 1
