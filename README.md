# codex-cli-sync

Git-backed roaming for `~/.codex`. The tool installs Codex CLI lifecycle hooks that pull on `SessionStart` and push on `Stop`, so settings, rules, skills, plugins, memories, and session state can follow you between machines.

The sync tool is designed to run from hooks through `uvx --from ...`, so the target machine only needs `uv`, `git`, and Codex CLI. Git LFS is not required unless you opt into LFS patterns in `.sync.toml`.

## Quick Start

Enroll the first machine. This creates a private GitHub repository with `gh` and uses the HTTPS remote URL:

```bash
uvx --from git+https://github.com/vanboardman7/codex-cli-sync codex-sync init --create --github-repo <you>/codex-config --install-hooks
```

If you already created the repository, or you are not using GitHub CLI, pass the HTTPS remote directly:

```bash
uvx --from git+https://github.com/vanboardman7/codex-cli-sync codex-sync init --create --remote https://github.com/<you>/codex-config.git --install-hooks
```

Enroll another machine:

```bash
uvx --from git+https://github.com/vanboardman7/codex-cli-sync codex-sync init --clone https://github.com/<you>/codex-config.git
uvx --from git+https://github.com/vanboardman7/codex-cli-sync codex-sync verify
uvx --from git+https://github.com/vanboardman7/codex-cli-sync codex-sync hooks install
```

If you are using a fork or private copy of this tool, pass `--hook-source <git-url>` during `init` or `hooks install`.

Use `uvx --from`, not `uvx --with`, when running from the Git repository. `--with` adds dependencies to another tool environment, while `--from` selects the package that provides the `codex-sync` executable.

## Commands

| Command | Description |
| --- | --- |
| `codex-sync init --create --github-repo <owner/name>` | Create a private GitHub repo, initialize `~/.codex`, and push it |
| `codex-sync init --create --remote <url>` | Initialize `~/.codex` as a git repo and push it |
| `codex-sync init --clone <url>` | Clone an existing config repo into `~/.codex` |
| `codex-sync verify` | Check config, git, and hook wiring |
| `codex-sync pull` | Manual pull from the remote |
| `codex-sync push` | Manual commit and push |
| `codex-sync status` | Show local sync state |
| `codex-sync config show` | Print generated ignore/attribute files |
| `codex-sync config apply` | Regenerate `.gitignore` and `.gitattributes` |
| `codex-sync hooks install` | Merge managed hooks into `~/.codex/hooks.json` |
| `codex-sync hooks uninstall` | Remove only managed hook entries |
| `codex-sync hooks status` | Inspect managed hook status |

## Configuration

`~/.codex/.sync.toml` is tracked and shared:

```toml
[sync]
auto_pull_on_start = true
auto_push_on_stop = true
branch = "main"

[paths]
exclude = [".sync.lock", ".sync.log", "auth.json", "*.tmp", "*.swp"]
include = []

[lfs]
patterns = []

[hooks]
source = "git+https://github.com/vanboardman7/codex-cli-sync"
ref = "main"
```

`auth.json` is excluded by default. Syncing credentials across machines is risky; log in separately on each machine.

Codex currently loads lifecycle hooks from the global `~/.codex/hooks.json`, not from plugin-local hook files, so `hooks install` edits that file and enables `[features].codex_hooks = true` in `config.toml`.

## Release Sync

Keep this dev checkout separate from the normal release repo. To publish only release-ready files into the sibling release repo, run:

```bash
scripts/release-sync.sh ../codex-cli-sync
```

The script uses `rsync --delete`, excludes dev-only directories like `.codex/`, `.serena/`, planning files, virtualenvs, caches, and build output, then commits and pushes the release repo's `main` branch when there are changes.
