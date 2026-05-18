from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
from typing import Any

from app.core.config import settings
from app.services.audit_log import record_audit
from app.services.covered_call_execution import prepare_covered_call_execution
from app.services.ib_account import get_account_positions_cached
from app.services.ib_gateway_runtime import load_gateway_runtime_health
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders
from app.services.trade_option_models import CoveredCallExecutionPrepareRequest, CoveredCallReviewRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
_APPROVAL_TOKEN_TTL_MINUTES = 15


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_review_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _extract_position_summary(payload: dict[str, Any], *, symbol: str) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        current_symbol = _normalize_symbol(item.get("symbol"))
        if current_symbol != symbol:
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


def build_covered_call_review(session, payload: CoveredCallReviewRequest) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    dry_run = bool(getattr(payload, "dry_run", True))
    if mode != "paper":
        raise ValueError("paper_only")
    if not dry_run:
        raise ValueError("dry_run_only")

    symbol = _normalize_symbol(getattr(payload, "symbol", ""))
    if not symbol:
        raise ValueError("symbol_required")

    prepare_result = prepare_covered_call_execution(
        session,
        CoveredCallExecutionPrepareRequest(
            mode=mode,
            symbol=symbol,
            max_candidates_per_symbol=int(getattr(payload, "max_candidates_per_symbol", 5) or 5),
            dte_min=int(getattr(payload, "dte_min", 21) or 21),
            dte_max=int(getattr(payload, "dte_max", 45) or 45),
            max_spread_ratio=float(getattr(payload, "max_spread_ratio", 0.15) or 0.15),
            dry_run=True,
        ),
    )

    bridge_root = resolve_bridge_root()
    runtime_payload = load_gateway_runtime_health(bridge_root)
    positions_payload = get_account_positions_cached(session, mode=mode, force_refresh=False)
    open_orders_payload = read_open_orders(bridge_root)

    runtime_summary = _build_runtime_summary(runtime_payload)
    position_summary = _extract_position_summary(positions_payload if isinstance(positions_payload, dict) else {}, symbol=symbol)
    open_orders_summary = _extract_open_orders_summary(open_orders_payload if isinstance(open_orders_payload, dict) else {}, symbol=symbol)

    status = str(prepare_result.get("status") or "blocked")
    gate_reason = prepare_result.get("gate_reason")
    approval_token = None
    approval_expires_at = None
    review_id = None

    if status != "blocked":
        artifact_dir = _build_artifact_dir()
        review_id = artifact_dir.name
        approval_token = secrets.token_urlsafe(24)
        approval_expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=_APPROVAL_TOKEN_TTL_MINUTES)
        ).isoformat().replace("+00:00", "Z")
    else:
        artifact_dir = _build_artifact_dir()

    bundle_payload = {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "approval_token": approval_token,
        "approval_expires_at": approval_expires_at,
        "eligible": prepare_result.get("eligible"),
        "order_plan": prepare_result.get("order_plan"),
        "runtime_summary": runtime_summary,
        "position_summary": position_summary,
        "open_orders_summary": open_orders_summary,
        "prepare_artifacts": dict(prepare_result.get("artifacts") or {}),
    }
    summary_path = _write_json(artifact_dir / "summary.json", bundle_payload)
    bundle_path = _write_json(artifact_dir / "review_bundle.json", bundle_payload)

    if status != "blocked":
        record_audit(
            session,
            action="covered_call_review_prepared",
            resource_type="options_review",
            detail={
                "symbol": symbol,
                "status": status,
                "review_id": review_id,
                "approval_expires_at": approval_expires_at,
            },
        )

    return {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "review_id": review_id,
        "approval_token": approval_token,
        "approval_expires_at": approval_expires_at,
        "eligible": prepare_result.get("eligible"),
        "order_plan": prepare_result.get("order_plan"),
        "runtime_summary": runtime_summary,
        "position_summary": position_summary,
        "open_orders_summary": open_orders_summary,
        "artifacts": {
            "summary": summary_path,
            "bundle": bundle_path,
            "prepare_summary": str((prepare_result.get("artifacts") or {}).get("summary") or "") or None,
        },
    }
