"""Track external dependencies referenced by synced Codex configuration."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = ".sync-dependencies.json"
STATE_FILENAME = ".sync-state.json"
MANIFEST_VERSION = 1

_SHELL_EXECUTABLES = {"bash", "sh", "zsh", "fish"}
_INSTALL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class DependencyRecord:  # pylint: disable=too-many-instance-attributes
    """One external command, package, path, or plugin source reference."""

    id: str
    kind: str
    name: str
    source_file: str
    executable: str = ""
    args: list[str] = field(default_factory=list)
    package_manager: str = ""
    package: str = ""
    scope: str = "global"
    install_command: list[str] = field(default_factory=list)
    install_commands: list[list[str]] = field(default_factory=list)
    reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Render this record as stable manifest JSON data."""
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "source_file": self.source_file,
            "scope": self.scope,
        }
        optional: dict[str, Any] = {
            "executable": self.executable,
            "args": self.args,
            "package_manager": self.package_manager,
            "package": self.package,
            "install_command": self.install_command,
            "reference": self.reference,
        }
        legacy_commands = [self.install_command] if self.install_command else []
        if self.install_commands and self.install_commands != legacy_commands:
            optional["install_commands"] = self.install_commands
        data.update({key: value for key, value in optional.items() if value})
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DependencyRecord":
        """Build a dependency record from manifest JSON data."""
        install_command = [
            str(item) for item in data.get("install_command", []) if isinstance(item, str)
        ]
        raw_install_commands = data.get("install_commands", [])
        install_commands = [
            [str(item) for item in command]
            for command in raw_install_commands
            if isinstance(command, list) and all(isinstance(item, str) for item in command)
        ]
        if install_command and install_command not in install_commands:
            install_commands.insert(0, install_command)
        if not install_command and install_commands:
            install_command = list(install_commands[0])
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            name=str(data["name"]),
            source_file=str(data["source_file"]),
            executable=str(data.get("executable", "")),
            args=list(data.get("args", [])),
            package_manager=str(data.get("package_manager", "")),
            package=str(data.get("package", "")),
            scope=str(data.get("scope", "global")),
            install_command=install_command,
            install_commands=install_commands,
            reference=str(data.get("reference", "")),
        )


