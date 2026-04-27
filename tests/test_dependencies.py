"""Tests for external dependency tracking."""

from __future__ import annotations

import json
from pathlib import Path

from codex_cli_sync.dependencies import (
    DependencyManifest,
    DependencyRecord,
    check_dependencies,
    collect_manifest,
    diff_manifests,
    install_dependencies,
    refresh_manifest,
)


def test_collect_manifest_extracts_mcp_and_hook_dependencies(tmp_path: Path) -> None:
    """Verify MCP servers and chained hooks become stable dependency records."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[mcp_servers.git]
command = "uvx"
args = ["--from", "git+https://github.com/example/mcp-git", "mcp-git"]
"""
    )
    hook_command = (
        "context-mode hook codex sessionstart && "
        "uvx --from git+https://github.com/vanboardman7/codex-cli-sync "
        "codex-sync hook pull"
    )
    (tmp_path / "hooks.json").write_text(
        json.dumps(
            {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": hook_command}]}
                ]
            }
        )
    )

    manifest = refresh_manifest(tmp_path)

    assert any(
        record.kind == "mcp_server"
        and record.name == "filesystem"
        and record.package_manager == "npx"
        and record.package == "@modelcontextprotocol/server-filesystem"
        for record in manifest.dependencies
    )
    assert any(
        record.kind == "hook"
        and record.executable == "context-mode"
        and record.package_manager == ""
        for record in manifest.dependencies
    )
    assert any(
        record.kind == "hook"
        and record.package_manager == "uvx"
        and record.package == "git+https://github.com/vanboardman7/codex-cli-sync"
        for record in manifest.dependencies
    )
    manifest_text = (tmp_path / ".sync-dependencies.json").read_text()
    assert "generated_at" not in manifest_text


def test_check_dependencies_resolves_relative_venv_binary(tmp_path: Path) -> None:
    """Verify local virtualenv binaries are checked by exact path."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.local]
command = ".venv/bin/mcp-server"
args = ["--stdio"]
"""
    )
    manifest = collect_manifest(tmp_path)

    missing = check_dependencies(manifest, tmp_path)

    assert missing[0].available is False
    assert missing[0].scope == "local"
    assert ".venv/bin/mcp-server" in missing[0].detail

    binary = tmp_path / ".venv" / "bin" / "mcp-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    available = check_dependencies(manifest, tmp_path)

    assert available[0].available is True
    assert available[0].scope == "local"


def test_diff_manifests_reports_added_removed_and_changed() -> None:
    """Verify dependency changes are grouped by user-visible change type."""
    before = DependencyManifest(
        [
            DependencyRecord(
                id="hook:SessionStart:tool",
                kind="hook",
                name="SessionStart",
                source_file="hooks.json",
                executable="tool",
                args=["--old"],
            ),
            DependencyRecord(
                id="mcp:old",
                kind="mcp_server",
                name="old",
                source_file="config.toml",
                executable="old-server",
            ),
        ]
    )
    after = DependencyManifest(
        [
            DependencyRecord(
                id="hook:SessionStart:tool",
                kind="hook",
                name="SessionStart",
                source_file="hooks.json",
                executable="tool",
                args=["--new"],
            ),
            DependencyRecord(
                id="mcp:new",
                kind="mcp_server",
                name="new",
                source_file="config.toml",
                executable="new-server",
            ),
        ]
    )

    changes = diff_manifests(before, after)

    assert [record.id for record in changes.added] == ["mcp:new"]
    assert [record.id for record in changes.removed] == ["mcp:old"]
    assert [record.id for record in changes.changed] == ["hook:SessionStart:tool"]


def test_npx_package_install_captures_all_package_flags(tmp_path: Path) -> None:
    """Verify npx launch specs with supplemental packages preserve all installs."""
    config = """
[mcp_servers.desktop-commander]
command = "npx"
args = [
  "-y",
  "-p",
  "@wonderwhy-er/desktop-commander@latest",
  "-p",
  "ajv",
  "desktop-commander",
]
"""
    (tmp_path / "config.toml").write_text(config)

    manifest = collect_manifest(tmp_path)

    record = manifest.dependencies[0]
    assert record.package == "@wonderwhy-er/desktop-commander@latest"
    assert record.install_command == [
        "npm",
        "install",
        "-g",
        "@wonderwhy-er/desktop-commander@latest",
        "ajv",
    ]


def test_collect_manifest_adds_crawl4ai_local_setup_recipe(tmp_path: Path) -> None:
    """Verify the local Crawl4AI MCP server can be bootstrapped from the manifest."""
    python_path = tmp_path / "crawl4ai" / "bin" / "python"
    server_path = tmp_path / "bin" / "crawl4ai-mcp-server.py"
    config = f"""
[mcp_servers.crawl4ai]
command = "{python_path}"
args = ["{server_path}"]
"""
    (tmp_path / "config.toml").write_text(config)

    manifest = collect_manifest(tmp_path)

    record = manifest.dependencies[0]
    playwright = tmp_path / "crawl4ai" / "bin" / "playwright"
    assert record.package == "crawl4ai"
    assert record.install_commands == [
        ["uv", "venv", str(tmp_path / "crawl4ai"), "--python", "3.13"],
        ["uv", "pip", "install", "--python", str(python_path), "crawl4ai"],
        [str(playwright), "install", "chromium"],
        [str(playwright), "install-deps", "chromium"],
    ]


def test_install_dependencies_dry_run_returns_supported_commands(tmp_path: Path) -> None:
    """Verify install planning is explicit and does not execute by default."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.git]
command = "uvx"
args = ["--from", "git+https://github.com/example/mcp-git", "mcp-git"]

[mcp_servers.web]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
"""
    )
    manifest = collect_manifest(tmp_path)

    results = install_dependencies(manifest, tmp_path, execute=False)

    commands = [result.command for result in results]
    assert ["uv", "tool", "install", "git+https://github.com/example/mcp-git"] in commands
    assert ["npm", "install", "-g", "@modelcontextprotocol/server-fetch"] in commands
    assert all(result.status == "planned" for result in results)
