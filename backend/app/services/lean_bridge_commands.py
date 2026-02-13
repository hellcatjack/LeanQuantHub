from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class LeanBridgeCommandRef:
    command_id: str
    command_path: str
    requested_at: str
    expires_at: str


def write_cancel_order_command(
    commands_dir: Path,
    *,
    order_id: int,
    tag: str,
    actor: str = "system",
    reason: str = "user_cancel",
    expires_seconds: int = 120,
    command_id: str | None = None,
) -> LeanBridgeCommandRef:
    """Enqueue a cancel request for a Lean bridge instance.

    Any Lean process running `LeanBridgeResultHandler` with
    `lean-bridge-commands-enabled=true` polls `lean-bridge-commands-dir` and executes
    cancels against its own brokerage open orders snapshot.
    """
    commands_dir = Path(commands_dir)
    now = _now_utc()
    expires_at = now + timedelta(seconds=max(5, int(expires_seconds)))
    # Monotonic-ish command id (helps correlate output-dir command_results across workers).
    if not command_id:
        millis = int(time.time() * 1000)
        command_id = f"cancel_order_{int(order_id)}_{millis}"
    payload: dict[str, Any] = {
        "command_id": command_id,
        "type": "cancel_order",
        "order_id": int(order_id),
        "tag": str(tag),
        "actor": str(actor or "system"),
        "reason": str(reason or "user_cancel"),
        "requested_at": _iso_z(now),
        "expires_at": _iso_z(expires_at),
        "version": 1,
    }
    path = commands_dir / f"{command_id}.json"
    _atomic_write_json(path, payload)
    return LeanBridgeCommandRef(
        command_id=command_id,
        command_path=str(path),
        requested_at=payload["requested_at"],
        expires_at=payload["expires_at"],
    )


def write_submit_order_command(
    commands_dir: Path,
    *,
    symbol: str,
    quantity: float,
    tag: str,
    order_type: str = "MKT",
    order_id: int | None = None,
    limit_price: float | None = None,
    outside_rth: bool = False,
    adaptive_priority: str | None = None,
    actor: str = "system",
    reason: str = "auto_trade_submit",
    expires_seconds: int = 120,
    command_id: str | None = None,
) -> LeanBridgeCommandRef:
    """Enqueue a submit-order request for a long-lived Lean bridge instance."""

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_tag = str(tag or "").strip()
    if not normalized_symbol:
        raise ValueError("symbol_required")
    if not normalized_tag:
        raise ValueError("tag_required")

    normalized_order_type = str(order_type or "MKT").strip().upper() or "MKT"
    now = _now_utc()
    expires_at = now + timedelta(seconds=max(5, int(expires_seconds)))
    if not command_id:
        millis = int(time.time() * 1000)
        if order_id is not None:
            command_id = f"submit_order_{int(order_id)}_{millis}"
        else:
            command_id = f"submit_order_{normalized_symbol}_{millis}"

    payload: dict[str, Any] = {
        "command_id": command_id,
        "type": "submit_order",
        "symbol": normalized_symbol,
        "quantity": float(quantity),
        "tag": normalized_tag,
        "order_type": normalized_order_type,
        "outside_rth": bool(outside_rth),
        "actor": str(actor or "system"),
        "reason": str(reason or "auto_trade_submit"),
        "requested_at": _iso_z(now),
        "expires_at": _iso_z(expires_at),
        "version": 1,
    }
    if order_id is not None:
        payload["order_id"] = int(order_id)
    if limit_price is not None:
        payload["limit_price"] = float(limit_price)
    if adaptive_priority:
        payload["adaptive_priority"] = str(adaptive_priority).strip()

    path = commands_dir / f"{command_id}.json"
    _atomic_write_json(path, payload)
    return LeanBridgeCommandRef(
        command_id=command_id,
        command_path=str(path),
        requested_at=payload["requested_at"],
        expires_at=payload["expires_at"],
    )
