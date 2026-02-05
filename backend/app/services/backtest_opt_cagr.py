from __future__ import annotations

import json
from pathlib import Path
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


def _pct(value: str | None) -> float:
    if not value:
        return 0.0
    s = str(value).strip().replace("%", "")
    return float(s) / 100.0


def parse_summary(path: Path) -> Dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("statistics", {})
    return {
        "cagr": _pct(stats.get("Compounding Annual Return")),
        "dd": _pct(stats.get("Drawdown")),
        "sharpe": float(stats.get("Sharpe Ratio") or 0.0),
        "sortino": float(stats.get("Sortino Ratio") or 0.0),
    }


def is_acceptable(stats: Dict[str, float], *, max_dd: float = 0.15) -> bool:
    return stats.get("dd", 1.0) <= max_dd


def score_manifest(
    manifest_path: Path,
    *,
    artifacts_root: Path,
    max_dd: float = 0.15,
    limit: int = 3,
) -> List[Dict[str, float]]:
    results: List[Dict[str, float]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        run_id = row.get("id") or row.get("run_id")
        params = row.get("params") or {}
        summary = artifacts_root / f"run_{run_id}" / "lean_results" / "-summary.json"
        if not summary.exists():
            continue
        stats = parse_summary(summary)
        if not is_acceptable(stats, max_dd=max_dd):
            continue
        results.append(
            {
                "run_id": int(run_id),
                "cagr": stats["cagr"],
                "dd": stats["dd"],
                "params": params,
            }
        )
    results.sort(key=lambda x: x["cagr"], reverse=True)
    return results[:limit]
