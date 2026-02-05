from __future__ import annotations

from typing import Dict, List

MAX_EXPOSURE_VALS = [0.60, 0.70, 0.80]
VOL_TARGET_VALS = [0.045, 0.050, 0.055]
MAX_WEIGHT_VALS = [0.030, 0.040]


def build_grid() -> List[Dict[str, float]]:
    grid: List[Dict[str, float]] = []
    for max_exposure in MAX_EXPOSURE_VALS:
        for vol_target in VOL_TARGET_VALS:
            for max_weight in MAX_WEIGHT_VALS:
                grid.append(
                    {
                        "max_exposure": max_exposure,
                        "vol_target": vol_target,
                        "max_weight": max_weight,
                    }
                )
    return grid


def _safe_weight(weight: float) -> float:
    if weight in MAX_WEIGHT_VALS:
        return weight - 0.005 if weight > 0.030 else weight + 0.005
    return weight


def build_perturbations(base: Dict[str, float]) -> List[Dict[str, float]]:
    base_exposure = base["max_exposure"]
    base_vol = base["vol_target"]
    base_weight = _safe_weight(base["max_weight"])

    exposures = [
        round(base_exposure - 0.05, 3),
        round(base_exposure, 3),
        round(base_exposure + 0.05, 3),
        round(base_exposure - 0.02, 3),
    ]
    vols = [
        round(base_vol - 0.005, 3),
        round(base_vol, 3),
        round(base_vol + 0.005, 3),
    ]

    grid_keys = {
        (g["max_exposure"], g["vol_target"], g["max_weight"]) for g in build_grid()
    }
    items: List[Dict[str, float]] = []
    seen = set()
    for max_exposure in exposures:
        for vol_target in vols:
            key = (max_exposure, vol_target, base_weight)
            if key in grid_keys or key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "max_exposure": max_exposure,
                    "vol_target": vol_target,
                    "max_weight": base_weight,
                }
            )
    return items[:12]
