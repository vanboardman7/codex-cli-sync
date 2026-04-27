"""Pull, push, and status operations for Codex config sync."""

# Sync commands return precise user-facing statuses from several early exits.
# pylint: disable=too-many-return-statements

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.dependencies import (
    collect_manifest,
    dependency_change_summary,
    diff_manifests,
    refresh_manifest,
    write_dependency_state,
)
from codex_cli_sync.errors import GitError
from codex_cli_sync.git_ops import (
    ahead_behind,
    current_branch,
    git,
    has_commits,
    has_remote,
    ignored_tracked_files,
    is_ancestor,
    is_repo,
    remote_ref_exists,
    staged_changes,
    status_porcelain,
    untrack_files,
)
from codex_cli_sync.lockfile import acquire_lock
from codex_cli_sync.logging_setup import log_event

PullStatus = Literal["pulled", "clean", "disabled", "not_repo", "no_remote", "conflict"]
PushStatus = Literal["pushed", "clean", "disabled", "not_repo", "no_remote", "conflict"]


@dataclass(frozen=True)
class PullOutcome:
    """Result returned after attempting a pull sync."""

    status: PullStatus
    detail: str = ""


@dataclass(frozen=True)
class PushOutcome:
    """Result returned after attempting a push sync."""

    status: PushStatus
    detail: str = ""


@dataclass(frozen=True)
class StatusReport:
    """Current repository and remote synchronization status."""

    repo: bool
    branch: str
    remote: bool
    dirty: bool
    ahead: int
    behind: int


def pull(
    codex_dir: Path = DEFAULT_CODEX_DIR, *, config: Config | None = None
) -> PullOutcome:
    """Pull remote sync changes into the Codex directory."""
    config = config or Config.load(codex_dir)
    if not config.auto_pull_on_start:
        return PullOutcome("disabled")
    with acquire_lock(codex_dir / ".sync.lock"):
        if not is_repo(codex_dir):
            return PullOutcome("not_repo")
        if not has_remote(codex_dir):
            return PullOutcome("no_remote")
        branch = config.branch
        fetch = git(codex_dir, "fetch", "--prune", "origin", check=False, timeout=20)
        if fetch.returncode != 0:
            return PullOutcome("no_remote", (fetch.stderr or fetch.stdout).strip())
        if not remote_ref_exists(codex_dir, branch):
            return PullOutcome("clean")
        before_dependencies = collect_manifest(codex_dir)
        stash_ref = _stash_if_dirty(codex_dir)
        try:
            if has_commits(codex_dir):
                merge = git(
                    codex_dir,
                    "merge",
                    "--ff-only",
                    f"origin/{branch}",
                    check=False,
                    timeout=20,
                )
            else:
                merge = git(
                    codex_dir,
                    "checkout",
                    "-B",
                    branch,
                    f"origin/{branch}",
                    check=False,
                    timeout=20,
                )
            if merge.returncode != 0:
                return PullOutcome("conflict", (merge.stderr or merge.stdout).strip())
            restored = _restore_stash(codex_dir, stash_ref)
            if not restored:
                return PullOutcome(
                    "conflict", "local changes conflicted while restoring stash"
                )
            config.apply(codex_dir)
            after_dependencies = refresh_manifest(codex_dir)
            dependency_changes = diff_manifests(before_dependencies, after_dependencies)
            write_dependency_state(codex_dir, dependency_changes)
            dependency_detail = dependency_change_summary(dependency_changes)
            outcome_status = "pulled" if merge.stdout.strip() else "clean"
            log_event(codex_dir, "pull", status=outcome_status)
            return PullOutcome(outcome_status, dependency_detail)
        finally:
            if stash_ref and _stash_exists(codex_dir, stash_ref):
                _restore_stash(codex_dir, stash_ref)


