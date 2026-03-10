from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math

from app.core.config import settings
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import (
    parse_bridge_timestamp,
    read_account_summary,
    read_bridge_status,
    read_open_orders,
    read_positions,
)

RUNTIME_HEALTH_FILENAME = "gateway_runtime_health.json"
_SNAPSHOT_STALE_SECONDS = max(
    int(getattr(settings, "ib_gateway_runtime_snapshot_stale_seconds", 120) or 120),
    30,
)
_PENDING_COMMAND_STALE_SECONDS = max(
    int(getattr(settings, "ib_gateway_runtime_pending_command_stale_seconds", 120) or 120),
    30,
)
_PROBE_FAILURE_THRESHOLD = max(
    int(getattr(settings, "ib_gateway_runtime_probe_failure_threshold", 2) or 2),
    1,
)
_TRADE_BLOCK_STATES = {"bridge_degraded", "gateway_degraded", "gateway_restarting"}
_TIMESTAMP_KEYS = ("refreshed_at", "updated_at", "timestamp", "last_heartbeat")
_COMMAND_RESULT_TIMESTAMP_KEYS = ("processed_at", "completed_at", "updated_at", "refreshed_at")


def _resolve_runtime_root(bridge_root: Path | str | None = None) -> Path:
    if bridge_root is None:
        return resolve_bridge_root()
    return Path(bridge_root)


