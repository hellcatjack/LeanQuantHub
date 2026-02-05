# 项目18 训练120可靠方向优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 以回测622的风控骨架为主线，统一风险资产为 VGSH，执行训练120的低暴露网格 + 对照风控组回测，并输出 DD≤0.15 下的最优参数或最接近阈值的结论。

**Architecture:** 新增“v2 参数生成器 + v2 回测提交脚本 + v2 评分脚本”，参数空间围绕 0.30–0.36 的暴露与 0.040–0.045 的波动目标，并引入更严格的 drawdown tiers/exposures 骨架。所有回测落在单独 manifest 文件中，便于回溯与评分。

**Tech Stack:** FastAPI API（/api/backtests, /api/ml/train-jobs）, Python 脚本（scripts/），SQLAlchemy 数据模型（仅读取），Lean 回测产物解析。

> 注意：项目禁止使用 git worktree，执行时在主工作区完成。

### Task 1: 新建 v2 参数生成器（低暴露网格 + 对照风控组）

**Files:**
- Create: `backend/app/services/backtest_opt_train120_v2.py`
- Create: `backend/tests/test_backtest_opt_train120_v2.py`

**Step 1: Write the failing test**

```python
from app.services.backtest_opt_train120_v2 import build_grid, build_contrast


def test_v2_grid_size_and_bounds():
    grid = build_grid()
    assert len(grid) == 24
    assert {g["max_exposure"] for g in grid} == {0.30, 0.32, 0.34, 0.36}
    assert {g["vol_target"] for g in grid} == {0.040, 0.0425, 0.045}
    assert {g["max_weight"] for g in grid} == {0.022, 0.026}


def test_v2_contrast_group():
    contrast = build_contrast()
    assert len(contrast) == 6
    for item in contrast:
        assert item["drawdown_tiers"] == "0.05,0.10,0.13"
        assert item["drawdown_exposures"] == "0.50,0.35,0.25"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_backtest_opt_train120_v2.py -q`
Expected: FAIL with import or missing function

**Step 3: Write minimal implementation**

```python
# backend/app/services/backtest_opt_train120_v2.py
from __future__ import annotations

from typing import Dict, List

BASE_RISK = {
    "drawdown_tiers": "0.05,0.09,0.12",
    "drawdown_exposures": "0.45,0.30,0.20",
}


def build_grid() -> List[Dict[str, float]]:
    grid: List[Dict[str, float]] = []
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
    # 对照风控组：略弱风控，用于验证收益上限
    return [
        {
            "drawdown_tiers": "0.05,0.10,0.13",
            "drawdown_exposures": "0.50,0.35,0.25",
        }
        for _ in range(6)
    ]
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_backtest_opt_train120_v2.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/backtest_opt_train120_v2.py backend/tests/test_backtest_opt_train120_v2.py
git commit -m "feat: add train120 v2 optimization parameter generator"
```

### Task 2: 新建 v2 回测提交脚本（基于回测622风控骨架）

**Files:**
- Create: `scripts/run_project18_train120_opt_v2.py`
- Create: `backend/tests/test_project18_train120_opt_v2_payload.py`

**Step 1: Write the failing test**

```python
from scripts.run_project18_train120_opt_v2 import build_payload


def test_v2_payload_risk_off_and_drawdown():
    baseline_algo = {"max_exposure": 0.3}
    overrides = {
        "max_exposure": 0.32,
        "vol_target": 0.0425,
        "max_weight": 0.026,
        "drawdown_tiers": "0.05,0.09,0.12",
        "drawdown_exposures": "0.45,0.30,0.20",
    }
    payload = build_payload(overrides, baseline_algo, "/tmp/scores.csv")
    algo = payload["params"]["algorithm_parameters"]
    assert algo["risk_off_symbols"] == "VGSH,IEF,GLD,TLT"
    assert algo["score_csv_path"] == "/tmp/scores.csv"
    assert algo["drawdown_tiers"] == "0.05,0.09,0.12"
    assert algo["drawdown_exposures"] == "0.45,0.30,0.20"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_project18_train120_opt_v2_payload.py -q`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
# scripts/run_project18_train120_opt_v2.py
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.backtest_opt_train120_v2 import build_grid, build_contrast

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
TRAIN_JOB_ID = 120
BASELINE_RUN_ID = 622
START = "2020-01-01"
END = "2026-01-13"
MAX_INFLIGHT = 8
OUT = Path("/app/stocklean/artifacts/train120_opt_v2_manifest.jsonl")
RISK_OFF = "VGSH,IEF,GLD,TLT"

