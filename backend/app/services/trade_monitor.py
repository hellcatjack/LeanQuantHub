from __future__ import annotations


def build_trade_overview(session, *, project_id: int, mode: str) -> dict[str, object]:
    return {"positions": [], "orders": [], "pnl": None}
