"""Filesystem lock handling for sync operations."""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from codex_cli_sync.errors import LockContentionError


@contextmanager
def acquire_lock(path: Path, *, stale_after_seconds: int = 600) -> Iterator[None]:
    """Acquire a filesystem lock and clear stale lock files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        if _is_stale(path, stale_after_seconds):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        else:
            raise LockContentionError(f"sync lock already held: {path}") from exc
    try:
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at": time.time(),
        }
        os.write(fd, json.dumps(payload).encode("utf-8"))
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _is_stale(path: Path, stale_after_seconds: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime > stale_after_seconds
    except OSError:
        return False