def push(
    codex_dir: Path = DEFAULT_CODEX_DIR, *, config: Config | None = None
) -> PushOutcome:
    """Commit and push local Codex configuration changes."""
    config = config or Config.load(codex_dir)
    if not config.auto_push_on_stop:
        return PushOutcome("disabled")
    with acquire_lock(codex_dir / ".sync.lock"):
        if not is_repo(codex_dir):
            return PushOutcome("not_repo")
        if not has_remote(codex_dir):
            return PushOutcome("no_remote")
        branch = config.branch
        config.apply(codex_dir)
        refresh_manifest(codex_dir)
        ignored_files = ignored_tracked_files(codex_dir)
        if ignored_files:
            untrack_files(codex_dir, ignored_files)
        fetch = git(codex_dir, "fetch", "--prune", "origin", check=False, timeout=20)
        if fetch.returncode != 0:
            return PushOutcome("no_remote", (fetch.stderr or fetch.stdout).strip())
        rebase_outcome = _rebase_before_commit(codex_dir, branch)
        if rebase_outcome:
            return rebase_outcome
        git(codex_dir, "add", "-A", timeout=20)
        committed = False
        if staged_changes(codex_dir):
            message = (
                f"Sync Codex config from {socket.gethostname()} at {_human_timestamp()}"
            )
            commit = git(codex_dir, "commit", "-m", message, check=False, timeout=20)
            if commit.returncode != 0:
                return PushOutcome("conflict", (commit.stderr or commit.stdout).strip())
            committed = True
        push_result = git(
            codex_dir, "push", "-u", "origin", f"HEAD:{branch}", check=False, timeout=30
        )
        if push_result.returncode != 0:
            return PushOutcome(
                "conflict", (push_result.stderr or push_result.stdout).strip()
            )
        outcome_status = (
            "pushed"
            if committed or "Everything up-to-date" not in push_result.stderr
            else "clean"
        )
        log_event(codex_dir, "push", status=outcome_status)
        return PushOutcome(outcome_status)


def status(
    codex_dir: Path = DEFAULT_CODEX_DIR, *, config: Config | None = None
) -> StatusReport:
    """Report repository, remote, dirty, and divergence status."""
    config = config or Config.load(codex_dir)
    if not is_repo(codex_dir):
        return StatusReport(
            repo=False,
            branch=config.branch,
            remote=False,
            dirty=False,
            ahead=0,
            behind=0,
        )
    branch = current_branch(codex_dir, config.branch)
    remote = has_remote(codex_dir)
    dirty = bool(status_porcelain(codex_dir).strip())
    ahead, behind = ahead_behind(codex_dir, branch) if remote else (0, 0)
    return StatusReport(
        repo=True, branch=branch, remote=remote, dirty=dirty, ahead=ahead, behind=behind
    )


def _rebase_before_commit(codex_dir: Path, branch: str) -> PushOutcome | None:
    if not has_commits(codex_dir):
        return None
    if not remote_ref_exists(codex_dir, branch):
        return None
    if is_ancestor(codex_dir, f"origin/{branch}", "HEAD"):
        return None
    stash_ref = _stash_if_dirty(codex_dir)
    try:
        rebase = git(codex_dir, "rebase", f"origin/{branch}", check=False, timeout=30)
        if rebase.returncode != 0:
            git(codex_dir, "rebase", "--abort", check=False, timeout=10)
            if stash_ref:
                restore_ref = stash_ref
                stash_ref = None
                if not _restore_stash(codex_dir, restore_ref):
                    return PushOutcome(
                        "conflict",
                        "remote changes conflicted while restoring local changes",
                    )
            return PushOutcome("conflict", (rebase.stderr or rebase.stdout).strip())
        if stash_ref:
            restore_ref = stash_ref
            stash_ref = None
            if not _restore_stash(codex_dir, restore_ref):
                return PushOutcome(
                    "conflict", "local changes conflicted while restoring stash"
                )
    finally:
        if stash_ref and _stash_exists(codex_dir, stash_ref):
            _restore_stash(codex_dir, stash_ref)
    return None


def _stash_if_dirty(codex_dir: Path) -> str | None:
    if not has_commits(codex_dir):
        return None
    if not status_porcelain(codex_dir).strip():
        return None
    before = git(
        codex_dir, "stash", "list", "--format=%gd", check=False
    ).stdout.splitlines()
    result = git(
        codex_dir,
        "stash",
        "push",
        "--include-untracked",
        "-m",
        f"codex-sync auto-stash {_human_timestamp()}",
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise GitError((result.stderr or result.stdout).strip())
    after = git(
        codex_dir, "stash", "list", "--format=%gd", check=False
    ).stdout.splitlines()
    return after[0] if after and after != before else None


def _restore_stash(codex_dir: Path, stash_ref: str | None) -> bool:
    if not stash_ref:
        return True
    result = git(codex_dir, "stash", "pop", stash_ref, check=False, timeout=20)
    return result.returncode == 0


def _stash_exists(codex_dir: Path, stash_ref: str) -> bool:
    return (
        git(codex_dir, "rev-parse", "--verify", stash_ref, check=False).returncode == 0
    )


def _human_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
