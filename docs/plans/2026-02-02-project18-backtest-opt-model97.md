# 项目18 回测优化（训练模型97）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 DD≤0.15 约束下对项目18回测做随机/自适应优化（80 次，中心 run=514，train_job_id=97）。

**Architecture:** 新增纯函数模块生成候选参数（可测试），新增执行脚本负责调用 API、并发调度与结果汇总；结果输出到 artifacts 目录。

**Tech Stack:** Python 3.11（/app/stocklean/.venv），FastAPI API（HTTP 调用），pytest。

---

### Task 1: 新增参数生成模块（TDD）

**Files:**
- Create: `backend/app/services/backtest_opt_random.py`
- Create: `backend/tests/test_backtest_opt_random.py`

**Step 1: Write the failing test**

```python
# backend/tests/test_backtest_opt_random.py
from app.services.backtest_opt_random import generate_candidates

def test_generate_candidates_respects_constraints():
    base = {
        "top_n": 30,
        "retain_top_n": 10,
        "max_weight": 0.033,
        "max_exposure": 0.45,
        "vol_target": 0.055,
        "max_drawdown": 0.15,
        "max_turnover_week": 0.08,
        "market_ma_window": 200,
    }
    candidates = generate_candidates(base, total=20, seed=7)
    assert len(candidates) == 20
    for item in candidates:
        assert item["retain_top_n"] <= item["top_n"]
        assert 0.01 <= item["max_weight"] <= 0.12
```

**Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_backtest_opt_random.py -q`
Expected: FAIL (module/function not found).

**Step 3: Write minimal implementation**

```python
# backend/app/services/backtest_opt_random.py
from __future__ import annotations
import random
from typing import Dict, List

PARAM_RANGES = {
    "max_weight": (0.01, 0.12),
    "max_exposure": (0.25, 0.80),
    "vol_target": (0.02, 0.12),
    "max_drawdown": (0.08, 0.20),
    "top_n": (3, 25),
    "retain_top_n": (3, 25),
    "max_turnover_week": (0.02, 0.20),
    "market_ma_window": (50, 260),
}

NUMERIC_KEYS = set(PARAM_RANGES.keys())


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def generate_candidates(base: Dict[str, float], total: int, seed: int = 0) -> List[Dict[str, float]]:
    rng = random.Random(seed)
    candidates: List[Dict[str, float]] = []
    seen = set()
    while len(candidates) < total:
        item = dict(base)
        for key, (lo, hi) in PARAM_RANGES.items():
            if key not in base:
                continue
            base_val = float(base[key])
            # 以 0.35 的比例扰动
            jitter = base_val * (rng.uniform(-0.35, 0.35))
            value = _clamp(base_val + jitter, lo, hi)
            if key in ("top_n", "retain_top_n", "market_ma_window"):
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
```

**Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_backtest_opt_random.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/backtest_opt_random.py backend/tests/test_backtest_opt_random.py
git commit -m "feat: add random backtest parameter generator"
```

---

### Task 2: 新增优化执行脚本

**Files:**
- Create: `scripts/run_backtest_opt_model97.py`

**Step 1: Write the failing test**

（脚本执行逻辑较重，不做 CLI 端到端单测；由 Task 1 覆盖核心参数生成与约束。）

**Step 2: Implement script**

