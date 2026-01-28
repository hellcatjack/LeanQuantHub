from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.config import settings

DEFAULT_ORPHAN_GUARD = {
    "enabled": True,
    "dry_run": False,
    "evidence_required": True,
}


def _resolve_data_root() -> Path:
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    if settings.data_root:
        return Path(settings.data_root)
    return Path("/data/share/stock/data")


def data_sync_orphan_guard_config_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "config" / "data_sync_orphan_guard.json"


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def load_data_sync_orphan_guard_config(data_root: Path | None = None) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = data_sync_orphan_guard_config_path(root)
    config = dict(DEFAULT_ORPHAN_GUARD)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            config["enabled"] = _coerce_bool(payload.get("enabled"), config["enabled"])
            config["dry_run"] = _coerce_bool(payload.get("dry_run"), config["dry_run"])
            config["evidence_required"] = _coerce_bool(
                payload.get("evidence_required"), config["evidence_required"]
            )
    return config
