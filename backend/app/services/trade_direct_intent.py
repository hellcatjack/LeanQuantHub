from __future__ import annotations


def build_direct_intent_items(*, order_id: int, symbol: str, side: str, quantity: float) -> list[dict]:
    signed = float(quantity)
    if str(side).strip().upper() == "SELL":
        signed = -abs(signed)
    else:
        signed = abs(signed)
    return [
        {
            "order_intent_id": f"direct:{order_id}",
            "symbol": str(symbol).strip().upper(),
            "quantity": signed,
        }
    ]
