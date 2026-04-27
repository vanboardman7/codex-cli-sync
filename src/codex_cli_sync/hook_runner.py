"""Lifecycle hook entry points that run sync actions safely."""

# Hook commands should log unexpected errors without blocking Codex startup/exit.
# pylint: disable=broad-exception-caught

from __future__ import annotations

import json
import sys
from pathlib import Path

from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.errors import CodexSyncError, LockContentionError
from codex_cli_sync.logging_setup import log_event
from codex_cli_sync.sync import pull, push


def pull_from_hook(codex_dir: Path = DEFAULT_CODEX_DIR) -> int:
    """Run the pull lifecycle hook without failing Codex startup."""
    return _run_hook("pull", codex_dir)


def push_from_hook(codex_dir: Path = DEFAULT_CODEX_DIR) -> int:
    """Run the push lifecycle hook without failing Codex shutdown."""
    return _run_hook("push", codex_dir)


def _run_hook(action: str, codex_dir: Path) -> int:
    hook_input = _read_hook_input()
    if hook_input.get("agent_id") or hook_input.get("agent_type"):
        log_event(codex_dir, f"hook_{action}", status="skipped_subagent")
        return 0
    try:
        config = Config.load(codex_dir)
        outcome = (
            pull(codex_dir, config=config)
            if action == "pull"
            else push(codex_dir, config=config)
        )
        if action == "pull" and outcome.detail.startswith("external dependencies changed"):
            print(f"codex-sync: {outcome.detail}", file=sys.stderr)
        log_event(
            codex_dir, f"hook_{action}", status=outcome.status, detail=outcome.detail
        )
    except LockContentionError:
        log_event(codex_dir, f"hook_{action}", status="locked")
    except CodexSyncError as exc:
        log_event(codex_dir, f"hook_{action}", status="error", detail=str(exc))
    except Exception as exc:  # pragma: no cover
        log_event(
            codex_dir, f"hook_{action}", status="unexpected_error", detail=str(exc)
        )
    return 0


def _read_hook_input() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    text = sys.stdin.read().strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
