"""Install, remove, and inspect managed Codex lifecycle hooks."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.errors import ConfigError

MANAGED_TOKEN = "codex-sync hook"
HOOK_EVENTS = {
    "SessionStart": "pull",
    "Stop": "push",
}


@dataclass(frozen=True)
class HookStatus:
    """Installed-state summary for managed lifecycle hooks."""

    session_start: bool
    stop: bool
    codex_hooks_enabled: bool

    @property
    def installed(self) -> bool:
        """Return whether all managed hook requirements are installed."""
        return self.session_start and self.stop and self.codex_hooks_enabled


def build_hook_command(action: str, config: Config) -> str:
    """Build the shell command used for a managed lifecycle hook."""
    source = config.hooks_source.strip()
    ref = config.hooks_ref.strip()
    if source:
        resolved_source = source
        if ref and source.startswith("git+") and "@" not in source.rsplit("/", 1)[-1]:
            resolved_source = f"{source}@{ref}"
        return " ".join(
            [
                "uvx",
                "--from",
                shlex.quote(resolved_source),
                "codex-sync",
                "hook",
                action,
            ]
        )
    return f"codex-sync hook {action}"


def install_hooks(
    codex_dir: Path = DEFAULT_CODEX_DIR, *, config: Config | None = None
) -> HookStatus:
    """Install managed Codex lifecycle hooks for enabled sync actions."""
    config = config or Config.load(codex_dir)
    data = _load_hooks(codex_dir / "hooks.json")
    hooks = data.setdefault("hooks", {})
    for event, action in HOOK_EVENTS.items():
        enabled = (action == "pull" and config.auto_pull_on_start) or (
            action == "push" and config.auto_push_on_stop
        )
        hooks[event] = _without_managed(hooks.get(event, []))
        if enabled:
            hooks[event].append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": build_hook_command(action, config),
                        }
                    ]
                }
            )
    _write_hooks(codex_dir / "hooks.json", data)
    ensure_codex_hooks_feature(codex_dir / "config.toml")
    return status(codex_dir)


def uninstall_hooks(codex_dir: Path = DEFAULT_CODEX_DIR) -> HookStatus:
    """Remove managed Codex lifecycle hooks and leave other hooks intact."""
    path = codex_dir / "hooks.json"
    data = _load_hooks(path)
    hooks = data.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        hooks[event] = _without_managed(hooks.get(event, []))
        if not hooks[event]:
            hooks.pop(event, None)
    _write_hooks(path, data)
    return status(codex_dir)


def status(codex_dir: Path = DEFAULT_CODEX_DIR) -> HookStatus:
    """Return the current managed hook installation status."""
    data = _load_hooks(codex_dir / "hooks.json")
    hooks = data.get("hooks", {})
    return HookStatus(
        session_start=_has_managed(hooks.get("SessionStart", []), "pull"),
        stop=_has_managed(hooks.get("Stop", []), "push"),
        codex_hooks_enabled=_codex_hooks_enabled(codex_dir / "config.toml"),
    )


def ensure_codex_hooks_feature(path: Path) -> None:
    """Ensure the Codex config enables lifecycle hook execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines()
    in_features = False
    features_index: int | None = None
    codex_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_features = stripped == "[features]"
            if in_features:
                features_index = index
            continue
        if in_features and stripped.startswith("codex_hooks"):
            codex_index = index
            break
    if codex_index is not None:
        lines[codex_index] = "codex_hooks = true"
    elif features_index is not None:
        lines.insert(features_index + 1, "codex_hooks = true")
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[features]", "codex_hooks = true"])
    path.write_text("\n".join(lines).rstrip() + "\n")


def _codex_hooks_enabled(path: Path) -> bool:
    if not path.exists():
        return False
    in_features = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_features = stripped == "[features]"
            continue
        if in_features and stripped.startswith("codex_hooks"):
            return stripped.split("=", 1)[-1].strip().lower() == "true"
    return False


def _load_hooks(path: Path) -> dict:
    if not path.exists():
        return {"hooks": {}}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ConfigError(f"{path} hooks must be a JSON object")
    return data


def _write_hooks(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _without_managed(entries: object) -> list[dict]:
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if not _entry_managed(entry)]


def _entry_managed(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []):
        if isinstance(hook, dict) and MANAGED_TOKEN in str(hook.get("command", "")):
            return True
    return False


def _has_managed(entries: object, action: str) -> bool:
    if not isinstance(entries, list):
        return False
    token = f"{MANAGED_TOKEN} {action}"
    return any(
        isinstance(hook, dict) and token in str(hook.get("command", ""))
        for entry in entries
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
    )
