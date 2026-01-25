from __future__ import annotations

from pathlib import Path

from app.core.config import settings


DEFAULT_LEAN_BRIDGE_FALLBACK = Path("/data/share/stock/data")


def resolve_bridge_root() -> Path:
    if settings.data_root:
        base = Path(settings.data_root)
        direct = base / "lean_bridge"
        if direct.exists():
            return direct
        nested = base / "data" / "lean_bridge"
        if nested.exists():
            return nested
        return direct

    artifact_bridge = Path(settings.artifact_root) / "lean_bridge"
    if artifact_bridge.exists():
        return artifact_bridge

    fallback_root = DEFAULT_LEAN_BRIDGE_FALLBACK
    if fallback_root.exists():
        return fallback_root / "lean_bridge"

    return artifact_bridge