```python
# scripts/run_backtest_opt_model97.py
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Dict, List
import requests

from app.services.backtest_opt_random import generate_candidates

BASE_URL = "http://192.168.1.31:8021"
PROJECT_ID = 18
BASE_RUN_ID = 514
TRAIN_JOB_ID = 97
TOTAL_RUNS = 80
MAX_CONCURRENCY = 8
BACKTEST_START = "2020-01-01"

ARTIFACT_ROOT = Path("/app/stocklean/artifacts/backtest_opt/project_18/train_97")
MANIFEST = ARTIFACT_ROOT / "manifest.jsonl"
SUMMARY_CSV = ARTIFACT_ROOT / "summary.csv"
TOP10_JSON = ARTIFACT_ROOT / "top10.json"


def _get(url: str, **kwargs):
    resp = requests.get(url, timeout=10, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _post(url: str, payload: Dict[str, Any]):
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def parse_pct(value: str | None) -> float:
    if not value:
        return 0.0
    return float(str(value).replace("%", "").strip()) / 100.0


def fetch_base_params() -> Dict[str, Any]:
    run = _get(f"{BASE_URL}/api/backtests/{BASE_RUN_ID}")
    params = run.get("params") or {}
    algo = params.get("algorithm_parameters") or {}
    config = _get(f"{BASE_URL}/api/projects/{PROJECT_ID}/config").get("config") or {}
    backtest_params = config.get("backtest_params") or {}
    # 补齐缺失
    for key, value in backtest_params.items():
        if key not in algo or algo.get(key) in (None, ""):
            algo[key] = value
    algo["backtest_start"] = BACKTEST_START
    algo["backtest_end"] = ""
    params["algorithm_parameters"] = algo
    params["pipeline_train_job_id"] = TRAIN_JOB_ID
    return params


def build_candidates(base_algo: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 仅抽取 8 个核心参数
    keys = [
        "max_weight",
        "max_exposure",
        "vol_target",
        "max_drawdown",
        "top_n",
        "retain_top_n",
        "max_turnover_week",
        "market_ma_window",
    ]
    base = {k: base_algo[k] for k in keys if k in base_algo}
    return generate_candidates(base, total=TOTAL_RUNS, seed=97)


def submit_backtest(params: Dict[str, Any]) -> int:
    payload = {"project_id": PROJECT_ID, "params": params}
    run = _post(f"{BASE_URL}/api/backtests", payload)
    return int(run["id"])


def fetch_run(run_id: int) -> Dict[str, Any]:
    return _get(f"{BASE_URL}/api/backtests/{run_id}")


def is_terminal(status: str | None) -> bool:
    return status in {"success", "failed"}


def main() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    base_params = fetch_base_params()
    base_algo = base_params.get("algorithm_parameters") or {}
    candidates = build_candidates(base_algo)

    active: Dict[int, Dict[str, Any]] = {}
    pending = list(candidates)
    results: List[Dict[str, Any]] = []

    with MANIFEST.open("w", encoding="utf-8") as handle:
        while pending or active:
            while pending and len(active) < MAX_CONCURRENCY:
                item = pending.pop(0)
                params = json.loads(json.dumps(base_params))
                params["algorithm_parameters"].update(item)
                run_id = submit_backtest(params)
                active[run_id] = {
                    "params": params["algorithm_parameters"],
                    "status": "queued",
                }
                handle.write(json.dumps({"id": run_id, "params": item, "status": "queued"}, ensure_ascii=False) + "\n")
                handle.flush()

            time.sleep(20)
            done_ids = []
            for run_id in list(active.keys()):
                run = fetch_run(run_id)
                status = run.get("status") or ""
                active[run_id]["status"] = status
                if is_terminal(status):
                    metrics = run.get("metrics") or {}
                    cagr = parse_pct(metrics.get("Compounding Annual Return"))
                    dd = parse_pct(metrics.get("Drawdown"))
                    results.append({
                        "run_id": run_id,
                        "status": status,
                        "cagr": cagr,
                        "dd": dd,
                        "metrics": metrics,
                        "params": active[run_id]["params"],
                    })
                    done_ids.append(run_id)
                    handle.write(json.dumps({"id": run_id, "status": status, "cagr": cagr, "dd": dd}, ensure_ascii=False) + "\n")
                    handle.flush()
            for run_id in done_ids:
                active.pop(run_id, None)

    # 输出 summary.csv
    with SUMMARY_CSV.open("w", encoding="utf-8") as handle:
        handle.write("run_id,status,cagr,dd\n")
        for row in results:
            handle.write(f"{row['run_id']},{row['status']},{row['cagr']:.6f},{row['dd']:.6f}\n")

    # TOP10
    candidates_ok = [r for r in results if r["status"] == "success" and r["dd"] <= 0.15]
    candidates_ok.sort(key=lambda x: x["cagr"], reverse=True)
    with TOP10_JSON.open("w", encoding="utf-8") as handle:
        json.dump(candidates_ok[:10], handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

**Step 3: Manual verification**

Run: `/app/stocklean/.venv/bin/python scripts/run_backtest_opt_model97.py`
Expected: manifest 持续更新，最后生成 summary.csv 与 top10.json。

**Step 4: Commit**

```bash
git add scripts/run_backtest_opt_model97.py
git commit -m "feat: add backtest optimization runner for project18"
```

---

### Task 3: 执行与结果汇报

**Files:**
- Output: `artifacts/backtest_opt/project_18/train_97/manifest.jsonl`
- Output: `artifacts/backtest_opt/project_18/train_97/summary.csv`
- Output: `artifacts/backtest_opt/project_18/train_97/top10.json`

**Step 1: Run optimization**

Run: `/app/stocklean/.venv/bin/python scripts/run_backtest_opt_model97.py`
Expected: 80 次回测完成，生成 top10.json。

**Step 2: Summarize results**

- 提取 top10.json 的最优 run_id / CAGR / DD
- 汇报最优参数建议

---

Plan complete and saved to `docs/plans/2026-02-02-project18-backtest-opt-model97.md`.

Two execution options:

1. Subagent-Driven (this session) — I dispatch fresh subagent per task, review between tasks
2. Parallel Session (separate) — Open new session with executing-plans

Which approach?
