from __future__ import annotations

from datetime import datetime, timezone


def _parse_expiry(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _spread_ratio(item: dict[str, object]) -> float | None:
    try:
        bid = float(item.get("bid") or 0.0)
        ask = float(item.get("ask") or 0.0)
    except (TypeError, ValueError):
        return None
    if bid < 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def _risk_tags(
    *,
    dte: int,
    dte_min: int,
    dte_max: int,
    spread_ratio: float,
    max_spread_ratio: float,
    moneyness_pct: float,
) -> list[str]:
    tags: list[str] = []
    if dte <= int(dte_min) + 3:
        tags.append("near_expiry_floor")
    if dte >= int(dte_max) - 3:
        tags.append("near_expiry_ceiling")
    if spread_ratio >= float(max_spread_ratio) * 0.66:
        tags.append("spread_near_limit")
    if moneyness_pct <= 0.01:
        tags.append("tight_otm_buffer")
    return tags


def pick_covered_call_candidate(
    candidates: list[dict[str, object]],
    *,
    dte_min: int,
    dte_max: int,
    max_spread_ratio: float,
) -> dict[str, object] | None:
    today = datetime.now(timezone.utc).date()
    target_dte = (int(dte_min) + int(dte_max)) / 2.0
    eligible: list[tuple[float, float, float, dict[str, object]]] = []

    for item in candidates:
        if not isinstance(item, dict):
            continue
        right = str(item.get("right") or "").strip().upper()
        if right != "C":
            continue
        expiry_dt = _parse_expiry(item.get("expiry"))
        if expiry_dt is None:
            continue
        dte = (expiry_dt.date() - today).days
        if dte < int(dte_min) or dte > int(dte_max):
            continue
        try:
            strike = float(item.get("strike") or 0.0)
            underlying_price = float(item.get("underlying_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if underlying_price <= 0:
            continue
        if strike <= underlying_price:
            continue
        spread_ratio = _spread_ratio(item)
        if spread_ratio is None or spread_ratio > float(max_spread_ratio):
            continue
        moneyness_pct = (strike - underlying_price) / underlying_price
        enriched = dict(item)
        enriched["dte"] = int(dte)
        enriched["spread_ratio"] = round(float(spread_ratio), 6)
        enriched["moneyness_pct"] = round(float(moneyness_pct), 6)
        enriched["risk_tags"] = _risk_tags(
            dte=int(dte),
            dte_min=int(dte_min),
            dte_max=int(dte_max),
            spread_ratio=float(spread_ratio),
            max_spread_ratio=float(max_spread_ratio),
            moneyness_pct=float(moneyness_pct),
        )
        eligible.append((abs(float(dte) - target_dte), spread_ratio, strike, enriched))

    if not eligible:
        return None
    eligible.sort(key=lambda row: (row[0], row[1], row[2]))
    return dict(eligible[0][3])
