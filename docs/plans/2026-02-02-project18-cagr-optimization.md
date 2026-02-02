# Project18 CAGR Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在最大回撤不超过 0.15 的硬约束下，基于项目 18 的回测记录与模型 83，系统化提升 CAGR，并输出最佳参数组合。

**Architecture:** 新增一个小型参数优化模块用于生成候选参数网格、解析回测结果并评分；配套脚本批量触发回测并监控状态，最终筛选满足 DD≤0.15 且 CAGR 最大的组合。

**Tech Stack:** Python 3.11, FastAPI 回测 API, requests/json/pathlib, pytest。

---

### Task 1: 设计候选参数网格（DD<=0.15 约束）

**Files:**
- Create: `backend/app/services/backtest_opt_cagr.py`
- Test: `backend/tests/test_backtest_opt_cagr.py`

**Step 1: 写失败测试（候选网格大小与内容）**

```python
from app.services.backtest_opt_cagr import build_grid

def test_build_grid_has_expected_candidates():
    base = {"max_exposure": 0.45, "vol_target": 0.055, "max_drawdown": 0.15}
    grid = build_grid(base)
    assert isinstance(grid, list)
    assert len(grid) >= 12
    assert all("max_exposure" in item for item in grid)
    assert all("vol_target" in item for item in grid)
```

**Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_backtest_opt_cagr.py::test_build_grid_has_expected_candidates -v`
Expected: FAIL（模块不存在）

**Step 3: 写最小实现**

```python
# backend/app/services/backtest_opt_cagr.py
from __future__ import annotations

from typing import Dict, List

def build_grid(base: Dict[str, float]) -> List[Dict[str, float]]:
    # 控制变量：只动收益敏感参数，保持 DD 上限 0.15
    max_exposure_vals = [0.35, 0.40, 0.45]
    vol_target_vals = [0.045, 0.055, 0.065]
    max_weight_vals = [0.028, 0.033, 0.038]
    grid = []
    for me in max_exposure_vals:
        for vt in vol_target_vals:
            for mw in max_weight_vals:
                item = dict(base)
                item.update({"max_exposure": me, "vol_target": vt, "max_weight": mw})
                grid.append(item)
    return grid
```

**Step 4: 运行测试确认通过**

Run: `pytest backend/tests/test_backtest_opt_cagr.py::test_build_grid_has_expected_candidates -v`
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/services/backtest_opt_cagr.py backend/tests/test_backtest_opt_cagr.py
git commit -m "feat: add CAGR optimization grid builder"
```

---

### Task 2: 解析回测结果并筛选（DD<=0.15）

**Files:**
- Modify: `backend/app/services/backtest_opt_cagr.py`
- Test: `backend/tests/test_backtest_opt_cagr.py`

**Step 1: 写失败测试（解析 summary 并筛选）**

```python
from app.services.backtest_opt_cagr import parse_summary, is_acceptable
from pathlib import Path

def test_parse_summary_and_dd_guard(tmp_path):
    summary_path = tmp_path / "-summary.json"
    summary_path.write_text('{"statistics": {"Compounding Annual Return": "12.3%", "Drawdown": "14.9%"}}')
    stats = parse_summary(summary_path)
    assert stats["cagr"] == 0.123
    assert stats["dd"] == 0.149
    assert is_acceptable(stats, max_dd=0.15) is True
```

**Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_backtest_opt_cagr.py::test_parse_summary_and_dd_guard -v`
Expected: FAIL

**Step 3: 写最小实现**

```python
# backend/app/services/backtest_opt_cagr.py
import json
from pathlib import Path
from typing import Dict

def _pct(value: str | None) -> float:
    if not value:
        return 0.0
    s = str(value).strip().replace('%', '')
    return float(s) / 100.0

def parse_summary(path: Path) -> Dict[str, float]:
    data = json.loads(path.read_text())
    stats = data.get("statistics", {})
    return {
        "cagr": _pct(stats.get("Compounding Annual Return")),
        "dd": _pct(stats.get("Drawdown")),
        "sharpe": float(stats.get("Sharpe Ratio") or 0.0),
        "sortino": float(stats.get("Sortino Ratio") or 0.0),
    }

def is_acceptable(stats: Dict[str, float], *, max_dd: float = 0.15) -> bool:
    return stats.get("dd", 1.0) <= max_dd
