from __future__ import annotations

from pathlib import Path

from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_bridge_status


def _resolve_bridge_root() -> Path:
    return resolve_bridge_root()


def build_ib_health(session) -> dict[str, object]:
    status = read_bridge_status(_resolve_bridge_root())
    connection_status = status.get("status") or "unknown"
    return {
        "connection_status": connection_status,
        "stream_status": connection_status,
        "stream_last_heartbeat": status.get("last_heartbeat"),
    }
