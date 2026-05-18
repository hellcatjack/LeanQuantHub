# Backtest/Paper Defensive Asset Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 Lean 回测、decision snapshot、paper/live 执行在防御资产选择与 idle allocation 上的行为结果。

**Architecture:** 抽出共享的防御/闲置资产选择 helper，先让 decision snapshot 固化有效 `risk_off_symbol/idle_symbol`，再让执行器与风险校验消费同一套结果。对旧 snapshot 保留兼容回退，但新 snapshot 必须完整。

**Tech Stack:** FastAPI backend, SQLAlchemy, pytest, local adjusted daily price files

---

### Task 1: 给共享防御/闲置资产选择逻辑写失败测试

**Files:**
- Create: `backend/tests/test_trade_execution_targets.py`
- Reference: `backend/app/services/trade_execution_targets.py`

- [ ] **Step 1: 写 `risk_off_symbols` 优先于 `risk_off_symbol` 的失败测试**
- [ ] **Step 2: 运行 `pytest backend/tests/test_trade_execution_targets.py -k risk_off_symbols_priority -v` 确认失败**
- [ ] **Step 3: 写 `best_momentum/lowest_vol` 选标失败测试**
- [ ] **Step 4: 运行对应测试确认失败**
- [ ] **Step 5: 写 `idle_allocation=defensive/benchmark` 解析失败测试**
- [ ] **Step 6: 运行对应测试确认失败**

### Task 2: 实现共享 helper 并接入执行目标解析

**Files:**
- Modify: `backend/app/services/trade_execution_targets.py`
- Test: `backend/tests/test_trade_execution_targets.py`

- [ ] **Step 1: 实现本地 adjusted 数据读取与 defensive picker**
- [ ] **Step 2: 实现 idle symbol 解析**
- [ ] **Step 3: 调整 `resolve_snapshot_execution_targets()`，让 `risk_on` 补齐 idle allocation，`risk_off` 保持 Lean 语义**
- [ ] **Step 4: 为旧 snapshot 增加兼容回退 metadata**
- [ ] **Step 5: 运行 `pytest backend/tests/test_trade_execution_targets.py -v` 确认通过**

### Task 3: 让 snapshot 管线固化真实防御/闲置资产

**Files:**
- Modify: `scripts/universe_pipeline.py`
- Modify: `backend/app/services/decision_snapshot.py`
- Test: `backend/tests/test_decision_snapshot_helpers.py`

- [ ] **Step 1: 为 snapshot 行包含 `risk_off_symbol/idle_symbol` 写失败测试**
- [ ] **Step 2: 运行对应 pytest 确认失败**
- [ ] **Step 3: 修改 `universe_pipeline.py`，把 benchmark/defensive symbols 纳入价格矩阵但不纳入选股 universe**
- [ ] **Step 4: 修改 `_pick_risk_off_symbol()` 使其与 Lean 逻辑一致**
- [ ] **Step 5: 在 `decision_snapshot.py` 保留并透传固化字段**
- [ ] **Step 6: 运行 snapshot 相关 pytest 确认通过**

### Task 4: 对齐执行器与风险校验

**Files:**
- Modify: `backend/app/services/trade_executor.py`
- Modify: `backend/app/services/trade_riskoff_validation.py`
- Modify: `backend/tests/test_trade_executor_rebalance_delta_intent.py`
- Modify: `backend/tests/test_trade_riskoff_validation.py`

- [ ] **Step 1: 为 `risk_on + idle_allocation` paper/live 补仓写失败测试**
- [ ] **Step 2: 为 risk-off 使用 snapshot 固化 symbol 写失败测试**
- [ ] **Step 3: 运行相关 pytest 确认失败**
- [ ] **Step 4: 接入新的有效目标解析与 meta 落盘**
- [ ] **Step 5: 让风险校验复用同一套有效目标**
- [ ] **Step 6: 运行相关 pytest 确认通过**

### Task 5: 运行回归与实际 dry-run 验证

**Files:**
- No code changes required unless回归暴露缺口

- [ ] **Step 1: 运行交易执行与 snapshot 相关 pytest 子集**
- [ ] **Step 2: 生成一个新的 preview snapshot，检查 `risk_off_symbol/idle_symbol` 不再为空**
- [ ] **Step 3: 做一次 `dry_run=True` 的 paper 执行，验证结果与 snapshot 一致**
- [ ] **Step 4: 若前端未改动则无需 build；总结验证结果与剩余边界**
