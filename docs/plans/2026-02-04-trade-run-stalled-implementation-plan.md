# 实盘交易停滞处理 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为实盘交易 run 增加 15 分钟无进展的 `stalled` 处理、可审计字段、人工处置入口与 UI 展示。

**Architecture:** 在 `trade_runs` 增加进度字段；核心服务统一更新进度并判定停滞；路由提供 resume/terminate/sync；前端展示停滞原因与操作按钮。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL、React + Vite、Pytest/Playwright。

> 说明：项目规则禁止使用 git worktree，本计划直接在主工作区执行。

### Task 1: 数据库变更脚本

**Files:**
- Create: `deploy/mysql/patches/20260204_trade_run_stalled.sql`

**Step 1: Write migration script**

```sql
-- 变更说明: 为 trade_runs 增加停滞进度字段
-- 影响范围: trade_runs 表
-- 回滚指引: 删除新增列

ALTER TABLE trade_runs
  ADD COLUMN IF NOT EXISTS last_progress_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS progress_reason TEXT NULL,
  ADD COLUMN IF NOT EXISTS stalled_at DATETIME NULL,
  ADD COLUMN IF NOT EXISTS stalled_reason TEXT NULL;
```

**Step 2: Run migration (manual)**

```bash
mysql -u <user> -p <db> < deploy/mysql/patches/20260204_trade_run_stalled.sql
```

**Step 3: Commit**

```bash
git add deploy/mysql/patches/20260204_trade_run_stalled.sql
git commit -m "Add trade run stalled fields"
```

### Task 2: 后端模型 + 进度更新工具函数

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/services/trade_run_progress.py`
- Create: `backend/tests/test_trade_run_progress.py`

**Step 1: Write failing test**

```python
from datetime import datetime, timedelta
from app.services.trade_run_progress import is_trade_run_stalled


def test_trade_run_stalled_true():
    now = datetime.utcnow()
    run = type("R", (), {"status": "running", "last_progress_at": now - timedelta(minutes=16)})
    assert is_trade_run_stalled(run, now)
```

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_trade_run_progress.py::test_trade_run_stalled_true -v`
Expected: FAIL

**Step 3: Implement minimal code**

- 增加 `TradeRun` 新字段
- `trade_run_progress.py` 提供：
  - `update_trade_run_progress(session, run, stage, reason=None)`
  - `is_trade_run_stalled(run, now, window_minutes=15, trading_open=True)`

**Step 4: Run tests**

Run: `pytest backend/tests/test_trade_run_progress.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/models.py backend/app/services/trade_run_progress.py backend/tests/test_trade_run_progress.py
git commit -m "Add trade run progress helpers"
```

### Task 3: 停滞判定与状态迁移

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/trade_run_summary.py`
- Modify: `backend/app/routes/trade.py`
- Create: `backend/tests/test_trade_run_stalled_route.py`

**Step 1: Write failing tests**

- 断言 `running` + 15 分钟无进展 -> `stalled`。
- 断言 `stalled` 时执行 run 会被拒绝（除非 force/resume）。
- 路由：`/api/trade/runs/{id}/resume`、`/terminate`、`/sync`。

**Step 2: Run tests to verify failure**

Run: `pytest backend/tests/test_trade_run_stalled_route.py -v`
Expected: FAIL

**Step 3: Implement**

- 在 `refresh_trade_run_status` 中加入停滞判断。
- 在订单创建/状态变更时调用 `update_trade_run_progress`。
- 路由增加 `resume/terminate/sync`，写审计日志。

**Step 4: Run tests**

Run: `pytest backend/tests/test_trade_run_stalled_route.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/services/trade_executor.py backend/app/services/trade_run_summary.py \
  backend/app/routes/trade.py backend/tests/test_trade_run_stalled_route.py
git commit -m "Add trade run stalled handling"
```

### Task 4: 前端展示与操作

**Files:**
- Modify: `frontend/src/pages/LiveTradePage.tsx`
- Modify: `frontend/src/i18n.tsx`
- Create: `frontend/tests/live-trade-stalled.spec.ts` (若必要)

**Step 1: Write failing test (optional)**

Playwright 断言 stalled 状态时按钮可见。

**Step 2: Implement**

- 展示 stalled 信息：last_progress_at、progress_stage、stalled_reason
- 按钮：继续/同步/终止（弹出原因输入）

**Step 3: Build & restart**

```bash
cd frontend && npm run build
systemctl --user restart stocklean-frontend
```

**Step 4: Commit**

```bash
git add frontend/src/pages/LiveTradePage.tsx frontend/src/i18n.tsx
# 若新增测试也一起 add

git commit -m "Show trade run stalled status and actions"
```

### Task 5: 集成验证

Run:
`pytest backend/tests/test_trade_run_progress.py backend/tests/test_trade_run_stalled_route.py -v`

手动验证：
- 运行中超过 15 分钟无进展显示 stalled
- resume/sync/terminate 有效且写审计