@dataclass(frozen=True)
class DependencyManifest:
    """Stable set of external dependency records for a Codex directory."""

    dependencies: list[DependencyRecord] = field(default_factory=list)
    version: int = MANIFEST_VERSION

    def sorted(self) -> "DependencyManifest":
        """Return a copy with records sorted by stable identity."""
        return DependencyManifest(
            dependencies=sorted(self.dependencies, key=lambda record: record.id),
            version=self.version,
        )

    def to_dict(self) -> dict[str, Any]:
        """Render this manifest as stable JSON data."""
        ordered = self.sorted()
        return {
            "version": ordered.version,
            "dependencies": [record.to_dict() for record in ordered.dependencies],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DependencyManifest":
        """Build a manifest from decoded JSON data."""
        dependencies = [
            DependencyRecord.from_dict(item)
            for item in data.get("dependencies", [])
            if isinstance(item, dict)
        ]
        return cls(dependencies=dependencies, version=int(data.get("version", 1))).sorted()


@dataclass(frozen=True)
class DependencyChanges:
    """Added, removed, and changed dependency records."""

    added: list[DependencyRecord] = field(default_factory=list)
    removed: list[DependencyRecord] = field(default_factory=list)
    changed: list[DependencyRecord] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Return whether any dependency records changed."""
        return bool(self.added or self.removed or self.changed)


@dataclass(frozen=True)
class DependencyStatus:
    """Availability check result for one dependency record."""

    record: DependencyRecord
    available: bool
    scope: str
    detail: str


@dataclass(frozen=True)
class InstallResult:
    """Install or dry-run result for one dependency record."""

    record: DependencyRecord
    command: list[str]
    status: str
    detail: str = ""


def collect_manifest(codex_dir: Path) -> DependencyManifest:
    """Collect external dependency references from known Codex config files."""
    root = codex_dir.expanduser()
    records: list[DependencyRecord] = []
    records.extend(_collect_toml_commands(root / "config.toml", root))
    records.extend(_collect_hook_commands(root / "hooks.json", root))
    records.extend(_collect_plugin_references(root))
    return DependencyManifest(_dedupe(records)).sorted()


def load_manifest(codex_dir: Path) -> DependencyManifest:
    """Load the tracked dependency manifest, returning an empty manifest if absent."""
    path = codex_dir / MANIFEST_FILENAME
    if not path.exists():
        return DependencyManifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DependencyManifest()
    if not isinstance(data, dict):
        return DependencyManifest()
    return DependencyManifest.from_dict(data)


def write_manifest(codex_dir: Path, manifest: DependencyManifest) -> None:
    """Write the tracked dependency manifest with stable formatting."""
    codex_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    (codex_dir / MANIFEST_FILENAME).write_text(payload, encoding="utf-8")


def refresh_manifest(codex_dir: Path) -> DependencyManifest:
    """Collect and write the current dependency manifest."""
    manifest = collect_manifest(codex_dir)
    write_manifest(codex_dir, manifest)
    return manifest


def diff_manifests(
    before: DependencyManifest, after: DependencyManifest
) -> DependencyChanges:
    """Compare two manifests by stable record identity."""
    before_by_id = {record.id: record for record in before.dependencies}
    after_by_id = {record.id: record for record in after.dependencies}
    added = [after_by_id[key] for key in sorted(after_by_id.keys() - before_by_id.keys())]
    removed = [
        before_by_id[key] for key in sorted(before_by_id.keys() - after_by_id.keys())
    ]
    changed = [
        after_by_id[key]
        for key in sorted(before_by_id.keys() & after_by_id.keys())
        if before_by_id[key].to_dict() != after_by_id[key].to_dict()
    ]
    return DependencyChanges(added=added, removed=removed, changed=changed)


def dependency_change_summary(changes: DependencyChanges) -> str:
    """Return a concise user-facing dependency change summary."""
    if not changes.has_changes:
        return ""
    return (
        "external dependencies changed: "
        f"{len(changes.added)} added, "
        f"{len(changes.removed)} removed, "
        f"{len(changes.changed)} changed; "
        "run codex-sync deps status"
    )


def write_dependency_state(codex_dir: Path, changes: DependencyChanges) -> None:
    """Record the latest dependency change summary in local sync state."""
    if not changes.has_changes:
        return
    state_path = codex_dir / STATE_FILENAME
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state["dependency_changes"] = {
        "added": len(changes.added),
        "removed": len(changes.removed),
        "changed": len(changes.changed),
        "added_ids": [record.id for record in changes.added],
        "removed_ids": [record.id for record in changes.removed],
        "changed_ids": [record.id for record in changes.changed],
    }
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check_dependencies(
    manifest: DependencyManifest, codex_dir: Path
) -> list[DependencyStatus]:
    """Check whether dependency executables and local paths are available."""
    return [_check_record(record, codex_dir) for record in manifest.dependencies]


def install_dependencies(
    manifest: DependencyManifest, codex_dir: Path, *, execute: bool = False
) -> list[InstallResult]:
    """Plan or run supported dependency installation commands."""
    results: list[InstallResult] = []
    for record in manifest.dependencies:
        for command in _record_install_commands(record):
            if not execute:
                results.append(InstallResult(record, command, "planned"))
                continue
            try:
                result = subprocess.run(
                    command,
                    cwd=codex_dir,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=_INSTALL_TIMEOUT_SECONDS,
                )
            except FileNotFoundError as exc:
                results.append(InstallResult(record, command, "error", str(exc)))
                continue
            except subprocess.TimeoutExpired:
                results.append(
                    InstallResult(
                        record,
                        command,
                        "error",
                        f"timed out after {_INSTALL_TIMEOUT_SECONDS}s",
                    )
                )
                continue
            detail = (result.stderr or result.stdout).strip()
            status = "installed" if result.returncode == 0 else "error"
            results.append(InstallResult(record, command, status, detail))
    return results


def _collect_toml_commands(path: Path, root: Path) -> list[DependencyRecord]:
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    records: list[DependencyRecord] = []
    for table_name in ("mcp_servers", "mcpServers"):
        servers = data.get(table_name, {})
        if not isinstance(servers, dict):
            continue
        for server_name, spec in servers.items():
            if isinstance(spec, dict):
                records.extend(
                    _records_from_command_spec(
                        kind="mcp_server",
                        name=str(server_name),
                        source_file=_relative_source(path, root),
                        identity=f"mcp_server:{_relative_source(path, root)}:{server_name}",
                        spec=spec,
                    )
                )
    for dotted_path, spec in _walk_command_specs(data):
        if dotted_path[:1] in (("mcp_servers",), ("mcpServers",)):
            continue
        name = ".".join(dotted_path)
        records.extend(
            _records_from_command_spec(
                kind="tool",
                name=name,
                source_file=_relative_source(path, root),
                identity=f"tool:{_relative_source(path, root)}:{name}",
                spec=spec,
            )
        )
    return records


def _collect_hook_commands(path: Path, root: Path) -> list[DependencyRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records: list[DependencyRecord] = []
    source_file = _relative_source(path, root)
    for event_name, event_config in _hook_events(data):
        for command_index, command in enumerate(_walk_command_strings(event_config)):
            for segment_index, tokens in enumerate(_split_shell_command(command)):
                for offset, inner_tokens in enumerate(_unwrap_shell(tokens)):
                    if not inner_tokens:
                        continue
                    executable = Path(inner_tokens[0]).name or inner_tokens[0]
                    identity = (
                        f"hook:{source_file}:{event_name}:"
                        f"{command_index}:{segment_index + offset}:{executable}"
                    )
                    records.append(
                        _record_from_tokens(
                            identity=identity,
                            kind="hook",
                            name=str(event_name),
                            source_file=source_file,
                            tokens=inner_tokens,
                        )
                    )
    return records


def _collect_plugin_references(root: Path) -> list[DependencyRecord]:
    records: list[DependencyRecord] = []
    for path in _plugin_metadata_paths(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_file = _relative_source(path, root)
        records.extend(_metadata_reference_records(data, source_file))
        for dotted_path, spec in _walk_command_specs(data):
            name = ".".join(dotted_path)
            records.extend(
                _records_from_command_spec(
                    kind="plugin_command",
                    name=name,
                    source_file=source_file,
                    identity=f"plugin_command:{source_file}:{name}",
                    spec=spec,
                )
            )
    return records


def _records_from_command_spec(
    *,
    kind: str,
    name: str,
    source_file: str,
    identity: str,
    spec: dict[str, Any],
) -> list[DependencyRecord]:
    command = spec.get("command") or spec.get("cmd")
    if not isinstance(command, str) or not command.strip():
        return []
    args = spec.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        args = []
    command_tokens = _split_command_words(command) + list(args)
    if not command_tokens:
        return []
    records: list[DependencyRecord] = []
    for segment_index, tokens in enumerate(_segments_from_tokens(command_tokens)):
        for offset, inner_tokens in enumerate(_unwrap_shell(tokens)):
            if not inner_tokens:
                continue
            segment_identity = identity
            if segment_index or offset:
                segment_identity = f"{identity}:{segment_index + offset}"
            records.append(
                _record_from_tokens(
                    identity=segment_identity,
                    kind=kind,
                    name=name,
                    source_file=source_file,
                    tokens=inner_tokens,
                )
            )
    return records


def _record_from_tokens(
    *,
    identity: str,
    kind: str,
    name: str,
    source_file: str,
    tokens: list[str],
) -> DependencyRecord:
    clean_tokens = _strip_env_prefix(tokens)
    executable = clean_tokens[0] if clean_tokens else tokens[0]
    args = clean_tokens[1:]
    package_manager, package, install_commands = _package_details(executable, args)
    local_package, local_install_commands = _local_setup_details(executable, args)
    if local_install_commands:
        package_manager = package_manager or "local"
        package = package or local_package
        install_commands.extend(local_install_commands)
    scope = "local" if _is_path_executable(executable) else "global"
    return DependencyRecord(
        id=identity,
        kind=kind,
        name=name,
        source_file=source_file,
        executable=executable,
        args=args,
        package_manager=package_manager,
        package=package,
        scope=scope,
        install_command=list(install_commands[0]) if install_commands else [],
        install_commands=install_commands,
    )


def _package_details(
    executable: str, args: list[str]
) -> tuple[str, str, list[list[str]]]:
    base = Path(executable).name
    if base == "uvx":
        package = _uvx_package(args)
        command = ["uv", "tool", "install", package] if package else []
        return "uvx", package, [command] if command else []
    if base == "npx":
        packages = _npx_packages(args)
        command = ["npm", "install", "-g", *packages] if packages else []
        return "npx", packages[0] if packages else "", [command] if command else []
    if base == "bunx":
        package = _first_non_option(args)
        command = ["bun", "add", "--global", package] if package else []
        return "bunx", package, [command] if command else []
    if base == "pipx":
        package = _pipx_package(args)
        command = ["pipx", "install", package] if package else []
        return "pipx", package, [command] if command else []
    return "", "", []


def _uvx_package(args: list[str]) -> str:
    for index, arg in enumerate(args):
        if arg == "--from" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("--from="):
            return arg.split("=", 1)[1]
    return _first_non_option(args)


def _npx_package(args: list[str]) -> str:
    packages = _npx_packages(args)
    return packages[0] if packages else ""


def _npx_packages(args: list[str]) -> list[str]:
    packages: list[str] = []
    for index, arg in enumerate(args):
        if arg in {"--package", "-p"} and index + 1 < len(args):
            packages.append(args[index + 1])
        elif arg.startswith("--package="):
            packages.append(arg.split("=", 1)[1])
    if packages:
        return _dedupe_strings(packages)
    package = _first_non_option(
        args, skip_options_with_values={"--cache", "--userconfig"}
    )
    return [package] if package else []


def _pipx_package(args: list[str]) -> str:
    if args[:1] == ["run"] and len(args) > 1:
        return args[1]
    if args[:1] == ["install"] and len(args) > 1:
        return args[1]
    return _first_non_option(args)


def _first_non_option(
    args: list[str], *, skip_options_with_values: set[str] | None = None
) -> str:
    skip_options = {
        "--from",
        "--with",
        "--python",
        "--cache",
        "--userconfig",
        "--index",
        "--default-index",
        "--extra-index-url",
        "-p",
    }
    if skip_options_with_values:
        skip_options.update(skip_options_with_values)
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-y", "--yes", "--no-install"}:
            continue
        if arg in skip_options:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        return arg
    return ""


def _record_install_commands(record: DependencyRecord) -> list[list[str]]:
    """Return install commands from current and legacy manifest fields."""
    commands = [list(command) for command in record.install_commands if command]
    if record.install_command and record.install_command not in commands:
        commands.insert(0, list(record.install_command))
    return commands


def _local_setup_details(
    executable: str, args: list[str]
) -> tuple[str, list[list[str]]]:
    """Return setup commands for local MCP servers with known bootstrap needs."""
    if not _is_crawl4ai_local_server(executable, args):
        return "", []
    python_path = Path(executable).expanduser()
    if python_path.parent.name != "bin":
        return "", []
    venv_dir = python_path.parent.parent
    playwright = python_path.parent / "playwright"
    return "crawl4ai", [
        ["uv", "venv", venv_dir.as_posix(), "--python", "3.13"],
        ["uv", "pip", "install", "--python", python_path.as_posix(), "crawl4ai"],
        [playwright.as_posix(), "install", "chromium"],
        [playwright.as_posix(), "install-deps", "chromium"],
    ]


def _is_crawl4ai_local_server(executable: str, args: list[str]) -> bool:
    """Return whether a command matches the bundled Crawl4AI MCP wrapper."""
    executable_name = Path(executable).name
    if not executable_name.startswith("python"):
        return False
    return any(Path(arg).name == "crawl4ai-mcp-server.py" for arg in args)


def _check_record(record: DependencyRecord, codex_dir: Path) -> DependencyStatus:
    if record.scope == "metadata":
        return DependencyStatus(record, True, record.scope, "tracked metadata reference")
    if record.scope == "local":
        target = _resolve_local_executable(codex_dir, record.executable)
        if target.exists() and os.access(target, os.X_OK):
            return DependencyStatus(record, True, record.scope, str(target))
        return DependencyStatus(record, False, record.scope, f"missing executable {target}")
    if record.executable and shutil.which(record.executable):
        detail = f"found {record.executable}"
        if record.package:
            detail = f"{detail}; package source {record.package}"
        return DependencyStatus(record, True, record.scope, detail)
    if record.executable:
        return DependencyStatus(
            record, False, record.scope, f"{record.executable} was not found on PATH"
        )
    return DependencyStatus(record, True, record.scope, "tracked reference")


def _split_shell_command(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    return _segments_from_tokens(tokens)


def _segments_from_tokens(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&&", "||", "|", "&"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _split_command_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _unwrap_shell(tokens: list[str]) -> list[list[str]]:
    clean_tokens = _strip_env_prefix(tokens)
    if not clean_tokens:
        return []
    executable = Path(clean_tokens[0]).name
    if executable not in _SHELL_EXECUTABLES:
        return [clean_tokens]
    for index, token in enumerate(clean_tokens[1:], start=1):
        short_option = token.startswith("-") and not token.startswith("--")
        if short_option and "c" in token.lstrip("-") and index + 1 < len(clean_tokens):
            return _split_shell_command(clean_tokens[index + 1])
    return [clean_tokens]


def _strip_env_prefix(tokens: list[str]) -> list[str]:
    clean = list(tokens)
    while clean and _is_env_assignment(clean[0]):
        clean.pop(0)
    if clean[:1] != ["env"]:
        return clean
    clean.pop(0)
    while clean:
        token = clean[0]
        if _is_env_assignment(token):
            clean.pop(0)
            continue
        if token in {"-i", "-0"}:
            clean.pop(0)
            continue
        if token in {"-u", "-C", "-S"} and len(clean) > 1:
            clean = clean[2:]
            continue
        if token.startswith("-"):
            clean.pop(0)
            continue
        break
    return clean


def _is_env_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    name = token.split("=", 1)[0]
    return name.replace("_", "").isalnum() and not name[0].isdigit()


def _is_path_executable(executable: str) -> bool:
    return (
        "/" in executable
        or "\\" in executable
        or executable.startswith(".")
        or executable.startswith("~")
    )


def _resolve_local_executable(codex_dir: Path, executable: str) -> Path:
    path = Path(executable).expanduser()
    return path if path.is_absolute() else codex_dir / path


def _hook_events(data: Any) -> list[tuple[str, Any]]:
    if isinstance(data, dict):
        return [(str(key), value) for key, value in data.items()]
    return [("hooks", data)]


def _walk_command_strings(value: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            item = value.get(key)
            if isinstance(item, str):
                commands.append(item)
        for item in value.values():
            commands.extend(_walk_command_strings(item))
    elif isinstance(value, list):
        for item in value:
            commands.extend(_walk_command_strings(item))
    return commands


def _walk_command_specs(
    value: Any, path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    specs: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if isinstance(value, dict):
        command = value.get("command") or value.get("cmd")
        if isinstance(command, str):
            specs.append((path, value))
        for key, item in value.items():
            specs.extend(_walk_command_specs(item, (*path, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            specs.extend(_walk_command_specs(item, (*path, str(index))))
    return specs


def _plugin_metadata_paths(root: Path) -> list[Path]:
    paths = [
        root / ".agents" / "plugins" / "marketplace.json",
        root / "plugins" / "marketplace.json",
    ]
    for pattern in (
        "plugins/**/plugin.json",
        "plugins/**/.codex-plugin/plugin.json",
        ".agents/plugins/**/plugin.json",
        ".agents/plugins/**/.codex-plugin/plugin.json",
    ):
        paths.extend(root.glob(pattern))
    unique: dict[str, Path] = {}
    for path in paths:
        if path.exists() and path.is_file():
            unique[str(path)] = path
    return [unique[key] for key in sorted(unique)]


def _metadata_reference_records(data: Any, source_file: str) -> list[DependencyRecord]:
    records: list[DependencyRecord] = []
    for path, key, value in _walk_external_references(data):
        identity = f"plugin_reference:{source_file}:{'.'.join(path)}:{key}"
        records.append(
            DependencyRecord(
                id=identity,
                kind="plugin_reference",
                name=".".join(path) or key,
                source_file=source_file,
                scope="metadata",
                reference=value,
            )
        )
    return records


def _walk_external_references(
    value: Any, path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], str, str]]:
    references: list[tuple[tuple[str, ...], str, str]] = []
    keys = {"source", "repo", "repository", "url", "package", "install"}
    if isinstance(value, dict):
        for key, item in value.items():
            lower_key = str(key).lower()
            if lower_key in keys and isinstance(item, str) and _looks_external(item):
                references.append((path, str(key), item))
            references.extend(_walk_external_references(item, (*path, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            references.extend(_walk_external_references(item, (*path, str(index))))
    return references


def _dedupe_strings(values: list[str]) -> list[str]:
    """Return strings in first-seen order without duplicates."""
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _looks_external(value: str) -> bool:
    return (
        value.startswith(("http://", "https://", "git+", "ssh://", "git@"))
        or value.count("/") == 1
        or value.startswith("@")
    )


def _dedupe(records: list[DependencyRecord]) -> list[DependencyRecord]:
    by_id: dict[str, DependencyRecord] = {}
    for record in records:
        by_id[record.id] = record
    return [by_id[key] for key in sorted(by_id)]


def _relative_source(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
