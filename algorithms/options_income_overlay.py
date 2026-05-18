from __future__ import annotations


def apply_income_sleeve(
    *,
    weights: dict[str, float],
    idle_symbol: str | None,
    income_symbol: str | None,
    sleeve_weight: float,
    mode: str,
) -> dict[str, float]:
    if mode not in {"idle_replacement", "defensive_replacement"}:
        return dict(weights)
    if not idle_symbol or not income_symbol or sleeve_weight <= 0:
        return dict(weights)

    current_idle = float(weights.get(idle_symbol, 0.0) or 0.0)
    if current_idle <= 0:
        return dict(weights)

    applied = min(current_idle, sleeve_weight)
    if applied <= 0:
        return dict(weights)

    updated = dict(weights)
    updated[idle_symbol] = max(0.0, current_idle - applied)
    updated[income_symbol] = updated.get(income_symbol, 0.0) + applied
    if updated[idle_symbol] <= 1e-9:
        updated.pop(idle_symbol, None)
    return updated
