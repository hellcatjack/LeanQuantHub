from __future__ import annotations

from typing import Dict, List


def build_grid(base: Dict[str, float]) -> List[Dict[str, float]]:
    # 控制变量：只动收益敏感参数，保持 DD 上限约束由外部筛选
    max_exposure_vals = [0.35, 0.40, 0.45]
    vol_target_vals = [0.045, 0.055, 0.065]
    max_weight_vals = [0.028, 0.033, 0.038]
    grid: List[Dict[str, float]] = []
    for max_exposure in max_exposure_vals:
        for vol_target in vol_target_vals:
            for max_weight in max_weight_vals:
                item = dict(base)
                item.update(
                    {
                        "max_exposure": max_exposure,
                        "vol_target": vol_target,
                        "max_weight": max_weight,
                    }
                )
                grid.append(item)
    return grid
