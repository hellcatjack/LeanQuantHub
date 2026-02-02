from __future__ import annotations

import random
from typing import Dict, List

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "max_weight": (0.01, 0.12),
    "max_exposure": (0.25, 0.80),
    "vol_target": (0.02, 0.12),
    "max_drawdown": (0.08, 0.20),
    "top_n": (3, 25),
    "retain_top_n": (3, 25),
    "max_turnover_week": (0.02, 0.20),
    "market_ma_window": (50, 260),
}

INT_KEYS = {"top_n", "retain_top_n", "market_ma_window"}


def _coerce_float(value: object, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return fallback


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def generate_candidates(
    base: Dict[str, float], total: int, seed: int = 0
) -> List[Dict[str, float]]:
    rng = random.Random(seed)
    candidates: List[Dict[str, float]] = []
    seen: set[tuple[tuple[str, object], ...]] = set()

    while len(candidates) < total:
        item = dict(base)
        for key, (lo, hi) in PARAM_RANGES.items():
            if key not in base:
                continue
            base_val = _coerce_float(base.get(key), lo)
            jitter = base_val * rng.uniform(-0.35, 0.35)
            value = _clamp(base_val + jitter, lo, hi)
            if key in INT_KEYS:
                value = int(round(value))
            item[key] = value

        if item.get("retain_top_n") and item.get("top_n"):
            if item["retain_top_n"] > item["top_n"]:
                item["retain_top_n"] = item["top_n"]

        signature = tuple((k, item.get(k)) for k in sorted(item.keys()))
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(item)
    return candidates
