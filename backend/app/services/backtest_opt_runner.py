from __future__ import annotations

from typing import Any, Dict

CORE_KEYS = (
    "max_weight",
    "max_exposure",
    "vol_target",
    "max_drawdown",
    "top_n",
    "retain_top_n",
    "max_turnover_week",
    "market_ma_window",
)

INT_KEYS = {"top_n", "retain_top_n", "market_ma_window"}


def parse_pct(value: str | None) -> float:
    if not value:
        return 0.0
    text = str(value).strip().replace("%", "")
    if not text:
        return 0.0
    return float(text) / 100.0


def _coerce_float(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return fallback


def merge_algo_params(base: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(defaults)
    merged.update({k: v for k, v in base.items() if v not in (None, "")})
    return merged


def select_core_params(base: Dict[str, Any]) -> Dict[str, float | int]:
    core: Dict[str, float | int] = {}
    for key in CORE_KEYS:
        if key not in base:
            continue
        value = _coerce_float(base.get(key))
        if key in INT_KEYS:
            core[key] = int(round(value))
        else:
            core[key] = value
    return core
