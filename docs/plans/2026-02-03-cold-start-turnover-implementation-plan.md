# 冷启动换手限制 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 `cold_start_turnover` 参数，在冷启动时使用独立换手上限，并在决策/回测输出中可审计。

**Architecture:** 前端新增参数输入与默认值；后端把参数映射到 weights 配置；`scripts/universe_pipeline.py` 在调仓前判定冷启动并选择生效换手上限，同时将 cold_start 与 effective_turnover_limit 记录到 summary 与 snapshot_summary。

**Tech Stack:** FastAPI + SQLAlchemy + Python（决策/脚本），React + Vite（前端），Pytest/Vitest。

> 说明：项目规则禁止使用 git worktree，本计划直接在主工作区执行。

### Task 1: 后端参数映射（decision_snapshot）

**Files:**
- Modify: `backend/app/services/decision_snapshot.py`
- Create: `backend/tests/test_decision_snapshot_algo_params.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.decision_snapshot import _apply_algorithm_params


def test_apply_algorithm_params_cold_start_turnover():
    weights_cfg = {}
    algo_params = {"max_turnover_week": 0.1, "cold_start_turnover": 0.3}
    result = _apply_algorithm_params(weights_cfg, algo_params)
    assert result["turnover_limit"] == 0.1
    assert result["cold_start_turnover"] == 0.3
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_decision_snapshot_algo_params.py::test_apply_algorithm_params_cold_start_turnover -v`
Expected: FAIL with `KeyError` or missing key for `cold_start_turnover`.

**Step 3: Write minimal implementation**

Add mapping in `_apply_algorithm_params`:

```python
cold_start_turnover = algo_params.get("cold_start_turnover")
if cold_start_turnover not in (None, ""):
    weights_cfg["cold_start_turnover"] = cold_start_turnover
```

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_decision_snapshot_algo_params.py::test_apply_algorithm_params_cold_start_turnover -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/decision_snapshot.py backend/tests/test_decision_snapshot_algo_params.py
git commit -m "Add cold start turnover param mapping"
```

### Task 2: 冷启动判定与生效换手上限（universe_pipeline）

**Files:**
- Modify: `scripts/universe_pipeline.py`
- Create: `backend/tests/test_universe_pipeline_turnover.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import universe_pipeline as up


def test_resolve_turnover_limit_cold_start():
    effective, cold_start = up.resolve_turnover_limit(0.1, 0.3, prev_weight_sum=0.0)
    assert cold_start is True
    assert effective == 0.3


def test_resolve_turnover_limit_non_cold_start():
    effective, cold_start = up.resolve_turnover_limit(0.1, 0.3, prev_weight_sum=0.2)
    assert cold_start is False
    assert effective == 0.1


def test_resolve_turnover_limit_fallback():
    effective, cold_start = up.resolve_turnover_limit(0.1, None, prev_weight_sum=0.0)
    assert cold_start is True
    assert effective == 0.1
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_universe_pipeline_turnover.py::test_resolve_turnover_limit_cold_start -v`
Expected: FAIL with `AttributeError` (function missing).

**Step 3: Write minimal implementation**

Add helper and integrate:

```python
COLD_START_EPSILON = 1e-6


def resolve_turnover_limit(
    turnover_limit: float | None,
    cold_start_turnover: float | None,
    prev_weight_sum: float,
    epsilon: float = COLD_START_EPSILON,
) -> tuple[float | None, bool]:
    cold_start = prev_weight_sum <= epsilon
    effective = turnover_limit
    if cold_start and cold_start_turnover is not None:
        effective = float(cold_start_turnover)
    return effective, cold_start
```

Integrate in pipeline loop:
- Parse `cold_start_turnover` from `execution_cfg`/`weights_cfg` and coerce to float.
- Compute `prev_weight_sum` each rebalance.
- Use `effective_turnover_limit` instead of `turnover_limit` in `_apply_turnover_limit`.
- Track `cold_start_count`.
- Extend `_append_snapshot_row` with `cold_start`, `prev_weight_sum`, `effective_turnover_limit` and add columns in `snapshot_summary.csv`.
- Add summary fields: `cold_start_turnover`, `cold_start_count`, `cold_start_epsilon`, `effective_turnover_limit_avg`（可选，若有多次调仓）。

**Step 4: Run tests to verify they pass**

Run:
`pytest backend/tests/test_universe_pipeline_turnover.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/universe_pipeline.py backend/tests/test_universe_pipeline_turnover.py
git commit -m "Apply cold start turnover limit"
```

### Task 3: 优化器核心参数更新（可选但建议）

**Files:**
- Modify: `backend/app/services/backtest_opt_runner.py`
- Modify: `backend/tests/test_backtest_opt_runner.py`

**Step 1: Write the failing test**

```python
base = {
    "max_weight": "0.033",
    "max_exposure": "0.45",
    "vol_target": 0.055,
    "max_drawdown": "0.15",
    "top_n": "30",
    "retain_top_n": "10",
    "max_turnover_week": "0.08",
    "market_ma_window": "200",
    "cold_start_turnover": "0.3",
}
core = select_core_params(base)
assert core["cold_start_turnover"] == 0.3
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_backtest_opt_runner.py::test_select_core_params_coerces -v`
Expected: FAIL (missing key)

**Step 3: Write minimal implementation**

Add `"cold_start_turnover"` to `CORE_KEYS`.

**Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_backtest_opt_runner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/backtest_opt_runner.py backend/tests/test_backtest_opt_runner.py
git commit -m "Include cold start turnover in core params"
```

### Task 4: 前端参数与文案

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/i18n.tsx`

**Step 1: Write the failing test**

若无现成前端单测，跳过此步，改为后续手动验证（记录在验证步骤）。

**Step 2: Implement UI changes**

- `PIPELINE_BACKTEST_FIELDS`、`PIPELINE_BACKTEST_NUMBER_FIELDS` 加入 `cold_start_turnover`
- `PIPELINE_BACKTEST_DEFAULTS` 增加 `cold_start_turnover: 0.3`
- 参数展示列表添加 `cold_start_turnover`
- 在表单中新增一行输入（紧邻“周换手上限”）
- i18n 新增字段与提示：
  - `projects.pipeline.backtest.fields.coldStartTurnover`
  - `projects.pipeline.backtest.hints.coldStartTurnover`
  - 英文对应项

**Step 3: Run build**

Run:
`cd frontend && npm run build`
Expected: build success

**Step 4: Restart service**

Run:
`systemctl --user restart stocklean-frontend`
Expected: service active

**Step 5: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx frontend/src/i18n.tsx
git commit -m "Add cold start turnover to pipeline UI"
```

### Task 5: 集成验证

**Files:**
- None

**Step 1: Run backend tests**

Run:
`pytest backend/tests/test_decision_snapshot_algo_params.py backend/tests/test_universe_pipeline_turnover.py backend/tests/test_backtest_opt_runner.py -v`
Expected: PASS

**Step 2: Manual verification (UI)**

- 项目 → 算法 → 回测参数中可见“冷启动换手上限”，默认 0.3。
- 创建一次 pipeline 回测，检查生成的 summary.json 与 snapshot_summary.csv 是否包含：
  - `cold_start` / `prev_weight_sum` / `effective_turnover_limit`
  - `cold_start_turnover`

**Step 3: Final commit**

如有零散修复，提交一次收尾 commit。