def _parse_iso(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    return parse_bridge_timestamp({"value": value}, ["value"])


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _timestamp_from_payload(payload: dict[str, object] | None) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    return parse_bridge_timestamp(payload, list(_TIMESTAMP_KEYS))


def _scan_pending_commands(bridge_root: Path, *, now: datetime) -> tuple[int, int | None]:
    commands_dir = bridge_root / "commands"
    if not commands_dir.exists():
        return 0, None

    pending_count = 0
    oldest_age_seconds: int | None = None
    for path in sorted(commands_dir.glob("*.json")):
        payload = _read_json(path)
        requested_at = parse_bridge_timestamp(payload, ["requested_at"]) if payload else None
        pending_count += 1
        if requested_at is None:
            continue
        age_seconds = max(0.0, (now - requested_at).total_seconds())
        age_value = int(math.floor(age_seconds))
        if oldest_age_seconds is None or age_value > oldest_age_seconds:
            oldest_age_seconds = age_value
    return pending_count, oldest_age_seconds


def _scan_last_command_result_at(bridge_root: Path) -> datetime | None:
    results_dir = bridge_root / "command_results"
    if not results_dir.exists():
        return None

    latest: datetime | None = None
    for path in sorted(results_dir.glob("*.json")):
        payload = _read_json(path)
        parsed = parse_bridge_timestamp(payload, list(_COMMAND_RESULT_TIMESTAMP_KEYS)) if payload else None
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _snapshot_is_stale(payload: dict[str, object] | None, *, now: datetime) -> bool:
    if not isinstance(payload, dict):
        return True
    if bool(payload.get("stale")):
        return True
    refreshed_at = _timestamp_from_payload(payload)
    if refreshed_at is None:
        return True
    return (now - refreshed_at).total_seconds() > _SNAPSHOT_STALE_SECONDS


def _default_runtime_health() -> dict[str, object]:
    return {
        "state": "unknown",
        "failure_count": 0,
        "pending_command_count": 0,
        "oldest_pending_command_age_seconds": None,
        "last_positions_at": None,
        "last_open_orders_at": None,
        "last_account_summary_at": None,
        "last_command_result_at": None,
        "last_probe_result": "unknown",
        "last_probe_latency_ms": None,
        "last_recovery_action": None,
        "last_recovery_at": None,
        "next_allowed_action_at": None,
    }


def load_gateway_runtime_health(bridge_root: Path | str | None = None) -> dict[str, object]:
    path = _resolve_runtime_root(bridge_root) / RUNTIME_HEALTH_FILENAME
    payload = _read_json(path)
    if payload is None:
        return _default_runtime_health()
    default_payload = _default_runtime_health()
    default_payload.update(payload)
    return default_payload


def write_gateway_runtime_health(
    bridge_root: Path | str | None,
    payload: dict[str, object],
) -> dict[str, object]:
    root = _resolve_runtime_root(bridge_root)
    root.mkdir(parents=True, exist_ok=True)
    stored_payload = _default_runtime_health()
    stored_payload.update(payload)
    (root / RUNTIME_HEALTH_FILENAME).write_text(
        json.dumps(stored_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return stored_payload


def build_gateway_runtime_health(
    *,
    bridge_root: Path | str | None = None,
    bridge_status: dict[str, object] | None = None,
    positions_payload: dict[str, object] | None = None,
    open_orders_payload: dict[str, object] | None = None,
    account_payload: dict[str, object] | None = None,
    direct_probe: dict[str, object] | None = None,
    previous_payload: dict[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    root = _resolve_runtime_root(bridge_root)
    current_time = _parse_iso(now) or datetime.now(timezone.utc)
    previous = dict(previous_payload or {})
    bridge = bridge_status if bridge_status is not None else read_bridge_status(root)
    positions = positions_payload if positions_payload is not None else read_positions(root)
    open_orders = open_orders_payload if open_orders_payload is not None else read_open_orders(root)
    account = account_payload if account_payload is not None else read_account_summary(root)
    pending_command_count, oldest_pending_command_age_seconds = _scan_pending_commands(root, now=current_time)
    last_command_result_at = _scan_last_command_result_at(root)

    probe_ok = None
    probe_latency_ms = previous.get("last_probe_latency_ms")
    probe_result = "unknown"
    if isinstance(direct_probe, dict):
        probe_ok = direct_probe.get("ok")
        probe_latency_ms = direct_probe.get("latency_ms", probe_latency_ms)
        if probe_ok is True:
            probe_result = "success"
        elif probe_ok is False:
            probe_result = "failure"
    elif isinstance(previous.get("last_probe_result"), str):
        probe_result = str(previous.get("last_probe_result"))

    previous_failures = int(previous.get("failure_count") or 0)
    if probe_ok is True:
        failure_count = 0
    elif probe_ok is False:
        failure_count = previous_failures + 1
    else:
        failure_count = previous_failures

    snapshot_stale = any(
        (
            _snapshot_is_stale(positions, now=current_time),
            _snapshot_is_stale(open_orders, now=current_time),
            _snapshot_is_stale(account, now=current_time),
        )
    )
    command_stuck = (
        pending_command_count > 0
        and oldest_pending_command_age_seconds is not None
        and oldest_pending_command_age_seconds >= _PENDING_COMMAND_STALE_SECONDS
    )
    bridge_degraded = bool(bridge.get("stale")) or (
        probe_ok is False and failure_count >= _PROBE_FAILURE_THRESHOLD
    )

    if bridge_degraded:
        state = "bridge_degraded"
    elif command_stuck:
        state = "command_stuck"
    elif snapshot_stale:
        state = "snapshot_stale"
    else:
        state = "healthy"

    return {
        "state": state,
        "failure_count": failure_count,
        "pending_command_count": pending_command_count,
        "oldest_pending_command_age_seconds": oldest_pending_command_age_seconds,
        "last_positions_at": _iso_z(_timestamp_from_payload(positions)),
        "last_open_orders_at": _iso_z(_timestamp_from_payload(open_orders)),
        "last_account_summary_at": _iso_z(_timestamp_from_payload(account)),
        "last_command_result_at": _iso_z(last_command_result_at),
        "last_probe_result": probe_result,
        "last_probe_latency_ms": probe_latency_ms,
        "last_recovery_action": previous.get("last_recovery_action"),
        "last_recovery_at": previous.get("last_recovery_at"),
        "next_allowed_action_at": previous.get("next_allowed_action_at"),
    }


def is_gateway_trade_blocked(payload: dict[str, object] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return str(payload.get("state") or "").strip().lower() in _TRADE_BLOCK_STATES


def get_gateway_trade_block_state(bridge_root: Path | str | None = None) -> str | None:
    payload = load_gateway_runtime_health(bridge_root)
    if not is_gateway_trade_blocked(payload):
        return None
    state = str(payload.get("state") or "").strip().lower()
    return state or "gateway_degraded"
