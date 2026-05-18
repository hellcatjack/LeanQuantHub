# Live Trade Risk-Off Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让实盘/虚拟盘在 `risk_off` 场景下自动按回测语义完成防御资产买卖，并与风险校验保持一致。

**Architecture:** 在 `trade_executor.py` 增加 snapshot 执行目标解析器，由它统一产出 `risk_off` 有效目标权重；正常 risk-on 继续使用 `decision_items.csv`。`trade_riskoff_validation.py` 复用同一套解析规则，避免执行与校验出现第二套语义。

**Tech Stack:** FastAPI backend, SQLAlchemy models, pytest

---

### Task 1: 为 risk_off 执行语义写失败测试

**Files:**
- Modify: `backend/tests/test_trade_executor_rebalance_delta_intent.py`

- [ ] **Step 1: 写 defensive 模式失败测试**
- [ ] **Step 2: 运行单测确认当前实现失败**
- [ ] **Step 3: 写 cash / benchmark 模式失败测试**
- [ ] **Step 4: 运行单测确认当前实现失败**

### Task 2: 实现 snapshot 执行目标解析器

**Files:**
- Modify: `backend/app/services/trade_executor.py`

- [ ] **Step 1: 增加 summary 解析 helper**
- [ ] **Step 2: 在正式执行路径使用 effective target weights**
- [ ] **Step 3: 保留 risk_on 和 risk_off_drill 既有行为**
- [ ] **Step 4: 运行新增单测确认通过**

### Task 3: 对齐 risk_off 校验逻辑

**Files:**
- Modify: `backend/app/services/trade_riskoff_validation.py`
- Modify: `backend/tests/test_trade_riskoff_validation.py`

- [ ] **Step 1: 为 summary 驱动的 risk_off 目标校验补失败测试**
- [ ] **Step 2: 运行单测确认失败**
- [ ] **Step 3: 实现有效目标解析与校验复用**
- [ ] **Step 4: 运行单测确认通过**

### Task 4: 回归验证

**Files:**
- Modify: `docs/superpowers/specs/2026-03-26-live-trade-riskoff-execution-design.md`（如实现边界与设计有偏差则更新）

- [ ] **Step 1: 运行相关 pytest 子集**
- [ ] **Step 2: 运行更广的交易执行/风险回归测试**
- [ ] **Step 3: 总结验证结果与运行边界**
