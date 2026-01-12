from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


DEFAULT_ALPHA_INCREMENTAL_ENABLED = True
DEFAULT_ALPHA_COMPACT_DAYS = 120


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def alpha_fetch_config_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "config" / "alpha_fetch.json"


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


def _coerce_int(value: Any, default: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return num if num > 0 else default


def _defaults() -> dict[str, Any]:
    return {
        "alpha_incremental_enabled": DEFAULT_ALPHA_INCREMENTAL_ENABLED,
        "alpha_compact_days": DEFAULT_ALPHA_COMPACT_DAYS,
    }


def load_alpha_fetch_config(data_root: Path | None = None) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = alpha_fetch_config_path(root)
    config = _defaults()
    source = "default"
    updated_at = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config["alpha_incremental_enabled"] = _coerce_bool(
                    payload.get("alpha_incremental_enabled"),
                    config["alpha_incremental_enabled"],
                )
                config["alpha_compact_days"] = _coerce_int(
                    payload.get("alpha_compact_days"),
                    config["alpha_compact_days"],
                )
                updated_at = payload.get("updated_at")
                source = "file"
        except (OSError, json.JSONDecodeError):
            source = "default"

    config["alpha_compact_days"] = _coerce_int(
        config.get("alpha_compact_days"), DEFAULT_ALPHA_COMPACT_DAYS
    )
    config["alpha_incremental_enabled"] = _coerce_bool(
        config.get("alpha_incremental_enabled"), DEFAULT_ALPHA_INCREMENTAL_ENABLED
    )
    config["updated_at"] = updated_at
    config["source"] = source
    config["path"] = str(path)
    return config


def write_alpha_fetch_config(
    updates: dict[str, Any], data_root: Path | None = None
) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = alpha_fetch_config_path(root)
    current = load_alpha_fetch_config(root)
    payload = {
        "alpha_incremental_enabled": current["alpha_incremental_enabled"],
        "alpha_compact_days": current["alpha_compact_days"],
    }
    if "alpha_incremental_enabled" in updates and updates["alpha_incremental_enabled"] is not None:
        payload["alpha_incremental_enabled"] = _coerce_bool(
            updates["alpha_incremental_enabled"], payload["alpha_incremental_enabled"]
        )
    if "alpha_compact_days" in updates and updates["alpha_compact_days"] is not None:
        payload["alpha_compact_days"] = _coerce_int(
            updates["alpha_compact_days"], payload["alpha_compact_days"]
        )
    payload["updated_at"] = datetime.utcnow().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return load_alpha_fetch_config(root)
