# 测试失败修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan.

**Goal:** 修复当前 12 个单测失败，确保 `backend/` 下 `PYTHONPATH=. pytest` 全绿。

**Architecture:** 以最小改动恢复缺失的 `ib_account` API；让 `lean_execution` 在 `cwd=None` 时不传参；`trade_executor` 在 `dry_run` 时跳过全局锁；`data_root` 解析优先环境变量覆盖，避免测试被 `.env` 影响。

**Tech Stack:** Python 3.10, FastAPI, pytest, SQLAlchemy

### Task 1: 修复 data_root 环境变量优先级（TDD）

**Files:**
- Modify: `backend/tests/test_data_sync_orphan_guard.py`
- Modify: `backend/app/services/data_sync_orphan_guard.py`

**Step 1: 写一个会失败的回归测试**

```python

def test_orphan_guard_env_overrides_settings(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "data_root", "/tmp/should-not-use")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    cfg_path = tmp_path / "config" / "data_sync_orphan_guard.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    cfg = load_data_sync_orphan_guard_config()
    assert cfg["enabled"] is False
```

**Step 2: 运行测试，确认失败**

Run: `PYTHONPATH=. pytest tests/test_data_sync_orphan_guard.py::test_orphan_guard_env_overrides_settings -v`
Expected: FAIL（仍使用 settings.data_root）

**Step 3: 写最小实现**

在 `_resolve_data_root()` 中优先使用 `DATA_ROOT` 环境变量，其次才用 `settings.data_root`。

**Step 4: 运行测试，确认通过**

Run: `PYTHONPATH=. pytest tests/test_data_sync_orphan_guard.py::test_orphan_guard_env_overrides_settings -v`
Expected: PASS

**Step 5: 提交**

```bash
git add backend/tests/test_data_sync_orphan_guard.py backend/app/services/data_sync_orphan_guard.py
git commit -m "fix: honor DATA_ROOT override in orphan guard"
```

### Task 2: 恢复 ib_account 缺失 API（使用现有失败测试作为 RED）

**Files:**
- Modify: `backend/app/services/ib_account.py`
- Test: `backend/tests/test_ib_account_summary.py`

**Step 1: 运行现有失败测试，确认 RED**

Run: `PYTHONPATH=. pytest tests/test_ib_account_summary.py -v`
Expected: FAIL（ImportError/AttributeError）

**Step 2: 写最小实现**

在 `ib_account.py` 中新增：
- `CORE_TAGS`（至少包含 `NetLiquidation`、`TotalCashValue`、`AvailableFunds`、`CashBalance`）
- `_filter_summary(raw, full)`
- `build_account_summary_tags(full)`
- `resolve_ib_account_settings(session)`（仅调用 `get_or_create_ib_settings`）
- `iter_account_client_ids(base, attempts=3)`

可选：在 `get_account_summary` 内用 `_filter_summary` 过滤 `items`。

**Step 3: 运行测试，确认通过**

Run: `PYTHONPATH=. pytest tests/test_ib_account_summary.py -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/services/ib_account.py
git commit -m "fix: restore ib account summary helpers"
```

### Task 3: 让 launch_execution 兼容 cwd=None（使用现有失败测试作为 RED）

**Files:**
- Modify: `backend/app/services/lean_execution.py`
- Test: `backend/tests/test_lean_execution_runner.py`

**Step 1: 运行现有失败测试，确认 RED**

Run: `PYTHONPATH=. pytest tests/test_lean_execution_runner.py::test_launch_execution_calls_subprocess -v`
Expected: FAIL（_fake_run 不接受 cwd）

**Step 2: 写最小实现**

`launch_execution` 构造 kwargs，只有在 `cwd` 非空时才传入：
```python
kwargs = {"check": False}
if cwd:
    kwargs["cwd"] = cwd
subprocess_run(cmd, **kwargs)
```

**Step 3: 运行测试，确认通过**

Run: `PYTHONPATH=. pytest tests/test_lean_execution_runner.py::test_launch_execution_calls_subprocess -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/services/lean_execution.py
git commit -m "fix: make launch_execution cwd optional"
```

### Task 4: dry_run 时跳过全局锁（使用现有失败测试作为 RED）

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Test: `backend/tests/test_trade_execution_builder.py`
- Test: `backend/tests/test_trade_risk_cash.py`
- Test: `backend/tests/test_trade_run_intent_path.py`
- Test: `backend/tests/test_trade_run_portfolio_value.py`
- Test: `backend/tests/test_trade_snapshot_binding.py`

**Step 1: 运行现有失败测试，确认 RED**

Run: `PYTHONPATH=. pytest tests/test_trade_execution_builder.py tests/test_trade_risk_cash.py tests/test_trade_run_intent_path.py tests/test_trade_run_portfolio_value.py tests/test_trade_snapshot_binding.py -v`
Expected: FAIL（trade_execution_lock_busy）

**Step 2: 写最小实现**

`execute_trade_run` 在 `dry_run=True` 时不获取全局 `JobLock`（其余逻辑保持不变）。

**Step 3: 运行测试，确认通过**

Run: `PYTHONPATH=. pytest tests/test_trade_execution_builder.py tests/test_trade_risk_cash.py tests/test_trade_run_intent_path.py tests/test_trade_run_portfolio_value.py tests/test_trade_snapshot_binding.py -v`
Expected: PASS

**Step 4: 提交**

```bash
git add backend/app/services/trade_executor.py
git commit -m "fix: skip trade execution lock in dry_run"
```

### Task 5: 全量回归

**Files:**
- Test: `backend/`

**Step 1: 运行全量测试**

Run: `PYTHONPATH=. pytest`
Expected: PASS（0 failures）

**Step 2: 提交（若有剩余变更）**

```bash
git add backend/
git commit -m "test: green backend suite"
```
