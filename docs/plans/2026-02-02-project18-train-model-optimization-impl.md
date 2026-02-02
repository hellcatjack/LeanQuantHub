# Project18 Train Model Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 固定 run 462 参数，对项目18全部训练模型进行回测并选出 DD≤0.15 且 CAGR 最高的训练模型。

**Architecture:** 新增训练模型优化调度脚本与评分脚本，复用现有回测 API 与评分逻辑；记录 manifest 作为可追溯基准，并生成报告。

**Tech Stack:** Python 3.11, FastAPI backtest API, pytest, JSONL manifest.

---

### Task 1: 训练模型列表采集工具

**Files:**
- Create: `scripts/list_train_jobs.py`
- Test: `backend/tests/test_list_train_jobs.py`

**Step 1: Write the failing test**

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import list_train_jobs  # noqa: E402


def test_extract_train_job_ids_filters_success():
    items = [
        {"id": 1, "status": "success"},
        {"id": 2, "status": "failed"},
        {"id": 3, "status": "success"},
    ]
    assert list_train_jobs.extract_train_job_ids(items) == [1, 3]
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_list_train_jobs.py::test_extract_train_job_ids_filters_success -v`
Expected: FAIL (module or function missing)

**Step 3: Write minimal implementation**

```python
# scripts/list_train_jobs.py
from __future__ import annotations

import json
from typing import Iterable
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8021"
PROJECT_ID = 18


def _get_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_train_job_ids(items: Iterable[dict]) -> list[int]:
    return [int(row["id"]) for row in items if row.get("status") == "success"]


def main() -> None:
    page = 1
    ids: list[int] = []
    while True:
        data = _get_json(f"{API}/api/ml/train_jobs/page?project_id={PROJECT_ID}&page={page}&page_size=200")
        items = data.get("items") or []
        ids.extend(extract_train_job_ids(items))
        if len(items) < 200:
            break
        page += 1
    print("\n".join(str(i) for i in ids))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_list_train_jobs.py::test_extract_train_job_ids_filters_success -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/list_train_jobs.py backend/tests/test_list_train_jobs.py
git commit -m "feat: add train job lister"
```

---

### Task 2: 训练模型优化调度脚本（固定 run462 参数）

**Files:**
- Modify: `scripts/run_cagr_opt.py`
- Create: `scripts/run_train_model_opt.py`
- Test: `backend/tests/test_run_train_model_opt_payload.py`

**Step 1: Write the failing test**

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import run_train_model_opt  # noqa: E402


def test_build_payload_includes_train_job_and_params():
    base_params = {"max_exposure": 0.4, "vol_target": 0.045, "max_weight": 0.028}
    payload = run_train_model_opt.build_payload(83, base_params)
    params = payload["params"]
    assert params["pipeline_train_job_id"] == 83
    algo = params["algorithm_parameters"]
    assert algo["max_exposure"] == 0.4
    assert algo["vol_target"] == 0.045
    assert algo["max_weight"] == 0.028
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_run_train_model_opt_payload.py::test_build_payload_includes_train_job_and_params -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# scripts/run_train_model_opt.py
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8021"
PROJECT_ID = 18
START = "2020-01-01"
END = "2026-01-13"
MAX_INFLIGHT = 8

BASE_PARAMS: Dict[str, str] = {
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
    "initial_cash": "30000.0",
    "fee_bps": "10.0",
}

OUT = Path("/app/stocklean/artifacts/train_model_opt_manifest.jsonl")


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_payload(train_job_id: int, params: Dict[str, float]) -> dict:
    algorithm_parameters = {
        **BASE_PARAMS,
        **params,
        "backtest_start": START,
        "backtest_end": END,
    }
    return {
        "project_id": PROJECT_ID,
        "params": {
            "pipeline_train_job_id": train_job_id,
            "algorithm_parameters": algorithm_parameters,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-jobs", required=True, help="train_job_id 列表文件")
    args = parser.parse_args()

    base = {"max_exposure": 0.4, "vol_target": 0.045, "max_weight": 0.028}
    with open(args.train_jobs, "r", encoding="utf-8") as f:
        ids = [int(x.strip()) for x in f.read().splitlines() if x.strip()]

    inflight: list[int] = []
    for train_job_id in ids:
        while len(inflight) >= MAX_INFLIGHT:
            time.sleep(5)
        payload = build_payload(train_job_id, base)
        res = _request_json(f"{API}/api/backtests", payload)
        inflight.append(int(res["id"]))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps({"train_job_id": train_job_id, "run_id": res["id"], "params": base}, ensure_ascii=False)
                + "\n"
            )


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_run_train_model_opt_payload.py::test_build_payload_includes_train_job_and_params -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/run_train_model_opt.py backend/tests/test_run_train_model_opt_payload.py
git commit -m "feat: add train model optimization runner"
```

