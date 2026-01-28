# 手动订单直连 Lean IB 执行设计

## 背景
当前“实盘交易 → 当前持仓”的买入/卖出/平仓只创建 `TradeOrder`，不会触发 Lean IB 执行器，订单长期停留在 `NEW`，回写也无法匹配。

## 目标
- 手动买/卖/平仓点击后 **立即** 生成独立 execution-intent 并启动一次 Lean。
- 手动订单 **绕过风控**，不影响 TradeRun 的风控与执行流程。
- 回写以 `client_order_id` 为唯一标识，确保订单/成交状态精确更新。

## 约束
- `run_id` 可为空。
- 回写严格使用 `tag (= client_order_id)` 进行匹配，不做 symbol/time 兜底。
- 不改变现有 TradeRun 执行逻辑。

## 方案概述
### 手动执行入口
1. UI 通过 `/api/trade/orders` 创建订单，`params` 注入：
   - `source=manual`
   - `project_id=<当前项目>`
   - `mode=<paper|live>`
2. 后端在订单创建成功后：
   - 生成 `order_intent_manual_<order_id>.json`，包含：
     - `order_intent_id = client_order_id`
     - `symbol`
     - `quantity`（SELL 使用负数）
     - `weight = 0`
   - 调用 `build_execution_config` + `launch_execution` 启动 Lean。

### Lean 执行
- `LeanBridgeExecutionAlgorithm` 读取 `order_intent_id` 作为 tag，下单并写回 `execution_events.jsonl`。

### 回写处理
- 解析 `execution_events.jsonl`（支持 JSONL），按 `tag` 查找 `TradeOrder.client_order_id`：
  - `Submitted` → `SUBMITTED`
  - `Filled` → `FILLED` + 生成 `TradeFill`
- 幂等处理：
  - 同一订单事件若 `event_time <= last_status_ts` 则跳过。

## 错误处理
- intent 写入或 Lean 启动失败：
  - 订单仍保留为 `NEW`
  - 返回 409 错误并在 UI 显示
  - 订单 `params` 增加 `manual_execution_error`

## 测试策略
- 后端单测：
  - intent 文件生成包含 `order_intent_id` 和正确数量方向。
  - JSONL 回写可更新订单状态与成交。
- 前端 Playwright：
  - 当前持仓买/卖各 1 股：
    - 断言订单创建成功
    - 轮询订单状态 ≥ `SUBMITTED`

## 影响范围
- `backend/app/routes/trade.py`
- `backend/app/services/*`（新增 manual execution + 回写处理）
- `frontend/src/pages/LiveTradePage.tsx`

## 归档
任务完成并验收后，归档本设计文档到 `docs/plans/_archive/`。
