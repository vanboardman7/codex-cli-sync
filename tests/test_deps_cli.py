"""Tests for dependency tracking CLI commands."""

from __future__ import annotations

from pathlib import Path

from codex_cli_sync.cli import main


def test_deps_status_reports_missing_local_path(tmp_path: Path, capsys) -> None:
    """Verify dependency status reports missing machine-local binaries."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.local]
command = ".venv/bin/mcp-server"
args = ["--stdio"]
"""
    )

    code = main(["--codex-dir", str(tmp_path), "deps", "status"])
    output = capsys.readouterr().out

    assert code == 1
    assert "missing" in output
    assert ".venv/bin/mcp-server" in output


def test_deps_refresh_writes_manifest(tmp_path: Path, capsys) -> None:
    """Verify dependency refresh writes the tracked manifest file."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.web]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
"""
    )

    code = main(["--codex-dir", str(tmp_path), "deps", "refresh"])
    output = capsys.readouterr().out

    assert code == 0
    assert "tracked 1 external dependency" in output
    assert (tmp_path / ".sync-dependencies.json").exists()


def test_deps_install_uses_pulled_manifest_when_available(tmp_path: Path, capsys) -> None:
    """Verify install plans use synced manifest recipes, not only local config scans."""
    manifest = """
{
  "version": 1,
  "dependencies": [
    {
      "id": "mcp_server:config.toml:context-mode",
      "kind": "mcp_server",
      "name": "context-mode",
      "source_file": "config.toml",
      "scope": "global",
      "executable": "context-mode",
      "package_manager": "npm",
      "package": "context-mode",
      "install_command": ["npm", "install", "-g", "context-mode"]
    }
  ]
}
"""
    (tmp_path / ".sync-dependencies.json").write_text(manifest)

    code = main(["--codex-dir", str(tmp_path), "deps", "install"])
    output = capsys.readouterr().out

    assert code == 0
    assert "npm install -g context-mode" in output


def test_deps_status_uses_pulled_manifest_when_available(tmp_path: Path, capsys) -> None:
    """Verify status checks cloud-pulled dependency records before config exists."""
    manifest = """
{
  "version": 1,
  "dependencies": [
    {
      "id": "mcp_server:config.toml:local",
      "kind": "mcp_server",
      "name": "local",
      "source_file": "config.toml",
      "scope": "local",
      "executable": ".venv/bin/mcp-server"
    }
  ]
}
"""
    (tmp_path / ".sync-dependencies.json").write_text(manifest)

    code = main(["--codex-dir", str(tmp_path), "deps", "status"])
    output = capsys.readouterr().out

    assert code == 1
    assert "missing" in output
    assert ".venv/bin/mcp-server" in output


def test_deps_install_requires_execute_for_mutation(tmp_path: Path, capsys) -> None:
    """Verify dependency install prints a plan unless execution is explicit."""
    (tmp_path / "config.toml").write_text(
        """
[mcp_servers.web]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-fetch"]
"""
    )

    code = main(["--codex-dir", str(tmp_path), "deps", "install"])
    output = capsys.readouterr().out

    assert code == 0
    assert "dry-run" in output
    assert "npm install -g @modelcontextprotocol/server-fetch" in output
