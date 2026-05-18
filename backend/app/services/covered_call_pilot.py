from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from app.core.config import settings
from app.services.covered_call_planner import pick_covered_call_candidate
from app.services.ib_account import get_account_positions_cached
from app.services.ib_gateway_runtime import get_gateway_trade_block_state, load_gateway_runtime_health
from app.services.ib_options_market import fetch_option_candidates
from app.services.lean_bridge_paths import resolve_bridge_root
from app.services.lean_bridge_reader import read_open_orders
from app.services.options_eligibility import evaluate_covered_call_eligibility

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")
_OCC_LOCAL_SYMBOL_RE = re.compile(r"^([A-Z]{1,6})\s*\d{6}[CP]\d{8}$")


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _normalize_positive_int(value: object) -> int:
    try:
        number = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _normalize_positive_float(value: object) -> float | None:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _extract_shares(item: dict[str, Any]) -> int:
    return _normalize_positive_int(item.get("quantity") or item.get("position"))


def _extract_underlying_price(item: dict[str, Any]) -> float | None:
    direct = _normalize_positive_float(item.get("market_price") or item.get("last_price") or item.get("last"))
    if direct is not None:
        return direct
    quantity = _extract_shares(item)
    market_value = _normalize_positive_float(item.get("market_value"))
    if quantity > 0 and market_value is not None:
        try:
            return float(market_value) / float(quantity)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def _is_option_position(item: dict[str, Any]) -> bool:
    for key in ("security_type", "sec_type", "asset_class", "contract_type"):
        value = str(item.get(key) or "").strip().upper()
        if value in {"OPT", "OPTION"}:
            return True
    local_symbol = str(item.get("local_symbol") or item.get("localSymbol") or "").strip().upper()
    if local_symbol and _OCC_LOCAL_SYMBOL_RE.match(local_symbol):
        return True
    return False


def _extract_option_underlying(item: dict[str, Any]) -> str | None:
    if not _is_option_position(item):
        return None
    for key in ("underlying_symbol", "underlying", "underlyingSymbol"):
        symbol = _normalize_symbol(item.get(key))
        if symbol:
            return symbol
    local_symbol = str(item.get("local_symbol") or item.get("localSymbol") or "").strip().upper()
    match = _OCC_LOCAL_SYMBOL_RE.match(local_symbol)
    if match:
        return match.group(1)
    return None


