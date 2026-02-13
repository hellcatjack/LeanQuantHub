# 实盘自动调仓：基于持仓 Delta 的 Lean 下单与偏离概览修正 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 调试并固化实盘自动交易（下单执行 + 风控）逻辑：执行前读取 Lean Bridge `positions.json` 全量持仓，用快照目标权重 + 最新价格/净值计算目标股数并生成 delta BUY/SELL；intent 采用 quantity 模式（SELL 为负数）且先卖后买；“目标偏离概览”基于当前持仓市值/权重计算 delta，并包含非目标持仓（目标权重=0，显示需清仓）。

**Architecture:** 后端 `trade_executor.execute_trade_run` 在首次执行（run 尚无 orders）时从 `positions.json`/`quotes.json`/`account_summary.json` 构建“SetHoldings+liquidateExistingHoldings=True”语义的 delta 订单，并写入 run 专属 intent 文件；前端继续消费 `/api/trade/runs/{id}/symbols`，由 `trade_run_summary.build_symbol_summary` 用 positions 的市值/权重产出偏离概览。

**Tech Stack:** FastAPI + SQLAlchemy（backend）, Pytest, Lean Bridge JSON files.

---

### Task 1: 为自动调仓 intent 生成补回归测试（TDD）

**Files:**
- Create: `backend/tests/test_trade_executor_rebalance_delta_intent.py`
- Modify: `backend/app/services/trade_executor.py`

**Step 1: Write the failing test**
- 构造快照权重（仅目标标的 AAA）+ 当前持仓（含非目标 ZZZ）+ 最新净值（NetLiquidation）+ 行情价格
- 断言：
  - 目标股数基于 *最新* NetLiquidation（而非 run.params 里旧的 portfolio_value）
  - delta = target_qty - current_qty
  - intent 为 quantity 模式，SELL 为负数
  - intent 文件内顺序先卖后买（sell items 在 buy items 之前）

**Step 2: Run test to verify it fails**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_rebalance_delta_intent.py -q`
Expected: FAIL（当前实现只在 portfolio_value 缺失时才读取 NetLiquidation）

**Step 3: Write minimal implementation**
- `trade_executor.execute_trade_run` 构建 delta 订单时：
  - 始终尝试读取 Lean Bridge `account_summary.json` 的 `NetLiquidation` 覆盖用于 sizing 的 `portfolio_value`（若有效 > 0）
  - 将更新后的 `portfolio_value` 回写到 `run.params`

**Step 4: Run test to verify it passes**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_rebalance_delta_intent.py -q`
Expected: PASS

---

### Task 2: 偏离概览基于 positions 市值/权重（含非目标持仓）补回归测试（TDD）

**Files:**
- Create: `backend/tests/test_trade_run_symbol_summary_positions_value.py`
- Modify: `backend/app/services/trade_run_summary.py`

**Step 1: Write the failing test**
- positions.json 里提供 `market_value`（并让 quotes/price_map 为空）
- 断言 summary 的：
  - `current_value` 优先使用 positions 的 `market_value`
  - `current_weight`/`delta_weight` 与 `portfolio_value` 一致
  - 非目标持仓（目标权重=0）仍出现在 summary，且 delta 为“需清仓”

**Step 2: Run test to verify it fails**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_run_symbol_summary_positions_value.py -q`
Expected: FAIL（当前实现仅用 quote price 计算 current_value，缺价格时 current_value=None）

**Step 3: Write minimal implementation**
- `trade_run_summary.build_symbol_summary` 读取 positions items 时同时提取：
  - `current_qty`
  - `current_market_value`（来自 `market_value`，或 `market_price * quantity`）
- 计算 `current_value` 时优先采用 `current_market_value`，缺失时再回退 `quantity * price_map`

**Step 4: Run test to verify it passes**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_run_symbol_summary_positions_value.py -q`
Expected: PASS

---

### Task 3: 允许 TradeSettings.execution_data_source 设为 lean（防止执行被阻断）

**Files:**
- Modify: `backend/app/routes/trade.py`
- Modify: `backend/tests/test_trade_settings_api.py`

**Step 1: Write the failing test**
- 更新 trade settings 时传入 `execution_data_source="lean"`，断言返回值仍为 `lean`

**Step 2: Run test to verify it fails**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_settings_api.py -q`
Expected: FAIL（当前 API 强制写回 `ib`）

**Step 3: Write minimal implementation**
- `update_trade_settings`：
  - 仅当 payload 提供 `execution_data_source` 时才更新该字段
  - 允许的值：`lean`（可选保留 `ib` 但会导致执行器阻断）

**Step 4: Run test to verify it passes**
Run: `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_settings_api.py -q`
Expected: PASS

---

### Task 4: 集中验证（回归）

**Files:**
- None

Run:
- `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_executor_rebalance_delta_intent.py -q`
- `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_run_symbol_summary_positions_value.py -q`
- `/app/stocklean/.venv/bin/python -m pytest backend/tests/test_trade_settings_api.py -q`

Expected: PASS

