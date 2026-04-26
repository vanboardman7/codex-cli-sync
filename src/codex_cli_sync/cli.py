"""Command-line interface for Codex config sync."""

from __future__ import annotations

import argparse
from pathlib import Path

from codex_cli_sync import __version__
from codex_cli_sync.config import Config, DEFAULT_CODEX_DIR
from codex_cli_sync.errors import CodexSyncError, ConfigError
from codex_cli_sync.hook_runner import pull_from_hook, push_from_hook
from codex_cli_sync.hooks import install_hooks, status as hook_status, uninstall_hooks
from codex_cli_sync.init import clone as clone_config
from codex_cli_sync.init import create as create_config
from codex_cli_sync.sync import pull, push, status
from codex_cli_sync.verify import verify


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CodexSyncError as exc:
        print(f"error: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the codex-sync CLI."""
    parser = argparse.ArgumentParser(
        prog="codex-sync", description="Sync ~/.codex through git"
    )
    parser.add_argument(
        "--version", action="version", version=f"codex-sync {__version__}"
    )
    parser.add_argument("--codex-dir", type=Path, default=DEFAULT_CODEX_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="create or clone the sync repository")
    mode = init_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true")
    mode.add_argument("--clone", metavar="URL")
    init_parser.add_argument("--remote")
    init_parser.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        help="create a private GitHub repo with gh and use its HTTPS remote",
    )
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--install-hooks", action="store_true")
    init_parser.add_argument("--hook-source")
    init_parser.add_argument("--hook-ref")
    init_parser.set_defaults(func=_cmd_init)

    sub.add_parser("pull", help="pull config now").set_defaults(func=_cmd_pull)
    sub.add_parser("push", help="commit and push config now").set_defaults(
        func=_cmd_push
    )
    sub.add_parser("status", help="show sync state").set_defaults(func=_cmd_status)
    sub.add_parser("verify", help="run preflight checks").set_defaults(func=_cmd_verify)

    config_parser = sub.add_parser("config", help="manage generated config files")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show").set_defaults(func=_cmd_config_show)
    config_sub.add_parser("apply").set_defaults(func=_cmd_config_apply)

    hooks_parser = sub.add_parser("hooks", help="manage Codex lifecycle hooks")
    hooks_sub = hooks_parser.add_subparsers(dest="hooks_command", required=True)
    hooks_install = hooks_sub.add_parser("install")
    hooks_install.add_argument("--hook-source")
    hooks_install.add_argument("--hook-ref")
    hooks_install.set_defaults(func=_cmd_hooks_install)
    hooks_sub.add_parser("uninstall").set_defaults(func=_cmd_hooks_uninstall)
    hooks_sub.add_parser("status").set_defaults(func=_cmd_hooks_status)

    hook_parser = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook_sub = hook_parser.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser("pull").set_defaults(
        func=lambda args: pull_from_hook(args.codex_dir)
    )
    hook_sub.add_parser("push").set_defaults(
        func=lambda args: push_from_hook(args.codex_dir)
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config.load(args.codex_dir)
    if getattr(args, "hook_source", None):
        config.hooks_source = args.hook_source
    if getattr(args, "hook_ref", None):
        config.hooks_ref = args.hook_ref
    return config


def _cmd_init(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    if args.create:
        create_config(
            args.codex_dir,
            remote=args.remote,
            github_repo=args.github_repo,
            install=args.install_hooks,
            config=config,
        )
    else:
        if args.github_repo:
            raise ConfigError("--github-repo can only be used with --create")
        clone_config(
            args.codex_dir,
            remote=args.clone,
            force=args.force,
            install=args.install_hooks,
        )
    print("initialized")
    return 0


def _cmd_pull(args: argparse.Namespace) -> int:
    outcome = pull(args.codex_dir)
    print(
        outcome.status if not outcome.detail else f"{outcome.status}: {outcome.detail}"
    )
    return 0 if outcome.status not in {"conflict"} else 1


def _cmd_push(args: argparse.Namespace) -> int:
    outcome = push(args.codex_dir)
    print(
        outcome.status if not outcome.detail else f"{outcome.status}: {outcome.detail}"
    )
    return 0 if outcome.status not in {"conflict"} else 1


def _cmd_status(args: argparse.Namespace) -> int:
    report = status(args.codex_dir)
    print(f"repo: {report.repo}")
    print(f"branch: {report.branch}")
    print(f"remote: {report.remote}")
    print(f"dirty: {report.dirty}")
    print(f"ahead: {report.ahead}")
    print(f"behind: {report.behind}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify(args.codex_dir)
    if report.ok:
        print("ok")
        return 0
    for problem in report.problems:
        print(f"- {problem}")
    return 1


def _cmd_config_show(args: argparse.Namespace) -> int:
    config = Config.load(args.codex_dir)
    print("# .gitignore")
    print(config.render_gitignore(), end="")
    print("# .gitattributes")
    print(config.render_gitattributes(), end="")
    return 0


def _cmd_config_apply(args: argparse.Namespace) -> int:
    Config.load(args.codex_dir).apply(args.codex_dir)
    print("applied")
    return 0


def _cmd_hooks_install(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    result = install_hooks(args.codex_dir, config=config)
    print(_format_hook_status(result))
    return 0 if result.installed else 1


def _cmd_hooks_uninstall(args: argparse.Namespace) -> int:
    result = uninstall_hooks(args.codex_dir)
    print(_format_hook_status(result))
    return 0


def _cmd_hooks_status(args: argparse.Namespace) -> int:
    result = hook_status(args.codex_dir)
    print(_format_hook_status(result))
    return 0 if result.installed else 1


def _format_hook_status(result) -> str:
    return (
        f"SessionStart: {result.session_start}\n"
        f"Stop: {result.stop}\n"
        f"codex_hooks: {result.codex_hooks_enabled}"
    )
