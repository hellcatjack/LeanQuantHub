from __future__ import annotations


def evaluate_covered_call_eligibility(
    *,
    symbol: str,
    shares: int | float,
    has_open_orders: bool,
    has_option_position: bool,
    runtime_state: str,
    mode: str,
) -> dict[str, object]:
    symbol_text = str(symbol or "").strip().upper()
    try:
        share_count = int(float(shares or 0))
    except (TypeError, ValueError):
        share_count = 0
    mode_text = str(mode or "").strip().lower()
    runtime_text = str(runtime_state or "").strip().lower()

    if mode_text != "paper":
        return {
            "symbol": symbol_text,
            "eligible": False,
            "reason": "paper_only",
            "coverable_contracts": 0,
        }
    if runtime_text != "healthy":
        return {
            "symbol": symbol_text,
            "eligible": False,
            "reason": "runtime_unhealthy",
            "coverable_contracts": 0,
        }
    if has_open_orders:
        return {
            "symbol": symbol_text,
            "eligible": False,
            "reason": "open_orders_present",
            "coverable_contracts": 0,
        }
    if has_option_position:
        return {
            "symbol": symbol_text,
            "eligible": False,
            "reason": "option_position_present",
            "coverable_contracts": 0,
        }
    if share_count < 100:
        return {
            "symbol": symbol_text,
            "eligible": False,
            "reason": "shares_below_100",
            "coverable_contracts": 0,
        }
    return {
        "symbol": symbol_text,
        "eligible": True,
        "reason": None,
        "coverable_contracts": share_count // 100,
    }
