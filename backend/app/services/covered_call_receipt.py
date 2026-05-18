from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ib_gateway_runtime import load_gateway_runtime_health
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders
from app.services.trade_option_models import CoveredCallReceiptRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
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


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_receipt_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _load_review_bundle(review_id: str) -> tuple[Path, dict[str, Any]]:
    bundle_path = ARTIFACT_ROOT / review_id / "review_bundle.json"
    if not bundle_path.exists():
        raise ValueError("review_not_found")
    payload = _read_json(bundle_path)
    if not isinstance(payload, dict):
        raise ValueError("review_bundle_invalid")
    return bundle_path, payload


def _build_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": str(payload.get("state") or "unknown"),
        "failure_count": int(payload.get("failure_count") or 0),
        "last_probe_result": str(payload.get("last_probe_result") or "unknown"),
        "last_probe_latency_ms": payload.get("last_probe_latency_ms"),
    }


def _match_open_orders(payload: dict[str, Any], *, command_result: dict[str, Any], review_id: str, review_bundle: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    stale = bool(payload.get("stale"))
    brokerage_ids = {str(item).strip() for item in (command_result.get("brokerage_ids") or []) if str(item).strip()}
    tag = str(command_result.get("tag") or f"covered_call:{review_id}").strip()
    underlying_symbol = _normalize_symbol(
        command_result.get("underlying_symbol")
        or command_result.get("symbol")
        or (review_bundle.get("order_plan") or {}).get("underlying_symbol")
    )

    matches: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_ids = {str(value).strip() for value in (item.get("brokerage_ids") or []) if str(value).strip()}
        item_tag = str(item.get("tag") or "").strip()
        item_underlying = _normalize_symbol(item.get("underlying_symbol") or item.get("underlying"))
        item_symbol = _normalize_symbol(item.get("symbol"))
        if brokerage_ids and item_ids.intersection(brokerage_ids):
            matches.append(item)
            continue
        if tag and item_tag and item_tag == tag:
            matches.append(item)
            continue
        if underlying_symbol and (item_underlying == underlying_symbol or item_symbol == underlying_symbol):
            matches.append(item)

    return {
        "stale": stale,
        "open_count": len(items),
        "matched_count": len(matches),
        "matched_brokerage_ids": sorted(brokerage_ids),
        "matched_tags": sorted({str(item.get("tag") or "").strip() for item in matches if str(item.get("tag") or "").strip()}),
    }


def build_covered_call_receipt(session, payload: CoveredCallReceiptRequest) -> dict[str, Any]:
    del session

    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    review_id = str(getattr(payload, "review_id", "") or "").strip()
    command_id = str(getattr(payload, "command_id", "") or "").strip()
    if mode != "paper":
        raise ValueError("paper_only")
    if not review_id:
        raise ValueError("review_id_required")
    if not command_id:
        raise ValueError("command_id_required")

    review_bundle_path, review_bundle = _load_review_bundle(review_id)
    bridge_root = resolve_bridge_root()
    runtime_payload = load_gateway_runtime_health(bridge_root)
    open_orders_payload = read_open_orders(bridge_root)
    command_result_path = Path(bridge_root) / "command_results" / f"{command_id}.json"

    command_result = _read_json(command_result_path) if command_result_path.exists() else {}
    command_result_status = str(command_result.get("status") or "").strip() or None
    runtime_summary = _build_runtime_summary(runtime_payload if isinstance(runtime_payload, dict) else {})
    open_orders_summary = _match_open_orders(
        open_orders_payload if isinstance(open_orders_payload, dict) else {},
        command_result=command_result,
        review_id=review_id,
        review_bundle=review_bundle,
    )

    if command_result_status in _REJECT_STATUSES:
        status = "rejected"
        receipt_state = "rejected"
        gate_reason = command_result_status
    elif command_result_status == "submitted":
        status = "submitted"
        if bool(open_orders_summary.get("stale")):
            receipt_state = "open_orders_stale"
        elif int(open_orders_summary.get("matched_count") or 0) > 0:
            receipt_state = "open_confirmed"
        else:
            receipt_state = "submitted_unconfirmed"
        gate_reason = None
    else:
        status = "pending"
        receipt_state = "pending_no_result"
        if runtime_summary.get("state") != "healthy":
            receipt_state = "pending_runtime_unhealthy"
        gate_reason = None

    artifact_dir = _build_artifact_dir()
    summary_payload = {
        "mode": mode,
        "status": status,
        "receipt_state": receipt_state,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "command_id": command_id,
        "command_result_status": command_result_status,
        "runtime_summary": runtime_summary,
        "open_orders_summary": open_orders_summary,
        "review_bundle": str(review_bundle_path),
        "command_result": str(command_result_path) if command_result_path.exists() else None,
    }
    summary_path = _write_json(artifact_dir / "summary.json", summary_payload)

    return {
        "mode": mode,
        "status": status,
        "receipt_state": receipt_state,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "command_id": command_id,
        "command_result_status": command_result_status,
        "runtime_summary": runtime_summary,
        "open_orders_summary": open_orders_summary,
        "artifacts": {
            "summary": summary_path,
            "command_result": str(command_result_path) if command_result_path.exists() else None,
            "review_bundle": str(review_bundle_path),
        },
    }
