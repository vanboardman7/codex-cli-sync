"""Tests for managed lifecycle hook installation."""

from __future__ import annotations

import json
from pathlib import Path

from codex_cli_sync.config import Config
from codex_cli_sync.hooks import (
    build_hook_command,
    install_hooks,
    status,
    uninstall_hooks,
)


def test_install_preserves_existing_hooks_and_enables_feature(tmp_path: Path) -> None:
    """Verify install preserves unmanaged hooks and enables hook support."""
    (tmp_path / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "context-mode hook codex sessionstart",
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    (tmp_path / "config.toml").write_text('model = "gpt-5"\n')
    result = install_hooks(tmp_path, config=Config(hooks_source="", hooks_ref=""))
    assert result.installed
    data = json.loads((tmp_path / "hooks.json").read_text())
    assert len(data["hooks"]["SessionStart"]) == 2
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "codex-sync hook push"
    assert "[features]\ncodex_hooks = true" in (tmp_path / "config.toml").read_text()


def test_uninstall_removes_only_managed_hooks(tmp_path: Path) -> None:
    """Verify uninstall removes only managed hook entries."""
    install_hooks(tmp_path, config=Config(hooks_source="", hooks_ref=""))
    data = json.loads((tmp_path / "hooks.json").read_text())
    data["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "other stop"}]}
    )
    (tmp_path / "hooks.json").write_text(json.dumps(data))
    result = uninstall_hooks(tmp_path)
    assert not result.session_start
    data = json.loads((tmp_path / "hooks.json").read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "other stop"


def test_status_detects_missing_feature_flag(tmp_path: Path) -> None:
    """Verify hook status notices when the feature flag is missing."""
    install_hooks(tmp_path, config=Config(hooks_source="", hooks_ref=""))
    (tmp_path / "config.toml").write_text("")
    assert not status(tmp_path).installed


def test_hook_command_uses_uvx_from_for_package_source() -> None:
    """Verify package hook commands use uvx with the configured source."""
    command = build_hook_command("pull", Config())
    assert command.startswith("uvx --from ")
    assert " --with " not in command
    assert command.endswith(" codex-sync hook pull")
