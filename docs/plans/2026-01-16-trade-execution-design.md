# 交易执行层（A+C-1）整合设计

> 目标：在**不依赖 IB API**的前提下，搭建可验证的交易闭环；同时预留 Lean/IB 执行器接入点，实现从 Mock → 实盘的无缝切换。

## 1. 背景与范围
- 当前系统已具备决策快照、TradeRun/TradeOrder/TradeFill 基础表与 UI。
- 需补齐“订单生成 + 风控 + 执行器抽象 + 状态机与幂等”的完整闭环。
- 不覆盖期权、分钟级高频与真实 IB 执行联调（待 IB API 可用）。

## 2. 设计原则
- **单流程多执行器**：业务流程保持一套，执行器可替换。
- **幂等优先**：重复触发不重复下单。
- **可审计可回放**：关键参数、快照、执行结果需可追溯。
- **Mock-first**：先验证逻辑与审计闭环，再接 IB/Lean。

## 3. 架构概览
```
PreTradeRun
  └─ DecisionSnapshot (冻结)
       └─ TradeRun (queued)
            ├─ OrderBuilder (权重→订单)
            ├─ RiskEngine (风控)
            └─ ExecutionProvider
                ├─ MockExecutionProvider (当前)
                └─ LeanExecutionProvider (预留)
```

## 4. 关键组件
### 4.1 OrderBuilder（订单生成器）
- 输入：DecisionSnapshot 权重、账户资金、现金保留比例、最小交易单位。
- 输出：标准化订单（side/qty/order_type/limit_price/client_order_id）。
- 规则：
  - 目标市值 = 权重 × portfolio_value
  - qty = floor(target_notional / price / lot_size) × lot_size
  - 现金不足时按比例剪裁

### 4.2 RiskEngine（风控引擎）
- 输入：订单列表 + 风控参数（最大订单名义、最大仓位比、单票/行业上限）。
- 输出：通过/阻断、被拦截订单与原因。
- 风控失败写入 `TradeRun.params.risk` + 审计日志。

### 4.3 ExecutionProvider（执行器抽象）
统一接口：
- `prepare(run, snapshot) -> orders`
- `risk_check(run, orders) -> (pass, blocked, reasons)`
- `execute(run, orders, dry_run) -> fills + status`
- `finalize(run, result)`

**MockExecutionProvider**：使用快照价格/历史回退价格模拟成交，落库 TradeFill。

**LeanExecutionProvider**：预留接入点，未来接 IB API 真实成交回报。

## 5. 状态机与幂等
- TradeRun：`queued → running → done/failed/blocked`
- TradeOrder：`NEW → SUBMITTED → PARTIAL/FILLED/CANCELED/REJECTED`
- 幂等键：`client_order_id = run_id + symbol + side + model_version`
- 重复执行同一 TradeRun 时：
  - 已存在订单则复用，不重复创建。
  - 已终态订单不再修改。

## 6. 错误处理与回退
- 输入校验失败：直接 `failed`，写 `run.message`。
- 风控阻断：`blocked`，写 `block_reason`。
- 执行失败：
  - 价格不可用 → order `REJECTED`
  - 其他异常 → run `failed` + error detail

## 7. 可观测性与审计
- 每次执行写入 `trade_run.execute` 审计日志
- 记录：快照 ID、风控参数、执行结果计数、错误原因

## 8. 测试策略
1) **单测**：订单生成、舍入、风控规则、状态机转移、幂等冲突。
2) **集成测试（Mock）**：快照→订单→执行→fills 全链路。
3) **回归测试**：重复执行同一 TradeRun，确保不重复下单。

## 9. 验收标准（Mock 阶段）
- 同一 TradeRun 重复执行不重复下单
- 订单生成与风控阻断结果可解释
- 执行结果与审计记录一致

## 10. 非目标
- 不在本阶段接入真实 IB 执行回报
- 不包含期权与高频策略

