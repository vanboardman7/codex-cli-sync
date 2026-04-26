"""Preflight verification for Codex sync setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.errors import ConfigError
from codex_cli_sync.git_ops import has_remote, is_repo
from codex_cli_sync.hooks import status as hook_status


@dataclass(frozen=True)
class VerifyReport:
    """Preflight verification result with any discovered problems."""

    ok: bool
    problems: list[str] = field(default_factory=list)


def verify(codex_dir: Path = DEFAULT_CODEX_DIR) -> VerifyReport:
    """Run local preflight checks for Codex sync configuration."""
    problems: list[str] = []
    try:
        Config.load(codex_dir)
    except ConfigError as exc:
        problems.append(str(exc))
    if not codex_dir.exists():
        problems.append(f"{codex_dir} does not exist")
    elif not is_repo(codex_dir):
        problems.append(f"{codex_dir} is not a git repository")
    elif not has_remote(codex_dir):
        problems.append("git remote origin is not configured")
    try:
        hooks = hook_status(codex_dir)
        if not hooks.installed:
            problems.append("managed hooks are not fully installed")
    except ConfigError as exc:
        problems.append(str(exc))
    return VerifyReport(ok=not problems, problems=problems)
