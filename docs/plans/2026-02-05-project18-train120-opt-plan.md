# 项目18 训练120优化回测 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 基于回测615参数（仅替换防御资产为 VGSH 并绑定训练120）执行 30 次回测优化，筛选 MaxDD≤0.15 下 CAGR 最大的参数组合。

**Architecture:** 以 run 615 为基线参数源，通过脚本从 API 拉取基线与训练任务信息，生成 18 个窄带网格 + 12 个局部扰动参数组合并提交回测，产出 manifest 与评分报告。

**Tech Stack:** FastAPI API（/api/backtests, /api/ml/train-jobs）, Python 脚本（scripts/），SQLAlchemy 数据模型（仅读取），Lean 回测产物解析。

> 注意：项目规定禁止使用 git worktree，执行时在主工作区完成。

### Task 1: 新建训练120优化参数生成器

**Files:**
- Create: `backend/app/services/backtest_opt_train120.py`
- Create: `backend/tests/test_backtest_opt_train120.py`

**Step 1: Write the failing test**

```python
from app.services.backtest_opt_train120 import build_grid, build_perturbations

def test_grid_has_expected_size_and_values():
    grid = build_grid()
    assert len(grid) == 18
    assert {item["max_exposure"] for item in grid} == {0.60, 0.70, 0.80}
    assert {item["vol_target"] for item in grid} == {0.045, 0.050, 0.055}
    assert {item["max_weight"] for item in grid} == {0.030, 0.040}


def test_perturbations_are_unique_and_within_bounds():
    grid = build_grid()
    perturb = build_perturbations(base={"max_exposure": 0.70, "vol_target": 0.050, "max_weight": 0.035})
    assert len(perturb) == 12
    assert len({tuple(sorted(p.items())) for p in perturb}) == 12
    assert not set(tuple(sorted(p.items())) for p in perturb).intersection(
        set(tuple(sorted(g.items())) for g in grid)
    )
    for p in perturb:
        assert 0.65 <= p["max_exposure"] <= 0.75
        assert 0.045 <= p["vol_target"] <= 0.055
        assert 0.030 <= p["max_weight"] <= 0.040
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_backtest_opt_train120.py -q`
Expected: FAIL with import or missing function

**Step 3: Write minimal implementation**

```python
# backend/app/services/backtest_opt_train120.py
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


def build_perturbations(base: Dict[str, float]) -> List[Dict[str, float]]:
    # 固定 12 组扰动，避免与网格重复
    candidates = [
        {"max_exposure": base["max_exposure"] + 0.05, "vol_target": base["vol_target"], "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"] - 0.05, "vol_target": base["vol_target"], "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"] + 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"] - 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"], "max_weight": base["max_weight"] + 0.005},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"], "max_weight": base["max_weight"] - 0.005},
        {"max_exposure": base["max_exposure"] + 0.05, "vol_target": base["vol_target"] + 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"] + 0.05, "vol_target": base["vol_target"] - 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"] - 0.05, "vol_target": base["vol_target"] + 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"] - 0.05, "vol_target": base["vol_target"] - 0.005, "max_weight": base["max_weight"]},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"] + 0.005, "max_weight": base["max_weight"] + 0.005},
        {"max_exposure": base["max_exposure"], "vol_target": base["vol_target"] - 0.005, "max_weight": base["max_weight"] - 0.005},
    ]
    grid_keys = {
        (g["max_exposure"], g["vol_target"], g["max_weight"]) for g in build_grid()
    }
    uniq = []
    seen = set()
    for item in candidates:
        key = (item["max_exposure"], item["vol_target"], item["max_weight"])
        if key in grid_keys or key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_backtest_opt_train120.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/backtest_opt_train120.py backend/tests/test_backtest_opt_train120.py
git commit -m "feat: add train120 optimization parameter generator"
```

### Task 2: 新建训练120优化回测提交脚本

**Files:**
- Create: `scripts/run_project18_train120_opt.py`

**Step 1: Write a failing test (payload transform)**

```python
from app.services.backtest_opt_train120 import build_grid

def test_grid_first_item_matches_expected():
    grid = build_grid()
    assert grid[0] == {"max_exposure": 0.60, "vol_target": 0.045, "max_weight": 0.030}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_backtest_opt_train120.py -q`
Expected: FAIL (until Task1 complete)

**Step 3: Implement submission script (minimal viable)**

