from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


DEFAULT_BULK_AUTO = {
    "status": "all",
    "batch_size": 200,
    "only_missing": True,
    "min_delay_seconds": 0.1,
    "refresh_listing_mode": "stale_only",
    "refresh_listing_ttl_days": 7,
}

_ALLOWED_REFRESH_MODES = {"always", "stale_only", "never"}


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def bulk_auto_config_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "config" / "bulk_auto.json"


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


def _coerce_int(value: Any, default: int, min_value: int | None = None) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    if min_value is None:
        return num
    return num if num >= min_value else default


def _coerce_float(value: Any, default: float, min_value: float | None = None) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if min_value is None:
        return num
    return num if num >= min_value else default


def _coerce_status(value: Any, default: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"all", "active", "delisted"}:
            return normalized
    return default


def _coerce_refresh_mode(value: Any, default: str) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _ALLOWED_REFRESH_MODES:
            return normalized
    return default


def _defaults() -> dict[str, Any]:
    return dict(DEFAULT_BULK_AUTO)


def load_bulk_auto_config(data_root: Path | None = None) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = bulk_auto_config_path(root)
    config = _defaults()
    source = "default"
    updated_at = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config["status"] = _coerce_status(payload.get("status"), config["status"])
                config["batch_size"] = _coerce_int(
                    payload.get("batch_size"), config["batch_size"], min_value=1
                )
                config["only_missing"] = _coerce_bool(
                    payload.get("only_missing"), config["only_missing"]
                )
                config["min_delay_seconds"] = _coerce_float(
                    payload.get("min_delay_seconds"), config["min_delay_seconds"], 0.0
                )
                config["refresh_listing_mode"] = _coerce_refresh_mode(
                    payload.get("refresh_listing_mode"), config["refresh_listing_mode"]
                )
                config["refresh_listing_ttl_days"] = _coerce_int(
                    payload.get("refresh_listing_ttl_days"),
                    config["refresh_listing_ttl_days"],
                    min_value=1,
                )
                updated_at = payload.get("updated_at")
                source = "file"
        except (OSError, json.JSONDecodeError):
            source = "default"

    config["batch_size"] = _coerce_int(config.get("batch_size"), DEFAULT_BULK_AUTO["batch_size"], 1)
    config["min_delay_seconds"] = _coerce_float(
        config.get("min_delay_seconds"), DEFAULT_BULK_AUTO["min_delay_seconds"], 0.0
    )
    config["refresh_listing_ttl_days"] = _coerce_int(
        config.get("refresh_listing_ttl_days"), DEFAULT_BULK_AUTO["refresh_listing_ttl_days"], 1
    )
    config["refresh_listing_mode"] = _coerce_refresh_mode(
        config.get("refresh_listing_mode"), DEFAULT_BULK_AUTO["refresh_listing_mode"]
    )
    config["status"] = _coerce_status(config.get("status"), DEFAULT_BULK_AUTO["status"])
    config["only_missing"] = _coerce_bool(
        config.get("only_missing"), DEFAULT_BULK_AUTO["only_missing"]
    )
    config["updated_at"] = updated_at
    config["source"] = source
    config["path"] = str(path)
    return config


def write_bulk_auto_config(
    updates: dict[str, Any], data_root: Path | None = None
) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = bulk_auto_config_path(root)
    current = load_bulk_auto_config(root)
    payload = {
        "status": current["status"],
        "batch_size": current["batch_size"],
        "only_missing": current["only_missing"],
        "min_delay_seconds": current["min_delay_seconds"],
        "refresh_listing_mode": current["refresh_listing_mode"],
        "refresh_listing_ttl_days": current["refresh_listing_ttl_days"],
    }
    if "status" in updates and updates["status"] is not None:
        payload["status"] = _coerce_status(updates["status"], payload["status"])
    if "batch_size" in updates and updates["batch_size"] is not None:
        payload["batch_size"] = _coerce_int(updates["batch_size"], payload["batch_size"], 1)
    if "only_missing" in updates and updates["only_missing"] is not None:
        payload["only_missing"] = _coerce_bool(updates["only_missing"], payload["only_missing"])
    if "min_delay_seconds" in updates and updates["min_delay_seconds"] is not None:
        payload["min_delay_seconds"] = _coerce_float(
            updates["min_delay_seconds"], payload["min_delay_seconds"], 0.0
        )
    if "refresh_listing_mode" in updates and updates["refresh_listing_mode"] is not None:
        payload["refresh_listing_mode"] = _coerce_refresh_mode(
            updates["refresh_listing_mode"], payload["refresh_listing_mode"]
        )
    if "refresh_listing_ttl_days" in updates and updates["refresh_listing_ttl_days"] is not None:
        payload["refresh_listing_ttl_days"] = _coerce_int(
            updates["refresh_listing_ttl_days"], payload["refresh_listing_ttl_days"], 1
        )
    payload["updated_at"] = datetime.utcnow().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return load_bulk_auto_config(root)