def _extract_open_order_symbols(payload: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    items = payload.get("items")
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("symbol", "underlying_symbol", "underlying"):
            symbol = _normalize_symbol(item.get(key))
            if symbol:
                result.add(symbol)
    return result


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_pilot_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _build_dry_run_order(symbol: str, recommendation: dict[str, Any]) -> dict[str, Any]:
    contracts = _normalize_positive_int(recommendation.get("contracts"))
    return {
        "underlying_symbol": symbol,
        "symbol": symbol,
        "side": "SELL",
        "sec_type": "OPT",
        "expiry": str(recommendation.get("expiry") or ""),
        "strike": float(recommendation.get("strike") or 0.0),
        "right": str(recommendation.get("right") or "C"),
        "contracts": contracts,
        "quantity": contracts,
        "order_type": "LMT",
        "limit_price": float(recommendation.get("mid") or 0.0),
        "dry_run": True,
    }


def _build_recommended_payload(
    *,
    symbol: str,
    shares: int,
    coverable_contracts: int,
    recommendation: dict[str, Any],
    underlying_price: float,
) -> dict[str, Any]:
    bid = float(recommendation.get("bid") or 0.0)
    ask = float(recommendation.get("ask") or 0.0)
    mid = float(recommendation.get("mid") or 0.0)
    if mid <= 0 and ask > 0 and ask >= bid >= 0:
        mid = round((bid + ask) / 2.0, 4)
    return {
        "symbol": symbol,
        "shares": shares,
        "coverable_contracts": coverable_contracts,
        "expiry": str(recommendation.get("expiry") or ""),
        "strike": float(recommendation.get("strike") or 0.0),
        "right": str(recommendation.get("right") or "C"),
        "contracts": coverable_contracts,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "underlying_price": float(underlying_price),
        "dte": int(recommendation.get("dte") or 0),
        "spread_ratio": float(recommendation.get("spread_ratio") or 0.0),
        "moneyness_pct": float(recommendation.get("moneyness_pct") or 0.0),
        "risk_tags": list(recommendation.get("risk_tags") or []),
    }


def run_covered_call_pilot(session, payload) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    dry_run = bool(getattr(payload, "dry_run", True))
    if mode != "paper":
        raise ValueError("paper_only")
    if not dry_run:
        raise ValueError("dry_run_only")

    bridge_root = resolve_bridge_root()
    runtime_payload = load_gateway_runtime_health(bridge_root)
    blocked_state = get_gateway_trade_block_state(bridge_root)
    runtime_state = str(runtime_payload.get("state") or "").strip().lower()
    if blocked_state:
        raise ValueError(str(blocked_state or "runtime_unhealthy"))
    if runtime_state != "healthy":
        raise ValueError("runtime_unhealthy")

    open_orders_payload = read_open_orders(bridge_root)
    if bool(open_orders_payload.get("stale")):
        raise ValueError("open_orders_stale")

    positions_payload = get_account_positions_cached(session, mode=mode, force_refresh=False)
    if bool(positions_payload.get("stale")):
        raise ValueError("positions_stale")

    requested_symbols = {
        _normalize_symbol(item)
        for item in (getattr(payload, "symbols", None) or [])
        if _normalize_symbol(item)
    }
    open_order_symbols = _extract_open_order_symbols(open_orders_payload)

    position_items = positions_payload.get("items")
    if not isinstance(position_items, list):
        position_items = []

    stock_positions: dict[str, dict[str, Any]] = {}
    option_underlyings: set[str] = set()
    for item in position_items:
        if not isinstance(item, dict):
            continue
        if _is_option_position(item):
            underlying = _extract_option_underlying(item)
            if underlying:
                option_underlyings.add(underlying)
            continue
        symbol = _normalize_symbol(item.get("symbol"))
        shares = _extract_shares(item)
        if not symbol or shares <= 0:
            continue
        stock_positions[symbol] = item

    eligible_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    candidate_rows: dict[str, list[dict[str, Any]]] = {}
    dry_run_orders: list[dict[str, Any]] = []

    selected_symbols = sorted(requested_symbols or set(stock_positions.keys()))
    for symbol in selected_symbols:
        item = stock_positions.get(symbol)
        if item is None:
            rejected_rows.append({"symbol": symbol, "reason": "not_held"})
            continue
        shares = _extract_shares(item)
        eligibility = evaluate_covered_call_eligibility(
            symbol=symbol,
            shares=shares,
            has_open_orders=symbol in open_order_symbols,
            has_option_position=symbol in option_underlyings,
            runtime_state=runtime_state,
            mode=mode,
        )
        if not bool(eligibility.get("eligible")):
            rejected_rows.append({"symbol": symbol, "reason": str(eligibility.get("reason") or "ineligible")})
            continue

        underlying_price = _extract_underlying_price(item)
        if underlying_price is None or underlying_price <= 0:
            rejected_rows.append({"symbol": symbol, "reason": "underlying_price_unavailable"})
            continue
        contracts = fetch_option_candidates(
            session,
            mode=mode,
            symbol=symbol,
            right="C",
            timeout_seconds=8.0,
            quote_limit=max(int(getattr(payload, "max_candidates_per_symbol", 5) or 5) * 8, 24),
            underlying_price=underlying_price,
        )
        candidate_rows[symbol] = contracts[: max(1, int(getattr(payload, "max_candidates_per_symbol", 5) or 5))]
        if not contracts:
            rejected_rows.append({"symbol": symbol, "reason": "option_chain_empty"})
            continue

        recommendation = pick_covered_call_candidate(
            contracts,
            dte_min=int(getattr(payload, "dte_min", 21) or 21),
            dte_max=int(getattr(payload, "dte_max", 45) or 45),
            max_spread_ratio=float(getattr(payload, "max_spread_ratio", 0.15) or 0.15),
        )
        if recommendation is None:
            rejected_rows.append({"symbol": symbol, "reason": "no_viable_contract"})
            continue

        coverable_contracts = int(eligibility.get("coverable_contracts") or 0)
        recommended_payload = _build_recommended_payload(
            symbol=symbol,
            shares=shares,
            coverable_contracts=coverable_contracts,
            recommendation=recommendation,
            underlying_price=underlying_price,
        )
        eligible_rows.append(
            {
                "symbol": symbol,
                "shares": shares,
                "coverable_contracts": coverable_contracts,
                "candidate_count": len(candidate_rows.get(symbol) or []),
                "recommended": recommended_payload,
            }
        )
        dry_run_orders.append(_build_dry_run_order(symbol, recommended_payload))

    artifact_dir = _build_artifact_dir()
    summary_path = _write_json(
        artifact_dir / "summary.json",
        {
            "mode": mode,
            "status": "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime_state": runtime_state,
            "requested_symbols": sorted(requested_symbols),
            "eligible_count": len(eligible_rows),
            "rejected_count": len(rejected_rows),
            "eligible_symbols": [item["symbol"] for item in eligible_rows],
            "rejected_symbols": [item["symbol"] for item in rejected_rows],
        },
    )
    candidates_path = _write_json(artifact_dir / "candidates.json", candidate_rows)
    orders_path = _write_json(artifact_dir / "dry_run_orders.json", dry_run_orders)

    return {
        "mode": mode,
        "status": "ok",
        "eligible": eligible_rows,
        "rejected": rejected_rows,
        "artifacts": {
            "summary": summary_path,
            "candidates": candidates_path,
            "orders": orders_path,
        },
    }
