# Paper/Live 决策快照参数来源修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `paper/live` 交易批次默认基于当前项目/当前 pipeline 配置生成 decision snapshot，不再自动继承历史回测参数。

**Architecture:** 修改 backtest 绑定解析函数的默认策略，统一影响 decision route 与 pretrade 入口；保留显式 `backtest_run_id` 回放能力；用回归测试锁定默认行为和显式行为。

**Tech Stack:** FastAPI, SQLAlchemy, pytest

---

### Task 1: 锁定默认绑定行为

**Files:**
- Modify: `backend/tests/test_decision_snapshot_backtest_link.py`
- Modify: `backend/tests/test_decision_snapshot_backtest_route.py`
- Modify: `backend/tests/test_trade_run_schedule.py`

- [ ] 写失败测试，断言未显式指定 `backtest_run_id` 时不再返回 `auto_project/auto_pipeline`
- [ ] 运行相关 pytest 用例，确认红灯

### Task 2: 修改 backtest link 默认策略

**Files:**
- Modify: `backend/app/services/decision_snapshot.py`
- Modify: `backend/app/services/pretrade_runner.py`（仅保持兼容断言/持久化）
- Modify: `backend/app/routes/decisions.py`（复用新状态）

- [ ] 修改 `resolve_backtest_run_link()` 默认返回 `current_project/current_pipeline`
- [ ] 确认 `generate_decision_snapshot()` 在 `backtest_run_id=None` 时走当前项目或当前 pipeline 参数
- [ ] 保留显式 `backtest_run_id` 路径不变

### Task 3: 回归验证

**Files:**
- Verify: `backend/tests/test_decision_snapshot_backtest_link.py`
- Verify: `backend/tests/test_decision_snapshot_backtest_route.py`
- Verify: `backend/tests/test_trade_run_schedule.py`

- [ ] 运行定向 pytest
- [ ] 运行更大范围的 decision/pretrade 相关 pytest
- [ ] 用本地 API/数据库抽样验证新的 `backtest_link_status` 与 `backtest_run_id` 行为
