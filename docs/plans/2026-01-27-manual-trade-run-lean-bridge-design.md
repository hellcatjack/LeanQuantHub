# 手动交易走 Lean IB 执行器设计

**目标**
- 手动买/卖/全仓清空通过 Lean IB 执行器发送到 TWS。  
- 手动订单在系统中生成可追踪的 `TradeRun`，订单与回写统一归档。  
- 绕过风险评估（按需求）。

**范围**
- 后端：新增“手动执行 Run”接口与 intent 写入逻辑；`trade_executor` 支持 `risk_bypass`。  
- Lean：扩展 `LeanBridgeExecutionAlgorithm` 支持负数量（SELL）。  
- 前端：调用手动执行接口并展示 run_id/状态。  
- 结果回写：沿用 `execution_events.jsonl` + `oi_{run_id}_{index}` tag。

---

## 1. 执行链路与数据流
1) 前端“当前持仓”触发买/卖/全仓清空 → 调用后端手动执行接口。  
2) 后端创建 `TradeRun`（`mode=paper/live`，`params.source=manual`）。  
3) 订单写入 `trade_orders`（带 `run_id`），生成 execution intent：  
   - 文件名：`order_intent_manual_run_{run_id}.json`  
   - 字段：`order_intent_id`, `symbol`, `quantity`, `weight`  
   - SELL 用 `quantity < 0`  
4) `trade_run.params.order_intent_path` 记录 intent 路径。  
5) 触发 `execute_trade_run(run_id, force=true)`，生成 Lean config 并启动 Lean。  
6) Lean ResultHandler 输出 `execution_events.jsonl`，后端 ingest 更新 `trade_orders` 状态与成交。

---

## 2. 接口与数据结构
**新增接口**（建议）：
- `POST /api/trade/runs/manual`

**请求体**
```
{
  project_id: number,
  mode: "paper" | "live",
  orders: [
    {
      client_order_id: string,
      symbol: string,
      side: "BUY" | "SELL",
      quantity: number,
      order_type: "MKT" | "LMT",
      params?: { account?: string, currency?: string }
    }
  ]
}
```

**后端处理**
- 创建 `trade_run`，`params.source=manual`  
- `create_trade_order(..., run_id=run.id)`  
- 写 intent 文件：
  - `order_intent_id = oi_{run_id}_{index}`
  - `quantity` 负数代表 SELL
  - `weight = 0`
- `params.order_intent_path = <intent_path>`  
- 调用 `execute_trade_run`，并在 `trade_executor` 中支持 `params.risk_bypass=true` 跳过 `evaluate_orders`

---

## 3. Lean 算法扩展
**LeanBridgeExecutionAlgorithm**：
- 解析 intent：
  - `quantity != 0` → 直接 `MarketOrder(symbol, quantity, tag: order_intent_id)`（负数代表 SELL）  
  - `quantity == 0 && weight != 0` → `SetHoldings(symbol, weight, tag: order_intent_id)`  
- `order_intent_id` 为空：写日志并跳过。

---

## 4. 测试与验证
**后端测试**
- `test_trade_manual_run_writes_intent`：  
  - 断言 `trade_run` 创建与 `trade_orders` 归属  
  - 断言 intent 文件存在，SELL 为负数量  
- `test_trade_executor_risk_bypass`：  
  - `params.risk_bypass=true` 时跳过 `evaluate_orders`  
  - 仍生成 Lean config 并触发 `launch_execution`（可 mock）

**Playwright**
- 扩展 live-trade 测试：  
  - 触发卖出/全仓清空  
  - 断言返回新的 `run_id`  
  - 断言 run 状态进入 `running/submitted_lean`

**人工验证**
- TWS paper 收到 SELL 订单  
- `execution_events.jsonl` 出现对应 `oi_{run_id}_{index}`  
- `trade_orders` 更新 `ib_order_id/filled`

---

## 5. 风险与约束
- 必须保持 paper/live 隔离，默认 paper。  
- 手动订单绕过风险评估仅用于该接口。  
- intent 格式必须与 Lean 算法对齐，避免漏发。