```python
# scripts/run_project18_train120_opt.py
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.backtest_opt_train120 import build_grid, build_perturbations

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
TRAIN_JOB_ID = 120
BASELINE_RUN_ID = 615
START = "2020-01-01"
END = "2026-01-13"
MAX_INFLIGHT = 8
OUT = Path("/app/stocklean/artifacts/train120_opt_manifest.jsonl")
RISK_OFF = "VGSH,IEF,GLD,TLT"


def _request_json(method: str, url: str, payload: dict | None = None, *, timeout: float = 30) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_baseline_params(run_id: int) -> dict:
    data = _request_json("GET", f"{API}/api/backtests/{run_id}")
    params = data.get("params") or {}
    algo = params.get("algorithm_parameters") or {}
    return algo


def fetch_train_job(job_id: int) -> dict:
    return _request_json("GET", f"{API}/api/ml/train-jobs/{job_id}")


def build_payload(overrides: dict, baseline_algo: dict, scores_path: str) -> dict:
    algo = dict(baseline_algo)
    algo.update(overrides)
    algo.update({"backtest_start": START, "backtest_end": END, "risk_off_symbols": RISK_OFF, "score_csv_path": scores_path})
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": TRAIN_JOB_ID,
            "algorithm_parameters": algo,
        },
    }


def is_done(run_id: int) -> bool:
    try:
        status = _request_json("GET", f"{API}/api/backtests/{run_id}", timeout=10)
    except Exception:
        return False
    return status.get("status") in {"completed", "failed", "canceled", "success"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    baseline = fetch_baseline_params(BASELINE_RUN_ID)
    train = fetch_train_job(TRAIN_JOB_ID)
    scores_path = train.get("scores_path") or train.get("metrics", {}).get("scores_path")
    if not scores_path:
        raise SystemExit("scores_path missing for train job 120")

    grid = build_grid()
    perturb = build_perturbations({"max_exposure": 0.70, "vol_target": 0.050, "max_weight": 0.035})
    batch = grid + perturb
    if args.limit:
        batch = batch[: args.limit]

    inflight: list[int] = []
    for item in batch:
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
            inflight = [rid for rid in inflight if not is_done(rid)]
        payload = build_payload(item, baseline, scores_path)
        res = _request_json("POST", f"{API}/api/backtests", payload)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": res["id"], "params": item}, ensure_ascii=False) + "\n")
        print(f"submitted {res['id']} -> {item}")


if __name__ == "__main__":
    main()
```

**Step 4: Run smoke submission (limit 2-3)**

Run: `python scripts/run_project18_train120_opt.py --limit 3`
Expected: 输出 2-3 个 run_id，状态为 queued/running

**Step 5: Commit**

```bash
git add scripts/run_project18_train120_opt.py
git commit -m "feat: add train120 optimization backtest runner"
```

### Task 3: 评分脚本与报告

**Files:**
- Create: `scripts/score_project18_train120_opt.py`
- (Optional) Create: `docs/reports/2026-02-05-project18-train120-opt.md`

**Step 1: Write minimal scoring script**

```python
from __future__ import annotations

import json
from pathlib import Path

from app.services.backtest_opt_cagr import score_manifest

MANIFEST = Path("/app/stocklean/artifacts/train120_opt_manifest.jsonl")
ARTIFACTS = Path("/app/stocklean/artifacts")


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit(f"manifest not found: {MANIFEST}")
    results = score_manifest(MANIFEST, artifacts_root=ARTIFACTS, max_dd=0.15, limit=3)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

**Step 2: Run scoring after backtests complete**

Run: `python scripts/score_project18_train120_opt.py`
Expected: 输出 Top3（含 run_id, cagr, dd, params）

**Step 3: Commit**

```bash
git add scripts/score_project18_train120_opt.py
git commit -m "feat: add train120 optimization scoring script"
```

### Task 4: 更新优化计划文档

**Files:**
- Create: `docs/reports/2026-02-05-project18-train120-opt.md`

**Step 1: Write report template**

```markdown
# 项目18 训练120优化回测报告

## 执行概览
- 基准 run：615（风险资产已替换为 VGSH）
- 训练任务：120
- 回测窗口：2020-01-01 ~ 最新数据
- 回测次数：30
- 约束：MaxDD ≤ 0.15

## Top3（按 CAGR 排序）
1. run_id=... / CAGR=... / DD=... / params=...
2. ...
3. ...

## 结论
- 是否达标：是/否
- 推荐参数：...
```

**Step 2: Commit**

```bash
git add docs/reports/2026-02-05-project18-train120-opt.md
git commit -m "docs: add train120 optimization report template"
```