# 复用已有的 _request_with_retry / _param_key / _load_existing_params / _load_inflight_runs 逻辑
# （可拷贝自 run_project18_train120_opt.py）


def fetch_baseline_params(run_id: int) -> dict:
    data = _request_with_retry("GET", f"{API}/api/backtests/{run_id}")
    params = data.get("params") or {}
    return params.get("algorithm_parameters") or {}


def fetch_train_job(job_id: int) -> dict:
    return _request_with_retry("GET", f"{API}/api/ml/train-jobs/{job_id}")


def build_payload(overrides: dict, baseline_algo: dict, scores_path: str) -> dict:
    algo = dict(baseline_algo)
    algo.update(overrides)
    algo.update(
        {
            "backtest_start": START,
            "backtest_end": END,
            "risk_off_symbols": RISK_OFF,
            "score_csv_path": scores_path,
        }
    )
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": TRAIN_JOB_ID,
            "algorithm_parameters": algo,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()

    baseline = fetch_baseline_params(BASELINE_RUN_ID)
    train = fetch_train_job(TRAIN_JOB_ID)
    scores_path = train.get("scores_path") or train.get("metrics", {}).get("scores_path")
    if not scores_path:
        raise SystemExit("scores_path missing for train job 120")

    batch = build_grid()
    if args.stage == 2:
        # 对照风控组：仅替换 drawdown 参数
        contrast = build_contrast()
        # 选取 grid 中前 6 条并替换 drawdown 参数作为对照
        for idx, item in enumerate(contrast):
            base = dict(batch[idx])
            base.update(item)
            batch.append(base)

    seen = _load_existing_params(OUT)
    inflight = _load_inflight_runs(OUT, is_done)
    for item in batch:
        if _param_key(item) in seen:
            continue
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
            inflight = [rid for rid in inflight if not is_done(rid)]
        payload = build_payload(item, baseline, scores_path)
        res = _request_with_retry("POST", f"{API}/api/backtests", payload)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": res["id"], "params": item}, ensure_ascii=False) + "\n")
        print(f"submitted {res['id']} -> {item}")


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_project18_train120_opt_v2_payload.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/run_project18_train120_opt_v2.py backend/tests/test_project18_train120_opt_v2_payload.py
git commit -m "feat: add train120 v2 optimization runner"
```

### Task 3: v2 评分脚本与报告模板

**Files:**
- Create: `scripts/score_project18_train120_opt_v2.py`
- Create: `backend/tests/test_project18_train120_opt_v2_score.py`
- Create: `docs/reports/2026-02-05-project18-train120-opt-v2.md`

**Step 1: Write the failing test**

```python
from scripts import score_project18_train120_opt_v2


def test_v2_manifest_path():
    assert str(score_project18_train120_opt_v2.MANIFEST) == "/app/stocklean/artifacts/train120_opt_v2_manifest.jsonl"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_project18_train120_opt_v2_score.py -q`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
# scripts/score_project18_train120_opt_v2.py
from __future__ import annotations

import json
from pathlib import Path

from app.services.backtest_opt_cagr import score_manifest

MANIFEST = Path("/app/stocklean/artifacts/train120_opt_v2_manifest.jsonl")
ARTIFACTS = Path("/app/stocklean/artifacts")


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit(f"manifest not found: {MANIFEST}")
    results = score_manifest(MANIFEST, artifacts_root=ARTIFACTS, max_dd=0.15, limit=3)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_project18_train120_opt_v2_score.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/score_project18_train120_opt_v2.py backend/tests/test_project18_train120_opt_v2_score.py
git commit -m "feat: add train120 v2 optimization scoring script"
```

**Step 6: Add report template**

```markdown
# 项目18 训练120可靠方向优化回测报告（v2）

## 执行概览
- 基准 run：622（风控骨架）
- 训练任务：120
- 风险资产：VGSH,IEF,GLD,TLT
- 回测窗口：2020-01-01 ~ 最新数据
- 回测次数：24（stage1）+ 6（stage2 可选）
- 约束：MaxDD ≤ 0.15

## Top3（按 DD 最低）
1. run_id=... / CAGR=... / DD=... / params=...
2. ...
3. ...

## Top3（按 CAGR 最高）
1. ...
2. ...
3. ...

## 结论
- 是否达标：是/否
- 推荐参数：...
```

Commit:
```bash
git add docs/reports/2026-02-05-project18-train120-opt-v2.md
git commit -m "docs: add train120 v2 optimization report template"
```
