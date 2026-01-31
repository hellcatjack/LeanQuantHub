# 实盘交易已实现盈亏（FIFO）设计方案

## 背景
当前“当前持仓”中的已实现盈亏（Realized PnL）无法获取，原因是 Lean Bridge 的 `positions.json` 未包含 `realized_pnl` 字段，后端也未进行补算。需要基于“系统首次持仓快照 + 成交明细”计算每个标的的已实现盈亏，并在 UI/接口中清晰展示可核对信息。

## 目标
- 采用 **FIFO + 手续费入成本** 计算每个标的的已实现盈亏。
- 起算基准为“系统首次持仓快照”（不追溯历史）。
- 在“订单明细 / 成交明细 / 回执”三子表中补齐关键字段以支持核对。
- 当前持仓表中展示 `realized_pnl` 的稳定数值（非空）。

## 非目标
- 不追溯系统启用前的历史成交。
- 不更改 IB 真实账户盈亏逻辑，仅实现系统内可解释计算。
- 暂不引入外部行情/成本库，仅依赖系统已有的 Lean/DB 交易数据。

## 数据源与范围
- **持仓基准**：Lean Bridge `positions.json`，首次可用时刻记为 T0。
- **成交明细**：`trade_fills`（DB），由 Lean 回执解析写入；必要时补充 `symbol/side` 等字段。
- **订单明细**：`trade_orders`（DB）。
- **回执**：Lean `execution_events.jsonl` 聚合为 receipts（用于补齐信息与核对）。

## 计算口径
### 1) FIFO 批次队列
- 每个标的维护 FIFO 批次队列，批次结构：
  - `qty`（正=多头，负=空头）
  - `cost`（单位成本）
  - `opened_at`（批次产生时间）
  - `source`（基准 or 成交）

### 2) 基准快照（T0）
- 在 T0 时刻读取 `positions.json`：
  - 若 `position > 0`，生成多头批次 `qty=position, cost=avg_cost`。
  - 若 `position < 0`，生成空头批次 `qty=position, cost=avg_cost`。
- 该批次作为 FIFO 起点，不追溯历史成交。

### 3) 成交归因
- 逐笔成交（TradeFill）按 `fill_time` 排序处理。
- **SELL（平多）**：
  - 用卖出数量匹配 FIFO 多头批次，计算每一段 realized：
  - `realized = (sell_price - batch_cost) * match_qty - commission_alloc`
- **BUY（回补空）**：
  - 用买入数量匹配 FIFO 空头批次，计算 realized：
  - `realized = (batch_cost - buy_price) * match_qty - commission_alloc`
- **方向超出**：
  - SELL 超出多头 -> 生成新的空头批次
  - BUY 超出空头 -> 生成新的多头批次

### 4) 手续费处理
- 优先使用 `TradeFill.commission`；缺失则 0。
- 手续费按成交笔归因进入 realized（直接扣减）。

## API 与字段调整
### 1) `/api/brokerage/account/positions`
- 增加字段 `realized_pnl`（按标的累计）。
- 返回值写入当前持仓表。  

### 2) `/api/trade/runs/{run_id}/detail`（成交明细）
- 关联 `TradeOrder` 补齐 `symbol/side`。
- 增加 `realized_pnl`（该笔成交贡献）。
- 增加 `commission`（若存在）。

### 3) `/api/trade/receipts`
- 补齐 `symbol/side`（若来自 order/lean 事件）。
- 增加 `commission` / `realized_pnl`（若可推导）。

### 4) 订单明细（orders）
- 新增 `realized_pnl` 汇总（订单级累计，部分成交可更新）。

## UI 调整
- 当前持仓表：`已实现盈亏` 列显示数值（若无，则显示 0 并标注“起算后无成交”）。
- 成交明细/回执表：新增列 `symbol`、`side`、`commission`、`realized_pnl`，便于核对。
- 订单明细：新增订单级 `realized_pnl`（可选列）。

## 边界与一致性
- 若成交时间早于 T0，忽略（不计入 realized）。
- 若成交缺失 `symbol/side`，尝试从订单/回执补齐；仍缺失则跳过并记录 warning。
- 若持仓快照缺失或为 stale：UI 提示“已实现盈亏起算点未建立”。

## 测试方案
### 后端单测
- FIFO 多笔成交（含手续费）计算正确。
- SELL 超出多头形成空头批次。
- BUY 回补空头批次。
- 缺失手续费时按 0 处理。

### 前端 Playwright
- “当前持仓”已实现盈亏列可见且非空。
- “成交明细/回执/订单明细”展示新增列。

## 验收标准
- 持仓已实现盈亏与成交明细累计一致（可交叉核对）。
- 交易明细三子表具备核对所需字段。
- 不追溯历史，起算点清晰可解释。