---

### Task 3: 训练模型评分脚本

**Files:**
- Create: `scripts/score_train_model_opt.py`
- Test: `backend/tests/test_score_train_model_opt.py`

**Step 1: Write the failing test**

```python
import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import score_train_model_opt  # noqa: E402


def test_score_filters_dd_and_sorts(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join([
        json.dumps({"train_job_id": 1, "run_id": 10, "params": {}}),
        json.dumps({"train_job_id": 2, "run_id": 20, "params": {}}),
    ]) + "\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    (artifacts / "run_10" / "lean_results").mkdir(parents=True)
    (artifacts / "run_20" / "lean_results").mkdir(parents=True)

    (artifacts / "run_10" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "10.0%", "Drawdown": "10.0%"}}',
        encoding="utf-8",
    )
    (artifacts / "run_20" / "lean_results" / "-summary.json").write_text(
        '{"statistics": {"Compounding Annual Return": "20.0%", "Drawdown": "20.0%"}}',
        encoding="utf-8",
    )

    results = score_train_model_opt.score_manifest(manifest, artifacts, 0.15)
    assert results[0]["train_job_id"] == 1
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_score_train_model_opt.py::test_score_filters_dd_and_sorts -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# scripts/score_train_model_opt.py
from __future__ import annotations

import json
from pathlib import Path
from app.services.backtest_opt_cagr import parse_summary, is_acceptable


def score_manifest(manifest: Path, artifacts_root: Path, max_dd: float):
    results = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        run_id = row["run_id"]
        summary = artifacts_root / f"run_{run_id}" / "lean_results" / "-summary.json"
        if not summary.exists():
            continue
        stats = parse_summary(summary)
        if not is_acceptable(stats, max_dd=max_dd):
            continue
        results.append({
            "train_job_id": row["train_job_id"],
            "run_id": run_id,
            "cagr": stats["cagr"],
            "dd": stats["dd"],
        })
    results.sort(key=lambda x: x["cagr"], reverse=True)
    return results


def main() -> None:
    manifest = Path("/app/stocklean/artifacts/train_model_opt_manifest.jsonl")
    artifacts = Path("/app/stocklean/artifacts")
    results = score_manifest(manifest, artifacts, 0.15)
    print(json.dumps(results[:3], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend /app/stocklean/.venv/bin/python -m pytest backend/tests/test_score_train_model_opt.py::test_score_filters_dd_and_sorts -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/score_train_model_opt.py backend/tests/test_score_train_model_opt.py
git commit -m "feat: add train model optimization scorer"
```

---

### Task 4: 执行与报告

**Files:**
- Create: `docs/reports/2026-02-02-project18-train-model-opt.md`

**Step 1: 执行流程**

Run:
- `PYTHONPATH=backend /app/stocklean/.venv/bin/python scripts/list_train_jobs.py > /app/stocklean/artifacts/train_job_ids.txt`
- `PYTHONPATH=backend /app/stocklean/.venv/bin/python scripts/run_train_model_opt.py --train-jobs /app/stocklean/artifacts/train_job_ids.txt`
- 等待全部 run 完成
- `PYTHONPATH=backend /app/stocklean/.venv/bin/python scripts/score_train_model_opt.py`

**Step 2: 写报告**

报告包含：
- 总训练模型数量
- 成功回测数量 / 失败数量
- Top3 训练模型（train_job_id / run_id / CAGR / DD）

**Step 3: Commit**

```bash
git add docs/reports/2026-02-02-project18-train-model-opt.md
git commit -m "docs: add project18 train model optimization report"
```

---

**交付物**
- 训练模型列表采集脚本
- 训练模型优化调度脚本
- 评分脚本
- 优化报告

**执行后验证**
- 确认 Top3 训练模型 DD≤0.15 且 CAGR 最大

