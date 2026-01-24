from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.services.lean_bridge_reader import read_bridge_status


def _resolve_bridge_root() -> Path:
    base = settings.data_root or settings.artifact_root
    return Path(base) / "lean_bridge"


def build_ib_health(session) -> dict[str, object]:
    status = read_bridge_status(_resolve_bridge_root())
    connection_status = status.get("status") or "unknown"
    return {
        "connection_status": connection_status,
        "stream_status": connection_status,
        "stream_last_heartbeat": status.get("last_heartbeat"),
    }
