"""User-facing exception types for Codex sync."""


class CodexSyncError(Exception):
    """Base error for user-facing sync failures."""


class ConfigError(CodexSyncError):
    """Raised when .sync.toml or generated config cannot be used."""


class GitError(CodexSyncError):
    """Raised when git exits unsuccessfully."""


class LockContentionError(CodexSyncError):
    """Raised when another sync operation already holds the lock."""
