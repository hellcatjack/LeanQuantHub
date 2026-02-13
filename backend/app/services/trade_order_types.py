from __future__ import annotations

import re

ALLOWED_ORDER_TYPES: set[str] = {
    "MKT",
    "LMT",
    "ADAPTIVE_LMT",
    "PEG_MID",
}


def normalize_order_type(value: object) -> str:
    """Normalize order_type to internal codes.

    Notes:
    - Keep storage/API payloads stable across UI/backend/Lean.
    - We accept a few human-friendly aliases, but always emit a canonical code.
    """

    text = str(value or "").strip().upper()
    if not text:
        return "MKT"

    # Drop hint suffixes like "(IBKR)" or "(IB)".
    text = re.sub(r"\(.*?\)", "", text).strip()

    # Canonical separators.
    text = text.replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    text = text.strip("_")

    if text in {"MARKET", "MARKET_ORDER"}:
        return "MKT"
    if text in {"LIMIT", "LIMIT_ORDER"}:
        return "LMT"
    if text in {"ADAPTIVE", "ADAPTIVELMT", "ADAPTIVE_LMT", "ADAPTIVE_LIMIT"}:
        return "ADAPTIVE_LMT"
    if text in {"PEG_MID", "PEGMID", "PEG_MIDPOINT", "PEG_MIDPOINTS", "MIDPOINT"}:
        return "PEG_MID"

    return text


def validate_order_type(value: object) -> str:
    normalized = normalize_order_type(value)
    if normalized not in ALLOWED_ORDER_TYPES:
        raise ValueError("order_type_invalid")
    return normalized


def is_limit_like(order_type: object) -> bool:
    normalized = normalize_order_type(order_type)
    return normalized in {"LMT", "PEG_MID"}
