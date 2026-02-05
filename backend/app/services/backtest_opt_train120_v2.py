from __future__ import annotations

from typing import Dict, List

BASE_RISK = {
    "drawdown_tiers": "0.05,0.09,0.12",
    "drawdown_exposures": "0.45,0.30,0.20",
}


def build_grid() -> List[Dict[str, float | str]]:
    grid: List[Dict[str, float | str]] = []
    for max_exposure in (0.30, 0.32, 0.34, 0.36):
        for vol_target in (0.040, 0.0425, 0.045):
            for max_weight in (0.022, 0.026):
                grid.append(
                    {
                        "max_exposure": max_exposure,
                        "vol_target": vol_target,
                        "max_weight": max_weight,
                        **BASE_RISK,
                    }
                )
    return grid


def build_contrast() -> List[Dict[str, str]]:
    return [
        {
            "drawdown_tiers": "0.05,0.10,0.13",
            "drawdown_exposures": "0.50,0.35,0.25",
        }
        for _ in range(6)
    ]
