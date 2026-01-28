# 直发 IB/TWS 订单接口设计

## 背景与目标
当前“实盘交易”页面的手动下单仅创建 `TradeOrder` 记录，不会触发 Lean/IB 执行，导致 TWS 无法收到订单。目标是新增一个“直发 IB/TWS”的后端接口，允许 Paper/Live 模式下将单笔订单直接送入现有 Lean 执行通道，并保留审计与追踪信息。

## 范围
- 新增后端接口 `POST /api/trade/orders/direct`。
- 生成直发 intent 文件并触发 Lean 执行。
- Lean 执行算法支持负数量（SELL）。
- 前端“手动下单”调用新接口。
- 增加审计日志与执行探针文件。

## 非目标
- 不新增 IB 直连实现（仍通过 Lean Bridge）。
- 不改变 TradeRun 执行流程。
- 不支持 LMT 直发（仅 MKT）。

## 约束与安全
- `mode` 仅允许 `paper` / `live`。
- `live` 必须 `live_confirm_token=LIVE`。
- 不走 guard/risk（按需求选择“更危险”的直发模式）。
- `order_type` 仅允许 `MKT`，否则拒绝。

## 接口设计
### 请求
`POST /api/trade/orders/direct`

字段：
- `project_id` (int, required)
- `mode` (string, required, paper/live)
- `live_confirm_token` (string, live 必填)
- `client_order_id` (string, required)
- `symbol` (string, required)
- `side` (string, required, BUY/SELL)
- `quantity` (float, required, >0)
- `order_type` (string, optional, default MKT)
- `limit_price` (float, optional, 仅当 LMT 时需要，但本接口将拒绝 LMT)
- `params` (dict, optional)

### 响应
- `order_id`
- `status`（下单记录状态，初始 NEW）
- `execution_status`（如 `submitted_lean`/`failed`）
- `config_path`/`intent_path`（用于排查）

### 错误码
- 400：参数无效（mode、symbol、side、quantity、order_type）
- 403：live_confirm_token 不通过
- 409：IB 配置不完整或 api_mode 非 ib

## 后端执行流程
1) 校验参数与 `mode`，live 校验 token。
2) 校验 IB 设置：`api_mode=ib` 且 `host/port` 完整。
3) 创建 `TradeOrder`（`run_id=null`），`params.source=direct`，记录 `mode`、`project_id`。
4) 生成直发 intent 文件：
   - 文件名：`artifacts/order_intents/order_intent_direct_{order_id}.json`
   - 字段：`order_intent_id`（建议 `direct:{order_id}`）、`symbol`、`quantity`（BUY 正数 / SELL 负数）。
5) 生成 Lean 执行配置并 `launch_execution()`。
6) 记录审计日志 `trade_order.direct_submit`。
7) 写入进度探针：`artifacts/lean_execution/direct_order_{order_id}.json`。

## Lean 执行算法适配
- 允许 `quantity != 0`（正数 BUY / 负数 SELL）。
- 若 `order_intent_id` 为空仍拒绝并写日志（保持安全）。
- 继续支持 `weight` 作为兜底（仅当 `quantity==0`）。

## 前端改动
- “手动下单”改用 `/api/trade/orders/direct`。
- Live 模式下携带 `live_confirm_token`。
- 展示返回的 `execution_status` 与 `order_id`。

## 可观测性
- 审计日志：`trade_order.direct_submit`（含 order_id、mode、intent_path、config_path）。
- 进度探针文件：`direct_order_{order_id}.json`（提交时间、配置路径、intent 路径）。

## 测试
- 后端测试：mock `launch_execution`，验证 intent 文件、config 文件路径、响应字段。
- Lean 算法测试：新增负数量 SELL 的用例。
- 前端 E2E：触发手动 SELL，断言请求命中 `/direct` 且 live token 透传。

## 验收标准
- Paper 直发可提交并触发 Lean 执行。
- Live 直发必须 token；token 错误返回 403。
- SELL 数量可正确触发 TWS 收到订单。
- 直发请求有审计与探针文件可追踪。