```

**Step 4: 运行测试确认通过**

Run: `pytest backend/tests/test_backtest_opt_cagr.py::test_parse_summary_and_dd_guard -v`
Expected: PASS

**Step 5: 提交**

```bash
git add backend/app/services/backtest_opt_cagr.py backend/tests/test_backtest_opt_cagr.py
git commit -m "feat: add backtest summary parser and dd guard"
```

---

### Task 3: 批量触发回测与监控（并发≤8）

**Files:**
- Create: `scripts/run_cagr_opt.py`

**Step 1: 写脚本骨架**

```python
# scripts/run_cagr_opt.py
import json
import time
import requests
from pathlib import Path
from app.services.backtest_opt_cagr import build_grid

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
TRAIN_JOB_ID = 83
START = "2020-01-01"
END = "2026-01-13"  # 当前数据上限
MAX_INFLIGHT = 8

BASE_PARAMS = {
    "top_n": "30",
    "retain_top_n": "10",
    "weighting": "score",
    "min_score": "0",
    "market_filter": "True",
    "market_ma_window": "200",
    "rebalance_frequency": "Weekly",
    "rebalance_day": "Monday",
    "rebalance_time_minutes": "30",
    "dynamic_exposure": "True",
    "drawdown_tiers": "0.08,0.12,0.15",
    "drawdown_exposures": "0.80,0.60,0.40",
    "max_drawdown": "0.15",
    "max_drawdown_52w": "0.15",
    "risk_off_mode": "defensive",
    "risk_off_pick": "lowest_vol",
    "risk_off_symbols": "SHY,IEF,GLD,TLT",
    "score_csv_path": "/app/stocklean/artifacts/ml_job_83/scores.csv",
    "initial_cash": "30000.0",
    "fee_bps": "10.0",
}

OUT = Path("/app/stocklean/artifacts/cagr_opt_manifest.jsonl")


def submit(params):
    payload = {
        "project_id": PROJECT_ID,
        "parameters": {**BASE_PARAMS, **params, "backtest_start": START, "backtest_end": END},
        "pipeline_train_job_id": TRAIN_JOB_ID,
    }
    r = requests.post(f"{API}/api/backtests", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    grid = build_grid({"max_exposure": 0.45, "vol_target": 0.055, "max_weight": 0.033})
    inflight = []
    for item in grid:
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
            inflight = [rid for rid in inflight if requests.get(f"{API}/api/backtests/{rid}").json()["status"] not in {"completed","failed","canceled"}]
        res = submit(item)
        inflight.append(res["id"])
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.open("a").write(json.dumps({"id": res["id"], "params": item}) + "\n")

if __name__ == "__main__":
    main()
```

**Step 2: 手动验证脚本（不运行全量）**

Run: `python scripts/run_cagr_opt.py --help`（或临时只跑 1 条）
Expected: 能成功创建单条回测记录

**Step 3: 提交**

```bash
git add scripts/run_cagr_opt.py
git commit -m "feat: add cagr optimization runner"
```

---

### Task 4: 评分与选优（CAGR 最大化，DD≤0.15）

**Files:**
- Create: `scripts/score_cagr_opt.py`

**Step 1: 脚本实现**

```python
import json
from pathlib import Path
from app.services.backtest_opt_cagr import parse_summary, is_acceptable

MANIFEST = Path("/app/stocklean/artifacts/cagr_opt_manifest.jsonl")

def main():
    results = []
    for line in MANIFEST.read_text().splitlines():
        row = json.loads(line)
        run_id = row["id"]
        summary = Path(f"/app/stocklean/artifacts/run_{run_id}/lean_results/-summary.json")
        if not summary.exists():
            continue
        stats = parse_summary(summary)
        if not is_acceptable(stats, max_dd=0.15):
            continue
        results.append({"run_id": run_id, "cagr": stats["cagr"], "dd": stats["dd"], "params": row["params"]})
    results.sort(key=lambda x: x["cagr"], reverse=True)
    print(json.dumps(results[:3], indent=2))

if __name__ == "__main__":
    main()
```

**Step 2: 运行脚本输出 Top3**

Run: `python scripts/score_cagr_opt.py`
Expected: 输出 3 个最优参数组合（DD≤0.15）

**Step 3: 提交**

```bash
git add scripts/score_cagr_opt.py
git commit -m "feat: add cagr optimization scorer"
```

---

### Task 5: 报告与结论

**Files:**
- Create: `docs/reports/2026-02-02-project18-cagr-opt.md`

**Step 1: 写报告**

包含：
- 运行列表与过滤规则
- Top3 组合（含 CAGR、DD）
- 推荐最终组合（CAGR 最大且 DD≤0.15）
- 是否需要二次微调

**Step 2: 提交**

```bash
git add docs/reports/2026-02-02-project18-cagr-opt.md
git commit -m "docs: add project18 cagr optimization report"
```

---

**执行后验证**
- 跑完所有回测后，用脚本确认 DD≤0.15 的 Top3
- 选出最终策略并记录

---

**交付物**
- 参数生成与筛选模块
- 批量回测脚本
- 评分脚本
- 优化报告
