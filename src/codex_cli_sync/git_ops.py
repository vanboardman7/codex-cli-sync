"""Small, typed wrappers around git commands used by sync operations."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from codex_cli_sync.errors import GitError


def git(
    cwd: Path,
    *args: str,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run git in a repository and return the completed process."""
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitError("git is required but was not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        rendered = " ".join(command)
        raise GitError(f"{rendered} timed out after {timeout}s") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        rendered = " ".join(command)
        raise GitError(detail or f"{rendered} failed with exit code {result.returncode}")
    return result


def is_repo(cwd: Path) -> bool:
    """Return whether the path is inside a Git work tree."""
    result = git(cwd, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def init_repo(cwd: Path, *, branch: str) -> None:
    """Initialize a Git repository with the configured branch name."""
    result = git(cwd, "init", "-b", branch, check=False)
    if result.returncode == 0:
        return
    git(cwd, "init")
    git(cwd, "checkout", "-B", branch)


def has_commits(cwd: Path) -> bool:
    """Return whether the repository has a HEAD commit."""
    result = git(cwd, "rev-parse", "--verify", "HEAD", check=False)
    return result.returncode == 0


def has_remote(cwd: Path, remote: str = "origin") -> bool:
    """Return whether the named remote is configured."""
    result = git(cwd, "remote", "get-url", remote, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def set_remote(cwd: Path, remote_url: str, remote: str = "origin") -> None:
    """Add or update the sync remote URL."""
    if has_remote(cwd, remote):
        git(cwd, "remote", "set-url", remote, remote_url)
    else:
        git(cwd, "remote", "add", remote, remote_url)


def staged_changes(cwd: Path) -> bool:
    """Return whether the index has staged changes."""
    result = git(cwd, "diff", "--cached", "--quiet", "--exit-code", check=False)
    if result.returncode in {0, 1}:
        return result.returncode == 1
    detail = (result.stderr or result.stdout).strip()
    raise GitError(detail or "git diff --cached failed")


def status_porcelain(cwd: Path) -> str:
    """Return porcelain status output for local changes."""
    return git(cwd, "status", "--porcelain=v1").stdout


def ignored_tracked_files(cwd: Path) -> list[str]:
    """Return tracked files that now match repository ignore rules."""
    result = git(cwd, "ls-files", "-ci", "--exclude-standard", "-z")
    return [path for path in result.stdout.split("\0") if path]


def untrack_files(cwd: Path, paths: Iterable[str]) -> None:
    """Remove paths from Git tracking while leaving working-tree files in place."""
    files = list(paths)
    for start in range(0, len(files), 100):
        git(
            cwd,
            "rm",
            "--cached",
            "-f",
            "--ignore-unmatch",
            "--",
            *files[start : start + 100],
            timeout=30,
        )


def current_branch(cwd: Path, default: str) -> str:
    """Return the current branch, falling back to the configured default."""
    result = git(cwd, "branch", "--show-current", check=False)
    return result.stdout.strip() or default


def remote_ref_exists(cwd: Path, branch: str) -> bool:
    """Return whether origin has the configured branch ref locally."""
    result = git(
        cwd,
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/remotes/origin/{branch}",
        check=False,
    )
    return result.returncode == 0


def is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    """Return whether one revision is an ancestor of another."""
    result = git(cwd, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return result.returncode == 0


def ahead_behind(cwd: Path, branch: str) -> tuple[int, int]:
    """Return commits ahead of and behind origin for the configured branch."""
    if not remote_ref_exists(cwd, branch):
        return 0, 0
    result = git(
        cwd,
        "rev-list",
        "--left-right",
        "--count",
        f"HEAD...origin/{branch}",
        check=False,
    )
    if result.returncode != 0:
        return 0, 0
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])
