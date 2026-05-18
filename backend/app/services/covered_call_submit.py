from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from app.core.config import settings
from app.services.audit_log import record_audit
from app.services.ib_account import get_account_positions_cached
from app.services.ib_gateway_runtime import load_gateway_runtime_health
from app.services.lean_bridge_commands import write_submit_order_command
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders
from app.services.trade_option_models import CoveredCallSubmitRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
_SUBMIT_WAIT_TIMEOUT_SECONDS = 20.0
_SUBMIT_POLL_INTERVAL_SECONDS = 0.5
_REJECT_STATUSES = {
    "invalid",
    "expired",
    "unsupported_order_type",
    "option_contract_invalid",
    "place_failed",
    "not_connected",
    "parse_error",
    "symbol_invalid",
    "quantity_invalid",
    "limit_price_invalid",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _build_artifact_dir() -> Path:
    timestamp = _now_utc().strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_submit_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_review_bundle(review_id: str) -> tuple[Path, dict[str, Any]]:
    bundle_path = ARTIFACT_ROOT / review_id / "review_bundle.json"
    if not bundle_path.exists():
        raise ValueError("review_not_found")
    payload = _read_json(bundle_path)
    if not isinstance(payload, dict):
        raise ValueError("review_bundle_invalid")
    return bundle_path, payload


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_position_summary(payload: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_symbol(item.get("symbol")) != symbol:
            continue
        try:
            shares = int(float(item.get("quantity") or item.get("position") or 0))
        except (TypeError, ValueError):
            shares = 0
        try:
            market_price = float(item.get("market_price") or item.get("last_price") or item.get("last") or 0.0)
        except (TypeError, ValueError):
            market_price = 0.0
        return {
            "found": True,
            "shares": shares,
            "market_price": market_price,
            "stale": bool(payload.get("stale")),
        }
    return {
        "found": False,
        "shares": 0,
        "market_price": 0.0,
        "stale": bool(payload.get("stale")),
    }


def _extract_open_orders_summary(payload: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    symbol_conflict = False
    for item in items:
        if not isinstance(item, dict):
            continue
        item_symbol = _normalize_symbol(item.get("symbol"))
        underlying = _normalize_symbol(item.get("underlying_symbol") or item.get("underlying"))
        if item_symbol == symbol or underlying == symbol:
            symbol_conflict = True
            break
    return {
        "stale": bool(payload.get("stale")),
        "symbol_conflict": symbol_conflict,
        "open_count": len(items),
    }


def _build_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": str(payload.get("state") or "unknown"),
        "failure_count": int(payload.get("failure_count") or 0),
        "last_probe_result": str(payload.get("last_probe_result") or "unknown"),
        "last_probe_latency_ms": payload.get("last_probe_latency_ms"),
    }


def _wait_for_command_result(path: Path, *, timeout_seconds: float, poll_interval_seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        if path.exists():
            try:
                payload = _read_json(path)
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                return payload
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.0, float(poll_interval_seconds)))


def build_covered_call_submit(session, payload: CoveredCallSubmitRequest) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    if mode != "paper":
        raise ValueError("paper_only")
    if bool(getattr(payload, "dry_run", False)):
        raise ValueError("real_submit_required")

    symbol = _normalize_symbol(getattr(payload, "symbol", ""))
    review_id = str(getattr(payload, "review_id", "") or "").strip()
    approval_token = str(getattr(payload, "approval_token", "") or "").strip()
    if not symbol:
        raise ValueError("symbol_required")
    if not review_id:
        raise ValueError("review_id_required")
    if not approval_token:
        raise ValueError("approval_token_required")

    review_bundle_path, review_bundle = _load_review_bundle(review_id)
    expected_token = str(review_bundle.get("approval_token") or "").strip()
    if approval_token != expected_token:
        raise ValueError("token_invalid")
    expires_at = _parse_utc(review_bundle.get("approval_expires_at"))
    if expires_at is None or expires_at <= _now_utc():
        raise ValueError("token_expired")

    order_plan = dict(review_bundle.get("order_plan") or {})
    plan_symbol = _normalize_symbol(order_plan.get("underlying_symbol") or review_bundle.get("symbol") or review_bundle.get("eligible", {}).get("symbol"))
    if plan_symbol and plan_symbol != symbol:
        raise ValueError("symbol_mismatch")

    bridge_root = resolve_bridge_root()
    runtime_payload = load_gateway_runtime_health(bridge_root)
    positions_payload = get_account_positions_cached(session, mode=mode, force_refresh=False)
    open_orders_payload = read_open_orders(bridge_root)
    runtime_summary = _build_runtime_summary(runtime_payload if isinstance(runtime_payload, dict) else {})
    position_summary = _extract_position_summary(positions_payload if isinstance(positions_payload, dict) else {}, symbol=symbol)
    open_orders_summary = _extract_open_orders_summary(open_orders_payload if isinstance(open_orders_payload, dict) else {}, symbol=symbol)

    artifact_dir = _build_artifact_dir()
    command_result_path = artifact_dir / "command_result.json"

    gate_reason = None
    if runtime_summary["state"] != "healthy":
        gate_reason = "runtime_unhealthy"
    elif bool(position_summary.get("stale")):
        gate_reason = "positions_stale"
    elif bool(open_orders_summary.get("stale")):
        gate_reason = "open_orders_stale"
    elif bool(open_orders_summary.get("symbol_conflict")):
        gate_reason = "open_orders_conflict"
    else:
        contracts = int(order_plan.get("contracts") or 0)
        multiplier = int(order_plan.get("multiplier") or 100)
        required_shares = max(0, contracts * multiplier)
        shares = int(position_summary.get("shares") or 0)
        if shares < required_shares or required_shares <= 0:
            gate_reason = "shares_insufficient"

    if gate_reason:
        summary_payload = {
            "mode": mode,
            "status": "blocked",
            "gate_reason": gate_reason,
            "review_id": review_id,
            "order_plan": order_plan or None,
            "runtime_summary": runtime_summary,
            "position_summary": position_summary,
            "open_orders_summary": open_orders_summary,
            "review_bundle": str(review_bundle_path),
        }
        summary_path = _write_json(artifact_dir / "summary.json", summary_payload)
        return {
            "mode": mode,
            "status": "blocked",
            "gate_reason": gate_reason,
            "review_id": review_id,
            "command_id": None,
            "command_result_status": None,
            "order_plan": order_plan or None,
            "runtime_summary": runtime_summary,
            "position_summary": position_summary,
            "open_orders_summary": open_orders_summary,
            "artifacts": {
                "summary": summary_path,
                "submit_request": None,
                "command_result": None,
                "review_bundle": str(review_bundle_path),
            },
        }

    commands_dir = Path(bridge_root) / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    contracts = int(order_plan.get("contracts") or 0)
    submit_ref = write_submit_order_command(
        commands_dir,
        symbol=symbol,
        underlying_symbol=symbol,
        sec_type=str(order_plan.get("sec_type") or "OPT"),
        expiry=str(order_plan.get("expiry") or ""),
        strike=float(order_plan.get("strike") or 0.0),
        right=str(order_plan.get("right") or ""),
        multiplier=int(order_plan.get("multiplier") or 100),
        quantity=float(-abs(contracts)),
        tag=f"covered_call:{review_id}",
        order_type=str(order_plan.get("order_type") or "LMT"),
        limit_price=float(order_plan.get("limit_price") or 0.0),
        actor="covered_call_submit",
        reason=f"covered_call_review_{review_id}",
        expires_seconds=120,
    )

    request_payload = {
        "review_id": review_id,
        "command_id": submit_ref.command_id,
        "command_path": submit_ref.command_path,
        "requested_at": submit_ref.requested_at,
        "expires_at": submit_ref.expires_at,
        "order_plan": order_plan,
    }
    submit_request_path = _write_json(artifact_dir / "submit_request.json", request_payload)
    record_audit(
        session,
        action="covered_call_submit_requested",
        resource_type="options_submit",
        detail={
            "symbol": symbol,
            "review_id": review_id,
            "command_id": submit_ref.command_id,
        },
    )

    result = _wait_for_command_result(
        Path(bridge_root) / "command_results" / f"{submit_ref.command_id}.json",
        timeout_seconds=_SUBMIT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds=_SUBMIT_POLL_INTERVAL_SECONDS,
    )
    command_result_status = None
    status = "timeout_pending"
    if isinstance(result, dict):
        _write_json(command_result_path, result)
        command_result_status = str(result.get("status") or "").strip().lower() or None
        if command_result_status == "submitted":
            status = "submitted"
        elif command_result_status in _REJECT_STATUSES:
            status = "rejected"
        else:
            status = "timeout_pending"

    gate_reason = None
    if status == "rejected":
        gate_reason = str((result or {}).get("error") or command_result_status or "submit_rejected")

    summary_payload = {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "command_id": submit_ref.command_id,
        "command_result_status": command_result_status,
        "order_plan": order_plan,
        "runtime_summary": runtime_summary,
        "position_summary": position_summary,
        "open_orders_summary": open_orders_summary,
        "review_bundle": str(review_bundle_path),
    }
    summary_path = _write_json(artifact_dir / "summary.json", summary_payload)
    record_audit(
        session,
        action="covered_call_submit_result",
        resource_type="options_submit",
        detail={
            "symbol": symbol,
            "review_id": review_id,
            "command_id": submit_ref.command_id,
            "status": status,
            "command_result_status": command_result_status,
        },
    )
    return {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "command_id": submit_ref.command_id,
        "command_result_status": command_result_status,
        "order_plan": order_plan,
        "runtime_summary": runtime_summary,
        "position_summary": position_summary,
        "open_orders_summary": open_orders_summary,
        "artifacts": {
            "summary": summary_path,
            "submit_request": submit_request_path,
            "command_result": str(command_result_path) if command_result_status else None,
            "review_bundle": str(review_bundle_path),
        },
    }
