"""Repository creation and clone helpers for Codex config sync."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.errors import ConfigError
from codex_cli_sync.git_ops import (
    git,
    has_commits,
    init_repo,
    is_repo,
    set_remote,
    staged_changes,
)
from codex_cli_sync.hooks import install_hooks

GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def create(
    codex_dir: Path = DEFAULT_CODEX_DIR,
    *,
    remote: str | None = None,
    github_repo: str | None = None,
    install: bool = False,
    config: Config | None = None,
) -> None:
    """Create and optionally push a new Codex sync repository."""
    if remote and github_repo:
        raise ConfigError("--remote and --github-repo cannot be used together")
    if github_repo:
        remote = create_github_repo(github_repo)

    config = config or Config()
    codex_dir.mkdir(parents=True, exist_ok=True)
    if not is_repo(codex_dir):
        init_repo(codex_dir, branch=config.branch)
    config.apply(codex_dir)
    if remote:
        set_remote(codex_dir, remote)
    git(codex_dir, "add", "-A")
    if staged_changes(codex_dir) or not has_commits(codex_dir):
        git(codex_dir, "commit", "--allow-empty", "-m", "Initial Codex config sync")
    if remote:
        git(codex_dir, "push", "-u", "origin", f"HEAD:{config.branch}")
    if install:
        install_hooks(codex_dir, config=config)


def clone(
    codex_dir: Path = DEFAULT_CODEX_DIR,
    *,
    remote: str,
    force: bool = False,
    install: bool = False,
) -> None:
    """Clone an existing sync repository into the Codex directory."""
    if codex_dir.exists() and any(codex_dir.iterdir()):
        if not force:
            raise ConfigError(f"{codex_dir} is not empty; use --force to move it aside")
        backup = codex_dir.with_name(f"{codex_dir.name}.bak-{_timestamp()}")
        shutil.move(str(codex_dir), str(backup))
    codex_dir.parent.mkdir(parents=True, exist_ok=True)
    result = git(
        codex_dir.parent, "clone", remote, str(codex_dir), check=False, timeout=60
    )
    if result.returncode != 0:
        raise ConfigError((result.stderr or result.stdout).strip())
    default_config = Config()
    if not has_commits(codex_dir):
        checkout = git(
            codex_dir,
            "checkout",
            "-B",
            default_config.branch,
            f"origin/{default_config.branch}",
            check=False,
            timeout=30,
        )
        if checkout.returncode != 0:
            fetch = git(
                codex_dir,
                "fetch",
                "origin",
                f"{default_config.branch}:refs/remotes/origin/{default_config.branch}",
                check=False,
                timeout=60,
            )
            if fetch.returncode == 0:
                checkout = git(
                    codex_dir,
                    "checkout",
                    "-B",
                    default_config.branch,
                    f"origin/{default_config.branch}",
                    check=False,
                    timeout=30,
                )
        if checkout.returncode != 0:
            raise ConfigError((checkout.stderr or checkout.stdout).strip())
    config = Config.load(codex_dir)
    config.apply(codex_dir)
    if install:
        install_hooks(codex_dir, config=config)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def create_github_repo(repo: str) -> str:
    """Create a private GitHub repository and return its HTTPS remote."""
    remote = github_https_remote(repo)
    if shutil.which("gh") is None:
        raise ConfigError(
            "gh is required for --github-repo; install GitHub CLI or pass --remote instead"
        )

    # Create the remote first so authentication failures leave local state unchanged.
    try:
        result = subprocess.run(
            ["gh", "repo", "create", repo, "--private"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(f"gh repo create {repo} --private timed out") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError(f"gh repo create {repo} --private failed: {detail}")
    return remote


def github_https_remote(repo: str) -> str:
    """Convert an owner/name GitHub repo identifier to an HTTPS remote URL."""
    # HTTPS works with GitHub CLI credential helpers and does not require SSH key setup.
    repo = repo.strip()
    if not GITHUB_REPO_RE.fullmatch(repo):
        raise ConfigError("--github-repo must be in owner/name form")
    owner, name = repo.split("/", maxsplit=1)
    return f"https://github.com/{owner}/{name}.git"
