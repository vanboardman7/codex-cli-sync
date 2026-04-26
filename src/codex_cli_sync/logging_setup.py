"""Best-effort JSON event logging for sync actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_event(codex_dir: Path, event: str, **fields: Any) -> None:
    """Append a best-effort JSON event to the sync log."""
    payload = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    try:
        with (codex_dir / ".sync.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass
