# Lean 回测与实盘统一执行设计（方案 A）

## 背景
当前系统同时存在：
- Lean 回测路径（BacktestRun）
- 决策快照的管线回测路径（scripts/universe_pipeline.py）
- 实盘执行路径（LeanBridgeExecutionAlgorithm + 后端订单编译）

由于后端与 Lean 各自实现部分执行约束，导致回测与实盘在执行层出现偏差。

## 目标
- 以 **Lean 回测** 为一致性基准。
- 回测与实盘共享同一套 **信号 + 执行** 逻辑。
- 审计闭环：执行参数与结果可追溯。

## 现状评估
- 回测：
  - Lean 回测：`backend/app/services/lean_runner.py`
  - 管线回测：`backend/app/services/decision_snapshot.py::_run_pipeline_backtest`
- 实盘：
  - 后端订单编译（`build_orders`）+ LeanBridgeExecutionAlgorithm 执行
- 执行约束（min_qty/cash_buffer/风控）目前在 **后端与 Lean 同时存在**，容易不一致。

## 方案 A（统一 Lean 执行内核）
### 核心思路
把执行逻辑统一收敛到 `algorithms/lean_trend_rotation.py`：
- 回测与实盘均由 Lean 决定 PortfolioTargets 与 Order
- 后端仅生成目标权重与参数，作为 Lean 输入

### 数据流
1) 生成决策快照/权重文件  
2) Lean 回测或 Lean 实盘执行，读取同一套权重与参数  
3) Lean 输出订单事件与成交记录，后端仅接收并入库  

## 统一参数与约束清单
- 资金与现金规则：`initial_cash`, `cash_buffer_ratio`
- 最小下单：`min_qty`, `lot_size`, `min_order_value` / `MinimumOrderMarginPortfolioPercentage`
- 风控约束：`max_order_notional`, `max_position_ratio`, `max_total_notional`, `max_symbols`
- 交易成本：`fee_bps`, `slippage_open_bps`, `slippage_close_bps`
- 价格来源：回测历史价 / 实盘最新价，但同一接口抽象

## 改动清单（预估）
### 代码
- `algorithms/lean_trend_rotation.py`
  - 增强参数解析与执行约束，统一回测/实盘逻辑
- `backend/app/services/trade_executor.py`
  - 移除后端订单编译（保留权重/参数下发）
- `backend/app/services/lean_runner.py`
  - 回测参数与实盘统一对齐
- `backend/app/services/decision_snapshot.py`
  - 只输出权重，不再生成订单

### 配置
- Lean 配置模板新增统一参数映射

### 测试
- 一致性测试：同一权重在回测与实盘模拟下的订单一致性
- 关键回归回测：CAGR/maxdd 变化评估
- 实盘 dry-run：LeanBridgeExecutionAlgorithm 事件审计完整性

## 影响评估
- **推理层（选股/权重）**：保持不变  
- **执行层（订单生成/过滤）**：将更一致，回测曲线可能变化

## 风险与回滚
- 风险：回测收益可能下降，但更接近实盘表现  
- 回滚：保留旧后端编译路径可快速切回

## 成功标准
- 回测与实盘订单方向/数量一致
- 执行参数可审计
- 无额外风控绕过

## 实施进度（2026-02-06）
- 已新增执行参数写入与测试（`backend/app/services/lean_execution_params.py`）。
- 已新增意图订单生成（`build_intent_orders`）与对应测试。
- 交易执行支持 Lean 意图 + 参数下发，并在配置中传递 `execution-params-path`。
- 回测入口新增执行参数 payload 构建函数与测试。
- Lean 算法新增执行约束函数与测试。
