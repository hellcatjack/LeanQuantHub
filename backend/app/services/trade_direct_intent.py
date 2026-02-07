from __future__ import annotations


def build_direct_intent_items(
    *,
    order_id: int,
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "MKT",
    limit_price: float | None = None,
    allow_outside_rth: bool = False,
    session: str | None = None,
) -> list[dict]:
    signed = float(quantity)
    if str(side).strip().upper() == "SELL":
        signed = -abs(signed)
    else:
        signed = abs(signed)
    normalized_type = str(order_type or "MKT").strip().upper() or "MKT"
    if normalized_type == "LIMIT":
        normalized_type = "LMT"
    payload = {
        "order_intent_id": f"direct:{order_id}",
        "symbol": str(symbol).strip().upper(),
        "quantity": signed,
        "order_type": normalized_type,
        "limit_price": limit_price,
    }
    if allow_outside_rth:
        payload["outside_rth"] = True
    if session:
        payload["session"] = str(session).strip().lower()
    return [
        payload
    ]
